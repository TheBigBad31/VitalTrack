"""Routeur FastAPI : weights."""

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
# Endpoints Pesées (Poids)
# =====================================================================

@router.get("/api/weights")
@router.get("/api/weight")
def get_weights(limit: int = Query(30, ge=1, le=180), current_user: AuthUser = Depends(get_current_user)):
    """Retourne la série chronologique des pesées pour l'utilisateur connecté."""
    weights = db.get_weights(limit=limit, user_id=current_user.id)
    return [w.model_dump() for w in weights]


@router.post("/api/weights")
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


@router.put("/api/weights/{weight_id}")
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


@router.delete("/api/weights/{weight_id}")
def delete_weight(weight_id: int, current_user: AuthUser = Depends(get_current_user)):
    """Supprime une pesée erronée pour l'utilisateur connecté."""
    deleted = db.delete_weight(weight_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pesée introuvable")
    return {"status": "success", "message": f"Pesée #{weight_id} supprimée avec succès"}


# =====================================================================
# Endpoints Activités & Exercices
# =====================================================================

@router.get("/api/activities")
@router.get("/api/activity")
def get_activities(limit: int = Query(30, ge=1, le=180), current_user: AuthUser = Depends(get_current_user)):
    """Retourne la série chronologique de l'activité quotidienne pour l'utilisateur connecté."""
    acts = db.get_activities(limit=limit, user_id=current_user.id)
    return [a.model_dump() for a in acts]


@router.post("/api/activities")
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

