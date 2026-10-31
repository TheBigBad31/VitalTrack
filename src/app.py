"""FastAPI Backend pour VitalTrack (Local \u0026 Vercel Serverless).

Endpoints :
- GET  /api/health            : statut de l'API
- GET  /api/dashboard         : données globales agrégées (30 jours, 5 vues)
- GET  /api/weights           : liste des pesées (historique + tendance 7j)
- POST /api/weights           : saisie rapide de pesée (kg, composition corporelle)
- GET  /api/activities        : liste des résumés d'activité
- POST /api/activities        : ajout / synchronisation d'exercice ou pas
- GET  /api/meals             : historique des repas
- POST /api/meals             : enregistrement d'un repas dans le journal
- POST /api/meals/estimate    : estimation calorique par photo ou description avec curseur portion
- GET  /api/devices           : statut et synchronisation des objets connectés (Withings, Garmin, Oura, etc.)
- POST /api/devices/sync      : déclenchement d'une synchronisation d'un appareil
- GET  /api/fallback-data     : jeu de données complet 30 jours embarqué
"""

import csv
import hmac
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
from src.models import (
    ActivityEntry, AssociatedBenefit, CatalogItem, FoodItem, MealEntry,
    MealLog, MealLogItem, MealType, NutritionBenefitItem, SavedMeal, WeightEntry,
    DailyMetricsEntry, WorkoutEntry, SleepSessionEntry, SleepStageEntry,
    IntradaySampleEntry, HydrationLogEntry, RawIngestEntry, UserConsentItem
)
from src.nutrition_engine import NutritionEngine
from src.nutrition_rules import evaluate_dish_benefits
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
    verify_password
)
from src.routers.friends import verify_view_access

# Initialisation de FastAPI
app = FastAPI(
    title="VitalTrack API",
    description="API REST pour VitalTrack : PWA Mobile-First, Nutrition Photo IA et Objets Connectés",
    version="1.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json"
)

# CORS permissif pour le support PWA et requêtes locales / Vercel
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Middleware de latence et Server-Timing
@app.middleware("http")
async def performance_and_latency_middleware(request: Request, call_next):
    """Mesure la latence par route backend, émet les logs de latence et injecte le Server-Timing header."""
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        logger.error(
            f"HTTP {request.method} {request.url.path} failed in {duration_ms:.2f}ms - Exception: {exc}"
        )
        raise exc

    duration_ms = (time.perf_counter() - start_time) * 1000.0
    # Header Server-Timing conforme au W3C: app;dur=...
    timing_value = f"app;dur={duration_ms:.2f};desc=\"App Processing\""
    existing_timing = response.headers.get("Server-Timing")
    if existing_timing:
        response.headers["Server-Timing"] = f"{existing_timing}, {timing_value}"
    else:
        response.headers["Server-Timing"] = timing_value

    logger.info(
        f"HTTP {request.method} {request.url.path} {response.status_code} in {duration_ms:.2f}ms"
    )
    return response


# Middleware de résolution de chemins Vercel
@app.middleware("http")
async def vercel_path_resolver_middleware(request: Request, call_next):
    """Résout et normalise les chemins Serverless sous Vercel (rewrites ?__path=...)."""
    path_param = request.query_params.get("__path")
    if path_param is not None:
        subpath = path_param.lstrip("/")
        request.scope["path"] = f"/api/{subpath}" if subpath else "/api"
    elif request.scope.get("path") in ("/api/index.py", "/api/index", "/api"):
        matched = request.headers.get("x-matched-path", "")
        if matched and matched not in ("/api/index.py", "/api/index", "/api"):
            request.scope["path"] = matched
        else:
            request.scope["path"] = "/api/health"
    elif not request.scope.get("path", "").startswith("/api") and not request.scope.get("path", "").startswith("/static") and request.scope.get("path") not in ("/", "/docs", "/openapi.json"):
        request.scope["path"] = f"/api{request.scope.get('path')}"

    return await call_next(request)


# Gestionnaire de panne de base de données
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
        }
    )


# Instances partagées
try:
    db = Database()
except DatabaseServiceUnavailableError as db_err:
    print(f"[VitalTrack Startup Warning] Base Neon Postgres inaccessible au demarrage: {db_err}")
    db = Database.__new__(Database)
    db.database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("NEON_DATABASE_URL")
    db.is_postgres = True
    db.db_path = get_db_path()
except Exception as db_err:
    print(f"[VitalTrack Startup Warning] Erreur inattendue lors de l'initialisation DB: {db_err}")
    db = Database.__new__(Database)
    db.database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL_NON_POOLING") or os.getenv("NEON_DATABASE_URL")
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


