"""Routeur FastAPI : meals."""

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
# Endpoints Nutrition, Photo IA et Journal
# =====================================================================

@router.get("/api/meals")
def get_meals(limit: int = Query(50, ge=1, le=200), current_user: AuthUser = Depends(get_current_user)):
    """Retourne les repas récemment enregistrés pour l'utilisateur connecté."""
    meals = db.get_meals(limit=limit, user_id=current_user.id)
    return [m.model_dump() for m in meals]


@router.get("/api/meals/analyze-photo")
def get_analyze_photo_info():
    """Information et métadonnées sur le moteur d'analyse photo de repas."""
    return {
        "status": "available",
        "description": "Moteur multimodal IA Gemini Vision et fallback hybride OpenFoodFacts",
        "supported_formats": ["image/jpeg", "image/png", "image/webp"],
        "max_size_mb": 10,
        "portion_scale_range": [0.5, 2.0]
    }


@router.post("/api/meals/analyze-photo")
@router.post("/api/meals/estimate")
def estimate_meal_calories(req: MealEstimateRequest):
    """Estime les calories et macronutriments à partir d'une photo ou d'une description.
    
    Prend en compte le curseur d'ajustement de portion interactive (0.5x - 2.0x).
    """
    scale = max(0.5, min(2.0, req.portion_scale))
    
    # Décoder image éventuelle si fournie sous forme data-url
    image_bytes = None
    mime_type = "image/jpeg"
    if req.photo_data_url and "base64," in req.photo_data_url:
        import base64
        try:
            header, encoded = req.photo_data_url.split("base64,", 1)
            if "image/png" in header:
                mime_type = "image/png"
            elif "image/webp" in header:
                mime_type = "image/webp"
            image_bytes = base64.b64decode(encoded)
        except Exception:
            image_bytes = None

    result = calorie_estimator.analyze_meal(
        image_bytes=image_bytes,
        mime_type=mime_type,
        description=req.description,
        portion_scale=scale,
        meal_type=req.meal_type
    )
    return result


@router.post("/api/meals")
def log_meal(req: MealSaveRequest, current_user: AuthUser = Depends(get_current_user)):
    """Enregistre définitivement un repas décomposé ou direct dans le journal alimentaire pour l'utilisateur connecté."""
    target_date = req.date or date.today()
    
    if req.items:
        items = req.items
        saved = nutrition_engine.log_meal(
            date_val=target_date,
            meal_type=req.meal_type,
            items=items,
            photo_data_url=req.photo_data_url,
            user_id=current_user.id
        )
    elif req.total_calories_kcal is not None:
        meal_name = req.meal_name or f"Repas direct ({req.meal_type})"
        items = [
            FoodItem(
                name=meal_name,
                calories_kcal=round(req.total_calories_kcal, 1),
                protein_g=round(req.protein_g or 0.0, 1),
                carbs_g=round(req.carbs_g or 0.0, 1),
                fat_g=round(req.fat_g or 0.0, 1),
                fiber_g=round(req.fiber_g or 0.0, 1),
                confidence_score=1.0
            )
        ]
        entry = MealEntry(
            date=target_date,
            meal_type=req.meal_type,
            total_calories_kcal=round(req.total_calories_kcal, 1),
            protein_g=round(req.protein_g or 0.0, 1),
            carbs_g=round(req.carbs_g or 0.0, 1),
            fat_g=round(req.fat_g or 0.0, 1),
            fiber_g=round(req.fiber_g or 0.0, 1),
            photo_data_url=req.photo_data_url,
            items=items
        )
        saved = db.insert_meal(entry, user_id=current_user.id)
    else:
        est = calorie_estimator.analyze_meal(
            description=None,
            portion_scale=req.portion_scale,
            meal_type=req.meal_type
        )
        items = [FoodItem(**item) for item in est.get("items", [])]
        saved = nutrition_engine.log_meal(
            date_val=target_date,
            meal_type=req.meal_type,
            items=items,
            photo_data_url=req.photo_data_url,
            user_id=current_user.id
        )
    return saved.model_dump()


