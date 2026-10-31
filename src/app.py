"""FastAPI Backend pour VitalTrack (Local & Vercel Serverless).

Point d'entrée modulaire : l'instance `app` inclut tous les routeurs dédiés
(weights, activities, meals, metrics, devices, auth, webhooks, friends)
ainsi que l'observabilité OpenTelemetry / Prometheus (`/metrics`).

Endpoints conservés directement dans app.py :
- GET  /api/health            : statut de l'API
- GET  /api/dashboard         : données globales agrégées (30 jours, 5 vues)
- GET  /api/profile           : profil utilisateur et appareils connectés
- POST /api/profile           : mise à jour du profil
- PUT  /api/profile           : alias
- GET  /api/backup/export     : export RGPD complet (JSON)
- GET  /api/export/json       : alias export JSON
- GET  /api/export/csv        : export CSV des données biométriques
- DELETE /api/user/data       : purge des données de santé (compte conservé)
- DELETE /api/user/account    : suppression définitive du compte (RGPD)
- GET  /api/user/consents     : préférences de consentement RGPD
- POST /api/user/consents     : mise à jour d'un consentement
- POST /api/backup/import     : restauration depuis un export JSON
- POST /api/profile/reset-demo: réinitialisation des données de démo 30j
- POST /api/profile/clear-history: efface l'historique, conserve le profil
- GET  /api/goals/presets     : profils métaboliques prédéfinis 1-clic
- GET  /api/downloads/android-bridge : téléchargement APK Android Health Bridge
- GET  /                      : sert l'index PWA
- GET /static/*               : fichiers statiques
"""

import asyncio
import csv
import io
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Configuration du logging structuré pour les latences et l'observabilité
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("vitaltrack.observability")

from src.db import Database, DatabaseServiceUnavailableError, get_db_path
from src.models import MealType
from src.nutrition_engine import NutritionEngine
from src.analytics import BiometricsAnalyticsService
from src.biometrics_math import DailyBiometrics
import yaml
from src.vision_nutrition import PhotoCalorieEstimator
from src.connectors.registry import DeviceConnectorRegistry, get_connector
from src.connectors.withings import WithingsScaleConnector
from src.connectors.oura import OuraRingConnector
from src.connectors.ringconn import RingConnConnector
from src.connectors.webhook import MobileHealthWebhookConnector
from src.auth import (
    AuthUser,
    GoogleAuthPayload,
    GoogleConfigUpdate,
    LoginRequest,
    RegisterRequest,
    create_access_token,
    decode_access_token,
    hash_password,
    parse_google_identity,
    validate_password_strength,
    verify_password,
)
from src.routers.friends import verify_view_access
from src.otel import get_tracer, record_http_metric, setup_otel


