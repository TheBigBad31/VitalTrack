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

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.db import Database, get_db_path
from src.models import ActivityEntry, FoodItem, MealEntry, MealType, WeightEntry
from src.nutrition_engine import NutritionEngine
import yaml
from src.vision_nutrition import PhotoCalorieEstimator
from src.connectors.registry import DeviceConnectorRegistry
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

# Initialisation de FastAPI
app = FastAPI(
    title="VitalTrack API",
    description="API REST pour VitalTrack : PWA Mobile-First, Nutrition Photo IA et Objets Connectés",
    version="1.0.0",
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


# Instances partagées
db = Database()
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

def get_current_user(authorization: Optional[str] = Header(None)) -> AuthUser:
    """Extrait et valide l'utilisateur authentifié depuis le jeton JWT Bearer.
    
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
    source: Literal["manual", "withings", "garmin", "apple_health", "demo"] = "manual"


class ActivityInput(BaseModel):
    date: Optional[dt_module.date] = None
    steps: int = Field(0, ge=0, description="Nombre de pas")
    active_calories_kcal: float = Field(0.0, ge=0.0, description="Calories actives en exercice")
    workout_minutes: int = Field(0, ge=0, description="Minutes d'activité physique")
    workout_type: Optional[str] = Field(None, description="Type d'entraînement")
    resting_hr_bpm: Optional[int] = Field(None, ge=30, le=220, description="Fréquence cardiaque au repos")
    hrv_ms: Optional[float] = Field(None, ge=0.0, description="Variabilité cardiaque (HRV en ms)")
    sleep_score: Optional[int] = Field(None, ge=0, le=100, description="Score de sommeil")
    source: Literal["oura", "health_connect", "apple_health", "strava", "demo"] = "health_connect"


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
    preferred_ring: Optional[str] = "ringconn"
    preferred_scale: Optional[str] = "withings"
    google_email: Optional[str] = None
    google_name: Optional[str] = None
    google_picture: Optional[str] = None
    google_sub: Optional[str] = None


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
@app.get("/health")
@app.get("/api/health")
def health_check():
    """Vérification de l'état du backend et de la base de données."""
    return {
        "status": "ok",
        "service": "VitalTrack API",
        "database": {
            "type": "postgresql" if db.is_postgres else "sqlite",
            "is_postgres": db.is_postgres,
            "target": "Neon PostgreSQL" if db.is_postgres else db.db_path
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
def get_dashboard_data(current_user: AuthUser = Depends(get_current_user)):
    """Renvoie les données unifiées pour alimenter l'ensemble des 5 vues de dashboards pour l'utilisateur connecté."""
    user_id = current_user.id
    weights = db.get_weights(limit=30, user_id=user_id)
    activities = db.get_activities(limit=30, user_id=user_id)
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

    # Synthèse du jour
    today_activity = next((a for a in reversed(activities) if a.date == today), None)
    if not today_activity and activities:
        today_activity = activities[-1]

    # Profil utilisateur personnalisé
    profile = db.get_user_profile(user_id=user_id)
    saved_devices = {dev["device_id"]: dev for dev in db.get_user_devices(user_id=user_id)}

    daily_nutrition = nutrition_engine.get_daily_nutrition_summary(today_activity.date if today_activity else today, user_id=user_id)
    energy_balance = nutrition_engine.calculate_daily_energy_balance(
        target_date=today_activity.date if today_activity else today,
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
            "steps": today_activity.steps if today_activity else 0,
            "steps_target": profile.get("target_steps", 10000),
            "calories_intake_kcal": energy_balance["calories_intake_kcal"],
            "calories_burned_kcal": energy_balance["calories_burned_kcal"],
            "bmr_kcal": energy_balance["bmr_kcal"],
            "net_energy_balance_kcal": energy_balance["net_energy_balance_kcal"],
            "target_calories_intake": profile.get("target_calories_intake", 2000.0),
            "energy_status": energy_balance["status"],
            "recommendation": energy_balance["recommendation"],
            "macros": daily_nutrition["macros"],
            "resting_hr_bpm": today_activity.resting_hr_bpm if today_activity else None,
            "hrv_ms": today_activity.hrv_ms if today_activity else None,
            "sleep_score": today_activity.sleep_score if today_activity else None,
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
def get_weights(limit: int = Query(30, ge=1, le=180), current_user: AuthUser = Depends(get_current_user)):
    """Retourne la série chronologique des pesées pour l'utilisateur connecté."""
    weights = db.get_weights(limit=limit, user_id=current_user.id)
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
# Endpoints Activités & Exercices
# =====================================================================

@app.get("/api/activities")
@app.get("/api/activity")
def get_activities(limit: int = Query(30, ge=1, le=180), current_user: AuthUser = Depends(get_current_user)):
    """Retourne la série chronologique de l'activité quotidienne pour l'utilisateur connecté."""
    acts = db.get_activities(limit=limit, user_id=current_user.id)
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
def get_meals(limit: int = Query(50, ge=1, le=200), current_user: AuthUser = Depends(get_current_user)):
    """Retourne les repas récemment enregistrés pour l'utilisateur connecté."""
    meals = db.get_meals(limit=limit, user_id=current_user.id)
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
# Endpoints Hub Objets Connectés & Gestion de Flotte Sécurisée
# =====================================================================

@app.get("/api/devices")
def list_devices(current_user: AuthUser = Depends(get_current_user)):
    """Liste tous les objets connectés de l'utilisateur avec leur statut temps réel et métriques récentes."""
    saved_devices = {dev["device_id"]: dev for dev in db.get_user_devices(user_id=current_user.id)}
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


@app.get("/api/devices/{device_id}")
def get_device_detail(device_id: str, current_user: AuthUser = Depends(get_current_user)):
    """Récupère les détails et l'état en direct d'un appareil pour l'utilisateur connecté."""
    dev = db.get_user_device(device_id, user_id=current_user.id, reveal_secrets=False)
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
    start_val = today_val - dt_module.timedelta(days=1)
    
    weights = []
    activities = []
    if getattr(connector, "is_configured", False):
        if hasattr(connector, "sync_weights"):
            raw_weights = [
                w for w in connector.sync_weights(start_val, today_val)
                if w.source != "demo" and "Démo" not in (w.notes or "")
            ]
            for w in raw_weights:
                db.insert_weight(w, user_id=current_user.id)
            weights = [w.model_dump() for w in raw_weights]

        if hasattr(connector, "sync_activities"):
            raw_acts = [
                a for a in connector.sync_activities(start_val, today_val)
                if a.source != "demo"
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
def sync_device_legacy(req: DeviceSyncRequest, current_user: AuthUser = Depends(get_current_user)):
    """Compatibilité rétroactive pour la synchronisation d'un appareil."""
    return sync_device_targeted(req.device_id, current_user=current_user)


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
def get_user_profile(current_user: AuthUser = Depends(get_current_user)):
    """Renvoie le profil utilisateur personnalisé et ses préférences d'objets pour l'utilisateur connecté."""
    profile = db.get_user_profile(user_id=current_user.id)
    devices = db.get_user_devices(user_id=current_user.id)
    return {
        "profile": profile,
        "connected_devices": devices
    }


@app.post("/api/profile")
def update_user_profile(profile_in: UserProfileInput, current_user: AuthUser = Depends(get_current_user)):
    """Met à jour ou crée le profil utilisateur pour l'utilisateur connecté."""
    updated = db.update_user_profile(profile_in.model_dump(), user_id=current_user.id)
    return {
        "status": "success",
        "message": "Profil mis à jour avec succès",
        "profile": updated
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


# =====================================================================
# Endpoints Sauvegarde / Restauration & Persistance Anti-Perte Vercel
# =====================================================================

class BackupRestoreInput(BaseModel):
    data: Dict[str, Any]
    overwrite: bool = False


@app.get("/api/backup/export")
def export_backup(current_user: AuthUser = Depends(get_current_user)):
    """Exporte l'intégralité du profil utilisateur, des appareils configurés et de l'historique."""
    backup_data = db.export_full_backup(user_id=current_user.id)
    return backup_data


@app.post("/api/backup/import")
def import_backup(payload: BackupRestoreInput, current_user: AuthUser = Depends(get_current_user)):
    """Restaure ou synchronise les données depuis un export JSON ou le localStorage/IndexedDB."""
    result = db.import_full_backup(payload.data, overwrite=payload.overwrite, user_id=current_user.id)
    return result


@app.post("/api/profile/reset-demo")
def reset_demo(current_user: AuthUser = Depends(get_current_user)):
    """Réinitialise et recharge le jeu complet de données de démonstration réaliste 30 jours."""
    db.reset_demo_data(user_id=current_user.id)
    return {
        "status": "success",
        "message": "Données de démonstration 30 jours réinitialisées avec succès"
    }


@app.post("/api/profile/clear-history")
def clear_history(current_user: AuthUser = Depends(get_current_user)):
    """Efface l'historique tout en conservant les paramètres de profil pour un suivi personnel réel."""
    db.clear_all_history(keep_profile=True, user_id=current_user.id)
    return {
        "status": "success",
        "message": "Historique effacé. Vous pouvez démarrer votre suivi réel !"
    }


# =====================================================================
# Endpoints Webhooks Universels (Health Connect, RingConn, Apple Santé)
# =====================================================================

@app.post("/api/webhook/health")
@app.post("/api/webhooks/health-connect")
@app.post("/api/webhooks/ringconn")
def handle_health_webhook(payload: Dict[str, Any], token: Optional[str] = Query(None)):
    """Point d'entrée universel pour les webhooks mobiles ou automatisations (Tasker, Raccourcis, RingConn)."""
    connector = MobileHealthWebhookConnector()
    if token and not connector.authenticate_request(token):
        raise HTTPException(status_code=401, detail="Token webhook invalide")

    weight_entry, act_entry = connector.process_webhook_payload(payload)
    saved_weight = None
    saved_act = None

    if weight_entry:
        saved_weight = db.insert_weight(weight_entry).model_dump()
    if act_entry:
        saved_act = db.insert_activity(act_entry).model_dump()

    # Mettre à jour l'état de l'appareil associé
    source_name = payload.get("source", "health_connect")
    dev_id = "ringconn" if "ring" in source_name.lower() else ("withings" if "withings" in source_name.lower() else "health_connect")
    db.update_user_device(
        device_id=dev_id,
        name=dev_id.replace("_", " ").title(),
        device_type="ring" if dev_id == "ringconn" else ("scale" if dev_id == "withings" else "mobile_aggregator"),
        connected=True,
        auth_type="webhook"
    )

    return {
        "status": "success",
        "message": "Données de santé webhook ingérées avec succès",
        "ingested": {
            "weight": saved_weight,
            "activity": saved_act
        }
    }





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
