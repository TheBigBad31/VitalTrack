"""Routeurs API v2 pour VitalTrack (Breaking changes, formats stricts et enrichis).

Nouvelle génération d'API :
- Réponses standardisées enveloppées (data, meta, error)
- Types stricts Pydantic v2
- OpenAPI 3.1 & documentation v2
"""

from fastapi import APIRouter, Depends, Query
from typing import Any, Dict, List, Optional
import datetime as dt_module

from pydantic import BaseModel, Field
import src.app as app_module
from src.auth import AuthUser
from src.models import WeightEntry

router = APIRouter(prefix="/api/v2", tags=["v2 - Core"])


class V2Response(BaseModel):
    version: str = "v2"
    status: str = "success"
    data: Any
    meta: Optional[Dict[str, Any]] = None


class V2WeightInput(BaseModel):
    date: Optional[dt_module.date] = None
    weight_kg: float = Field(..., gt=20.0, lt=350.0, description="Poids en kilogrammes")
    body_fat_pct: Optional[float] = Field(None, ge=3.0, le=60.0, description="Pourcentage de masse grasse")
    muscle_mass_kg: Optional[float] = Field(None, ge=10.0, le=150.0, description="Masse musculaire en kg")
    water_pct: Optional[float] = Field(None, ge=30.0, le=80.0, description="Pourcentage d'hydratation")
    source: str = Field(default="manual", description="Source de mesure certifiée")
    notes: Optional[str] = None


@router.get("/health", response_model=V2Response)
def get_v2_health():
    """Statut de santé API v2 standardisé."""
    return V2Response(
        data={
            "service": "VitalTrack API v2",
            "status": "operational",
            "features": ["standardized_envelopes", "rfc_deprecation_headers", "enhanced_types"],
        },
        meta={"timestamp": dt_module.datetime.now(dt_module.timezone.utc).isoformat()},
    )


@router.get("/weights", response_model=V2Response)
def get_v2_weights(
    limit: int = Query(30, ge=1, le=180),
    current_user: AuthUser = Depends(app_module.get_current_user),
):
    """Liste v2 des pesées enveloppées avec métadonnées."""
    db = app_module.db
    weights = db.get_weights(limit=limit, user_id=current_user.id)
    return V2Response(
        data=[w.model_dump() for w in weights],
        meta={
            "count": len(weights),
            "limit": limit,
            "user_id": current_user.id,
        },
    )


@router.post("/weights", response_model=V2Response)
def create_v2_weight(
    entry_in: V2WeightInput,
    current_user: AuthUser = Depends(app_module.get_current_user),
):
    """Enregistrement d'une pesée via v2 avec calcul automatique de l'IMC et enveloppe v2."""
    db = app_module.db
    target_date = entry_in.date or dt_module.date.today()
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
    app_module.invalidate_dashboard_cache(current_user.id)
    return V2Response(
        data=saved.model_dump(),
        meta={"created": True, "user_id": current_user.id},
    )


@router.get("/dashboard", response_model=V2Response)
async def get_v2_dashboard(
    current_user: AuthUser = Depends(app_module.get_current_user),
):
    """Dashboard agrégé v2 avec enveloppe standardisée."""
    raw_dashboard = await app_module.get_dashboard_data(current_user=current_user)
    return V2Response(
        data=raw_dashboard,
        meta={"version": "2.0.0", "user_id": current_user.id},
    )