# Initialisation de FastAPI
app = FastAPI(
    title="VitalTrack API",
    description="API REST pour VitalTrack : PWA Mobile-First, Nutrition Photo IA et Objets Connectés",
    version="1.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# Instrumentation OpenTelemetry + Prometheus (/metrics) avec protection Serverless Vercel (BALI-117)
setup_otel(app, service_name="vitaltrack")
tracer = get_tracer("vitaltrack.observability")

# CORS restreint aux origines connues (BALI-103 — spec CORS : allow_credentials interdit
# allow_origins=["*"]). Origines configurables via CORS_ALLOWED_ORIGINS
# (séparées par des virgules), par défaut production Vercel + localhost.
_cors_origins_env = os.getenv("CORS_ALLOWED_ORIGINS", "")
if _cors_origins_env:
    allow_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
else:
    allow_origins = [
        "https://vital-track-one.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

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
            pass

        # Header Server-Timing conforme au W3C: app;dur=...
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
        and request.scope.get("path") not in ("/", "/docs", "/openapi.json", "/metrics")
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
    # En environnement de production, créer l'instance sans exécuter de requêtes SQLite fallback
    db = Database.__new__(Database)
    db.database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("NEON_DATABASE_URL")
    db.is_postgres = True
    db.db_path = get_db_path()
except Exception as db_err:
    # Renfort hotfix BALI-97 : aucune exception (migration, seed, import psycopg manquant, etc.)
    # ne doit crasher l'import de src.app sinon Vercel renvoie 500 FUNCTION_INVOCATION_FAILED sur 100% des routes.
    print(f"[VitalTrack Startup Warning] Erreur inattendue lors de l'initialisation DB: {db_err}")
    db = Database.__new__(Database)
    db.database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("POSTGRES_URL_NON_POOLING") or os.getenv("NEON_DATABASE_URL")
    db.is_postgres = bool(db.database_url)
    db.db_path = get_db_path()

nutrition_engine = NutritionEngine(db=db)
calorie_estimator = PhotoCalorieEstimator()

# Initialisation du registre IoT
device_registry = DeviceConnectorRegistry()
device_registry.register(RingConnConnector(), device_id="ringconn", name="RingConn Smart Ring (Gen 1 / Gen 2 / Gen 3)", device_type="ring")
device_registry.register(MobileHealthWebhookConnector(), device_id="health_connect", name="Google Health Connect (Google Health / Android)", device_type="mobile_aggregator")
device_registry.register(WithingsScaleConnector(), device_id="withings", name="Withings Body Scan & Scales", device_type="scale")
device_registry.register(OuraRingConnector(), device_id="oura", name="Oura Ring Gen3", device_type="ring")
device_registry.register(MobileHealthWebhookConnector(), device_id="apple_health", name="Apple Santé (HealthKit)", device_type="mobile_aggregator")


# =====================================================================
# Middleware & Dépendances d'Authentification JWT
# =====================================================================

def get_current_user(
    authorization: Optional[str] = Header(None),
    x_webhook_token: Optional[str] = Header(None, alias="X-Webhook-Token")
) -> AuthUser:
    """Extrait et valide l'utilisateur authentifié depuis le jeton JWT Bearer ou un token d'appareil X-Webhook-Token.

    En l'absence de jeton Bearer ou de session Google explicite, résout le profil
    démo / invité actif (`user_id=1`) afin que l'ouverture initiale de la PWA,
    les endpoints publics (`/api/dashboard`, `/api/meals/journal`) et les 139 tests
    d'intégration fonctionnent sans erreur 401 bloquante (conformément au contrat BALI-104/BALI-123).
    Lorsque `REQUIRE_STRICT_AUTH=1` est activé, lève explicitement une HTTP 401.
    """
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

    # Vérifier l'authentification par token d'appareil (passerelle mobile Android / webhook)
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

    # Vérifier si une session Google active existe en base
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

    if os.getenv("REQUIRE_STRICT_AUTH") == "1":
        raise HTTPException(
            status_code=401,
            detail="Authentification requise : aucun jeton Bearer, token d'appareil ou session Google valide",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Mode démo / ouverture initiale PWA : résolution explicite du profil user_id=1
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


# Import des routeurs modulaires (BALI-105 — après définition des dépendances partagées)
from src.routers.weights import router as weights_router
from src.routers.activities import router as activities_router
from src.routers.meals import router as meals_router
from src.routers.metrics import router as metrics_router
from src.routers.devices import router as devices_router
from src.routers.auth import router as auth_router
from src.routers.webhooks import router as webhooks_router
from src.routers.friends import router as friends_router


# =====================================================================
# Modèles de requêtes Pydantic (profil uniquement, le reste est dans les routers)
# =====================================================================

class UserProfileInput(BaseModel):
    name: Optional[str] = "Sébastien"
    gender: Optional[Literal["male", "female"]] = "male"
    age: Optional[int] = Field(35, ge=10, le=120)
    height_cm: Optional[float] = Field(178.0, ge=80.0, le=250.0)
    target_weight_kg: Optional[float] = Field(77.0, ge=30.0, le=300.0)
    goal_profile_id: Optional[str] = "weight_loss"
    target_steps: Optional[int] = Field(10000, ge=1000, le=50000)
    target_calories_intake: Optional[float] = Field(2000.0, ge=800.0, le=6000.0)
    protein_target_per_kg: Optional[float] = Field(1.8, ge=0.8, le=3.5)
    daily_protein_target_g: Optional[float] = Field(None, ge=20.0, le=500.0)
    daily_carbs_target_g: Optional[float] = Field(None, ge=20.0, le=1000.0)
    daily_fat_target_g: Optional[float] = Field(None, ge=10.0, le=500.0)
    daily_water_target_ml: Optional[float] = Field(2000.0, ge=500.0, le=10000.0)
    goal_type: Optional[str] = "weight_loss"
    activity_level: Optional[str] = "moderately_active"
    birth_date: Optional[str] = None
    current_weight_kg: Optional[float] = Field(None, ge=30.0, le=300.0)
    meal_distribution: Optional[Any] = None
    preferred_ring: Optional[str] = "ringconn"
    preferred_scale: Optional[str] = "withings"
    google_email: Optional[str] = None
    google_name: Optional[str] = None
    google_picture: Optional[str] = None
    google_sub: Optional[str] = None


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

    # Test actif de connectivité à la base de données
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1;")
            cursor.fetchone()
    except Exception as db_err:
        db_status = f"degraded: {str(db_err)}"

    # Évaluation de l'état des connecteurs enregistrés
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
# Endpoints Dashboard & Données Agrégées (BALI-106 : parallélisé via asyncio.gather)
# =====================================================================

@app.get("/api/dashboard")
async def get_dashboard_data(
    include_simulation: bool = Query(False, description="Inclure ou exclure les données de simulation"),
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un utilisateur ami pour consultation en lecture seule"),
    current_user: AuthUser = Depends(get_current_user),
):
    """Renvoie les données unifiées pour alimenter l'ensemble des 5 vues de dashboards pour l'utilisateur connecté ou un ami."""
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    user_id = target_uid

    # Vague 1 : appels DB indépendants (profil, repas, métriques quotidiennes, appareils)
    profile, meals, daily_metrics_rows, saved_devices_raw = await asyncio.gather(
        asyncio.to_thread(db.get_user_profile, user_id=user_id),
        asyncio.to_thread(db.get_meals, limit=60, user_id=user_id),
        asyncio.to_thread(db.get_daily_metrics, limit=5, user_id=user_id),
        asyncio.to_thread(db.get_user_devices, user_id=user_id),
    )
    saved_devices = {dev["device_id"]: dev for dev in saved_devices_raw}

    # Exclure par défaut les données simulées sauf si confirmation explicite d'un profil de démo ou requête include_simulation=True
    effective_exclude = not include_simulation and not bool(profile.get("is_demo_profile"))

    # Vague 2 : poids et activités dépendent du profil (effective_exclude)
    weights, activities = await asyncio.gather(
        asyncio.to_thread(db.get_weights, limit=30, user_id=user_id, exclude_simulation=effective_exclude),
        asyncio.to_thread(db.get_activities, limit=30, user_id=user_id, exclude_simulation=effective_exclude),
    )
    # Fallbacks séquentiels si aucune donnée réelle (dépendent du résultat de la vague 2)
    if not weights and not effective_exclude:
        weights = await asyncio.to_thread(db.get_weights, limit=30, user_id=user_id, exclude_simulation=False)
    if not activities and not effective_exclude:
        activities = await asyncio.to_thread(db.get_activities, limit=30, user_id=user_id, exclude_simulation=False)

    # Date du jour (ou dernière pesée)
    today = date.today()
    latest_weight = weights[-1] if weights else None

    # Évolution 7j
    weight_7d_change = 0.0
    if len(weights) >= 7:
        weight_7d_change = round(weights[-1].weight_kg - weights[-7].weight_kg, 2)
    elif len(weights) >= 2:
        weight_7d_change = round(weights[-1].weight_kg - weights[0].weight_kg, 2)

    # Synthèse du jour (strictement rattachée à la date du jour pour éviter d'afficher d'anciens pas de simulation)
    today_activity = next((a for a in reversed(activities) if a.date == today), None)
    today_metrics = [m for m in daily_metrics_rows if m.date == today]
    today_metric = today_metrics[0] if today_metrics else None

    daily_nutrition = nutrition_engine.get_daily_nutrition_summary(today, user_id=user_id)
    energy_balance = nutrition_engine.calculate_daily_energy_balance(
        target_date=today,
        user_weight_kg=latest_weight.weight_kg if latest_weight else 79.5,
        user_height_cm=profile.get("height_cm", 178.0),
        user_age=profile.get("age", 35),
        gender=profile.get("gender", "male"),
        user_id=user_id,
    )

    # Répartition des repas par jour pour les graphiques empilés (7 derniers jours)
    seven_days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    meals_by_day = {}
    for d_str in seven_days:
        d_date = date.fromisoformat(d_str)
        day_meals = [m for m in meals if m.date == d_date]
        day_dict = {"breakfast": 0.0, "lunch": 0.0, "dinner": 0.0, "snack": 0.0, "total": 0.0}
        for m in day_meals:
            day_dict[m.meal_type] = round(day_dict[m.meal_type] + m.total_calories_kcal, 1)
            day_dict["total"] = round(day_dict["total"] + m.total_calories_kcal, 1)
        meals_by_day[d_str] = day_dict

    # État des objets connectés avec statut de connexion de l'utilisateur
    device_statuses = []
    for d in device_registry.list_all():
        saved_d = saved_devices.get(d.id, {})
        is_conn = bool(saved_d.get("connected"))
        sync_status = saved_d.get("sync_status", "connected" if is_conn else "disconnected")
        last_sync = saved_d.get("last_sync_at") or saved_d.get("last_sync")
        device_statuses.append({
            "id": d.id,
            "device_id": d.id,
            "name": saved_d.get("name") or d.name,
            "device_type": d.device_type,
            "is_configured": is_conn,
            "connected": is_conn,
            "status": sync_status,
            "sync_status": sync_status,
            "auth_type": saved_d.get("auth_type", "none"),
            "account_email": saved_d.get("account_email"),
            "last_sync": last_sync,
            "last_sync_at": last_sync,
            "has_credentials": bool(saved_d.get("has_credentials")),
            "api_key_masked": saved_d.get("api_key_masked"),
        })

    return {
        "profile": profile,
        "current_user": current_user.model_dump(),
        "summary": {
            "current_weight_kg": latest_weight.weight_kg if latest_weight else None,
            "weight_trend_7d_kg": latest_weight.trend_7d_kg if latest_weight else None,
            "weight_7d_variation_kg": weight_7d_change if latest_weight else None,
            "body_fat_pct": latest_weight.body_fat_pct if latest_weight else None,
            "muscle_mass_kg": latest_weight.muscle_mass_kg if latest_weight else None,
            "water_pct": latest_weight.water_pct if latest_weight else None,
            "bmi": latest_weight.bmi if latest_weight else None,
            "target_weight_kg": profile.get("target_weight_kg", 77.0),
            "steps": (today_activity.steps if today_activity else (today_metric.steps if today_metric else 0)) or 0,
            "steps_target": profile.get("target_steps", 10000),
            "calories_intake_kcal": energy_balance["calories_intake_kcal"],
            "calories_burned_kcal": energy_balance["calories_burned_kcal"],
            "bmr_kcal": energy_balance["bmr_kcal"],
            "net_energy_balance_kcal": energy_balance["net_energy_balance_kcal"],
            "target_calories_intake": profile.get("target_calories_intake", 2000.0),
            "energy_status": energy_balance["status"],
            "recommendation": energy_balance["recommendation"],
            "macros": daily_nutrition["macros"],
            "resting_hr_bpm": (today_activity.resting_hr_bpm if today_activity and today_activity.resting_hr_bpm else (today_metric.resting_hr_bpm if today_metric else None)),
            "hrv_ms": (today_activity.hrv_ms if today_activity and today_activity.hrv_ms else (today_metric.hrv_rmssd_ms if today_metric else None)),
            "sleep_score": (today_activity.sleep_score if today_activity and today_activity.sleep_score else (today_metric.sleep_score if today_metric else None)),
        },
        "weights_history": [w.model_dump() for w in weights],
        "activities_history": [a.model_dump() for a in activities],
        "recent_meals": [m.model_dump() for m in meals],
        "meals_by_day_7d": meals_by_day,
        "devices": device_statuses,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# =====================================================================
# Endpoints Profil Utilisateur & Assistant de Connexion
# =====================================================================

@app.get("/api/profile")
def get_user_profile(
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un utilisateur ami pour consultation en lecture seule"),
    current_user: AuthUser = Depends(get_current_user),
):
    """Renvoie le profil utilisateur personnalisé et ses préférences d'objets pour l'utilisateur connecté ou un ami."""
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    is_owner = target_uid == current_user.id
    profile = db.get_user_profile(user_id=target_uid)
    devices = db.get_user_devices(user_id=target_uid)

    # Masquage strict des données sensibles pour les amis consultants
    if not is_owner:
        sanitized_devices = []
        for dev in devices:
            d = dict(dev)
            d.pop("encrypted_credentials", None)
            d.pop("credentials", None)
            d.pop("api_key", None)
            d.pop("api_key_masked", None)
            d.pop("account_email", None)
            d["has_credentials"] = False
            sanitized_devices.append(d)
        devices = sanitized_devices

    return {
        "profile": profile,
        "connected_devices": devices,
    }


@app.post("/api/profile")
@app.put("/api/profile")
def update_user_profile(profile_in: UserProfileInput, current_user: AuthUser = Depends(get_current_user)):
    """Met à jour ou crée le profil utilisateur pour l'utilisateur connecté."""
    updated = db.update_user_profile(profile_in.model_dump(), user_id=current_user.id)
    return {
        "status": "success",
        "message": "Profil mis à jour avec succès",
        "profile": updated,
    }


# =====================================================================
# Endpoints Sauvegarde / Restauration & Persistance Anti-Perte Vercel
# =====================================================================

class BackupRestoreInput(BaseModel):
    data: Dict[str, Any]
    overwrite: bool = False


@app.get("/api/backup/export")
@app.get("/api/export/json")
def export_backup(current_user: AuthUser = Depends(get_current_user)):
    """Exporte l'intégralité du profil utilisateur, des appareils configurés et de l'historique en JSON (RGPD)."""
    backup_data = db.export_full_backup(user_id=current_user.id)
    return backup_data


@app.get("/api/export/csv")
def export_data_csv(
    limit: Optional[int] = Query(None, description="Limite optionnelle pour pagination ou export complet"),
    current_user: AuthUser = Depends(get_current_user),
):
    """Exporte l'intégralité des données biométriques (pesées et activités) au format CSV standard sans troncature (RGPD)."""
    fetch_limit = limit if limit and limit > 0 else 1000000
    weights = db.get_weights(limit=fetch_limit, user_id=current_user.id)
    activities = db.get_activities(limit=fetch_limit, user_id=current_user.id)

    output = io.StringIO()
    writer = csv.writer(output)

    # 1. Section Pesées
    writer.writerow(["### SECTION: WEIGHTS ###"])
    writer.writerow(["date", "weight_kg", "body_fat_pct", "muscle_mass_kg", "water_pct", "bmi", "trend_7d_kg", "source", "external_id", "notes"])
    for w in weights:
        writer.writerow([
            w.date.isoformat(),
            w.weight_kg,
            w.body_fat_pct if w.body_fat_pct is not None else "",
            w.muscle_mass_kg if w.muscle_mass_kg is not None else "",
            w.water_pct if w.water_pct is not None else "",
            w.bmi if w.bmi is not None else "",
            w.trend_7d_kg if w.trend_7d_kg is not None else "",
            w.source,
            w.external_id or "",
            w.notes or "",
        ])

    writer.writerow([])
    # 2. Section Activités
    writer.writerow(["### SECTION: ACTIVITIES ###"])
    writer.writerow(["date", "steps", "active_calories_kcal", "bmr_kcal", "total_burned_kcal", "workout_minutes", "workout_type", "resting_hr_bpm", "hrv_ms", "sleep_score", "source", "external_id"])
    for a in activities:
        writer.writerow([
            a.date.isoformat(),
            a.steps,
            a.active_calories_kcal,
            a.bmr_kcal,
            a.total_burned_kcal,
            a.workout_minutes,
            a.workout_type or "",
            a.resting_hr_bpm if a.resting_hr_bpm is not None else "",
            a.hrv_ms if a.hrv_ms is not None else "",
            a.sleep_score if a.sleep_score is not None else "",
            a.source,
            a.external_id or "",
        ])

    csv_content = output.getvalue()
    filename = f"vitaltrack_export_{current_user.id}_{date.today().isoformat()}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


class ConfirmDeletionPayload(BaseModel):
    confirm: bool = Field(True, description="Confirmation explicite de la suppression")
    password: Optional[str] = Field(None, description="Mot de passe optionnel pour confirmation")


@app.delete("/api/user/data")
def delete_user_data_only_endpoint(
    confirm: bool = Query(True, description="Confirmation de purge des données"),
    payload: Optional[ConfirmDeletionPayload] = None,
    current_user: AuthUser = Depends(get_current_user),
):
    """Efface l'intégralité des données et de l'historique biométrique tout en conservant le compte et les accès de l'utilisateur."""
    is_confirmed = confirm and (payload.confirm if payload else True)
    if not is_confirmed:
        raise HTTPException(status_code=400, detail="Confirmation requise pour la suppression des données (confirm=true)")
    success = db.delete_user_data_only(user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return {
        "status": "success",
        "message": f"Toutes les données de santé pour {current_user.email} ont été purgées avec succès. Le compte utilisateur reste actif.",
    }


@app.delete("/api/user/account")
def delete_user_account_endpoint(
    confirm: bool = Query(True, description="Confirmation de suppression du compte"),
    payload: Optional[ConfirmDeletionPayload] = None,
    current_user: AuthUser = Depends(get_current_user),
):
    """Supprime définitivement le compte utilisateur et l'ensemble de ses données associées (Droit à l'oubli RGPD)."""
    is_confirmed = confirm and (payload.confirm if payload else True)
    if not is_confirmed:
        raise HTTPException(status_code=400, detail="Confirmation requise pour la suppression définitive du compte (confirm=true)")
    success = db.delete_user_account_and_data(user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable ou déjà supprimé")
    return {
        "status": "success",
        "message": f"Compte et toutes les données associées pour {current_user.email} ont été définitivement supprimés.",
    }


@app.get("/api/user/consents")
def get_user_consents_endpoint(current_user: AuthUser = Depends(get_current_user)):
    """Retourne les préférences de consentement RGPD par catégorie pour l'utilisateur."""
    consents = db.get_user_consents(user_id=current_user.id)
    return {
        "user_id": current_user.id,
        "consents": consents,
    }


class ConsentUpdatePayload(BaseModel):
    category: str = Field(..., description="biometrics, nutrition, analytics, devices")
    consented: bool = Field(..., description="true ou false")


@app.post("/api/user/consents")
def update_user_consent_endpoint(payload: ConsentUpdatePayload, current_user: AuthUser = Depends(get_current_user)):
    """Met à jour le consentement pour une catégorie spécifique."""
    allowed_categories = {"biometrics", "nutrition", "analytics", "devices"}
    if payload.category not in allowed_categories:
        raise HTTPException(status_code=400, detail=f"Catégorie invalide. Choix possibles: {allowed_categories}")
    res = db.set_user_consent(category=payload.category, consented=payload.consented, user_id=current_user.id)
    return {
        "status": "success",
        "consent": res.model_dump(),
    }


@app.post("/api/backup/import")
def import_backup(payload: BackupRestoreInput, current_user: AuthUser = Depends(get_current_user)):
    """Restaure ou synchronise les données depuis un export JSON ou le localStorage/IndexedDB."""
    result = db.import_full_backup(payload.data, overwrite=payload.overwrite, user_id=current_user.id)
    return result


@app.post("/api/profile/reset-demo")
def reset_demo(current_user: AuthUser = Depends(get_current_user)):
    """Réinitialise et recharge le jeu complet de données de démonstration réaliste 30 jours."""
    db.update_user_profile({"is_demo_profile": 1}, user_id=current_user.id)
    db.reset_demo_data(user_id=current_user.id)
    return {
        "status": "success",
        "message": "Données de démonstration 30 jours réinitialisées avec succès",
    }


@app.post("/api/profile/clear-history")
def clear_history(current_user: AuthUser = Depends(get_current_user)):
    """Efface l'historique tout en conservant les paramètres de profil pour un suivi personnel réel."""
    db.clear_all_history(keep_profile=True, user_id=current_user.id)
    db.update_user_profile({"is_demo_profile": 0}, user_id=current_user.id)
    return {
        "status": "success",
        "message": "Historique effacé. Vous pouvez démarrer votre suivi réel !",
    }


# =====================================================================
# Inclusion des routeurs modulaires (BALI-105)
# =====================================================================

app.include_router(weights_router)
app.include_router(activities_router)
app.include_router(meals_router)
app.include_router(metrics_router)
app.include_router(devices_router)
app.include_router(auth_router)
app.include_router(webhooks_router)
app.include_router(friends_router)


# =====================================================================
# Endpoints Profils d'Objectifs Métaboliques 1-Clic
# =====================================================================

GOALS_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "config", "goals_presets.yaml")

DEFAULT_GOALS_PRESETS = {
    "default_profile": "weight_loss",
    "profiles": {
        "weight_loss": {
            "id": "weight_loss",
            "title": "🔥 Perte de Poids Durable (-0,5 kg/sem)",
            "short_title": "Perte de Poids",
            "badge": "-0,5 kg/sem",
            "calorie_target_delta": -500,
            "target_steps": 10000,
            "protein_per_kg": 1.8,
            "carb_ratio": 0.40,
            "fat_ratio": 0.30,
            "protein_ratio": 0.30,
            "description": "Déficit calorique régulier de 500 kcal/j pour cibler -0,5 kg/semaine avec apport protéiné élevé (1,8 g/kg) afin de préserver la masse musculaire et 10 000 pas quotidiens.",
            "focus": "Masse grasse & conservation musculaire",
            "recommended_cardio_min_week": 150,
        },
        "maintenance": {
            "id": "maintenance",
            "title": "⚖️ Maintien & Équilibre Vitalité",
            "short_title": "Maintien Vitalité",
            "badge": "Équilibre 0 kcal",
            "calorie_target_delta": 0,
            "target_steps": 8500,
            "protein_per_kg": 1.4,
            "carb_ratio": 0.45,
            "fat_ratio": 0.30,
            "protein_ratio": 0.25,
            "description": "Équilibre calorique total (Déficit 0 kcal), répartition optimale P/G/L pour maximiser l'énergie au quotidien et 8 500 pas/j.",
            "focus": "Stabilité métabolique, niveau d'énergie & longévité",
            "recommended_cardio_min_week": 120,
        },
        "recomposition": {
            "id": "recomposition",
            "title": "💪 Recomposition Corporelle & Sport",
            "short_title": "Recomposition & Sport",
            "badge": "-200 kcal & P+ 2.2g/kg",
            "calorie_target_delta": -200,
            "target_steps": 10000,
            "protein_per_kg": 2.2,
            "carb_ratio": 0.35,
            "fat_ratio": 0.25,
            "protein_ratio": 0.40,
            "description": "Léger déficit de 200 kcal/j combiné à un apport protéiné très élevé (2,2 g/kg) pour stimuler la synthèse musculaire tout en réduisant l'adiposité viscérale.",
            "focus": "Masse musculaire, force & calories actives d'entraînement",
            "recommended_cardio_min_week": 180,
        },
    },
}


@app.get("/api/goals/presets")
def get_goals_presets():
    """Retourne la configuration des profils métaboliques prédéfinis 1-clic."""
    if os.path.isfile(GOALS_CONFIG_FILE):
        try:
            with open(GOALS_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data and "profiles" in data:
                    return data
        except Exception:
            pass
    return DEFAULT_GOALS_PRESETS


# =====================================================================
# Téléchargement direct de l'APK Android (Health Bridge)
# =====================================================================

GITHUB_LATEST_RELEASE_APK_URL = "https://github.com/TheBigBad31/VitalTrack/releases/latest/download/vitaltrack-health-bridge.apk"


@app.get("/api/downloads/android-bridge")
def download_android_bridge():
    """Téléchargement direct de l'APK VitalTrack Android Health Bridge.

    Vérifie en priorité si un binaire statique compilé existe localement
    dans static/downloads/vitaltrack-health-bridge.apk. Sinon, redirige vers
    la dernière release GitHub Actions hébergeant l'artefact officiel.
    """
    local_apk = os.path.join(STATIC_DIR, "downloads", "vitaltrack-health-bridge.apk")
    if os.path.isfile(local_apk):
        return FileResponse(
            local_apk,
            media_type="application/vnd.android.package-archive",
            filename="vitaltrack-health-bridge.apk",
        )
    return RedirectResponse(url=GITHUB_LATEST_RELEASE_APK_URL, status_code=307)


# =====================================================================
# Fichiers Statiques et Fallback pour PWA
# =====================================================================

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_index():
    """Sert l'application PWA index.html."""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_file):
        return FileResponse(index_file, media_type="text/html")
    root_index = os.path.join(os.path.dirname(__file__), "..", "index.html")
    if os.path.isfile(root_index):
        return FileResponse(root_index, media_type="text/html")
    return {"message": "VitalTrack PWA - interface en cours d'initialisation"}
