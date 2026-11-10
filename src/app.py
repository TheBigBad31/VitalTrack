"""FastAPI Backend pour VitalTrack (Local & Vercel Serverless).

Point d'entrée modulaire : l'instance `app` inclut tous les routeurs dédiés
(weights, activities, meals, metrics, devices, auth, webhooks, friends, profile, system, dashboard)
ainsi que l'observabilité OpenTelemetry / Prometheus (`/metrics`).

Endpoints conservés directement dans app.py :
- GET  /api/health            : statut de l'API
- GET  /                      : sert l'index PWA
- GET  /static/*              : fichiers statiques
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

# Configuration du logging structuré pour les latences et l'observabilité
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("vitaltrack.observability")

from src.db import Database, DatabaseServiceUnavailableError, get_db_path
from src.dependencies import set_db
from src.nutrition_engine import NutritionEngine
from src.vision_nutrition import PhotoCalorieEstimator
from src.connectors.registry import DeviceConnectorRegistry, create_device_registry, get_connector
from src.auth import AuthUser, decode_access_token
from src.otel import get_tracer, record_http_metric, setup_otel
from src.rate_limit import (
    RateLimitExceeded,
    limiter,
    rate_limit_exceeded_handler,
)


# Initialisation de FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gère le cycle de vie de l'application FastAPI (démarrage et extinction propres).

    Initialise le ConnectionPool PostgreSQL Neon lors du démarrage et assure la fermeture
    propre de toutes les connexions au shutdown pour éviter les fuites de ressources.
    """
    if getattr(db, "is_postgres", False):
        try:
            pool = db.create_pool()
            app.state.db_pool = pool
        except Exception as e:
            logger.warning(f"Impossible d'initialiser le pool PostgreSQL dans le lifespan: {e}")
            app.state.db_pool = None
    else:
        app.state.db_pool = None

    yield

    # Arrêt propre / Shutdown : fermeture du pool de connexions
    try:
        db.close_pool()
    except Exception as e:
        logger.warning(f"Erreur lors de la fermeture du pool PostgreSQL au shutdown: {e}")
    app.state.db_pool = None


