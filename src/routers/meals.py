"""Router FastAPI pour la nutrition, le journal des repas, le catalogue d'aliments et les bienfaits (VitalTrack).

Endpoints :
- GET  /api/meals             : historique des repas
- GET  /api/meals/analyze-photo : métadonnées du moteur d'analyse photo
- POST /api/meals/analyze-photo : estimation calorique par photo ou description
- POST /api/meals/estimate    : alias de /api/meals/analyze-photo
- POST /api/meals             : enregistrement d'un repas dans le journal
- PUT  /api/meals/{id}        : mise à jour d'un repas
- DELETE /api/meals/{id}      : suppression d'un repas
- GET  /api/meals/saved       : liste des plats sauvegardés/réutilisables
- POST /api/meals/saved       : création d'un plat type
- GET  /api/meals/saved/{id}  : détails d'un plat réutilisable
- PUT  /api/meals/saved/{id}  : mise à jour d'un plat réutilisable
- DELETE /api/meals/saved/{id}: suppression d'un plat réutilisable
- POST /api/meals/saved/{id}/log : logge un plat réutilisable dans le journal
- GET  /api/catalog/items     : catalogue d'aliments et de plats
- POST /api/catalog/items     : création d'un aliment/plat dans le catalogue
- PUT  /api/catalog/items/{id}: mise à jour d'un élément du catalogue
- DELETE /api/catalog/items/{id}: suppression d'un élément du catalogue
- GET  /api/catalog/subscriptions : liste des abonnements aux catalogues d'amis
- POST /api/catalog/subscriptions : abonnement au catalogue d'un utilisateur
- DELETE /api/catalog/subscriptions/{id} : désabonnement du catalogue d'un ami
- GET  /api/catalog/friends/{id}/items : exploration du catalogue d'un ami
- GET  /api/catalog/items/{id}/benefits : bienfaits associés à un aliment/plat
- PUT  /api/catalog/items/{id}/benefits : mise à jour des bienfaits
- GET  /api/nutrition/benefits   : liste de tous les bienfaits disponibles
- POST /api/nutrition/evaluate   : évaluation des bienfaits nutritionnels (EFSA/ANSES)
- GET  /api/meals/journal        : 4 repas du jour avec composition et totaux
- POST /api/meals/journal/{type}/items : ajoute des aliments à un repas
- DELETE /api/meals/journal/items/{id} : retire un aliment d'un repas
- POST /api/meals/journal/{type}/save-as-dish : transforme un repas en plat réutilisable
"""

from datetime import date
import datetime as dt_module
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import src.app as app_module
from src.auth import AuthUser
from src.db import Database
from src.models import (
    CatalogItem,
    FoodItem,
    MealEntry,
    MealLog,
    MealType,
    SavedMeal,
)
from src.nutrition_engine import NutritionEngine
from src.nutrition_rules import evaluate_dish_benefits
from src.routers.friends import verify_view_access


router = APIRouter(tags=["meals"])


class MealEstimateRequest(BaseModel):
    photo_data_url: Optional[str] = None
    description: Optional[str] = None
    meal_type: MealType = "lunch"
    portion_scale: float = Field(1.0, ge=0.5, le=2.0, description="Curseur de portion (0.5x à 2.0x)")


class MealSaveRequest(BaseModel):
    date: Optional[dt_module.date] = None
    meal_type: MealType
    photo_data_url: Optional[str] = None
    portion_scale: float = Field(1.0, ge=0.5, le=2.0)
    items: List[FoodItem] = Field(default_factory=list)
    total_calories_kcal: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    fiber_g: Optional[float] = None
    meal_name: Optional[str] = None


class SavedMealCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Nom du plat")
    meal_type: MealType = Field("lunch", description="Type de repas (breakfast, lunch, snack, dinner)")
    serving_size: Optional[str] = Field("1 portion", description="Taille ou libellé de portion")
    quantity_grams: Optional[float] = Field(None, ge=0.0)
    calories: float = Field(..., ge=0.0, description="Calories (kcal)")
    protein_g: float = Field(0.0, ge=0.0)
    carbs_g: float = Field(0.0, ge=0.0)
    fat_g: float = Field(0.0, ge=0.0)
    fiber_g: Optional[float] = Field(0.0, ge=0.0)
    ingredients: Optional[str] = None
    items: Optional[List[FoodItem]] = Field(default_factory=list)
    photo_url: Optional[str] = None
    is_favorite: Optional[bool] = False