@router.put("/api/meals/{meal_id}")
def update_meal(meal_id: int, req: MealSaveRequest, current_user: AuthUser = Depends(get_current_user)):
    """Met à jour un repas existant dans le journal pour l'utilisateur connecté."""
    target_date = req.date or date.today()
    if req.items:
        items = req.items
        tot_cal = round(sum(i.calories_kcal for i in items), 1)
        tot_prot = round(sum(i.protein_g for i in items), 1)
        tot_carbs = round(sum(i.carbs_g for i in items), 1)
        tot_fat = round(sum(i.fat_g for i in items), 1)
        tot_fiber = round(sum(i.fiber_g or 0.0 for i in items), 1)
    elif req.total_calories_kcal is not None:
        meal_name = req.meal_name or f"Repas direct ({req.meal_type})"
        items = [
            FoodItem(
                name=meal_name,
                calories_kcal=round(req.total_calories_kcal, 1),
                protein_g=round(req.protein_g or 0.0, 1),
                carbs_g=round(req.carbs_g or 0.0, 1),
                fat_g=round(req.fat_g or 0.0, 1),
                fiber_g=round(req.fiber_g or 0.0, 1),
                confidence_score=1.0
            )
        ]
        tot_cal = round(req.total_calories_kcal, 1)
        tot_prot = round(req.protein_g or 0.0, 1)
        tot_carbs = round(req.carbs_g or 0.0, 1)
        tot_fat = round(req.fat_g or 0.0, 1)
        tot_fiber = round(req.fiber_g or 0.0, 1)
    else:
        raise HTTPException(status_code=400, detail="Données de repas invalides")

    entry = MealEntry(
        date=target_date,
        meal_type=req.meal_type,
        total_calories_kcal=tot_cal,
        protein_g=tot_prot,
        carbs_g=tot_carbs,
        fat_g=tot_fat,
        fiber_g=tot_fiber,
        photo_data_url=req.photo_data_url,
        items=items
    )
    updated = db.update_meal(meal_id, entry, user_id=current_user.id)
    if not updated:
        raise HTTPException(status_code=404, detail="Repas introuvable")
    return updated.model_dump()


