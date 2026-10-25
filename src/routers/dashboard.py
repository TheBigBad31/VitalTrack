"""Routeur FastAPI : dashboard."""

import os
import datetime as dt_module
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Union
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
import yaml

from src.models import (
    ActivityEntry, AssociatedBenefit, CatalogItem, FoodItem, MealEntry,
    MealLog, MealLogItem, MealType, NutritionBenefitItem, SavedMeal, WeightEntry
)
from src.nutrition_rules import evaluate_dish_benefits
from src.connectors.webhook import MobileHealthWebhookConnector
from src.auth import (
    AuthUser, GoogleAuthPayload, GoogleConfigUpdate, LoginRequest, RegisterRequest,
    create_access_token, decode_access_token, hash_password, parse_google_identity,
    validate_password_strength, verify_password
)
from src.deps import (
    db, nutrition_engine, calorie_estimator, device_registry,
    get_current_user, get_strict_user
)
from src.schemas import *  # noqa: F401,F403

router = APIRouter()


# =====================================================================
# Endpoints de Santé et Métadonnées
# =====================================================================

@router.get("/api")
@router.get("/api/")
@router.get("/health")
@router.get("/api/health")
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

@router.get("/api/dashboard")
def get_dashboard_data(current_user: AuthUser = Depends(get_current_user)):
    """Renvoie les données unifiées pour alimenter l'ensemble des 5 vues de dashboards pour l'utilisateur connecté."""
    user_id = current_user.id
    db.sync_all_meal_logs_to_meals(user_id=user_id)
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


@router.get("/api/goals/presets")
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

