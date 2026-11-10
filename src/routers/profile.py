"""Router FastAPI pour les endpoints de profil utilisateur, préférences et démo (VitalTrack).

Endpoints :
- GET  /api/profile           : profil utilisateur et appareils connectés
- POST /api/profile           : mise à jour du profil
- PUT  /api/profile           : alias mise à jour du profil
- POST /api/profile/reset-demo: réinitialisation des données de démo 30j
- POST /api/profile/clear-history: efface l'historique, conserve le profil
"""

from typing import Any, Dict, List, Literal, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

import src.app as app_module
from src.auth import AuthUser
from src.db import Database
from src.routers.friends import verify_view_access


router = APIRouter(tags=["profile"])


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


def get_db() -> Database:
    """Retourne l'instance Database courante depuis src.app (supporte le monkeypatch des tests)."""
    return app_module.db


@router.get("/api/profile")
def get_user_profile(
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un utilisateur ami pour consultation en lecture seule"),
    current_user: AuthUser = Depends(app_module.get_current_user),
):
    """Renvoie le profil utilisateur personnalisé et ses préférences d'objets pour l'utilisateur connecté ou un ami."""
    db = get_db()
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    is_owner = target_uid == current_user.id
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
        "connected_devices": devices,
    }


@router.post("/api/profile")
@router.put("/api/profile")
def update_user_profile(profile_in: UserProfileInput, current_user: AuthUser = Depends(app_module.get_current_user)):
    """Met à jour ou crée le profil utilisateur pour l'utilisateur connecté."""
    db = get_db()
    updated = db.update_user_profile(profile_in.model_dump(), user_id=current_user.id)
    app_module.invalidate_dashboard_cache(current_user.id)
    return {
        "status": "success",
        "message": "Profil mis à jour avec succès",
        "profile": updated,
    }


@router.post("/api/profile/reset-demo")
def reset_demo(current_user: AuthUser = Depends(app_module.get_current_user)):
    """Réinitialise et recharge le jeu complet de données de démonstration réaliste 30 jours."""
    db = get_db()
    db.update_user_profile({"is_demo_profile": 1}, user_id=current_user.id)
    db.reset_demo_data(user_id=current_user.id)
    app_module.invalidate_dashboard_cache(current_user.id)
    return {
        "status": "success",
        "message": "Données de démonstration 30 jours réinitialisées avec succès",
    }


@router.post("/api/profile/clear-history")
def clear_history(current_user: AuthUser = Depends(app_module.get_current_user)):
    """Efface l'historique tout en conservant les paramètres de profil pour un suivi personnel réel."""
    db = get_db()
    db.clear_all_history(keep_profile=True, user_id=current_user.id)
    db.update_user_profile({"is_demo_profile": 0}, user_id=current_user.id)
    app_module.invalidate_dashboard_cache(current_user.id)
    return {
        "status": "success",
        "message": "Historique effacé. Vous pouvez démarrer votre suivi réel !",
    }