app = FastAPI(
    title="VitalTrack API",
    description="API REST pour VitalTrack : PWA Mobile-First, Nutrition Photo IA et Objets Connectés",
    version="1.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Instrumentation OpenTelemetry + Prometheus (/metrics) avec protection Serverless Vercel (BALI-117)
setup_otel(app, service_name="vitaltrack")
tracer = get_tracer("vitaltrack.observability")

# CORS restreint aux origines connues (BALI-103 / BALI-126)
DEFAULT_CORS_ORIGINS: List[str] = [
    "https://vital-track-one.vercel.app",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


def get_cors_origins() -> List[str]:
    """Résout la liste des origines CORS autorisées depuis CORS_ORIGINS / CORS_ALLOWED_ORIGINS."""
    raw = os.getenv("CORS_ORIGINS") or os.getenv("CORS_ALLOWED_ORIGINS") or ""
    parsed = [o.strip() for o in raw.split(",") if o.strip()]
    return parsed if parsed else list(DEFAULT_CORS_ORIGINS)


allow_origins = get_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def performance_and_latency_middleware(request: Request, call_next):
    """Mesure la latence par route backend, émet les logs de latence, injecte le Server-Timing header et les spans OTel."""
    start_time = time.perf_counter()
    with tracer.start_as_current_span(
        f"HTTP {request.method} {request.url.path}",
        attributes={
            "http.method": request.method,
            "http.url": str(request.url),
            "http.scheme": request.url.scheme,
            "http.host": getattr(request.url, "hostname", None) or getattr(request.url, "netloc", None) or "",
            "http.path": request.url.path,
            "http.client_ip": request.client.host if request.client else "",
        },
    ) as span:
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            record_http_metric(request.method, request.url.path, 500, duration_ms)
            logger.error(
                f"HTTP {request.method} {request.url.path} failed in {duration_ms:.2f}ms - Exception: {exc}"
            )
            raise exc

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        record_http_metric(request.method, request.url.path, response.status_code, duration_ms)

        try:
            span.set_attribute("http.status_code", response.status_code)
            span.set_attribute("http.route", request.url.path)
            span.set_attribute("http.duration_ms", duration_ms)
        except Exception:
            logger.debug("Impossible de définir les attributs du span OpenTelemetry", exc_info=True)

        timing_value = f'app;dur={duration_ms:.2f};desc="App Processing"'
        existing_timing = response.headers.get("Server-Timing")
        if existing_timing:
            response.headers["Server-Timing"] = f"{existing_timing}, {timing_value}"
        else:
            response.headers["Server-Timing"] = timing_value

        logger.info(
            f"HTTP {request.method} {request.url.path} {response.status_code} in {duration_ms:.2f}ms"
        )
        return response


@app.middleware("http")
async def vercel_path_resolver_middleware(request: Request, call_next):
    """Résout et normalise les chemins Serverless sous Vercel (rewrites ?__path=...)."""
    path_param = request.query_params.get("__path")
    if path_param is not None:
        subpath = path_param.lstrip("/")
        if subpath == "metrics":
            request.scope["path"] = "/api/metrics"
        else:
            request.scope["path"] = f"/api/{subpath}" if subpath else "/api"
    elif request.scope.get("path") in ("/api/index.py", "/api/index", "/api"):
        matched = request.headers.get("x-matched-path", "")
        if matched and matched not in ("/api/index.py", "/api/index", "/api"):
            request.scope["path"] = matched
        else:
            request.scope["path"] = "/api/health"
    elif (
        not request.scope.get("path", "").startswith("/api")
        and not request.scope.get("path", "").startswith("/static")
        and request.scope.get("path") not in ("/", "/docs", "/openapi.json", "/metrics", "/sw.js", "/offline.html")
    ):
        request.scope["path"] = f"/api{request.scope.get('path')}"

    return await call_next(request)


@app.exception_handler(DatabaseServiceUnavailableError)
async def database_service_unavailable_handler(request: Request, exc: DatabaseServiceUnavailableError):
    """Intercepte les pannes de connexion Neon PostgreSQL en environnement de production et renvoie une 503."""
    return JSONResponse(
        status_code=503,
        content={
            "status": "error",
            "error": "Service Unavailable",
            "detail": "Base de données Neon PostgreSQL temporairement inaccessible en production. Sauvegarde sur SQLite désactivée pour éviter toute perte de données.",
            "technical_error": str(exc),
        },
    )


# Instances partagées
try:
    db = Database()
except DatabaseServiceUnavailableError as db_err:
    print(f"[VitalTrack Startup Warning] Base Neon Postgres inaccessible au demarrage: {db_err}")
try:
    db = Database()
except DatabaseServiceUnavailableError as db_err:
    print(f"[VitalTrack Startup Warning] Base Neon Postgres inaccessible au demarrage: {db_err}")
    # En environnement de production, créer l'instance sans exécuter de requêtes SQLite fallback
    db = Database(
        database_url=os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("NEON_DATABASE_URL"),
        db_path=get_db_path(),
        auto_migrate=False,
    )
    db.is_postgres = True
except Exception as db_err:
    print(f"[VitalTrack Startup Warning] Erreur inattendue lors de l'initialisation DB: {db_err}")
    db_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("POSTGRES_URL_NON_POOLING") or os.getenv("NEON_DATABASE_URL")
    db = Database(
        database_url=db_url,
        db_path=get_db_path(),
        auto_migrate=False,
    )
    db.is_postgres = bool(db_url)

set_db(db)

nutrition_engine = NutritionEngine(db=db)
calorie_estimator = PhotoCalorieEstimator()

# Initialisation du registre IoT via DI factory (VTR-001 / BALI-202)
device_registry = create_device_registry()


# =====================================================================
# Middleware & Dépendances d'Authentification JWT
# =====================================================================

def get_current_user(
    authorization: Optional[str] = Header(None),
    x_webhook_token: Optional[str] = Header(None, alias="X-Webhook-Token")
) -> AuthUser:
    """Extrait et valide l'utilisateur authentifié depuis le jeton JWT Bearer ou un token d'appareil X-Webhook-Token."""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
        payload = decode_access_token(token)
        if payload and "user_id" in payload:
            user_data = db.get_user_by_id(int(payload["user_id"]))
            if user_data:
                return AuthUser(
                    id=user_data["id"],
                    uuid=user_data["uuid"],
                    email=user_data["email"],
                    name=user_data.get("name"),
                    picture=user_data.get("picture"),
                    auth_provider=user_data.get("auth_provider", "google"),
                    google_sub=user_data.get("google_sub"),
                )

    if x_webhook_token and str(x_webhook_token).strip():
        user_match = db.find_user_by_device_token(str(x_webhook_token).strip())
        if user_match and user_match.get("user"):
            u = user_match["user"]
            return AuthUser(
                id=u["id"],
                uuid=u["uuid"],
                email=u["email"],
                name=u.get("name"),
                picture=u.get("picture"),
                auth_provider=u.get("auth_provider", "device_token"),
                google_sub=u.get("google_sub"),
            )

    sess = db.get_google_session()
    if sess.get("is_authenticated") and sess.get("user_id"):
        user_data = db.get_user_by_id(int(sess["user_id"]))
        if user_data:
            return AuthUser(
                id=user_data["id"],
                uuid=user_data["uuid"],
                email=user_data["email"],
                name=user_data.get("name"),
                picture=user_data.get("picture"),
                auth_provider=user_data.get("auth_provider", "google"),
                google_sub=user_data.get("google_sub"),
            )

    is_prod_env = os.getenv("VERCEL") == "1" or os.getenv("ENV") == "production" or os.getenv("ENVIRONMENT") == "production"
    require_strict = os.getenv("REQUIRE_STRICT_AUTH") == "1" or (is_prod_env and os.getenv("REQUIRE_STRICT_AUTH") != "0")

    if require_strict:
        raise HTTPException(
            status_code=401,
            detail="Authentification requise : aucun jeton Bearer, token d'appareil ou session Google valide",
            headers={"WWW-Authenticate": "Bearer"},
        )

    demo_user = db.get_user_by_id(1) or db._ensure_default_user()
    return AuthUser(
        id=demo_user["id"],
        uuid=demo_user["uuid"],
        email=demo_user["email"],
        name=demo_user.get("name"),
        picture=demo_user.get("picture"),
        auth_provider=demo_user.get("auth_provider", "demo"),
        google_sub=demo_user.get("google_sub"),
    )


def get_strict_user(authorization: Optional[str] = Header(None)) -> AuthUser:
    """Dépendance stricte exigeant un jeton Bearer JWT valide."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Jeton d'authentification Bearer manquant ou invalide")
    token = authorization.split("Bearer ", 1)[1].strip()
    payload = decode_access_token(token)
    if not payload or "user_id" not in payload:
        raise HTTPException(status_code=401, detail="Jeton JWT expiré ou signature invalide")
    user_data = db.get_user_by_id(int(payload["user_id"]))
    if not user_data:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return AuthUser(
        id=user_data["id"],
        uuid=user_data["uuid"],
        email=user_data["email"],
        name=user_data.get("name"),
        picture=user_data.get("picture"),
        auth_provider=user_data.get("auth_provider", "google"),
        google_sub=user_data.get("google_sub"),
    )


# =====================================================================
# Endpoints de Santé et Métadonnées
# =====================================================================

@app.get("/api")
@app.get("/api/")
@app.post("/api/")
@app.get("/health")
@app.post("/health")
@app.get("/api/health")
@app.post("/api/health")
@app.get("/api/health/")
@app.post("/api/health/")
def health_check():
    """Vérification de l'état du backend, de la base de données et des connecteurs IoT."""
    db_status = "ok"
    db_engine = "postgresql" if db.is_postgres else "sqlite"
    db_target = "Neon PostgreSQL" if db.is_postgres else db.db_path

    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1;")
            cursor.fetchone()
    except Exception as db_err:
        db_status = f"degraded: {str(db_err)}"

    connectors_summary = {}
    total_connectors = 0
    configured_connectors = 0
    try:
        all_devs = device_registry.list_all()
        total_connectors = len(all_devs)
        for dev in all_devs:
            is_cfg = dev.is_configured() if callable(getattr(dev, "is_configured", None)) else bool(getattr(dev, "is_configured", False))
            if is_cfg:
                configured_connectors += 1
            connectors_summary[dev.id] = {
                "name": dev.name,
                "type": dev.device_type,
                "is_configured": is_cfg,
                "status": "ready" if is_cfg else "unconfigured",
            }
    except Exception as conn_err:
        connectors_summary["error"] = str(conn_err)

    overall_status = "ok" if db_status == "ok" else "degraded"

    return {
        "status": overall_status,
        "service": "VitalTrack API",
        "database": {
            "status": db_status,
            "engine": db_engine,
            "type": db_engine,
            "is_postgres": db.is_postgres,
            "target": db_target,
        },
        "connectors": {
            "total": total_connectors,
            "configured": configured_connectors,
            "items": connectors_summary,
        },
        "db_path": db.db_path,
        "is_vercel": os.getenv("VERCEL") == "1",
        "has_gemini_vision": calorie_estimator.has_gemini_api,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# =====================================================================
# Inclusion des routeurs modulaires (BALI-105 & BALI-210)
# =====================================================================

from src.routers.weights import router as weights_router
from src.routers.activities import router as activities_router
from src.routers.meals import router as meals_router
from src.routers.metrics import router as metrics_router
from src.routers.devices import router as devices_router
from src.routers.auth import router as auth_router
from src.routers.webhooks import router as webhooks_router
from src.routers.friends import router as friends_router
from src.routers.system import router as system_router, GITHUB_LATEST_RELEASE_APK_URL, KCAL_PER_KG
from src.routers.dashboard import router as dashboard_router, DASHBOARD_CACHE, invalidate_dashboard_cache
from src.routers.profile import router as profile_router, UserProfileInput

app.include_router(weights_router)
app.include_router(activities_router)
app.include_router(meals_router)
app.include_router(metrics_router)
app.include_router(devices_router)
app.include_router(auth_router)
app.include_router(webhooks_router)
app.include_router(friends_router)
app.include_router(profile_router)
app.include_router(system_router)
app.include_router(dashboard_router)


# =====================================================================
# Fichiers Statiques et Fallback pour PWA
# =====================================================================

class CachedStaticFiles(StaticFiles):
    """StaticFiles avec en-têtes de cache optimisés (immutable pour assets avec ?v=)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        query_string = scope.get("query_string", b"").decode("latin-1")
        if "v=" in query_string:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path.endswith((".js", ".css", ".png", ".jpg", ".svg", ".woff2", ".ico")):
            response.headers.setdefault("Cache-Control", "public, max-age=3600")
        return response


STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", CachedStaticFiles(directory=STATIC_DIR), name="static")


@app.get("/sw.js")
def serve_service_worker():
    """Sert le service worker PWA à la racine pour un scope / complet."""
    sw_file = os.path.join(STATIC_DIR, "sw.js")
    if os.path.isfile(sw_file):
        return FileResponse(
            sw_file,
            media_type="application/javascript",
            headers={
                "Cache-Control": "no-cache",
                "Service-Worker-Allowed": "/",
            },
        )
    raise HTTPException(status_code=404, detail="Service worker non trouvé")


@app.get("/offline.html")
def serve_offline():
    """Sert la page de fallback hors-ligne."""
    offline_file = os.path.join(STATIC_DIR, "offline.html")
    if os.path.isfile(offline_file):
        return FileResponse(
            offline_file,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )
    raise HTTPException(status_code=404, detail="Page hors-ligne non trouvée")


@app.get("/")
def serve_index():
    """Sert l'application PWA index.html."""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_file):
        return FileResponse(
            index_file,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )
    root_index = os.path.join(os.path.dirname(__file__), "..", "index.html")
    if os.path.isfile(root_index):
        return FileResponse(
            root_index,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )
    return Response(
        content='{"message": "VitalTrack PWA - interface en cours d\'initialisation"}',
        media_type="application/json",
        headers={"Cache-Control": "no-cache"},
    )