@router.delete("/api/meals/{meal_id}")
def delete_meal(meal_id: int, current_user: AuthUser = Depends(get_current_user)):
    """Supprime un repas du journal pour l'utilisateur connecté."""
    deleted = db.delete_meal(meal_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Repas introuvable")
    return {"status": "success", "message": f"Repas #{meal_id} supprimé avec succès"}


# =====================================================================
# Endpoints Bibliothèque de Plats Sauvegardés / Favoris Réutilisables
# =====================================================================

@router.get("/api/meals/saved")
def list_saved_meals(
    meal_type: Optional[str] = Query(None, description="Filtre par repas (breakfast, lunch, snack, dinner)"),
    is_favorite: Optional[bool] = Query(None, description="Filtre par favoris"),
    current_user: AuthUser = Depends(get_current_user)
):
    """Récupère la liste des plats sauvegardés/réutilisables de l'utilisateur connecté."""
    meals = db.get_saved_meals(meal_type=meal_type, is_favorite=is_favorite, user_id=current_user.id)
    return [m.model_dump() for m in meals]


@router.post("/api/meals/saved")
def create_saved_meal(
    req: SavedMealCreateRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """Crée et enregistre un nouveau plat type dans la bibliothèque réutilisable."""
    saved_meal = SavedMeal(
        user_id=current_user.id,
        name=req.name,
        meal_type=req.meal_type,
        serving_size=req.serving_size or "1 portion",
        quantity_grams=req.quantity_grams,
        calories=req.calories,
        protein_g=req.protein_g,
        carbs_g=req.carbs_g,
        fat_g=req.fat_g,
        fiber_g=req.fiber_g or 0.0,
        ingredients=req.ingredients,
        items=req.items or [],
        photo_url=req.photo_url,
        is_favorite=bool(req.is_favorite)
    )
    created = db.insert_saved_meal(saved_meal, user_id=current_user.id)
    return created.model_dump()


@router.get("/api/meals/saved/{meal_id}")
def get_saved_meal(
    meal_id: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Récupère les détails d'un plat type réutilisable."""
    saved = db.get_saved_meal_by_id(meal_id, user_id=current_user.id)
    if not saved:
        raise HTTPException(status_code=404, detail="Plat réutilisable introuvable")
    return saved.model_dump()


@router.put("/api/meals/saved/{meal_id}")
def update_saved_meal(
    meal_id: int,
    req: SavedMealUpdateRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """Met à jour un plat type réutilisable existant."""
    existing = db.get_saved_meal_by_id(meal_id, user_id=current_user.id)
    if not existing:
        raise HTTPException(status_code=404, detail="Plat réutilisable introuvable")

    data = existing.model_dump()
    req_data = req.model_dump(exclude_unset=True)
    for k, v in req_data.items():
        if v is not None:
            data[k] = v

    to_save = SavedMeal(**data)
    updated = db.update_saved_meal(meal_id, to_save, user_id=current_user.id)
    if not updated:
        raise HTTPException(status_code=404, detail="Plat réutilisable introuvable")
    return updated.model_dump()


@router.delete("/api/meals/saved/{meal_id}")
def delete_saved_meal(
    meal_id: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Supprime un plat réutilisable de la bibliothèque."""
    deleted = db.delete_saved_meal(meal_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Plat réutilisable introuvable")
    return {"status": "success", "message": f"Plat sauvegardé #{meal_id} supprimé avec succès"}


@router.post("/api/meals/saved/{meal_id}/log")
def log_saved_meal_to_journal(
    meal_id: int,
    req: SavedMealLogRequest = SavedMealLogRequest(),
    current_user: AuthUser = Depends(get_current_user)
):
    """Logge instantanément un plat réutilisable dans le journal alimentaire du jour."""
    saved = db.get_saved_meal_by_id(meal_id, user_id=current_user.id)
    if not saved:
        raise HTTPException(status_code=404, detail="Plat réutilisable introuvable")

    factor = req.portion_factor if req.portion_factor is not None else 1.0
    target_date = req.date or date.today()
    meal_type = req.meal_type or saved.meal_type

    # Mise à l'échelle des aliments ou de l'aliment global
    if saved.items:
        scaled_items = []
        for it in saved.items:
            scaled_items.append(FoodItem(
                name=it.name,
                portion_g=round(it.portion_g * factor, 1) if it.portion_g else None,
                calories_kcal=round(it.calories_kcal * factor, 1),
                protein_g=round(it.protein_g * factor, 1),
                carbs_g=round(it.carbs_g * factor, 1),
                fat_g=round(it.fat_g * factor, 1),
                fiber_g=round((it.fiber_g or 0.0) * factor, 1),
                confidence_score=it.confidence_score
            ))
    else:
        scaled_items = [FoodItem(
            name=saved.name,
            portion_g=round(saved.quantity_grams * factor, 1) if saved.quantity_grams else None,
            calories_kcal=round(saved.calories * factor, 1),
            protein_g=round(saved.protein_g * factor, 1),
            carbs_g=round(saved.carbs_g * factor, 1),
            fat_g=round(saved.fat_g * factor, 1),
            fiber_g=round((saved.fiber_g or 0.0) * factor, 1),
            confidence_score=1.0
        )]

    entry = MealEntry(
        date=target_date,
        meal_type=meal_type,
        total_calories_kcal=round(saved.calories * factor, 1),
        protein_g=round(saved.protein_g * factor, 1),
        carbs_g=round(saved.carbs_g * factor, 1),
        fat_g=round(saved.fat_g * factor, 1),
        fiber_g=round((saved.fiber_g or 0.0) * factor, 1),
        photo_data_url=saved.photo_url,
        items=scaled_items
    )

    logged = db.insert_meal(entry, user_id=current_user.id)
    return {
        "status": "success",
        "message": f"Plat '{saved.name}' ajouté au journal ({meal_type}) avec portion x{factor}",
        "logged_meal": logged.model_dump()
    }


# =====================================================================
# Endpoints Journal des Repas Quotidiens (Stage 12)
# =====================================================================

@router.get("/api/meals/journal")
def get_meals_journal(
    date_param: Optional[str] = Query(None, alias="date", description="Date YYYY-MM-DD"),
    current_user: AuthUser = Depends(get_current_user)
):
    """Récupère les 4 repas du jour avec la composition et les totaux."""
    target_date = date.fromisoformat(date_param) if date_param else date.today()
    logs = db.get_meal_logs_for_date(target_date, user_id=current_user.id)
    logs_by_type = {log.meal_type: log for log in logs}

    meal_types = ["breakfast", "lunch", "snack", "dinner"]
    meals_response = []
    day_total_cal = 0.0
    day_total_prot = 0.0
    day_total_carbs = 0.0
    day_total_fat = 0.0
    day_total_fiber = 0.0

    for mt in meal_types:
        mlog = logs_by_type.get(mt)
        if not mlog:
            mlog = db.get_or_create_meal_log(target_date, mt, user_id=current_user.id)
        
        m_dict = mlog.model_dump()
        meals_response.append(m_dict)

        day_total_cal += mlog.total_calories
        day_total_prot += mlog.total_protein_g
        day_total_carbs += mlog.total_carbs_g
        day_total_fat += mlog.total_fat_g
        day_total_fiber += (mlog.total_fiber_g or 0.0)

    # Calcul des pourcentages de macros pour la journée
    cal_p = day_total_prot * 4.0
    cal_c = day_total_carbs * 4.0
    cal_f = day_total_fat * 9.0
    sum_macro_cal = cal_p + cal_c + cal_f
    macros_pct = {
        "protein_pct": round((cal_p / sum_macro_cal) * 100.0, 1) if sum_macro_cal > 0 else 0.0,
        "carbs_pct": round((cal_c / sum_macro_cal) * 100.0, 1) if sum_macro_cal > 0 else 0.0,
        "fat_pct": round((cal_f / sum_macro_cal) * 100.0, 1) if sum_macro_cal > 0 else 0.0
    }

    return {
        "date": target_date.isoformat(),
        "meals": meals_response,
        "day_summary": {
            "total_calories": round(day_total_cal, 1),
            "total_protein_g": round(day_total_prot, 1),
            "total_carbs_g": round(day_total_carbs, 1),
            "total_fat_g": round(day_total_fat, 1),
            "total_fiber_g": round(day_total_fiber, 1),
            "macros_pct": macros_pct
        }
    }


@router.post("/api/meals/journal/{meal_type}/items")
def add_item_to_meal_journal(
    meal_type: str,
    payload: Union[MealJournalAddItemRequest, MealJournalAddBatchRequest, List[MealJournalAddItemRequest]],
    current_user: AuthUser = Depends(get_current_user)
):
    """Ajoute un ou plusieurs aliments/plats (avec quantité spécifiée) dans le repas d'une date."""
    if meal_type not in ["breakfast", "lunch", "snack", "dinner"]:
        raise HTTPException(status_code=400, detail="meal_type invalide (breakfast, lunch, snack, dinner)")

    # Déterminer la liste d'items à ajouter
    if isinstance(payload, list):
        items_to_add = payload
        target_date = date.today()
    elif isinstance(payload, MealJournalAddBatchRequest):
        items_to_add = payload.items
        target_date = payload.date or date.today()
    else:
        items_to_add = [payload]
        target_date = payload.date or date.today()

    last_log = None
    for it in items_to_add:
        item_target_date = it.date or target_date
        # Résolution par food_item_id si fourni
        food_item = None
        if it.food_item_id:
            food_item = db.get_food_item_by_id(it.food_item_id, user_id=current_user.id)
            if not food_item:
                raise HTTPException(status_code=404, detail=f"Aliment de catalogue #{it.food_item_id} introuvable")

        name = it.name or (food_item.name if food_item else "Aliment")
        unit = it.unit or (food_item.default_unit if food_item else "g")
        qty = it.quantity

        if food_item:
            ratio = qty / (food_item.default_quantity or 100.0)
            cal = round(food_item.calories_per_unit * ratio, 1)
            prot = round(food_item.protein_per_unit_g * ratio, 1)
            carbs = round(food_item.carbs_per_unit_g * ratio, 1)
            fat = round(food_item.fat_per_unit_g * ratio, 1)
            fiber = round((food_item.fiber_per_unit_g or 0.0) * ratio, 1)
        else:
            cal = it.calories if it.calories is not None else 0.0
            prot = it.protein_g if it.protein_g is not None else 0.0
            carbs = it.carbs_g if it.carbs_g is not None else 0.0
            fat = it.fat_g if it.fat_g is not None else 0.0
            fiber = it.fiber_g if it.fiber_g is not None else 0.0

        last_log = db.add_item_to_meal_log(
            date_val=item_target_date,
            meal_type=meal_type,
            name=name,
            quantity=qty,
            unit=unit,
            calories=cal,
            protein_g=prot,
            carbs_g=carbs,
            fat_g=fat,
            fiber_g=fiber,
            food_item_id=it.food_item_id,
            user_id=current_user.id
        )

    return {
        "status": "success",
        "meal_type": meal_type,
        "meal_log": last_log.model_dump() if last_log else None
    }


@router.delete("/api/meals/journal/items/{item_id}")
def delete_meal_journal_item(
    item_id: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Retire un aliment d'un repas et actualise le repas parent."""
    updated_log = db.delete_meal_log_item(item_id, user_id=current_user.id)
    if not updated_log:
        raise HTTPException(status_code=404, detail="Ligne d'aliment introuvable dans le journal")
    return {
        "status": "success",
        "message": f"Aliment #{item_id} retiré du repas",
        "meal_log": updated_log.model_dump()
    }


@router.post("/api/meals/journal/{meal_type}/save-as-dish")
def save_meal_as_dish(
    meal_type: str,
    req: SaveAsDishRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """Transforme la composition d'un repas consommé en un nouveau plat réutilisable dans le catalogue."""
    target_date = req.date or date.today()
    meal_log = db.get_or_create_meal_log(target_date, meal_type, user_id=current_user.id)

    if not meal_log.items:
        raise HTTPException(status_code=400, detail="Ce repas ne contient aucun aliment à sauvegarder comme plat")

    dish_item = CatalogItem(
        user_id=current_user.id,
        name=req.name.strip(),
        item_type="dish",
        default_unit="portion",
        default_quantity=1.0,
        calories_per_unit=meal_log.total_calories,
        protein_per_unit_g=meal_log.total_protein_g,
        carbs_per_unit_g=meal_log.total_carbs_g,
        fat_per_unit_g=meal_log.total_fat_g,
        fiber_per_unit_g=meal_log.total_fiber_g or 0.0,
        photo_url=req.photo_url or meal_log.photo_url
    )
    created_dish = db.insert_food_item(dish_item, user_id=current_user.id)
    return {
        "status": "success",
        "message": f"Repas transformé en plat '{created_dish.name}' dans votre catalogue !",
        "dish": created_dish.model_dump()
    }

