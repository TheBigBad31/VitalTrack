"""Routeur FastAPI : catalog."""

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


@router.get("/api/catalog/items")
def get_catalog_items(
    type: Optional[str] = Query(None, description="Filtre par type ('food' ou 'dish')"),
    q: Optional[str] = Query(None, description="Recherche textuelle par nom"),
    current_user: AuthUser = Depends(get_current_user)
):
    """Récupère le catalogue d'aliments et de plats de l'utilisateur."""
    items = db.get_food_items(item_type=type, query=q, user_id=current_user.id)
    return [it.model_dump() for it in items]


@router.post("/api/catalog/items")
def create_catalog_item(
    req: CatalogItemCreateRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """Crée un nouvel aliment ou plat dans le catalogue."""
    item = CatalogItem(
        user_id=current_user.id,
        name=req.name.strip(),
        item_type=req.item_type,
        default_unit=req.default_unit or "g",
        default_quantity=req.default_quantity or 100.0,
        calories_per_unit=req.calories_per_unit,
        protein_per_unit_g=req.protein_per_unit_g or 0.0,
        carbs_per_unit_g=req.carbs_per_unit_g or 0.0,
        fat_per_unit_g=req.fat_per_unit_g or 0.0,
        fiber_per_unit_g=req.fiber_per_unit_g or 0.0,
        photo_url=req.photo_url,
        recipe_items=req.recipe_items or []
    )
    created = db.insert_food_item(item, user_id=current_user.id)
    return created.model_dump()


@router.put("/api/catalog/items/{item_id}")
def update_catalog_item(
    item_id: int,
    req: CatalogItemUpdateRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """Met à jour un aliment ou un plat du catalogue."""
    update_data = {k: v for k, v in req.model_dump().items() if v is not None}
    updated = db.update_food_item(item_id, update_data, user_id=current_user.id)
    if not updated:
        raise HTTPException(status_code=404, detail="Élément de catalogue introuvable")
    return updated.model_dump()


@router.delete("/api/catalog/items/{item_id}")
def delete_catalog_item(
    item_id: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Supprime un aliment ou un plat du catalogue."""
    deleted = db.delete_food_item(item_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Élément de catalogue introuvable")
    return {"status": "success", "message": f"Élément #{item_id} supprimé du catalogue"}


@router.get("/api/catalog/items/{item_id}/benefits")
def get_catalog_item_benefits(
    item_id: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Récupère les bienfaits associés à un aliment/plat donné."""
    item = db.get_food_item_by_id(item_id, user_id=current_user.id)
    if not item:
        raise HTTPException(status_code=404, detail="Élément de catalogue introuvable")
    benefits = db.get_food_item_benefits(item_id)
    return [b.model_dump() for b in benefits]


@router.put("/api/catalog/items/{item_id}/benefits")
def update_catalog_item_benefits(
    item_id: int,
    req: UpdateCatalogItemBenefitsRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """Met à jour les bienfaits associés à un aliment/plat donné (sélection manuelle ou auto)."""
    item = db.get_food_item_by_id(item_id, user_id=current_user.id)
    if not item:
        raise HTTPException(status_code=404, detail="Élément de catalogue introuvable")
    updated_benefits = db.set_food_item_benefits(item_id, req.benefits)
    return [b.model_dump() for b in updated_benefits]


@router.get("/api/nutrition/benefits")
def get_nutrition_benefits():
    """Récupère la liste de tous les bienfaits disponibles dans le référentiel expert groupés par catégorie."""
    all_benefits = db.get_all_nutrition_benefits()
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for b in all_benefits:
        if b.category not in grouped:
            grouped[b.category] = []
        grouped[b.category].append(b.model_dump())
    return {
        "count": len(all_benefits),
        "benefits": [b.model_dump() for b in all_benefits],
        "categories": grouped
    }


@router.post("/api/nutrition/evaluate")
def evaluate_nutrition_benefits(req: NutritionEvaluateRequest):
    """Évalue instantanément un ensemble de valeurs nutritionnelles et retourne les bienfaits qualifiés (règles EFSA/ANSES)."""
    data = req.model_dump()
    results = evaluate_dish_benefits(data)
    return {
        "matched_count": len(results),
        "results": [r.model_dump() for r in results]
    }