# Dépendances d'Authentification JWT
def get_current_user(
    authorization: Optional[str] = Header(None),
    x_webhook_token: Optional[str] = Header(None, alias="X-Webhook-Token")
) -> AuthUser:
    """Extrait et valide l'utilisateur authentifié depuis le jeton JWT Bearer ou un token d'appareil X-Webhook-Token.
    
    En l'absence de token valide, retourne un utilisateur invité par défaut
    (remplacement explicite de l'ancien fallback silencieux sur default_user — BALI-104).
    L'app reste fonctionnelle pour l'ouverture PWA et le mode démo sans authentification.
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
                    google_sub=user_data.get("google_sub")
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
                google_sub=u.get("google_sub")
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
                google_sub=user_data.get("google_sub")
            )

    # Aucun token valide : retour utilisateur invité par défaut (pas de fallback silencieux sur default_user)
    return AuthUser(
        id=0,
        uuid="",
        email="",
        name="Invité",
        picture="",
        auth_provider="local",
        google_sub=""
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
        google_sub=user_data.get("google_sub")
    )


# =====================================================================
# Modèles de requêtes Pydantic
# =====================================================================

import datetime as dt_module

class WeightInput(BaseModel):
    date: Optional[dt_module.date] = None
    weight_kg: float = Field(..., gt=20.0, lt=350.0, description="Poids en kg")
    body_fat_pct: Optional[float] = Field(None, ge=3.0, le=60.0, description="% masse grasse")
    muscle_mass_kg: Optional[float] = Field(None, ge=10.0, le=150.0, description="Masse musculaire en kg")
    water_pct: Optional[float] = Field(None, ge=30.0, le=80.0, description="% eau")
    bmi: Optional[float] = Field(None, ge=10.0, le=70.0, description="IMC")
    notes: Optional[str] = None
    source: Literal["manual", "withings", "garmin", "apple_health", "demo", "simulation"] = "manual"


class ActivityInput(BaseModel):
    date: Optional[dt_module.date] = None
    steps: int = Field(0, ge=0, description="Nombre de pas")
    active_calories_kcal: float = Field(0.0, ge=0.0, description="Calories actives en exercice")
    workout_minutes: int = Field(0, ge=0, description="Minutes d'activité physique")
    workout_type: Optional[str] = Field(None, description="Type d'entraînement")
    resting_hr_bpm: Optional[int] = Field(None, ge=30, le=220, description="Fréquence cardiaque au repos")
    hrv_ms: Optional[float] = Field(None, ge=0.0, description="Variabilité cardiaque (HRV en ms)")
    sleep_score: Optional[int] = Field(None, ge=0, le=100, description="Score de sommeil")
    source: Literal["oura", "health_connect", "apple_health", "strava", "demo", "simulation"] = "health_connect"


class MealEstimateRequest(BaseModel):
    photo_data_url: Optional[str] = None
    description: Optional[str] = None
    meal_type: MealType = "lunch"
    portion_scale: float = Field(1.0, ge=0.5, le=2.0, description="Curseur de portion (0.5x à 2.0x)")


class MealSaveRequest(BaseModel):
    date: Optional[dt_module.date] = None
    meal_type: MealType
    photo_data_url: Optional[str] = None
    portion_scale: float = Field(1.0, ge=0.5, le=2.0)
    items: List[FoodItem] = Field(default_factory=list)
    total_calories_kcal: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    fiber_g: Optional[float] = None
    meal_name: Optional[str] = None


class SavedMealCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Nom du plat")
    meal_type: MealType = Field("lunch", description="Type de repas (breakfast, lunch, snack, dinner)")
    serving_size: Optional[str] = Field("1 portion", description="Taille ou libellé de portion")
    quantity_grams: Optional[float] = Field(None, ge=0.0)
    calories: float = Field(..., ge=0.0, description="Calories (kcal)")
    protein_g: float = Field(0.0, ge=0.0)
    carbs_g: float = Field(0.0, ge=0.0)
    fat_g: float = Field(0.0, ge=0.0)
    fiber_g: Optional[float] = Field(0.0, ge=0.0)
    ingredients: Optional[str] = None
    items: Optional[List[FoodItem]] = Field(default_factory=list)
    photo_url: Optional[str] = None
    is_favorite: Optional[bool] = False


class SavedMealUpdateRequest(BaseModel):
    name: Optional[str] = None
    meal_type: Optional[MealType] = None
    serving_size: Optional[str] = None
    quantity_grams: Optional[float] = None
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    fiber_g: Optional[float] = None
    ingredients: Optional[str] = None
    items: Optional[List[FoodItem]] = None
    photo_url: Optional[str] = None
    is_favorite: Optional[bool] = False


class SavedMealLogRequest(BaseModel):
    date: Optional[dt_module.date] = None
    meal_type: Optional[MealType] = None
    portion_factor: Optional[float] = Field(1.0, ge=0.1, le=10.0, description="Facteur multiplicateur de portion")


class DeviceConnectInput(BaseModel):
    device_id: str
    name: Optional[str] = None
    device_type: Optional[str] = None
    auth_type: Optional[str] = "connected"  # "cloud_api", "google_health", "bluetooth", "connected", "ringconn_openapi", "withings_oauth", "oura_bearer_token"
    api_key: Optional[str] = None
    token: Optional[str] = None
    credentials: Optional[Dict[str, Any]] = None
    account_email: Optional[str] = None
    connected: bool = True


# =====================================================================
# Health Check
# =====================================================================

@app.get("/api/health")
@app.post("/api/health")
@app.get("/health")
@app.post("/health")
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
                "status": "ready" if is_cfg else "unconfigured"
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
            "is_postgres": db.is_postgres,
            "target": db_target
        },
        "connectors": {
            "total": total_connectors,
            "configured": configured_connectors,
            "items": connectors_summary
        },
        "db_path": db.db_path,
        "is_vercel": os.getenv("VERCEL") == "1",
        "has_gemini_vision": calorie_estimator.has_gemini_api,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# =====================================================================
# Endpoints Dashboard & Données Agrégées
# =====================================================================

@app.get("/api/dashboard")
def get_dashboard_data(
    include_simulation: bool = Query(False, description="Inclure ou exclure les données de simulation"),
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un utilisateur ami pour consultation en lecture seule"),
    current_user: AuthUser = Depends(get_current_user)
):
    """Renvoie les données unifiées pour alimenter l'ensemble des 5 vues de dashboards pour l'utilisateur connecté ou un ami."""
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    user_id = target_uid
    
    profile = db.get_user_profile(user_id=user_id)
    
    # Exclure par défaut les données simulées sauf si confirmation explicite d'un profil de démo ou requête include_simulation=True
    effective_exclude = not include_simulation and not bool(profile.get("is_demo_profile"))
    weights = db.get_weights(limit=30, user_id=user_id, exclude_simulation=effective_exclude)
    if not weights and not effective_exclude:
        weights = db.get_weights(limit=30, user_id=user_id, exclude_simulation=False)
    
    activities = db.get_activities(limit=30, user_id=user_id, exclude_simulation=effective_exclude)
    if not activities and not effective_exclude:
        activities = db.get_activities(limit=30, user_id=user_id, exclude_simulation=False)
    meals = db.get_meals(limit=60, user_id=user_id)
    
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
    today_metrics = [m for m in db.get_daily_metrics(limit=5, user_id=user_id) if m.date == today]
    today_metric = today_metrics[0] if today_metrics else None
    
    # Profil utilisateur personnalisé
    profile = db.get_user_profile(user_id=user_id)
    saved_devices = {dev["device_id"]: dev for dev in db.get_user_devices(user_id=user_id)}
    
    daily_nutrition = nutrition_engine.get_daily_nutrition_summary(today, user_id=user_id)
    energy_balance = nutrition_engine.calculate_daily_energy_balance(
        target_date=today,
        user_weight_kg=latest_weight.weight_kg if latest_weight else 79.5,
        user_height_cm=profile.get("height_cm", 178.0),
        user_age=profile.get("age", 35),
        gender=profile.get("gender", "male"),
        user_id=user_id
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
            "api_key_masked": saved_d.get("api_key_masked")
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
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


# =====================================================================
# Inclusion des routeurs modulaires (BALI-105)
# =====================================================================

# Import lent des routeurs pour éviter les boucles circulaires au moment du chargement
def _include_routers():
    """Inclure les routeurs modulaires après l'initialisation complète de l'app."""
    from src.routers.weights import router as weights_router
    from src.routers.activities import router as activities_router
    from src.routers.meals import router as meals_router
    from src.routers.metrics import router as metrics_router
    from src.routers.devices import router as devices_router
    from src.routers.auth import router as auth_router
    from src.routers.webhooks import router as webhooks_router
    from src.routers.friends import router as friends_router
    
    app.include_router(weights_router)
    app.include_router(activities_router)
    app.include_router(meals_router)
    app.include_router(metrics_router)
    app.include_router(devices_router)
    app.include_router(auth_router)
    app.include_router(webhooks_router)
    app.include_router(friends_router)

#include_routers()  # Décommenter pour activer les routeurs