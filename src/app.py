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
from src.routers.webhooks import router as webhooks_router
from src.routers.friends import verify_view_access, router as friends_router
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
    # En environnement de production, créer l'instance sans exécuter de requêtes SQLite fallback
    db = Database.__new__(Database)
    db.database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("NEON_DATABASE_URL")
    db.is_postgres = True
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
    
    Supporte également le compte démo/principal par défaut si aucun header n'est fourni,
    permettant l'accès direct et la rétrocompatibilité tout en isolant par user_id.
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

    # Utilisateur par défaut (Sébastien LAMOLIATE, user_id=1)
    default_user = db._ensure_default_user()
    return AuthUser(
        id=default_user["id"],
        uuid=default_user["uuid"],
        email=default_user["email"],
        name=default_user.get("name"),
        picture=default_user.get("picture"),
        auth_provider=default_user.get("auth_provider", "google"),
        google_sub=default_user.get("google_sub")
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



class DeviceSyncRequest(BaseModel):
    device_id: str


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
    is_favorite: Optional[bool] = None


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
            "type": db_engine,
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
    # Si le profil est un profil démo ou si l'utilisateur n'a pas encore de pesées réelles et que l'utilisateur est sur profil démo
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
# Endpoints Pesées (Poids)
# =====================================================================

@app.get("/api/weights")
@app.get("/api/weight")
def get_weights(
    limit: int = Query(30, ge=1, le=180),
    include_simulation: Optional[bool] = Query(None, description="Inclure les données simulées (défaut False hors profil démo)"),
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un utilisateur ami pour consultation en lecture seule"),
    current_user: AuthUser = Depends(get_current_user)
):
    """Retourne la série chronologique des pesées pour l'utilisateur connecté ou un ami autorisé."""
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    profile = db.get_user_profile(user_id=target_uid)
    is_demo = bool(profile.get("is_demo_profile"))
    effective_exclude = not include_simulation if include_simulation is not None else not is_demo
    weights = db.get_weights(limit=limit, user_id=target_uid, exclude_simulation=effective_exclude)
    return [w.model_dump() for w in weights]


@app.post("/api/weights")
def create_weight(entry_in: WeightInput, current_user: AuthUser = Depends(get_current_user)):
    """Enregistre une nouvelle pesée manuelle ou connectée pour l'utilisateur connecté."""
    target_date = entry_in.date or date.today()
    
    # Estimation BMI si non fourni (sur base d'1m78)
    bmi_val = entry_in.bmi
    if bmi_val is None and entry_in.weight_kg > 0:
        bmi_val = round(entry_in.weight_kg / (1.78 ** 2), 1)

    entry = WeightEntry(
        date=target_date,
        weight_kg=entry_in.weight_kg,
        body_fat_pct=entry_in.body_fat_pct,
        muscle_mass_kg=entry_in.muscle_mass_kg,
        water_pct=entry_in.water_pct,
        bmi=bmi_val,
        source=entry_in.source,
        notes=entry_in.notes,
    )
    saved = db.insert_weight(entry, user_id=current_user.id)
    return saved.model_dump()


@app.put("/api/weights/{weight_id}")
def update_weight(weight_id: int, entry_in: WeightInput, current_user: AuthUser = Depends(get_current_user)):
    """Met à jour une pesée existante pour l'utilisateur connecté."""
    target_date = entry_in.date or date.today()
    bmi_val = entry_in.bmi
    if bmi_val is None and entry_in.weight_kg > 0:
        bmi_val = round(entry_in.weight_kg / (1.78 ** 2), 1)

    entry = WeightEntry(
        date=target_date,
        weight_kg=entry_in.weight_kg,
        body_fat_pct=entry_in.body_fat_pct,
        muscle_mass_kg=entry_in.muscle_mass_kg,
        water_pct=entry_in.water_pct,
        bmi=bmi_val,
        source=entry_in.source,
        notes=entry_in.notes,
    )
    updated = db.update_weight(weight_id, entry, user_id=current_user.id)
    if not updated:
        raise HTTPException(status_code=404, detail="Pesée introuvable")
    return updated.model_dump()


@app.delete("/api/weights/{weight_id}")
def delete_weight(weight_id: int, current_user: AuthUser = Depends(get_current_user)):
    """Supprime une pesée erronée pour l'utilisateur connecté."""
    deleted = db.delete_weight(weight_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pesée introuvable")
    return {"status": "success", "message": f"Pesée #{weight_id} supprimée avec succès"}



# =====================================================================
# Endpoints Métriques Biométriques & Visualisations Avancées (Palier 3)
# =====================================================================


@app.get("/api/daily-metrics")
def get_daily_metrics_list(
    limit: int = Query(30, ge=1, le=180, description="Nombre d'entrées"),
    source: Optional[str] = Query(None, description="Filtre source"),
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un utilisateur ami pour consultation en lecture seule"),
    current_user: AuthUser = Depends(get_current_user)
):
    """Retourne la liste des métriques quotidiennes biométriques (pas, sommeil, HRV, etc.)."""
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    metrics = db.get_daily_metrics(limit=limit, source=source, user_id=target_uid)
    return [m.model_dump() for m in metrics]

@app.get("/api/metrics")
def get_biometrics_metrics(
    days: int = Query(30, ge=7, le=90, description="Nombre de jours d'historique (30 à 90)"),
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un utilisateur ami pour consultation en lecture seule"),
    current_user: AuthUser = Depends(get_current_user)
):
    """Agrégat biométrique complet pour les visualisations Palier 3 pour l'utilisateur connecté ou un ami."""
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    user_id = target_uid

    profile = db.get_user_profile(user_id=user_id)
    is_demo = bool(profile.get("is_demo_profile"))

    # Récupération des données brutes
    daily_metrics_list = db.get_daily_metrics(limit=days, user_id=user_id)
    workouts_list = db.get_workouts(limit=days, user_id=user_id)
    sleep_sessions_list = db.get_sleep_sessions(limit=days, user_id=user_id)
    intraday_hr_samples = db.get_intraday_samples(metric_type="hr", limit=288, user_id=user_id)

    # Pesées et activités pour corrélations
    weights_list = db.get_weights(limit=days, user_id=user_id, exclude_simulation=not is_demo)
    activities_list = db.get_activities(limit=days, user_id=user_id, exclude_simulation=not is_demo)

    # Convertir en DailyBiometrics pour le moteur mathématique
    bio_history = []
    # Map date -> weight
    weights_by_date = {w.date.isoformat(): w.weight_kg for w in weights_list}
    # Map date -> activity
    acts_by_date = {a.date.isoformat(): a for a in activities_list}

    for m in daily_metrics_list:
        d_str = m.date.isoformat()
        w_val = weights_by_date.get(d_str)
        act_val = acts_by_date.get(d_str)
        act_load = m.active_calories_kcal or (act_val.active_calories_kcal if act_val else None)
        
        bio_history.append(DailyBiometrics(
            date=m.date,
            hrv_rmssd_ms=m.hrv_rmssd_ms or (act_val.hrv_ms if act_val else None),
            resting_hr_bpm=float(m.resting_hr_bpm) if m.resting_hr_bpm is not None else (float(act_val.resting_hr_bpm) if act_val and act_val.resting_hr_bpm else None),
            sleep_score=float(m.sleep_score) if m.sleep_score is not None else (float(act_val.sleep_score) if act_val and act_val.sleep_score else None),
            spo2_pct=m.spo2_pct,
            skin_temp_deviation_c=m.skin_temperature_c,
            weight_kg=w_val,
            activity_load=act_load
        ))

    analytics_svc = BiometricsAnalyticsService(target_sleep_hours=float(profile.get("target_sleep_hours", 8.0) or 8.0))

    # Dernier jour disponible
    today_bio = bio_history[-1] if bio_history else None
    prior_history = bio_history[:-1] if len(bio_history) > 1 else bio_history

    # Score de Récupération & Bandes de normalité
    recovery_data = None
    corridors_data = {}
    anomalies_data = []

    if today_bio and prior_history:
        rec_res = analytics_svc.analyze_recovery(today_bio, prior_history)
        recovery_data = {
            "score": round(rec_res.score, 1),
            "category": rec_res.category,
            "confidence": round(rec_res.confidence, 2),
            "factors_summary": rec_res.factors_summary,
            "hrv_contribution": rec_res.hrv_contribution,
            "rhr_contribution": rec_res.rhr_contribution,
            "sleep_contribution": rec_res.sleep_contribution,
            "load_contribution": rec_res.load_contribution
        }

        corrs = analytics_svc.compute_all_corridors(today_bio, prior_history)
        for k, c in corrs.items():
            corridors_data[k] = {
                "metric_name": c.metric_name,
                "median": round(c.median, 2),
                "lower_bound": round(c.lower_bound, 2),
                "upper_bound": round(c.upper_bound, 2),
                "p15": round(c.p15, 2),
                "p85": round(c.p85, 2),
                "current_value": round(c.current_value, 2) if c.current_value is not None else None,
                "is_in_corridor": c.is_in_corridor
            }

        anomalies_res = analytics_svc.detect_anomalies(today_bio, prior_history)
        anomalies_data = [
            {
                "severity": a.severity,
                "category": a.category,
                "title": a.title,
                "explanation": a.explanation,
                "actionable_insight": a.actionable_insight,
                "trigger_metrics": a.trigger_metrics
            }
            for a in anomalies_res
        ]
    elif today_bio:
        recovery_data = {
            "score": today_bio.sleep_score or 75.0,
            "category": "good",
            "confidence": 0.5,
            "factors_summary": "Données initiales enregistrées.",
            "hrv_contribution": 0.0,
            "rhr_contribution": 0.0,
            "sleep_contribution": 0.0,
            "load_contribution": 0.0
        }

    # Sommeil & Hypnogramme de la dernière session
    latest_sleep = sleep_sessions_list[-1] if sleep_sessions_list else None
    sleep_analysis = None
    if latest_sleep:
        total_h = (latest_sleep.duration_minutes or 0) / 60.0
        eff = latest_sleep.efficiency_pct or 85.0
        deep_h = (latest_sleep.deep_minutes or 0) / 60.0
        rem_h = (latest_sleep.rem_minutes or 0) / 60.0
        light_h = (latest_sleep.light_minutes or 0) / 60.0
        awake_h = (latest_sleep.awake_minutes or 0) / 60.0

        sleep_history_tuples = [
            (s.date, (s.duration_minutes or 0) / 60.0, s.efficiency_pct)
            for s in sleep_sessions_list
        ]
        curr_daily_sleep = DailyBiometrics(
            date=latest_sleep.date,
            sleep_duration_hours=total_h,
            sleep_efficiency_pct=eff,
            deep_sleep_hours=deep_h,
            rem_sleep_hours=rem_h,
            light_sleep_hours=light_h,
            awake_hours=awake_h
        )
        analyzed_sleep = analytics_svc.analyze_sleep(curr_daily_sleep, sleep_history_tuples)
        arch = analyzed_sleep["architecture"]
        debt = analyzed_sleep["debt"]

        sleep_analysis = {
            "latest_session": {
                "id": latest_sleep.id,
                "date": latest_sleep.date.isoformat(),
                "start_time": latest_sleep.start_time,
                "end_time": latest_sleep.end_time,
                "duration_minutes": latest_sleep.duration_minutes,
                "efficiency_pct": latest_sleep.efficiency_pct,
                "sleep_score": latest_sleep.sleep_score,
                "deep_minutes": latest_sleep.deep_minutes,
                "light_minutes": latest_sleep.light_minutes,
                "rem_minutes": latest_sleep.rem_minutes,
                "awake_minutes": latest_sleep.awake_minutes,
                "stages": [
                    {
                        "stage": st.stage,
                        "start_time": st.start_time,
                        "end_time": st.end_time,
                        "duration_seconds": st.duration_seconds
                    }
                    for st in latest_sleep.stages
                ]
            },
            "architecture": {
                "score": round(arch.architecture_score, 1),
                "is_restorative": arch.is_restorative,
                "deep_pct": round(arch.deep_sleep_pct, 1),
                "rem_pct": round(arch.rem_sleep_pct, 1),
                "light_pct": round(arch.light_sleep_pct, 1),
                "awake_pct": round(arch.awake_pct, 1),
                "warnings": list(arch.warnings)
            },
            "debt": {
                "target_hours": debt.target_sleep_hours,
                "cumulative_debt_hours": round(debt.cumulative_debt_hours, 2),
                "debt_level": debt.debt_level,
                "description": debt.description
            }
        }

    # Série temporelle Trends (RHR & HRV)
    trends = []
    for m in daily_metrics_list:
        d_iso = m.date.isoformat()
        act = acts_by_date.get(d_iso)
        rhr = m.resting_hr_bpm if m.resting_hr_bpm is not None else (act.resting_hr_bpm if act else None)
        hrv = m.hrv_rmssd_ms if m.hrv_rmssd_ms is not None else (act.hrv_ms if act else None)
        trends.append({
            "date": d_iso,
            "resting_hr_bpm": rhr,
            "hrv_rmssd_ms": hrv,
            "sleep_score": m.sleep_score or (act.sleep_score if act else None),
            "recovery_score": m.recovery_score
        })

    # Intraday FC 24h
    intraday_hr = [
        {
            "timestamp": s.timestamp,
            "value": s.value,
            "source": s.source
        }
        for s in intraday_hr_samples
    ]

    # Séances / Workouts
    workouts_data = [w.model_dump() for w in workouts_list]

    # Analyse Croisée & Corrélations (Poids vs Calories, Sommeil vs HRV)
    correlations_weight_calories = []
    # Créer un map des calories consommées ou brûlées
    for d_iso, w_kg in weights_by_date.items():
        act = acts_by_date.get(d_iso)
        if act and w_kg is not None:
            correlations_weight_calories.append({
                "date": d_iso,
                "weight_kg": w_kg,
                "calories_burned": act.total_burned_kcal,
                "active_calories": act.active_calories_kcal
            })

    correlations_sleep_hrv = []
    for tr in trends:
        if tr["sleep_score"] is not None and tr["hrv_rmssd_ms"] is not None:
            correlations_sleep_hrv.append({
                "date": tr["date"],
                "sleep_score": tr["sleep_score"],
                "hrv_rmssd_ms": tr["hrv_rmssd_ms"]
            })

    # Heatmap d'assiduité (30 à 90 jours : activité quotidienne présente)
    heatmap = []
    today_dt = date.today()
    for day_idx in range(days - 1, -1, -1):
        d_val = today_dt - timedelta(days=day_idx)
        d_str = d_val.isoformat()
        act = acts_by_date.get(d_str)
        m_item = next((m for m in daily_metrics_list if m.date.isoformat() == d_str), None)
        has_workout = any(w.start_time.startswith(d_str) for w in workouts_list)

        steps = (act.steps if act else (m_item.steps if m_item else 0)) or 0
        intensity = 0
        if steps >= 10000 or has_workout:
            intensity = 3  # Haut
        elif steps >= 6000:
            intensity = 2  # Moyen
        elif steps > 0:
            intensity = 1  # Faible

        heatmap.append({
            "date": d_str,
            "steps": steps,
            "has_workout": has_workout,
            "intensity": intensity
        })

    # Objectifs / Anneaux du jour
    target_steps = int(profile.get("target_steps", 10000) or 10000)
    target_calories = float(profile.get("target_calories_intake", 2000.0) or 2000.0)
    target_sleep_h = float(profile.get("target_sleep_hours", 8.0) or 8.0)

    today_str = today_dt.isoformat()
    today_act = acts_by_date.get(today_str)
    today_metric = next((m for m in daily_metrics_list if m.date.isoformat() == today_str), None)

    current_steps = (today_act.steps if today_act else (today_metric.steps if today_metric else 0)) or 0
    current_active_cals = (today_act.active_calories_kcal if today_act else (today_metric.active_calories_kcal if today_metric else 0.0)) or 0.0
    current_sleep_h = (latest_sleep.duration_minutes / 60.0) if latest_sleep else 0.0
    current_rec_score = recovery_data["score"] if recovery_data else None

    rings = {
        "steps": {
            "current": current_steps,
            "target": target_steps,
            "pct": min(100.0, round((current_steps / target_steps) * 100, 1)) if target_steps > 0 else 0.0
        },
        "active_calories": {
            "current": round(current_active_cals, 1),
            "target": 500.0,  # Cible d'exercice actif standard 500 kcal
            "pct": min(100.0, round((current_active_cals / 500.0) * 100, 1))
        },
        "sleep_recovery": {
            "current_sleep_hours": round(current_sleep_h, 1),
            "target_sleep_hours": round(target_sleep_h, 1),
            "recovery_score": current_rec_score,
            "pct": min(100.0, round((current_rec_score or (current_sleep_h / target_sleep_h * 100) if target_sleep_h > 0 else 0.0), 1))
        }
    }

    has_real_data = bool(
        daily_metrics_list or workouts_list or sleep_sessions_list or
        intraday_hr_samples or (weights_list and not is_demo) or (activities_list and not is_demo)
    )

    return {
        "status": "success",
        "has_real_data": has_real_data,
        "is_demo_profile": is_demo,
        "rings": rings,
        "recovery": recovery_data,
        "corridors": corridors_data,
        "anomalies": anomalies_data,
        "sleep": sleep_analysis,
        "trends": trends,
        "intraday_hr": intraday_hr,
        "workouts": workouts_data,
        "correlations": {
            "weight_vs_calories": correlations_weight_calories,
            "sleep_vs_hrv": correlations_sleep_hrv
        },
        "heatmap": heatmap,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


# =====================================================================
# Endpoints Activités & Exercices
# =====================================================================

@app.get("/api/activities")
@app.get("/api/activity")
def get_activities(
    limit: int = Query(30, ge=1, le=180),
    include_simulation: Optional[bool] = Query(None, description="Inclure les données simulées (défaut False hors profil démo)"),
    current_user: AuthUser = Depends(get_current_user)
):
    """Retourne la série chronologique de l'activité quotidienne pour l'utilisateur connecté."""
    profile = db.get_user_profile(user_id=current_user.id)
    is_demo = bool(profile.get("is_demo_profile"))
    effective_exclude = not include_simulation if include_simulation is not None else not is_demo
    acts = db.get_activities(limit=limit, user_id=current_user.id, exclude_simulation=effective_exclude)
    return [a.model_dump() for a in acts]


@app.post("/api/activities")
def create_activity(act_in: ActivityInput, current_user: AuthUser = Depends(get_current_user)):
    """Ajoute ou synchronise une entrée d'activité physique quotidienne pour l'utilisateur connecté."""
    target_date = act_in.date or date.today()
    bmr = 1780.0
    active_cal = act_in.active_calories_kcal
    if active_cal <= 0 and act_in.steps > 0:
        active_cal = round(act_in.steps * 0.045, 1)

    total_burned = round(bmr + active_cal, 1)

    entry = ActivityEntry(
        date=target_date,
        steps=act_in.steps,
        active_calories_kcal=active_cal,
        bmr_kcal=bmr,
        total_burned_kcal=total_burned,
        workout_minutes=act_in.workout_minutes,
        workout_type=act_in.workout_type,
        resting_hr_bpm=act_in.resting_hr_bpm,
        hrv_ms=act_in.hrv_ms,
        sleep_score=act_in.sleep_score,
        source=act_in.source
    )
    saved = db.insert_activity(entry, user_id=current_user.id)
    return saved.model_dump()


# =====================================================================
# Endpoints Nutrition, Photo IA et Journal
# =====================================================================

@app.get("/api/meals")
def get_meals(
    limit: int = Query(50, ge=1, le=200),
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un utilisateur ami pour consultation en lecture seule"),
    current_user: AuthUser = Depends(get_current_user)
):
    """Retourne les repas récemment enregistrés pour l'utilisateur connecté ou un ami autorisé."""
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    meals = db.get_meals(limit=limit, user_id=target_uid)
    return [m.model_dump() for m in meals]


@app.get("/api/meals/analyze-photo")
def get_analyze_photo_info():
    """Information et métadonnées sur le moteur d'analyse photo de repas."""
    return {
        "status": "available",
        "description": "Moteur multimodal IA Gemini Vision et fallback hybride OpenFoodFacts",
        "supported_formats": ["image/jpeg", "image/png", "image/webp"],
        "max_size_mb": 10,
        "portion_scale_range": [0.5, 2.0]
    }


@app.post("/api/meals/analyze-photo")
@app.post("/api/meals/estimate")
def estimate_meal_calories(req: MealEstimateRequest):
    """Estime les calories et macronutriments à partir d'une photo ou d'une description.
    
    Prend en compte le curseur d'ajustement de portion interactive (0.5x - 2.0x).
    """
    scale = max(0.5, min(2.0, req.portion_scale))
    
    # Décoder image éventuelle si fournie sous forme data-url
    image_bytes = None
    mime_type = "image/jpeg"
    if req.photo_data_url and "base64," in req.photo_data_url:
        import base64
        try:
            header, encoded = req.photo_data_url.split("base64,", 1)
            if "image/png" in header:
                mime_type = "image/png"
            elif "image/webp" in header:
                mime_type = "image/webp"
            image_bytes = base64.b64decode(encoded)
        except Exception:
            image_bytes = None

    result = calorie_estimator.analyze_meal(
        image_bytes=image_bytes,
        mime_type=mime_type,
        description=req.description,
        portion_scale=scale,
        meal_type=req.meal_type
    )
    # Aplatir les macros à la racine si présentes pour compatibilité client
    if isinstance(result, dict) and "macros" in result and isinstance(result["macros"], dict):
        macros = result["macros"]
        result.setdefault("protein_g", macros.get("protein_g", 0.0))
        result.setdefault("carbs_g", macros.get("carbs_g", 0.0))
        result.setdefault("fat_g", macros.get("fat_g", 0.0))
        result.setdefault("fiber_g", macros.get("fiber_g", 0.0))
    return result


@app.post("/api/meals")
def log_meal(req: MealSaveRequest, current_user: AuthUser = Depends(get_current_user)):
    """Enregistre définitivement un repas décomposé ou direct dans le journal alimentaire pour l'utilisateur connecté."""
    target_date = req.date or date.today()
    
    if req.items:
        items = req.items
        saved = nutrition_engine.log_meal(
            date_val=target_date,
            meal_type=req.meal_type,
            items=items,
            photo_data_url=req.photo_data_url,
            user_id=current_user.id
        )
    elif req.total_calories_kcal is not None:
        meal_name = req.meal_name or f"Repas direct ({req.meal_type})"
        items = [
            FoodItem(
                name=meal_name,
                calories_kcal=round(req.total_calories_kcal, 1),
                protein_g=round(req.protein_g or 0.0, 1),
                carbs_g=round(req.carbs_g or 0.0, 1),
                fat_g=round(req.fat_g or 0.0, 1),
                fiber_g=round(req.fiber_g or 0.0, 1),
                confidence_score=1.0
            )
        ]
        entry = MealEntry(
            date=target_date,
            meal_type=req.meal_type,
            total_calories_kcal=round(req.total_calories_kcal, 1),
            protein_g=round(req.protein_g or 0.0, 1),
            carbs_g=round(req.carbs_g or 0.0, 1),
            fat_g=round(req.fat_g or 0.0, 1),
            fiber_g=round(req.fiber_g or 0.0, 1),
            photo_data_url=req.photo_data_url,
            items=items
        )
        saved = db.insert_meal(entry, user_id=current_user.id)
    else:
        est = calorie_estimator.analyze_meal(
            description=None,
            portion_scale=req.portion_scale,
            meal_type=req.meal_type
        )
        items = [FoodItem(**item) for item in est.get("items", [])]
        saved = nutrition_engine.log_meal(
            date_val=target_date,
            meal_type=req.meal_type,
            items=items,
            photo_data_url=req.photo_data_url,
            user_id=current_user.id
        )
    return saved.model_dump()


@app.put("/api/meals/{meal_id}")
def update_meal(meal_id: int, req: MealSaveRequest, current_user: AuthUser = Depends(get_current_user)):
    """Met à jour un repas existant dans le journal pour l'utilisateur connecté."""
    target_date = req.date or date.today()
    if req.items:
        items = req.items
        tot_cal = round(sum(i.calories_kcal for i in items), 1)
        tot_prot = round(sum(i.protein_g for i in items), 1)
        tot_carbs = round(sum(i.carbs_g for i in items), 1)
        tot_fat = round(sum(i.fat_g for i in items), 1)
        tot_fiber = round(sum(i.fiber_g or 0.0 for i in items), 1)
    elif req.total_calories_kcal is not None:
        meal_name = req.meal_name or f"Repas direct ({req.meal_type})"
        items = [
            FoodItem(
                name=meal_name,
                calories_kcal=round(req.total_calories_kcal, 1),
                protein_g=round(req.protein_g or 0.0, 1),
                carbs_g=round(req.carbs_g or 0.0, 1),
                fat_g=round(req.fat_g or 0.0, 1),
                fiber_g=round(req.fiber_g or 0.0, 1),
                confidence_score=1.0
            )
        ]
        tot_cal = round(req.total_calories_kcal, 1)
        tot_prot = round(req.protein_g or 0.0, 1)
        tot_carbs = round(req.carbs_g or 0.0, 1)
        tot_fat = round(req.fat_g or 0.0, 1)
        tot_fiber = round(req.fiber_g or 0.0, 1)
    else:
        raise HTTPException(status_code=400, detail="Données de repas invalides")

    entry = MealEntry(
        date=target_date,
        meal_type=req.meal_type,
        total_calories_kcal=tot_cal,
        protein_g=tot_prot,
        carbs_g=tot_carbs,
        fat_g=tot_fat,
        fiber_g=tot_fiber,
        photo_data_url=req.photo_data_url,
        items=items
    )
    updated = db.update_meal(meal_id, entry, user_id=current_user.id)
    if not updated:
        raise HTTPException(status_code=404, detail="Repas introuvable")
    return updated.model_dump()


@app.delete("/api/meals/{meal_id}")
def delete_meal(meal_id: int, current_user: AuthUser = Depends(get_current_user)):
    """Supprime un repas du journal pour l'utilisateur connecté."""
    deleted = db.delete_meal(meal_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Repas introuvable")
    return {"status": "success", "message": f"Repas #{meal_id} supprimé avec succès"}


# =====================================================================
# Endpoints Bibliothèque de Plats Sauvegardés / Favoris Réutilisables
# =====================================================================

@app.get("/api/meals/saved")
def list_saved_meals(
    meal_type: Optional[str] = Query(None, description="Filtre par repas (breakfast, lunch, snack, dinner)"),
    is_favorite: Optional[bool] = Query(None, description="Filtre par favoris"),
    current_user: AuthUser = Depends(get_current_user)
):
    """Récupère la liste des plats sauvegardés/réutilisables de l'utilisateur connecté."""
    meals = db.get_saved_meals(meal_type=meal_type, is_favorite=is_favorite, user_id=current_user.id)
    return [m.model_dump() for m in meals]


@app.post("/api/meals/saved")
def create_saved_meal(
    req: SavedMealCreateRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """Crée et enregistre un nouveau plat type dans la bibliothèque réutilisable."""
    saved_meal = SavedMeal(
        user_id=current_user.id,
        name=req.name,
        meal_type=req.meal_type,
        serving_size=req.serving_size or "1 portion",
        quantity_grams=req.quantity_grams,
        calories=req.calories,
        protein_g=req.protein_g,
        carbs_g=req.carbs_g,
        fat_g=req.fat_g,
        fiber_g=req.fiber_g or 0.0,
        ingredients=req.ingredients,
        items=req.items or [],
        photo_url=req.photo_url,
        is_favorite=bool(req.is_favorite)
    )
    created = db.insert_saved_meal(saved_meal, user_id=current_user.id)
    return created.model_dump()


@app.get("/api/meals/saved/{meal_id}")
def get_saved_meal(
    meal_id: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Récupère les détails d'un plat type réutilisable."""
    saved = db.get_saved_meal_by_id(meal_id, user_id=current_user.id)
    if not saved:
        raise HTTPException(status_code=404, detail="Plat réutilisable introuvable")
    return saved.model_dump()


@app.put("/api/meals/saved/{meal_id}")
def update_saved_meal(
    meal_id: int,
    req: SavedMealUpdateRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """Met à jour un plat type réutilisable existant."""
    existing = db.get_saved_meal_by_id(meal_id, user_id=current_user.id)
    if not existing:
        raise HTTPException(status_code=404, detail="Plat réutilisable introuvable")

    data = existing.model_dump()
    req_data = req.model_dump(exclude_unset=True)
    for k, v in req_data.items():
        if v is not None:
            data[k] = v

    to_save = SavedMeal(**data)
    updated = db.update_saved_meal(meal_id, to_save, user_id=current_user.id)
    if not updated:
        raise HTTPException(status_code=404, detail="Plat réutilisable introuvable")
    return updated.model_dump()


@app.delete("/api/meals/saved/{meal_id}")
def delete_saved_meal(
    meal_id: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Supprime un plat réutilisable de la bibliothèque."""
    deleted = db.delete_saved_meal(meal_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Plat réutilisable introuvable")
    return {"status": "success", "message": f"Plat sauvegardé #{meal_id} supprimé avec succès"}


@app.post("/api/meals/saved/{meal_id}/log")
def log_saved_meal_to_journal(
    meal_id: int,
    req: SavedMealLogRequest = SavedMealLogRequest(),
    current_user: AuthUser = Depends(get_current_user)
):
    """Logge instantanément un plat réutilisable dans le journal alimentaire du jour."""
    saved = db.get_saved_meal_by_id(meal_id, user_id=current_user.id)
    if not saved:
        raise HTTPException(status_code=404, detail="Plat réutilisable introuvable")

    factor = req.portion_factor if req.portion_factor is not None else 1.0
    target_date = req.date or date.today()
    meal_type = req.meal_type or saved.meal_type

    # Mise à l'échelle des aliments ou de l'aliment global
    if saved.items:
        scaled_items = []
        for it in saved.items:
            scaled_items.append(FoodItem(
                name=it.name,
                portion_g=round(it.portion_g * factor, 1) if it.portion_g else None,
                calories_kcal=round(it.calories_kcal * factor, 1),
                protein_g=round(it.protein_g * factor, 1),
                carbs_g=round(it.carbs_g * factor, 1),
                fat_g=round(it.fat_g * factor, 1),
                fiber_g=round((it.fiber_g or 0.0) * factor, 1),
                confidence_score=it.confidence_score
            ))
    else:
        scaled_items = [FoodItem(
            name=saved.name,
            portion_g=round(saved.quantity_grams * factor, 1) if saved.quantity_grams else None,
            calories_kcal=round(saved.calories * factor, 1),
            protein_g=round(saved.protein_g * factor, 1),
            carbs_g=round(saved.carbs_g * factor, 1),
            fat_g=round(saved.fat_g * factor, 1),
            fiber_g=round((saved.fiber_g or 0.0) * factor, 1),
            confidence_score=1.0
        )]

    entry = MealEntry(
        date=target_date,
        meal_type=meal_type,
        total_calories_kcal=round(saved.calories * factor, 1),
        protein_g=round(saved.protein_g * factor, 1),
        carbs_g=round(saved.carbs_g * factor, 1),
        fat_g=round(saved.fat_g * factor, 1),
        fiber_g=round((saved.fiber_g or 0.0) * factor, 1),
        photo_data_url=saved.photo_url,
        items=scaled_items
    )

    logged = db.insert_meal(entry, user_id=current_user.id)
    return {
        "status": "success",
        "message": f"Plat '{saved.name}' ajouté au journal ({meal_type}) avec portion x{factor}",
        "logged_meal": logged.model_dump()
    }




# =====================================================================
# Endpoints Catalogue d'Aliments & Plats (Stage 12)
# =====================================================================

class UpdateCatalogItemBenefitsRequest(BaseModel):
    benefits: List[Dict[str, Any]] = Field(default_factory=list, description="Liste des bienfaits associés [{benefit_id, source, explanation}]")


class NutritionEvaluateRequest(BaseModel):
    name: Optional[str] = None
    default_quantity: Optional[float] = None
    portion_g: Optional[float] = None
    quantity_grams: Optional[float] = None
    calories: Optional[float] = None
    calories_per_unit: Optional[float] = None
    calories_kcal: Optional[float] = None
    protein_g: Optional[float] = None
    protein_per_unit_g: Optional[float] = None
    carbs_g: Optional[float] = None
    carbs_per_unit_g: Optional[float] = None
    fat_g: Optional[float] = None
    fat_per_unit_g: Optional[float] = None
    fiber_g: Optional[float] = None
    fiber_per_unit_g: Optional[float] = None
    sugars_g: Optional[float] = None
    saturated_fat_g: Optional[float] = None
    unsaturated_fat_g: Optional[float] = None
    sodium_mg: Optional[float] = None
    potassium_mg: Optional[float] = None
    calcium_mg: Optional[float] = None
    water_pct: Optional[float] = None
    ingredients: Optional[str] = None


class CatalogItemCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Nom de l'aliment ou du plat")
    item_type: Literal["food", "dish"] = Field("food", description="'food' pour aliment simple, 'dish' pour plat/recette")
    default_unit: str = Field("g", description="Unité de référence (g, portion, ml, pièce)")
    default_quantity: float = Field(100.0, gt=0, description="Quantité de référence")
    calories_per_unit: float = Field(..., ge=0.0, description="Calories (kcal) pour la quantité de référence")
    protein_per_unit_g: float = Field(0.0, ge=0.0, description="Protéines (g)")
    carbs_per_unit_g: float = Field(0.0, ge=0.0, description="Glucides (g)")
    fat_per_unit_g: float = Field(0.0, ge=0.0, description="Lipides (g)")
    fiber_per_unit_g: Optional[float] = Field(0.0, ge=0.0, description="Fibres (g)")
    photo_url: Optional[str] = Field(None, description="Photo ou data URL")
    recipe_items: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Ingrédients composant le plat")
    benefits: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Bienfaits associés à la création")
    is_public: Optional[bool] = Field(False, description="True si l'aliment doit être public")


class CatalogItemUpdateRequest(BaseModel):
    name: Optional[str] = None
    item_type: Optional[Literal["food", "dish"]] = None
    default_unit: Optional[str] = None
    default_quantity: Optional[float] = None
    calories_per_unit: Optional[float] = None
    protein_per_unit_g: Optional[float] = None
    carbs_per_unit_g: Optional[float] = None
    fat_per_unit_g: Optional[float] = None
    fiber_per_unit_g: Optional[float] = None
    photo_url: Optional[str] = None
    recipe_items: Optional[List[Dict[str, Any]]] = None
    is_public: Optional[bool] = None


class CatalogSubscriptionCreateRequest(BaseModel):
    target_user_id: Optional[int] = Field(None, description="ID de l'utilisateur auquel s'abonner")
    email: Optional[str] = Field(None, description="Email de l'utilisateur auquel s'abonner")


class MealJournalAddItemRequest(BaseModel):
    date: Optional[dt_module.date] = None
    food_item_id: Optional[int] = None
    name: Optional[str] = None
    quantity: float = Field(..., gt=0, description="Quantité consommée")
    unit: Optional[str] = "g"
    # Macros optionnelles si pas de food_item_id
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    fiber_g: Optional[float] = None


class MealJournalAddBatchRequest(BaseModel):
    date: Optional[dt_module.date] = None
    items: List[MealJournalAddItemRequest] = Field(..., min_length=1)


class SaveAsDishRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Nom du plat à créer dans le catalogue")
    date: Optional[dt_module.date] = None
    photo_url: Optional[str] = None


@app.get("/api/catalog/items")
def get_catalog_items(
    type: Optional[str] = Query(None, description="Filtre par type ('food' ou 'dish')"),
    q: Optional[str] = Query(None, description="Recherche textuelle par nom"),
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un ami pour consultation en lecture seule"),
    source: Optional[str] = Query(None, description="Source des aliments ('all', 'mine', 'public', 'friends')"),
    friend_id: Optional[int] = Query(None, description="ID d'un ami spécifique pour explorer son catalogue"),
    current_user: AuthUser = Depends(get_current_user)
):
    """Récupère le catalogue d'aliments et de plats selon la source (all, mine, public, friends) ou friend_id."""
    # Consultation en lecture seule : cible l'utilisateur concerné (ami ou soi-même) après vérification d'accès.
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    # Par défaut, si friend_id est spécifié on filtre sur l'ami, sinon si source n'est pas spécifié, on retourne "mine"
    effective_source = source if source is not None else ("mine" if not friend_id else "friends")
    items = db.get_food_items(
        item_type=type,
        query=q,
        user_id=target_uid,
        source=effective_source,
        friend_id=friend_id
    )
    return [it.model_dump() for it in items]


@app.post("/api/catalog/items")
def create_catalog_item(
    req: CatalogItemCreateRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """Crée un nouvel aliment ou plat dans le catalogue."""
    item = CatalogItem(
        user_id=current_user.id,
        name=req.name.strip(),
        item_type=req.item_type,
        default_unit=req.default_unit or "g",
        default_quantity=req.default_quantity or 100.0,
        calories_per_unit=req.calories_per_unit,
        protein_per_unit_g=req.protein_per_unit_g or 0.0,
        carbs_per_unit_g=req.carbs_per_unit_g or 0.0,
        fat_per_unit_g=req.fat_per_unit_g or 0.0,
        fiber_per_unit_g=req.fiber_per_unit_g or 0.0,
        photo_url=req.photo_url,
        recipe_items=req.recipe_items or [],
        is_public=bool(req.is_public)
    )
    created = db.insert_food_item(item, user_id=current_user.id)
    return created.model_dump()


@app.put("/api/catalog/items/{item_id}")
def update_catalog_item(
    item_id: int,
    req: CatalogItemUpdateRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """Met à jour un aliment ou un plat du catalogue."""
    update_data = {k: v for k, v in req.model_dump().items() if v is not None}
    updated = db.update_food_item(item_id, update_data, user_id=current_user.id)
    if not updated:
        raise HTTPException(status_code=404, detail="Élément de catalogue introuvable ou non autorisé")
    return updated.model_dump()


@app.delete("/api/catalog/items/{item_id}")
def delete_catalog_item(
    item_id: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Supprime un aliment ou un plat du catalogue."""
    deleted = db.delete_food_item(item_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Élément de catalogue introuvable ou non autorisé")
    return {"status": "success", "message": f"Élément #{item_id} supprimé du catalogue"}


# ---------------------------------------------------------
# Abonnements aux catalogues d'amis
# ---------------------------------------------------------

@app.get("/api/catalog/subscriptions")
def get_catalog_subscriptions(current_user: AuthUser = Depends(get_current_user)):
    """Liste tous les catalogues d'amis auxquels l'utilisateur est abonné."""
    subs = db.get_catalog_subscriptions(subscriber_id=current_user.id)
    return subs


@app.post("/api/catalog/subscriptions")
def create_catalog_subscription(
    req: CatalogSubscriptionCreateRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """S'abonne au catalogue d'un utilisateur par son ID ou son adresse email."""
    target_user_id = req.target_user_id
    if not target_user_id and req.email:
        target_user = db.get_user_by_email(req.email)
        if not target_user:
            raise HTTPException(status_code=404, detail="Utilisateur cible introuvable")
        target_user_id = target_user["id"]

    if not target_user_id:
        raise HTTPException(status_code=400, detail="target_user_id ou email obligatoire")

    if target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Impossible de s'abonner à son propre catalogue")

    success = db.add_catalog_subscription(subscriber_id=current_user.id, target_user_id=target_user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Utilisateur cible introuvable")

    return {
        "status": "success",
        "message": f"Abonnement au catalogue de l'utilisateur #{target_user_id} activé",
        "subscriber_id": current_user.id,
        "target_user_id": target_user_id
    }


@app.delete("/api/catalog/subscriptions/{target_user_id}")
def delete_catalog_subscription(
    target_user_id: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Se désabonne du catalogue d'un ami."""
    removed = db.remove_catalog_subscription(subscriber_id=current_user.id, target_user_id=target_user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Abonnement introuvable ou déjà supprimé")
    return {
        "status": "success",
        "message": f"Désabonnement du catalogue #{target_user_id} effectué"
    }


@app.get("/api/catalog/friends/{target_user_id}/items")
def get_friend_catalog_items(
    target_user_id: int,
    type: Optional[str] = Query(None, description="Filtre par type ('food' ou 'dish')"),
    q: Optional[str] = Query(None, description="Recherche textuelle par nom"),
    current_user: AuthUser = Depends(get_current_user)
):
    """Explore le catalogue complet d'un ami spécifique."""
    friend = db.get_user_by_id(target_user_id)
    if not friend:
        raise HTTPException(status_code=404, detail="Ami introuvable")

    items = db.get_food_items(
        item_type=type,
        query=q,
        user_id=current_user.id,
        source="mine",
        friend_id=target_user_id
    )
    return {
        "friend": {
            "id": friend["id"],
            "name": friend.get("name"),
            "email": friend.get("email"),
            "picture": friend.get("picture")
        },
        "is_subscribed": db.is_subscribed_to_catalog(current_user.id, target_user_id),
        "items": [it.model_dump() for it in items]
    }


@app.get("/api/catalog/items/{item_id}/benefits")
def get_catalog_item_benefits(
    item_id: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Récupère les bienfaits associés à un aliment/plat donné."""
    item = db.get_food_item_by_id(item_id, user_id=current_user.id)
    if not item:
        raise HTTPException(status_code=404, detail="Élément de catalogue introuvable")
    benefits = db.get_food_item_benefits(item_id)
    return [b.model_dump() for b in benefits]


@app.put("/api/catalog/items/{item_id}/benefits")
def update_catalog_item_benefits(
    item_id: int,
    req: UpdateCatalogItemBenefitsRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """Met à jour les bienfaits associés à un aliment/plat donné (sélection manuelle ou auto)."""
    item = db.get_food_item_by_id(item_id, user_id=current_user.id)
    if not item:
        raise HTTPException(status_code=404, detail="Élément de catalogue introuvable")
    updated_benefits = db.set_food_item_benefits(item_id, req.benefits)
    return [b.model_dump() for b in updated_benefits]


@app.get("/api/nutrition/benefits")
def get_nutrition_benefits():
    """Récupère la liste de tous les bienfaits disponibles dans le référentiel expert groupés par catégorie."""
    all_benefits = db.get_all_nutrition_benefits()
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for b in all_benefits:
        if b.category not in grouped:
            grouped[b.category] = []
        grouped[b.category].append(b.model_dump())
    return {
        "count": len(all_benefits),
        "benefits": [b.model_dump() for b in all_benefits],
        "categories": grouped
    }


@app.post("/api/nutrition/evaluate")
def evaluate_nutrition_benefits(req: NutritionEvaluateRequest):
    """Évalue instantanément un ensemble de valeurs nutritionnelles et retourne les bienfaits qualifiés (règles EFSA/ANSES)."""
    data = req.model_dump()
    results = evaluate_dish_benefits(data)
    return {
        "matched_count": len(results),
        "results": [r.model_dump() for r in results]
    }


# =====================================================================
# Endpoints Journal des Repas Quotidiens (Stage 12)
# =====================================================================

def calculate_day_summary(target_date: date, user_id: int = 1) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Calcule les 4 repas et le résumé nutritionnel de la journée sans écriture en base."""
    logs = db.get_meal_logs_for_date(target_date, user_id=user_id)
    logs_by_type = {log.meal_type: log for log in logs}

    meal_types = ["breakfast", "lunch", "snack", "dinner"]
    meals_response = []
    day_total_cal = 0.0
    day_total_prot = 0.0
    day_total_carbs = 0.0
    day_total_fat = 0.0
    day_total_fiber = 0.0

    for mt in meal_types:
        mlog = logs_by_type.get(mt)
        if not mlog:
            mlog = MealLog(
                id=None,
                user_id=user_id,
                date=target_date,
                meal_type=mt,
                total_calories=0.0,
                total_protein_g=0.0,
                total_carbs_g=0.0,
                total_fat_g=0.0,
                total_fiber_g=0.0,
                items=[]
            )
        m_dict = mlog.model_dump()
        meals_response.append(m_dict)

        day_total_cal += mlog.total_calories
        day_total_prot += mlog.total_protein_g
        day_total_carbs += mlog.total_carbs_g
        day_total_fat += mlog.total_fat_g
        day_total_fiber += (mlog.total_fiber_g or 0.0)

    cal_p = day_total_prot * 4.0
    cal_c = day_total_carbs * 4.0
    cal_f = day_total_fat * 9.0
    sum_macro_cal = cal_p + cal_c + cal_f
    macros_pct = {
        "protein_pct": round((cal_p / sum_macro_cal) * 100.0, 1) if sum_macro_cal > 0 else 0.0,
        "carbs_pct": round((cal_c / sum_macro_cal) * 100.0, 1) if sum_macro_cal > 0 else 0.0,
        "fat_pct": round((cal_f / sum_macro_cal) * 100.0, 1) if sum_macro_cal > 0 else 0.0
    }

    day_summary = {
        "total_calories": round(day_total_cal, 1),
        "total_protein_g": round(day_total_prot, 1),
        "total_carbs_g": round(day_total_carbs, 1),
        "total_fat_g": round(day_total_fat, 1),
        "total_fiber_g": round(day_total_fiber, 1),
        "macros_pct": macros_pct
    }
    return meals_response, day_summary


@app.get("/api/meals/journal")
def get_meals_journal(
    date_param: Optional[str] = Query(None, alias="date", description="Date YYYY-MM-DD"),
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un utilisateur ami pour consultation en lecture seule"),
    current_user: AuthUser = Depends(get_current_user)
):
    """Récupère les 4 repas du jour avec la composition et les totaux (lecture pure sans écriture en base)."""
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    target_date = date.fromisoformat(date_param) if date_param else date.today()
    meals_response, day_summary = calculate_day_summary(target_date, user_id=target_uid)

    return {
        "date": target_date.isoformat(),
        "meals": meals_response,
        "day_summary": day_summary
    }


@app.post("/api/meals/journal/{meal_type}/items")
def add_item_to_meal_journal(
    meal_type: str,
    payload: Union[MealJournalAddItemRequest, MealJournalAddBatchRequest, List[MealJournalAddItemRequest]],
    current_user: AuthUser = Depends(get_current_user)
):
    """Ajoute un ou plusieurs aliments/plats (avec quantité spécifiée) dans le repas d'une date."""
    if meal_type not in ["breakfast", "lunch", "snack", "dinner"]:
        raise HTTPException(status_code=400, detail="meal_type invalide (breakfast, lunch, snack, dinner)")

    # Déterminer la liste d'items à ajouter
    if isinstance(payload, list):
        items_to_add = payload
        target_date = date.today()
    elif isinstance(payload, MealJournalAddBatchRequest):
        items_to_add = payload.items
        target_date = payload.date or date.today()
    else:
        items_to_add = [payload]
        target_date = payload.date or date.today()

    last_log = None
    for it in items_to_add:
        item_target_date = it.date or target_date
        # Résolution par food_item_id si fourni
        food_item = None
        if it.food_item_id:
            food_item = db.get_food_item_by_id(it.food_item_id, user_id=current_user.id)
            if not food_item:
                raise HTTPException(status_code=404, detail=f"Aliment de catalogue #{it.food_item_id} introuvable")

        name = it.name or (food_item.name if food_item else "Aliment")
        unit = it.unit or (food_item.default_unit if food_item else "g")
        qty = it.quantity

        if food_item:
            ratio = qty / (food_item.default_quantity or 100.0)
            cal = round(food_item.calories_per_unit * ratio, 1)
            prot = round(food_item.protein_per_unit_g * ratio, 1)
            carbs = round(food_item.carbs_per_unit_g * ratio, 1)
            fat = round(food_item.fat_per_unit_g * ratio, 1)
            fiber = round((food_item.fiber_per_unit_g or 0.0) * ratio, 1)
        else:
            cal = it.calories if it.calories is not None else 0.0
            prot = it.protein_g if it.protein_g is not None else 0.0
            carbs = it.carbs_g if it.carbs_g is not None else 0.0
            fat = it.fat_g if it.fat_g is not None else 0.0
            fiber = it.fiber_g if it.fiber_g is not None else 0.0

        last_log = db.add_item_to_meal_log(
            date_val=item_target_date,
            meal_type=meal_type,
            name=name,
            quantity=qty,
            unit=unit,
            calories=cal,
            protein_g=prot,
            carbs_g=carbs,
            fat_g=fat,
            fiber_g=fiber,
            food_item_id=it.food_item_id,
            user_id=current_user.id
        )

    action_date = last_log.date if last_log else target_date
    _, day_summary = calculate_day_summary(action_date, user_id=current_user.id)

    return {
        "status": "success",
        "meal_type": meal_type,
        "meal_log": last_log.model_dump() if last_log else None,
        "day_summary": day_summary
    }


@app.delete("/api/meals/journal/items/{item_id}")
def delete_meal_journal_item(
    item_id: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Retire un aliment d'un repas et actualise le repas parent."""
    updated_log = db.delete_meal_log_item(item_id, user_id=current_user.id)
    if not updated_log:
        raise HTTPException(status_code=404, detail="Ligne d'aliment introuvable dans le journal")

    _, day_summary = calculate_day_summary(updated_log.date, user_id=current_user.id)

    return {
        "status": "success",
        "message": f"Aliment #{item_id} retiré du repas",
        "meal_log": updated_log.model_dump(),
        "day_summary": day_summary
    }


@app.post("/api/meals/journal/{meal_type}/save-as-dish")
def save_meal_as_dish(
    meal_type: str,
    req: SaveAsDishRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """Transforme la composition d'un repas consommé en un nouveau plat réutilisable dans le catalogue."""
    target_date = req.date or date.today()
    meal_log = db.get_or_create_meal_log(target_date, meal_type, user_id=current_user.id)

    if not meal_log.items:
        raise HTTPException(status_code=400, detail="Ce repas ne contient aucun aliment à sauvegarder comme plat")

    dish_item = CatalogItem(
        user_id=current_user.id,
        name=req.name.strip(),
        item_type="dish",
        default_unit="portion",
        default_quantity=1.0,
        calories_per_unit=meal_log.total_calories,
        protein_per_unit_g=meal_log.total_protein_g,
        carbs_per_unit_g=meal_log.total_carbs_g,
        fat_per_unit_g=meal_log.total_fat_g,
        fiber_per_unit_g=meal_log.total_fiber_g or 0.0,
        photo_url=req.photo_url or meal_log.photo_url
    )
    created_dish = db.insert_food_item(dish_item, user_id=current_user.id)
    return {
        "status": "success",
        "message": f"Repas transformé en plat '{created_dish.name}' dans votre catalogue !",
        "dish": created_dish.model_dump()
    }

# =====================================================================
# Endpoints Hub Objets Connectés & Gestion de Flotte Sécurisée
# =====================================================================

@app.get("/api/devices")
@app.post("/api/devices")
@app.get("/api/devices/")
@app.post("/api/devices/")
def list_devices(current_user: AuthUser = Depends(get_current_user)):
    """Liste tous les objets connectés de l'utilisateur avec leur statut temps réel et métriques récentes."""
    user_id = current_user.id if current_user else 1
    saved_devices = {dev["device_id"]: dev for dev in db.get_user_devices(user_id=user_id)}
    statuses = []
    for d in device_registry.list_all():
        saved_d = saved_devices.get(d.id, {})
        is_conn = bool(saved_d.get("connected"))
        sync_status = saved_d.get("sync_status", "connected" if is_conn else "disconnected")
        last_sync = saved_d.get("last_sync_at") or saved_d.get("last_sync")

        statuses.append({
            "id": d.id,
            "device_id": d.id,
            "name": saved_d.get("name") or d.name,
            "device_type": d.device_type,
            "is_configured": is_conn,
            "connected": is_conn,
            "status": sync_status,
            "sync_status": sync_status,
            "last_sync": last_sync,
            "last_sync_at": last_sync,
            "has_credentials": bool(saved_d.get("has_credentials")),
            "api_key_masked": saved_d.get("api_key_masked"),
            "supported_features": getattr(d, "supported_features", ["sync", "demo_mode"])
        })
    return statuses


@app.get("/api/devices/comparison")
def get_devices_comparison():
    """Guide comparatif technique pour le choix de la balance connectée et l'interconnexion bague."""
    return {
        "title": "Guide Comparatif des Balances Connectées & Configuration Bague",
        "author": "Ingénieur Vision Nutrition & Coach Métabolique",
        "last_updated": "2026-10-18",
        "recommendation": "Withings Body Smart / Body Comp",
        "recommendation_summary": "Withings est la solution n°1 recommandée grâce à son API OAuth2 officielle ouverte, gratuite et sans restriction de clés développeur, permettant la synchronisation automatique cloud-to-cloud directe du poids et de l'impédancemétrie.",
        "scales": [
            {
                "id": "withings",
                "name": "Withings Body Smart / Body Comp",
                "brand": "Withings",
                "price_approx": "100 € - 199 €",
                "connectivity": ["Wi-Fi", "Bluetooth"],
                "api_type": "OAuth 2.0 REST API Cloud-to-Cloud directe",
                "api_openness": "Excellente (API ouverte, documentation complète, jetons illimités)",
                "metrics": [
                    "Poids (résolution 50g)",
                    "Masse grasse (%)",
                    "Masse musculaire (kg)",
                    "Masse osseuse (kg)",
                    "Masse hydrique (%)",
                    "Graisse viscérale",
                    "Rythme cardiaque stationnaire"
                ],
                "ease_of_sync": "5/5 (100% automatique après pesée via Wi-Fi direct)",
                "vitaltrack_support": "Natif (connecteur `WithingsScaleConnector` dans `src/connectors/withings.py`)",
                "verdict": "Choix Recommandé n°1 : Ingestion instantanée sans intermédiaire."
            },
            {
                "id": "garmin",
                "name": "Garmin Index S2",
                "brand": "Garmin",
                "price_approx": "149 €",
                "connectivity": ["Wi-Fi", "ANT+", "Bluetooth"],
                "api_type": "Garmin Connect Developer Program / Health Sync Webhook",
                "api_openness": "Moyenne (L'API officielle Garmin Connect nécessite une validation d'entreprise ; synchronisation possible via pont Health Sync ou Apple Santé)",
                "metrics": [
                    "Poids",
                    "IMC",
                    "Masse grasse (%)",
                    "Masse musculaire squelettique",
                    "Masse osseuse",
                    "Masse hydrique (%)"
                ],
                "ease_of_sync": "3.5/5 (Nécessite soit un pont webhook Apple Santé/Android, soit accès pro)",
                "vitaltrack_support": "Via Webhook universel (`/api/webhook/health`) ou template (`TemplateHealthConnector`)",
                "verdict": "Excellent choix pour les adeptes de montres Garmin via pont Health Connect."
            },
            {
                "id": "xiaomi",
                "name": "Xiaomi Mi Body Composition Scale 2",
                "brand": "Xiaomi",
                "price_approx": "25 € - 35 €",
                "connectivity": ["Bluetooth uniquement (BLE)"],
                "api_type": "Aucune API Cloud publique ; synchro via Mi Fitness / Zepp Life -> Health Connect",
                "api_openness": "Faible (fermé, Bluetooth local uniquement)",
                "metrics": [
                    "Poids",
                    "Masse grasse (%)",
                    "Masse musculaire",
                    "Masse hydrique (%)",
                    "Graisse viscérale",
                    "Métabolisme de base estimé"
                ],
                "ease_of_sync": "3/5 (Obligation d'ouvrir l'app mobile en Bluetooth pour remonter les données vers Health Connect)",
                "vitaltrack_support": "Via Webhook Health Connect (`/api/webhook/health`)",
                "verdict": "Option très économique mais nécessite l'intermédiaire du smartphone."
            }
        ],
        "ring_integration": {
            "name": "RingConn Gen 3 & Bagues de Santé (RingConn / Oura)",
            "primary_ring": "RingConn Gen 3",
            "api_type": "RingConn Open API & Google Health Connect (Android)",
            "sync_flow": "Synchronisation matinale & continue : Récupération du score de sommeil, HRV nocturne (RMSSD), Fréquence Cardiaque au repos, BMR, pas et calories actives soit via Google Health Connect, soit via API RingConn.",
            "status": "Connecteur RingConn et passerelle Google Health Connect actifs (`RingConnConnector` dans `src/connectors/ringconn.py`)"
        }
    }


@app.post("/api/devices/connect")
def connect_device_wizard(connect_in: DeviceConnectInput, current_user: AuthUser = Depends(get_current_user)):
    """Assistant de connexion d'un objet connecté (RingConn Gen 3, Google Health Connect, Withings, Oura) pour l'utilisateur connecté avec chiffrement et test immédiat."""
    connector = device_registry.get(connect_in.device_id)
    name = connect_in.name or (getattr(connector, "name", connect_in.device_id.title()) if connector else connect_in.device_id.title())
    dev_type = connect_in.device_type or (getattr(connector, "device_type", "health_sensor") if connector else "health_sensor")

    # Consolidation des credentials
    creds = dict(connect_in.credentials) if connect_in.credentials else {}
    if connect_in.api_key:
        creds["api_key"] = connect_in.api_key
    if connect_in.token:
        creds["token"] = connect_in.token
    if connect_in.account_email:
        creds["account_email"] = connect_in.account_email

    # Test de connectivité si supporté
    connectivity_test = {"ok": True, "message": "Connexion établie avec succès"}
    if connector and hasattr(connector, "test_connection"):
        try:
            connectivity_test = connector.test_connection()
        except Exception as e:
            connectivity_test = {"ok": False, "message": f"Test de liaison échoué: {e}"}

    saved = db.update_user_device(
        device_id=connect_in.device_id,
        name=name,
        device_type=dev_type,
        connected=connect_in.connected,
        auth_type=connect_in.auth_type or "connected",
        api_key=connect_in.api_key or connect_in.token,
        credentials=creds,
        account_email=connect_in.account_email,
        sync_status="connected" if connectivity_test.get("ok", True) else "error",
        user_id=current_user.id
    )

    # Si c'est une bague ou une balance, mettre à jour la préférence dans le profil
    if dev_type == "ring":
        db.update_user_profile({"preferred_ring": connect_in.device_id}, user_id=current_user.id)
    elif dev_type == "scale":
        db.update_user_profile({"preferred_scale": connect_in.device_id}, user_id=current_user.id)

    # Si l'appareil est connecté, déclencher une synchronisation initiale
    if connect_in.connected:
        try:
            sync_device_targeted(connect_in.device_id, current_user=current_user)
        except Exception:
            pass

    return {
        "status": "success",
        "message": f"Appareil {name} configuré et connecté avec succès via l'assistant (identifiants chiffrés au repos)",
        "connectivity_test": connectivity_test,
        "device": saved
    }


@app.post("/api/devices/{device_id}/sync")
def sync_device_targeted(device_id: str, current_user: AuthUser = Depends(get_current_user)):
    """Déclenche la synchronisation ciblée d'un appareil et persiste les métriques en base."""
    # Instancier le connecteur avec les credentials utilisateur déchiffrés si existants
    user_device = db.get_user_device(device_id, user_id=current_user.id, reveal_secrets=True)
    custom_cfg = {}
    if user_device and user_device.get("credentials"):
        custom_cfg.update(user_device["credentials"])
    if user_device and user_device.get("api_key"):
        custom_cfg["api_key"] = user_device["api_key"]
    if user_device and user_device.get("account_email"):
        custom_cfg["account_email"] = user_device["account_email"]

    try:
        connector = get_connector(device_id, custom_config=custom_cfg)
    except Exception:
        connector = device_registry.get(device_id)

    if not connector:
        raise HTTPException(status_code=404, detail=f"Appareil '{device_id}' non trouvé")
    
    today_val = dt_module.date.today()
    start_val = today_val - dt_module.timedelta(days=7)
    
    weights = []
    activities = []
    if getattr(connector, "is_configured", False):
        if hasattr(connector, "sync_weights"):
            # Si le connecteur Withings a une DB associée, lui lier l'instance actuelle
            if hasattr(connector, "db") and not connector.db:
                connector.db = db
                connector.user_id = current_user.id
            raw_weights = [
                w for w in connector.sync_weights(start_val, today_val)
                if w.source not in ("demo", "simulation") and "Démo" not in (w.notes or "")
            ]
            for w in raw_weights:
                db.insert_weight(w, user_id=current_user.id)
            weights = [w.model_dump() for w in raw_weights]

        if hasattr(connector, "sync_activities"):
            raw_acts = [
                a for a in connector.sync_activities(start_val, today_val)
                if a.source not in ("demo", "simulation")
            ]
            for a in raw_acts:
                db.insert_activity(a, user_id=current_user.id)
            activities = [a.model_dump() for a in raw_acts]

    # Mettre à jour l'état de synchronisation en base
    db.update_device_sync_status(device_id, sync_status="connected", user_id=current_user.id)

    return {
        "device_id": device_id,
        "name": getattr(connector, "name", device_id.capitalize()),
        "status": "success",
        "sync_status": "connected",
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "details": {
            "weights_synced": len(weights),
            "activities_synced": len(activities)
        }
    }


@app.post("/api/devices/sync")
@app.post("/api/devices/sync/")
def sync_device_legacy(req: Optional[DeviceSyncRequest] = None, current_user: AuthUser = Depends(get_current_user)):
    """Compatibilité rétroactive pour la synchronisation d'un appareil."""
    dev_id = req.device_id if req and req.device_id else "health_connect"
    return sync_device_targeted(dev_id, current_user=current_user)


@app.get("/api/devices/{device_id}")
@app.post("/api/devices/{device_id}")
def get_device_detail(
    device_id: str,
    payload: Optional[Dict[str, Any]] = None,
    current_user: AuthUser = Depends(get_current_user)
):
    """Récupère les détails et l'état en direct d'un appareil, ou gère la synchronisation si invoqué par erreur en POST."""
    user_id = current_user.id if current_user else 1
    dev = db.get_user_device(device_id, user_id=user_id, reveal_secrets=False)
    connector = device_registry.get(device_id)
    if not dev and not connector:
        raise HTTPException(status_code=404, detail=f"Appareil '{device_id}' non trouvé")
    
    if not dev:
        dev = {
            "device_id": device_id,
            "name": getattr(connector, "name", device_id.title()),
            "device_type": getattr(connector, "device_type", "health_sensor"),
            "connected": False,
            "sync_status": "disconnected",
            "last_sync_at": None,
            "has_credentials": False
        }
    return dev


@app.delete("/api/devices/{device_id}")
def disconnect_device(device_id: str, current_user: AuthUser = Depends(get_current_user)):
    """Déconnecte et révoque un appareil en supprimant ses identifiants chiffrés."""
    deleted = db.delete_user_device(device_id, user_id=current_user.id)
    return {
        "status": "success",
        "message": f"Appareil '{device_id}' déconnecté et identifiants révoqués avec succès",
        "deleted": deleted
    }


@app.get("/api/devices/{device_id}/token")
def get_device_token_endpoint(
    device_id: str,
    current_user: AuthUser = Depends(get_current_user)
):
    """Récupère le jeton webhook secret déchiffré associé à l'appareil pour l'utilisateur connecté."""
    dev = db.get_user_device(device_id, user_id=current_user.id, reveal_secrets=True)
    if not dev:
        raise HTTPException(status_code=404, detail=f"Aucun appareil configuré pour '{device_id}'")
    
    creds = dev.get("credentials") or {}
    token = creds.get("webhook_token") or creds.get("api_key") or dev.get("api_key")
    if not token:
        raise HTTPException(status_code=404, detail=f"Aucun jeton trouvé pour '{device_id}'")
    
    return {
        "status": "success",
        "device_id": device_id,
        "token": token
    }


@app.post("/api/devices/{device_id}/token")
def create_device_token_endpoint(
    device_id: str,
    payload: Optional[Dict[str, Any]] = None,
    current_user: AuthUser = Depends(get_current_user)
):
    """Génère ou renouvelle un token secret individuel sécurisé pour un appareil/passerelle mobile."""
    req_payload = payload or {}
    name = req_payload.get("name")
    dev_type = req_payload.get("device_type")
    device_token_info = db.generate_device_token(
        device_id=device_id,
        name=name,
        device_type=dev_type,
        user_id=current_user.id
    )
    return {
        "status": "success",
        "message": f"Jeton individuel d'appareil généré avec succès pour '{device_id}'",
        "device_id": device_id,
        "token": device_token_info["token"],
        "device": device_token_info
    }


# =====================================================================
# Endpoints Authentification Google Sign-In (OAuth2 / GIS) & JWT
# =====================================================================

@app.get("/api/auth/config")
def get_auth_config():
    """Retourne la configuration Google OAuth/GIS (Client ID, scopes et statut)."""
    return db.get_google_config()


@app.put("/api/auth/config")
def update_auth_config(payload: GoogleConfigUpdate):
    """Enregistre ou met à jour le Google Client ID depuis l'interface."""
    res = db.set_google_client_id(payload.google_client_id)
    return {
        "status": "success",
        "message": "Configuration Google Client ID enregistrée avec succès",
        "config": res
    }


@app.post("/api/auth/register")
def register_user(payload: RegisterRequest):
    """Inscription classique avec email et mot de passe sécurisé (hash bcrypt / PBKDF2)."""
    if not validate_password_strength(payload.password):
        raise HTTPException(status_code=400, detail="Le mot de passe doit contenir au minimum 8 caractères")

    # Vérification de doublon d'email
    existing = db.get_user_by_email(payload.email)
    if existing and existing.get("password_hash"):
        raise HTTPException(status_code=400, detail="Un compte avec cet email existe déjà")

    pwd_hash = hash_password(payload.password, method="bcrypt")
    user = db.get_or_create_user(
        email=payload.email,
        name=payload.name or payload.email.split("@")[0],
        password_hash=pwd_hash,
        auth_provider="email"
    )
    token = create_access_token(user["id"], user["uuid"], user["email"], user.get("name"))
    return {
        "status": "success",
        "message": "Compte créé avec succès",
        "access_token": token,
        "token_type": "bearer",
        "user": user
    }


@app.post("/api/auth/login")
def login_user(payload: LoginRequest):
    """Connexion classique par email et mot de passe."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (payload.email.strip().lower(),))
        user = cursor.fetchone()

    if not user or not user.get("password_hash"):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    if not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    token = create_access_token(user["id"], user["uuid"], user["email"], user.get("name"))
    return {
        "status": "success",
        "message": "Connexion réussie",
        "access_token": token,
        "token_type": "bearer",
        "user": dict(user)
    }


@app.post("/api/auth/google")
def authenticate_google_user(payload: GoogleAuthPayload):
    """Authentifie l'utilisateur via Google GIS (ID Token JWT) ou connexion directe 1-clic.
    
    Associe automatiquement le compte Google au profil utilisateur et génère un jeton JWT d'accès.
    """
    cfg = db.get_google_config()
    client_id = cfg.get("google_client_id")
    user_info = parse_google_identity(payload, verify_signature=True, client_id=client_id)
    session = db.login_google_user(
        email=user_info["email"],
        name=user_info["name"],
        picture=user_info.get("picture", ""),
        google_sub=user_info.get("google_sub", ""),
        auth_method=user_info.get("auth_method", "google")
    )
    user_id = session.get("user_id") or 1
    user_uuid = session.get("uuid") or "00000000-0000-4000-8000-000000000001"
    user_profile = db.get_user_profile(user_id=user_id)

    # Générer le token JWT Bearer pour les requêtes futures
    access_token = create_access_token(user_id, user_uuid, user_info["email"], user_info["name"])

    # Assurer que l'appareil Google Health Connect est configuré pour cet utilisateur
    db.update_user_device(
        device_id="health_connect",
        name="Google Health Connect (Android)",
        device_type="mobile_aggregator",
        connected=True,
        auth_type="google_health_connect",
        account_email=user_info["email"],
        user_id=user_id
    )

    return {
        "status": "success",
        "message": f"Connecté avec succès en tant que {user_info['name']} ({user_info['email']})",
        "access_token": access_token,
        "token_type": "bearer",
        "session": session,
        "profile": user_profile
    }


@app.get("/api/auth/me")
def get_current_google_session(current_user: AuthUser = Depends(get_current_user)):
    """Retourne la session active, le jeton JWT et le profil associé."""
    session = db.get_google_session()
    profile = db.get_user_profile(user_id=current_user.id)
    token = create_access_token(current_user.id, current_user.uuid, current_user.email, current_user.name)
    return {
        "session": session,
        "profile": profile,
        "current_user": current_user.model_dump(),
        "access_token": token
    }


@app.post("/api/auth/logout")
def logout_google_session():
    """Déconnecte la session active Google."""
    res = db.logout_google_user()
    return res


# =====================================================================
# Endpoints Profil Utilisateur & Assistant de Connexion
# =====================================================================

@app.get("/api/profile")
def get_user_profile(
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un utilisateur ami pour consultation en lecture seule"),
    current_user: AuthUser = Depends(get_current_user)
):
    """Renvoie le profil utilisateur personnalisé et ses préférences d'objets pour l'utilisateur connecté ou un ami."""
    target_uid = current_user.id if user_id is None else user_id
    access = verify_view_access(target_uid, current_user, database=db)
    is_owner = (target_uid == current_user.id)
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
        "connected_devices": devices
    }


@app.post("/api/profile")
@app.put("/api/profile")
def update_user_profile(profile_in: UserProfileInput, current_user: AuthUser = Depends(get_current_user)):
    """Met à jour ou crée le profil utilisateur pour l'utilisateur connecté."""
    updated = db.update_user_profile(profile_in.model_dump(), user_id=current_user.id)
    return {
        "status": "success",
        "message": "Profil mis à jour avec succès",
        "profile": updated
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
def export_data_csv(limit: Optional[int] = Query(None, description="Limite optionnelle pour pagination ou export complet"), current_user: AuthUser = Depends(get_current_user)):
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
            w.notes or ""
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
            a.external_id or ""
        ])

    csv_content = output.getvalue()
    filename = f"vitaltrack_export_{current_user.id}_{date.today().isoformat()}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


class ConfirmDeletionPayload(BaseModel):
    confirm: bool = Field(True, description="Confirmation explicite de la suppression")
    password: Optional[str] = Field(None, description="Mot de passe optionnel pour confirmation")


@app.delete("/api/user/data")
def delete_user_data_only_endpoint(
    confirm: bool = Query(True, description="Confirmation de purge des données"),
    payload: Optional[ConfirmDeletionPayload] = None,
    current_user: AuthUser = Depends(get_current_user)
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
        "message": f"Toutes les données de santé pour {current_user.email} ont été purgées avec succès. Le compte utilisateur reste actif."
    }


@app.delete("/api/user/account")
def delete_user_account_endpoint(
    confirm: bool = Query(True, description="Confirmation de suppression du compte"),
    payload: Optional[ConfirmDeletionPayload] = None,
    current_user: AuthUser = Depends(get_current_user)
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
        "message": f"Compte et toutes les données associées pour {current_user.email} ont été définitivement supprimés."
    }


@app.get("/api/user/consents")
def get_user_consents_endpoint(current_user: AuthUser = Depends(get_current_user)):
    """Retourne les préférences de consentement RGPD par catégorie pour l'utilisateur."""
    consents = db.get_user_consents(user_id=current_user.id)
    return {
        "user_id": current_user.id,
        "consents": consents
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
        "consent": res.model_dump()
    }


@app.post("/api/backup/import")
def import_backup(payload: BackupRestoreInput, current_user: AuthUser = Depends(get_current_user)):
    """Restaure ou synchronise les données depuis un export JSON ou le localStorage/IndexedDB."""
    result = db.import_full_backup(payload.data, overwrite=payload.overwrite, user_id=current_user.id)
    return result


@app.post("/api/profile/reset-demo")
def reset_demo(current_user: AuthUser = Depends(get_current_user)):
    """Réinitialise et recharge le jeu complet de données de démonstration réaliste 30 jours."""
    # Marquer explicitement le profil comme profil de démonstration confirmé
    db.update_user_profile({"is_demo_profile": 1}, user_id=current_user.id)
    db.reset_demo_data(user_id=current_user.id)
    return {
        "status": "success",
        "message": "Données de démonstration 30 jours réinitialisées avec succès"
    }


@app.post("/api/profile/clear-history")
def clear_history(current_user: AuthUser = Depends(get_current_user)):
    """Efface l'historique tout en conservant les paramètres de profil pour un suivi personnel réel."""
    db.clear_all_history(keep_profile=True, user_id=current_user.id)
    # Rétablir le profil en profil réel (non démo)
    db.update_user_profile({"is_demo_profile": 0}, user_id=current_user.id)
    return {
        "status": "success",
        "message": "Historique effacé. Vous pouvez démarrer votre suivi réel !"
    }


# =====================================================================
# Endpoints Webhooks Universels (Health Connect, RingConn, Apple Santé)
# =====================================================================
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
            "recommended_cardio_min_week": 150
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
            "recommended_cardio_min_week": 120
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
            "recommended_cardio_min_week": 180
        }
    }
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
            filename="vitaltrack-health-bridge.apk"
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