class SavedMealUpdateRequest(BaseModel):
    name: Optional[str] = None
    meal_type: Optional[MealType] = None
    serving_size: Optional[str] = None
    quantity_grams: Optional[float] = None
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    fiber_g: Optional[float] = None
    ingredients: Optional[str] = None
    items: Optional[List[FoodItem]] = None
    photo_url: Optional[str] = None
    is_favorite: Optional[bool] = None


class SavedMealLogRequest(BaseModel):
    date: Optional[dt_module.date] = None
    meal_type: Optional[MealType] = None
    portion_factor: Optional[float] = Field(1.0, ge=0.1, le=10.0, description="Facteur multiplicateur de portion")


class UpdateCatalogItemBenefitsRequest(BaseModel):
    benefits: List[Dict[str, Any]] = Field(default_factory=list, description="Liste des bienfaits associés [{benefit_id, source, explanation}]")


class NutritionEvaluateRequest(BaseModel):
    name: Optional[str] = None
    default_quantity: Optional[float] = None
    portion_g: Optional[float] = None
    quantity_grams: Optional[float] = None
    calories: Optional[float] = None
    calories_per_unit: Optional[float] = None
    calories_kcal: Optional[float] = None
    protein_g: Optional[float] = None
    protein_per_unit_g: Optional[float] = None
    carbs_g: Optional[float] = None
    carbs_per_unit_g: Optional[float] = None
    fat_g: Optional[float] = None
    fat_per_unit_g: Optional[float] = None
    fiber_g: Optional[float] = None
    fiber_per_unit_g: Optional[float] = None
    sugars_g: Optional[float] = None
    saturated_fat_g: Optional[float] = None
    unsaturated_fat_g: Optional[float] = None
    sodium_mg: Optional[float] = None
    potassium_mg: Optional[float] = None
    calcium_mg: Optional[float] = None
    water_pct: Optional[float] = None
    ingredients: Optional[str] = None


class CatalogItemCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Nom de l'aliment ou du plat")
    item_type: Literal["food", "dish"] = Field("food", description="'food' pour aliment simple, 'dish' pour plat/recette")
    default_unit: str = Field("g", description="Unité de référence (g, portion, ml, pièce)")
    default_quantity: float = Field(100.0, gt=0, description="Quantité de référence")
    calories_per_unit: float = Field(..., ge=0.0, description="Calories (kcal) pour la quantité de référence")
    protein_per_unit_g: float = Field(0.0, ge=0.0, description="Protéines (g)")
    carbs_per_unit_g: float = Field(0.0, ge=0.0, description="Glucides (g)")
    fat_per_unit_g: float = Field(0.0, ge=0.0, description="Lipides (g)")
    fiber_per_unit_g: Optional[float] = Field(0.0, ge=0.0, description="Fibres (g)")
    photo_url: Optional[str] = Field(None, description="Photo ou data URL")
    recipe_items: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Ingrédients composant le plat")
    benefits: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Bienfaits associés à la création")
    is_public: Optional[bool] = Field(False, description="True si l'aliment doit être public")


class CatalogItemUpdateRequest(BaseModel):
    name: Optional[str] = None
    item_type: Optional[Literal["food", "dish"]] = None
    default_unit: Optional[str] = None
    default_quantity: Optional[float] = None
    calories_per_unit: Optional[float] = None
    protein_per_unit_g: Optional[float] = None
    carbs_per_unit_g: Optional[float] = None
    fat_per_unit_g: Optional[float] = None
    fiber_per_unit_g: Optional[float] = None
    photo_url: Optional[str] = None
    recipe_items: Optional[List[Dict[str, Any]]] = None
    is_public: Optional[bool] = None


class CatalogSubscriptionCreateRequest(BaseModel):
    target_user_id: Optional[int] = Field(None, description="ID de l'utilisateur auquel s'abonner")
    email: Optional[str] = Field(None, description="Email de l'utilisateur auquel s'abonner")


