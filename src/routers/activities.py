"""Routeur FastAPI pour les endpoints d'activités et d'exercices."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from typing import Optional

from src.app import app, db, AuthUser, get_current_user
from src.routers.auth import verify_view_access

router = APIRouter(prefix="/api/activities", tags=["activities"])


@router.get("")
def get_activities(
    limit: int = 30,
    include_simulation: Optional[bool] = None,
    user_id: Optional[int] = None,
    current_user: AuthUser = Depends(get_current_user),
):
    """Retourne la série chronologique de l'activité quotidienne pour l'utilisateur connecté."""
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    profile = db.get_user_profile(user_id=target_uid)
    is_demo = bool(profile.get("is_demo_profile"))
    effective_exclude = not include_simulation if include_simulation is not None else not is_demo
    acts = db.get_activities(limit=limit, user_id=target_uid, exclude_simulation=effective_exclude)
    return [a.model_dump() for a in acts]


@router.post("")
def create_activity(
    act_in: dict,
    current_user: AuthUser = Depends(get_current_user),
):
    """Ajoute ou synchronise une entrée d'activité physique quotidienne pour l'utilisateur connecté."""
    steps = act_in.get("steps", 0)
    active_calories_kcal = act_in.get("active_calories_kcal", 0.0)
    workout_minutes = act_in.get("workout_minutes", 0)
    workout_type = act_in.get("workout_type")
    resting_hr_bpm = act_in.get("resting_hr_bpm")
    hrv_ms = act_in.get("hrv_ms")
    sleep_score = act_in.get("sleep_score")
    source = act_in.get("source", "health_connect")
    target_date = act_in.get("date", None)

    bmr = 1780.0
    active_cal = active_calories_kcal
    if active_cal <= 0 and steps > 0:
        active_cal = round(steps * 0.045, 1)

    total_burned = round(bmr + active_cal, 1)

    from src.models import ActivityEntry
    from datetime import date

    entry = ActivityEntry(
        date=target_date or date.today(),
        steps=steps,
        active_calories_kcal=active_cal,
        bmr_kcal=bmr,
        total_burned_kcal=total_burned,
        workout_minutes=workout_minutes,
        workout_type=workout_type,
        resting_hr_bpm=resting_hr_bpm,
        hrv_ms=hrv_ms,
        sleep_score=sleep_score,
        source=source,
    )
    saved = db.insert_activity(entry, user_id=current_user.id)
    return saved.model_dump()