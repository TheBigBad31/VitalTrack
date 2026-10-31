"""Router FastAPI pour les endpoints d'activité physique et exercices (VitalTrack).

Endpoints :
- GET  /api/activities   : liste des résumés d'activité
- GET  /api/activity     : alias de /api/activities
- POST /api/activities   : ajout / synchronisation d'exercice ou pas
"""

import datetime as dt_module
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

import src.app as app_module
from src.auth import AuthUser
from src.db import Database
from src.models import ActivityEntry


router = APIRouter(tags=["activities"])


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


def get_db() -> Database:
    """Retourne l'instance Database courante depuis src.app (supporte le monkeypatch des tests)."""
    return app_module.db


@router.get("/api/activities")
@router.get("/api/activity")
def get_activities(
    limit: int = Query(30, ge=1, le=180),
    include_simulation: Optional[bool] = Query(None, description="Inclure les données simulées (défaut False hors profil démo)"),
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Retourne la série chronologique de l'activité quotidienne pour l'utilisateur connecté."""
    db = get_db()
    profile = db.get_user_profile(user_id=current_user.id)
    is_demo = bool(profile.get("is_demo_profile"))
    effective_exclude = not include_simulation if include_simulation is not None else not is_demo
    acts = db.get_activities(limit=limit, user_id=current_user.id, exclude_simulation=effective_exclude)
    return [a.model_dump() for a in acts]


@router.post("/api/activities")
def create_activity(act_in: ActivityInput, current_user: AuthUser = Depends(app_module.get_current_user)):
    """Ajoute ou synchronise une entrée d'activité physique quotidienne pour l'utilisateur connecté."""
    db = get_db()
    target_date = act_in.date or dt_module.date.today()
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