class MealJournalAddItemRequest(BaseModel):
    date: Optional[dt_module.date] = None
    food_item_id: Optional[int] = None
    name: Optional[str] = None
    quantity: float = Field(..., gt=0, description="Quantité consommée")
    unit: Optional[str] = "g"
    # Macros optionnelles si pas de food_item_id
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    fiber_g: Optional[float] = None


class MealJournalAddBatchRequest(BaseModel):
    date: Optional[dt_module.date] = None
    items: List[MealJournalAddItemRequest] = Field(..., min_length=1)


class SaveAsDishRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Nom du plat à créer dans le catalogue")
    date: Optional[dt_module.date] = None
    photo_url: Optional[str] = None


def get_db() -> Database:
    """Retourne l'instance Database courante depuis src.app (supporte le monkeypatch des tests)."""
    return app_module.db


def get_nutrition_engine() -> NutritionEngine:
    """Retourne l'instance NutritionEngine courante depuis src.app."""
    return app_module.nutrition_engine


def calculate_day_summary(target_date: date, user_id: int = 1) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Calcule les 4 repas et le résumé nutritionnel de la journée sans écriture en base."""
    db = get_db()
    logs = db.get_meal_logs_for_date(target_date, user_id=user_id)
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
            mlog = MealLog(
                id=None,
                user_id=user_id,
                date=target_date,
                meal_type=mt,
                total_calories=0.0,
                total_protein_g=0.0,
                total_carbs_g=0.0,
                total_fat_g=0.0,
                total_fiber_g=0.0,
                items=[]
            )
        m_dict = mlog.model_dump()
        meals_response.append(m_dict)

        day_total_cal += mlog.total_calories
        day_total_prot += mlog.total_protein_g
        day_total_carbs += mlog.total_carbs_g
        day_total_fat += mlog.total_fat_g
        day_total_fiber += (mlog.total_fiber_g or 0.0)

    cal_p = day_total_prot * 4.0
    cal_c = day_total_carbs * 4.0
    cal_f = day_total_fat * 9.0
    sum_macro_cal = cal_p + cal_c + cal_f
    macros_pct = {
        "protein_pct": round((cal_p / sum_macro_cal) * 100.0, 1) if sum_macro_cal > 0 else 0.0,
        "carbs_pct": round((cal_c / sum_macro_cal) * 100.0, 1) if sum_macro_cal > 0 else 0.0,
        "fat_pct": round((cal_f / sum_macro_cal) * 100.0, 1) if sum_macro_cal > 0 else 0.0
    }

    day_summary = {
        "total_calories": round(day_total_cal, 1),
        "total_protein_g": round(day_total_prot, 1),
        "total_carbs_g": round(day_total_carbs, 1),
        "total_fat_g": round(day_total_fat, 1),
        "total_fiber_g": round(day_total_fiber, 1),
        "macros_pct": macros_pct
    }
    return meals_response, day_summary


# =====================================================================
# Endpoints Nutrition, Photo IA et Journal
# =====================================================================

@router.get("/api/meals")
def get_meals(
    limit: int = Query(50, ge=1, le=200),
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un utilisateur ami pour consultation en lecture seule"),
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Retourne les repas récemment enregistrés pour l'utilisateur connecté ou un ami autorisé."""
    db = get_db()
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    meals = db.get_meals(limit=limit, user_id=target_uid)
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

    calorie_estimator = app_module.calorie_estimator
    result = calorie_estimator.analyze_meal(
        image_bytes=image_bytes,
        mime_type=mime_type,
        description=req.description,
        portion_scale=scale,
        meal_type=req.meal_type
    )
    # Aplatir les macros à la racine si présentes pour compatibilité client
    if isinstance(result, dict) and "macros" in result and isinstance(result["macros"], dict):
        macros = result["macros"]
        result.setdefault("protein_g", macros.get("protein_g", 0.0))
        result.setdefault("carbs_g", macros.get("carbs_g", 0.0))
        result.setdefault("fat_g", macros.get("fat_g", 0.0))
        result.setdefault("fiber_g", macros.get("fiber_g", 0.0))
    return result


