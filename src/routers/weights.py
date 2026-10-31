"""Routeur FastAPI pour les endpoints de pesées (Poids)."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional

router = APIRouter(prefix="/api/weights", tags=["weights"])


def _get_db():
    """Obtenir une instance de base de données (import lent pour éviter les boucles circulaires)."""
    from src.db import Database
    return Database()


def _get_auth():
    """Obtenir les dépendances d'authentification (import lent)."""
    from src.app import db, AuthUser
    from src.routers.auth import verify_view_access, get_current_user
    return db, AuthUser, verify_view_access, get_current_user


@router.get("")
def get_weights(
    limit: int = 30,
    include_simulation: Optional[bool] = None,
    user_id: Optional[int] = None,
):
    """Retourne la série chronologique des pesées pour l'utilisateur connecté ou un ami autorisé."""
    from src.app import db, AuthUser
    from src.routers.auth import verify_view_access, get_current_user

    current_user = get_current_user()
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    profile = db.get_user_profile(user_id=target_uid)
    is_demo = bool(profile.get("is_demo_profile"))
    effective_exclude = not include_simulation if include_simulation is not None else not is_demo
    weights = db.get_weights(limit=limit, user_id=target_uid, exclude_simulation=effective_exclude)
    return [w.model_dump() for w in weights]


@router.post("")
def create_weight(
    entry_in: dict,
):
    """Enregistre une nouvelle pesée manuelle ou connectée pour l'utilisateur connecté."""
    from src.app import db
    from src.routers.auth import get_current_user

    current_user = get_current_user()
    weight_kg = entry_in.get("weight_kg", 0.0)
    body_fat_pct = entry_in.get("body_fat_pct")
    muscle_mass_kg = entry_in.get("muscle_mass_kg")
    water_pct = entry_in.get("water_pct")
    notes = entry_in.get("notes", "")
    source = entry_in.get("source", "manual")
    target_date = entry_in.get("date", None)

    bmi_val = entry_in.get("bmi")
    if bmi_val is None and weight_kg > 0:
        bmi_val = round(weight_kg / (1.78 ** 2), 1)

    from src.models import WeightEntry
    entry = WeightEntry(
        date=target_date,
        weight_kg=weight_kg,
        body_fat_pct=body_fat_pct,
        muscle_mass_kg=muscle_mass_kg,
        water_pct=water_pct,
        bmi=bmi_val,
        source=source,
        notes=notes,
    )
    db = _get_db()
    saved = db.insert_weight(entry, user_id=current_user.id)
    return saved.model_dump()


@router.put("/{weight_id}")
def update_weight(
    weight_id: int,
    entry_in: dict,
):
    """Met à jour une pesée existante pour l'utilisateur connecté."""
    from src.app import db
    from src.routers.auth import get_current_user

    current_user = get_current_user()
    weight_kg = entry_in.get("weight_kg", 0.0)
    body_fat_pct = entry_in.get("body_fat_pct")
    muscle_mass_kg = entry_in.get("muscle_mass_kg")
    water_pct = entry_in.get("water_pct")
    notes = entry_in.get("notes", "")
    source = entry_in.get("source", "manual")
    target_date = entry_in.get("date", None)

    bmi_val = entry_in.get("bmi")
    if bmi_val is None and weight_kg > 0:
        bmi_val = round(weight_kg / (1.78 ** 2), 1)

    from src.models import WeightEntry
    entry = WeightEntry(
        date=target_date,
        weight_kg=weight_kg,
        body_fat_pct=body_fat_pct,
        muscle_mass_kg=muscle_mass_kg,
        water_pct=water_pct,
        bmi=bmi_val,
        source=source,
        notes=notes,
    )
    db = _get_db()
    updated = db.update_weight(weight_id, entry, user_id=current_user.id)
    if not updated:
        return JSONResponse(status_code=404, content={"detail": "Pesée introuvable"})
    return updated.model_dump()


@router.delete("/{weight_id}")
def delete_weight(
    weight_id: int,
):
    """Supprime une pesée erronée pour l'utilisateur connecté."""
    from src.app import db
    from src.routers.auth import get_current_user

    current_user = get_current_user()
    db = _get_db()
    deleted = db.delete_weight(weight_id, user_id=current_user.id)
    if not deleted:
        return JSONResponse(status_code=404, content={"detail": "Pesée introuvable"})
    return {"status": "success", "message": f"Pesée #{weight_id} supprimée avec succès"}