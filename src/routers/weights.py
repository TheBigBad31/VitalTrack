"""Router FastAPI pour les endpoints de pesées et composition corporelle (VitalTrack).

Endpoints :
- GET  /api/weights          : liste des pesées (historique + tendance 7j)
- GET  /api/weight           : alias de /api/weights
- POST /api/weights          : saisie rapide de pesée (kg, composition corporelle)
- PUT  /api/weights/{id}     : mise à jour d'une pesée existante
- DELETE /api/weights/{id}   : suppression d'une pesée
"""

import datetime as dt_module
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

import src.app as app_module
from src.auth import AuthUser
from src.db import Database
from src.models import WeightEntry
from src.routers.friends import verify_view_access


router = APIRouter(tags=["weights"])


class WeightInput(BaseModel):
    date: Optional[dt_module.date] = None
    weight_kg: float = Field(..., gt=20.0, lt=350.0, description="Poids en kg")
    body_fat_pct: Optional[float] = Field(None, ge=3.0, le=60.0, description="% masse grasse")
    muscle_mass_kg: Optional[float] = Field(None, ge=10.0, le=150.0, description="Masse musculaire en kg")
    water_pct: Optional[float] = Field(None, ge=30.0, le=80.0, description="% eau")
    bmi: Optional[float] = Field(None, ge=10.0, le=70.0, description="IMC")
    notes: Optional[str] = None
    source: Literal["manual", "withings", "garmin", "apple_health", "demo", "simulation"] = "manual"


def get_db() -> Database:
    """Retourne l'instance Database courante depuis src.app (supporte le monkeypatch des tests)."""
    return app_module.db


@router.get("/api/weights")
@router.get("/api/weight")
def get_weights(
    limit: int = Query(30, ge=1, le=180),
    include_simulation: Optional[bool] = Query(None, description="Inclure les données simulées (défaut False hors profil démo)"),
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un utilisateur ami pour consultation en lecture seule"),
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Retourne la série chronologique des pesées pour l'utilisateur connecté ou un ami autorisé."""
    db = get_db()
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    profile = db.get_user_profile(user_id=target_uid)
    is_demo = bool(profile.get("is_demo_profile"))
    effective_exclude = not include_simulation if include_simulation is not None else not is_demo
    weights = db.get_weights(limit=limit, user_id=target_uid, exclude_simulation=effective_exclude)
    return [w.model_dump() for w in weights]


@router.post("/api/weights")
def create_weight(entry_in: WeightInput, current_user: AuthUser = Depends(app_module.get_current_user)):
    """Enregistre une nouvelle pesée manuelle ou connectée pour l'utilisateur connecté."""
    db = get_db()
    target_date = entry_in.date or dt_module.date.today()

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
def update_weight(
    weight_id: int,
    entry_in: WeightInput,
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Met à jour une pesée existante pour l'utilisateur connecté."""
    db = get_db()
    target_date = entry_in.date or dt_module.date.today()
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
def delete_weight(weight_id: int, current_user: AuthUser = Depends(app_module.get_current_user)):
    """Supprime une pesée erronée pour l'utilisateur connecté."""
    db = get_db()
    deleted = db.delete_weight(weight_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pesée introuvable")
    return {"status": "success", "message": f"Pesée #{weight_id} supprimée avec succès"}