@router.post("/api/meals")
def log_meal(req: MealSaveRequest, current_user: AuthUser = Depends(app_module.get_current_user)):
    """Enregistre définitivement un repas décomposé ou direct dans le journal alimentaire pour l'utilisateur connecté."""
    db = get_db()
    nutrition_engine = get_nutrition_engine()
    target_date = req.date or dt_module.date.today()

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
        calorie_estimator = app_module.calorie_estimator
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
def update_meal(meal_id: int, req: MealSaveRequest, current_user: AuthUser = Depends(app_module.get_current_user)):
    """Met à jour un repas existant dans le journal pour l'utilisateur connecté."""
    db = get_db()
    target_date = req.date or dt_module.date.today()
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
def delete_meal(meal_id: int, current_user: AuthUser = Depends(app_module.get_current_user)):
    """Supprime un repas du journal pour l'utilisateur connecté."""
    db = get_db()
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
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Récupère la liste des plats sauvegardés/réutilisables de l'utilisateur connecté."""
    db = get_db()
    meals = db.get_saved_meals(meal_type=meal_type, is_favorite=is_favorite, user_id=current_user.id)
    return [m.model_dump() for m in meals]


@router.post("/api/meals/saved")
def create_saved_meal(
    req: SavedMealCreateRequest,
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Crée et enregistre un nouveau plat type dans la bibliothèque réutilisable."""
    db = get_db()
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
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Récupère les détails d'un plat type réutilisable."""
    db = get_db()
    saved = db.get_saved_meal_by_id(meal_id, user_id=current_user.id)
    if not saved:
        raise HTTPException(status_code=404, detail="Plat réutilisable introuvable")
    return saved.model_dump()


@router.put("/api/meals/saved/{meal_id}")
def update_saved_meal(
    meal_id: int,
    req: SavedMealUpdateRequest,
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Met à jour un plat type réutilisable existant."""
    db = get_db()
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
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Supprime un plat réutilisable de la bibliothèque."""
    db = get_db()
    deleted = db.delete_saved_meal(meal_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Plat réutilisable introuvable")
    return {"status": "success", "message": f"Plat sauvegardé #{meal_id} supprimé avec succès"}


@router.post("/api/meals/saved/{meal_id}/log")
def log_saved_meal_to_journal(
    meal_id: int,
    req: SavedMealLogRequest = SavedMealLogRequest(),
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Logge instantanément un plat réutilisable dans le journal alimentaire du jour."""
    db = get_db()
    saved = db.get_saved_meal_by_id(meal_id, user_id=current_user.id)
    if not saved:
        raise HTTPException(status_code=404, detail="Plat réutilisable introuvable")

    factor = req.portion_factor if req.portion_factor is not None else 1.0
    target_date = req.date or dt_module.date.today()
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
# Endpoints Catalogue d'Aliments & Plats (Stage 12)
# =====================================================================

@router.get("/api/catalog/items")
def get_catalog_items(
    type: Optional[str] = Query(None, description="Filtre par type ('food' ou 'dish')"),
    q: Optional[str] = Query(None, description="Recherche textuelle par nom"),
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un ami pour consultation en lecture seule"),
    source: Optional[str] = Query(None, description="Source des aliments ('all', 'mine', 'public', 'friends')"),
    friend_id: Optional[int] = Query(None, description="ID d'un ami spécifique pour explorer son catalogue"),
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Récupère le catalogue d'aliments et de plats selon la source (all, mine, public, friends) ou friend_id."""
    db = get_db()
    # Consultation en lecture seule : cible l'utilisateur concerné (ami ou soi-même) après vérification d'accès.
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    # Par défaut, si friend_id est spécifié on filtre sur l'ami, sinon si source n'est pas spécifié, on retourne "mine"
    effective_source = source if source is not None else ("mine" if not friend_id else "friends")
    items = db.get_food_items(
        item_type=type,
        query=q,
        user_id=target_uid,
        source=effective_source,
        friend_id=friend_id
    )
    return [it.model_dump() for it in items]


@router.post("/api/catalog/items")
def create_catalog_item(
    req: CatalogItemCreateRequest,
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Crée un nouvel aliment ou plat dans le catalogue."""
    db = get_db()
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
        recipe_items=req.recipe_items or [],
        is_public=bool(req.is_public)
    )
    created = db.insert_food_item(item, user_id=current_user.id)
    return created.model_dump()


@router.put("/api/catalog/items/{item_id}")
def update_catalog_item(
    item_id: int,
    req: CatalogItemUpdateRequest,
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Met à jour un aliment ou un plat du catalogue."""
    db = get_db()
    update_data = {k: v for k, v in req.model_dump().items() if v is not None}
    updated = db.update_food_item(item_id, update_data, user_id=current_user.id)
    if not updated:
        raise HTTPException(status_code=404, detail="Élément de catalogue introuvable ou non autorisé")
    return updated.model_dump()


@router.delete("/api/catalog/items/{item_id}")
def delete_catalog_item(
    item_id: int,
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Supprime un aliment ou un plat du catalogue."""
    db = get_db()
    deleted = db.delete_food_item(item_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Élément de catalogue introuvable ou non autorisé")
    return {"status": "success", "message": f"Élément #{item_id} supprimé du catalogue"}


# ---------------------------------------------------------
# Abonnements aux catalogues d'amis
# ---------------------------------------------------------

@router.get("/api/catalog/subscriptions")
def get_catalog_subscriptions(current_user: AuthUser = Depends(app_module.get_current_user)):
    """Liste tous les catalogues d'amis auxquels l'utilisateur est abonné."""
    db = get_db()
    subs = db.get_catalog_subscriptions(subscriber_id=current_user.id)
    return subs


@router.post("/api/catalog/subscriptions")
def create_catalog_subscription(
    req: CatalogSubscriptionCreateRequest,
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """S'abonne au catalogue d'un utilisateur par son ID ou son adresse email."""
    db = get_db()
    target_user_id = req.target_user_id
    if not target_user_id and req.email:
        target_user = db.get_user_by_email(req.email)
        if not target_user:
            raise HTTPException(status_code=404, detail="Utilisateur cible introuvable")
        target_user_id = target_user["id"]

    if not target_user_id:
        raise HTTPException(status_code=400, detail="target_user_id ou email obligatoire")

    if target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Impossible de s'abonner à son propre catalogue")

    success = db.add_catalog_subscription(subscriber_id=current_user.id, target_user_id=target_user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Utilisateur cible introuvable")

    return {
        "status": "success",
        "message": f"Abonnement au catalogue de l'utilisateur #{target_user_id} activé",
        "subscriber_id": current_user.id,
        "target_user_id": target_user_id
    }


@router.delete("/api/catalog/subscriptions/{target_user_id}")
def delete_catalog_subscription(
    target_user_id: int,
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Se désabonne du catalogue d'un ami."""
    db = get_db()
    removed = db.remove_catalog_subscription(subscriber_id=current_user.id, target_user_id=target_user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Abonnement introuvable ou déjà supprimé")
    return {
        "status": "success",
        "message": f"Désabonnement du catalogue #{target_user_id} effectué"
    }


@router.get("/api/catalog/friends/{target_user_id}/items")
def get_friend_catalog_items(
    target_user_id: int,
    type: Optional[str] = Query(None, description="Filtre par type ('food' ou 'dish')"),
    q: Optional[str] = Query(None, description="Recherche textuelle par nom"),
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Explore le catalogue complet d'un ami spécifique."""
    db = get_db()
    friend = db.get_user_by_id(target_user_id)
    if not friend:
        raise HTTPException(status_code=404, detail="Ami introuvable")

    items = db.get_food_items(
        item_type=type,
        query=q,
        user_id=current_user.id,
        source="mine",
        friend_id=target_user_id
    )
    return {
        "friend": {
            "id": friend["id"],
            "name": friend.get("name"),
            "email": friend.get("email"),
            "picture": friend.get("picture")
        },
        "is_subscribed": db.is_subscribed_to_catalog(current_user.id, target_user_id),
        "items": [it.model_dump() for it in items]
    }


@router.get("/api/catalog/items/{item_id}/benefits")
def get_catalog_item_benefits(
    item_id: int,
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Récupère les bienfaits associés à un aliment/plat donné."""
    db = get_db()
    item = db.get_food_item_by_id(item_id, user_id=current_user.id)
    if not item:
        raise HTTPException(status_code=404, detail="Élément de catalogue introuvable")
    benefits = db.get_food_item_benefits(item_id)
    return [b.model_dump() for b in benefits]


@router.put("/api/catalog/items/{item_id}/benefits")
def update_catalog_item_benefits(
    item_id: int,
    req: UpdateCatalogItemBenefitsRequest,
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Met à jour les bienfaits associés à un aliment/plat donné (sélection manuelle ou auto)."""
    db = get_db()
    item = db.get_food_item_by_id(item_id, user_id=current_user.id)
    if not item:
        raise HTTPException(status_code=404, detail="Élément de catalogue introuvable")
    updated_benefits = db.set_food_item_benefits(item_id, req.benefits)
    return [b.model_dump() for b in updated_benefits]


@router.get("/api/nutrition/benefits")
def get_nutrition_benefits():
    """Récupère la liste de tous les bienfaits disponibles dans le référentiel expert groupés par catégorie."""
    db = get_db()
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


# =====================================================================
# Endpoints Journal des Repas Quotidiens (Stage 12)
# =====================================================================

@router.get("/api/meals/journal")
def get_meals_journal(
    date_param: Optional[str] = Query(None, alias="date", description="Date YYYY-MM-DD"),
    user_id: Optional[int] = Query(None, description="Identifiant optionnel d'un utilisateur ami pour consultation en lecture seule"),
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Récupère les 4 repas du jour avec la composition et les totaux (lecture pure sans écriture en base)."""
    db = get_db()
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    target_date = dt_module.date.fromisoformat(date_param) if date_param else dt_module.date.today()
    meals_response, day_summary = calculate_day_summary(target_date, user_id=target_uid)

    return {
        "date": target_date.isoformat(),
        "meals": meals_response,
        "day_summary": day_summary
    }


@router.post("/api/meals/journal/{meal_type}/items")
def add_item_to_meal_journal(
    meal_type: str,
    payload: Union[MealJournalAddItemRequest, MealJournalAddBatchRequest, List[MealJournalAddItemRequest]],
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Ajoute un ou plusieurs aliments/plats (avec quantité spécifiée) dans le repas d'une date."""
    db = get_db()
    if meal_type not in ["breakfast", "lunch", "snack", "dinner"]:
        raise HTTPException(status_code=400, detail="meal_type invalide (breakfast, lunch, snack, dinner)")

    # Déterminer la liste d'items à ajouter
    if isinstance(payload, list):
        items_to_add = payload
        target_date = dt_module.date.today()
    elif isinstance(payload, MealJournalAddBatchRequest):
        items_to_add = payload.items
        target_date = payload.date or dt_module.date.today()
    else:
        items_to_add = [payload]
        target_date = payload.date or dt_module.date.today()

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

    action_date = last_log.date if last_log else target_date
    _, day_summary = calculate_day_summary(action_date, user_id=current_user.id)

    return {
        "status": "success",
        "meal_type": meal_type,
        "meal_log": last_log.model_dump() if last_log else None,
        "day_summary": day_summary
    }


@router.delete("/api/meals/journal/items/{item_id}")
def delete_meal_journal_item(
    item_id: int,
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Retire un aliment d'un repas et actualise le repas parent."""
    db = get_db()
    updated_log = db.delete_meal_log_item(item_id, user_id=current_user.id)
    if not updated_log:
        raise HTTPException(status_code=404, detail="Ligne d'aliment introuvable dans le journal")

    _, day_summary = calculate_day_summary(updated_log.date, user_id=current_user.id)

    return {
        "status": "success",
        "message": f"Aliment #{item_id} retiré du repas",
        "meal_log": updated_log.model_dump(),
        "day_summary": day_summary
    }


@router.post("/api/meals/journal/{meal_type}/save-as-dish")
def save_meal_as_dish(
    meal_type: str,
    req: SaveAsDishRequest,
    current_user: AuthUser = Depends(app_module.get_current_user)
):
    """Transforme la composition d'un repas consommé en un nouveau plat réutilisable dans le catalogue."""
    db = get_db()
    target_date = req.date or dt_module.date.today()
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
