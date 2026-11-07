"""Router FastAPI pour l'agrégation du Dashboard (VitalTrack).

Endpoints :
- GET /api/dashboard : données globales unifiées pour les 5 vues de dashboards
"""

import asyncio
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, Query

import src.app as app_module
from src.auth import AuthUser
from src.routers.friends import verify_view_access


router = APIRouter(tags=["dashboard"])

DASHBOARD_CACHE: Dict[Tuple[int, bool], Tuple[float, Any]] = {}
DASHBOARD_CACHE_TTL_SECONDS = 45.0


def invalidate_dashboard_cache(user_id: Optional[int] = None):
    """Invalide le cache en mémoire du dashboard (global ou par utilisateur)."""
    if user_id is None:
        DASHBOARD_CACHE.clear()
    else:
        for k in list(DASHBOARD_CACHE.keys()):
            if k[0] == user_id:
                DASHBOARD_CACHE.pop(k, None)


@router.get("/api/dashboard")
async def get_dashboard_data(
    include_simulation: bool = Query(False, description="Inclure ou exclure les données de simulation"),
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un utilisateur ami pour consultation en lecture seule"),
    current_user: AuthUser = Depends(app_module.get_current_user),
):
    """Renvoie les données unifiées pour alimenter l'ensemble des 5 vues de dashboards pour l'utilisateur connecté ou un ami."""
    db = app_module.db
    nutrition_engine = app_module.nutrition_engine
    device_registry = app_module.device_registry

    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    user_id = target_uid

    cache_key = (user_id, include_simulation)
    now_ts = time.time()
    if cache_key in DASHBOARD_CACHE:
        cached_ts, cached_data = DASHBOARD_CACHE[cache_key]
        if now_ts - cached_ts < DASHBOARD_CACHE_TTL_SECONDS:
            return cached_data

    profile, meals, daily_metrics_rows, saved_devices_raw = await asyncio.gather(
        asyncio.to_thread(db.get_user_profile, user_id=user_id),
        asyncio.to_thread(db.get_meals, limit=60, user_id=user_id),
        asyncio.to_thread(db.get_daily_metrics, limit=5, user_id=user_id),
        asyncio.to_thread(db.get_user_devices, user_id=user_id),
    )
    saved_devices = {dev["device_id"]: dev for dev in saved_devices_raw}

    effective_exclude = not include_simulation and not bool(profile.get("is_demo_profile"))

    weights, activities = await asyncio.gather(
        asyncio.to_thread(db.get_weights, limit=30, user_id=user_id, exclude_simulation=effective_exclude),
        asyncio.to_thread(db.get_activities, limit=30, user_id=user_id, exclude_simulation=effective_exclude),
    )
    if not weights and not effective_exclude:
        weights = await asyncio.to_thread(db.get_weights, limit=30, user_id=user_id, exclude_simulation=False)
    if not activities and not effective_exclude:
        activities = await asyncio.to_thread(db.get_activities, limit=30, user_id=user_id, exclude_simulation=False)

    today = date.today()
    latest_weight = weights[-1] if weights else None

    weight_7d_change = 0.0
    if len(weights) >= 7:
        weight_7d_change = round(weights[-1].weight_kg - weights[-7].weight_kg, 2)
    elif len(weights) >= 2:
        weight_7d_change = round(weights[-1].weight_kg - weights[0].weight_kg, 2)

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

    dashboard_res = {
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
    DASHBOARD_CACHE[cache_key] = (now_ts, dashboard_res)
    return dashboard_res
