"""Routeur FastAPI pour les endpoints Nutrition, Photo IA et Journal."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from typing import Optional

from src.app import app, db, AuthUser, nutrition_engine, calorie_estimator, get_current_user
from src.models import FoodItem, MealType
from src.nutrition_engine import NutritionEngine

router = APIRouter(prefix="/api/meals", tags=["meals"])


@router.get("")
def get_meals(
    limit: int = 50,
    user_id: Optional[int] = None,
    current_user: AuthUser = Depends(get_current_user),
):
    """Retourne les repas récemment enregistrés pour l'utilisateur connecté ou un ami autorisé."""
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    meals = db.get_meals(limit=limit, user_id=target_uid)
    return [m.model_dump() for m in meals]


@router.get("/analyze-photo")
def get_analyze_photo_info():
    """Information et métadonnées sur le moteur d'analyse photo de repas."""
    return {
        "status": "available",
        "description": "Moteur multimodal IA Gemini Vision et fallback hybride OpenFoodFacts",
        "supported_formats": ["image/jpeg", "image/png", "image/webp"],
        "max_size_mb": 10,
        "portion_scale_range": [0.5, 2.0]
    }


@router.post("/estimate")
def estimate_meal_calories(
    req: dict,
    current_user: AuthUser = Depends(get_current_user),
):
    """Estime les calories et macronutriments à partir d'une photo ou d'une description."""
    scale = max(0.5, min(2.0, req.get("portion_scale", 1.0)))

    photo_data_url = req.get("photo_data_url")
    description = req.get("description")
    meal_type = req.get("meal_type", "lunch")

    # Décoder image éventuelle si fournie sous forme data-url
    image_bytes = None
    mime_type = "image/jpeg"
    if photo_data_url and "base64," in photo_data_url:
        import base64
        try:
            header, encoded = photo_data_url.split("base64,", 1)
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
        description=description,
        portion_scale=scale,
        meal_type=meal_type
    )
    # Aplatir les macros à la racine si présentes pour compatibilité client
    if isinstance(result, dict) and "macros" in result and isinstance(result["macros"], dict):
        macros = result["macros"]
        result.setdefault("protein_g", macros.get("protein_g", 0.0))
        result.setdefault("carbs_g", macros.get("carbs_g", 0.0))
        result.setdefault("fat_g", macros.get("fat_g", 0.0))
        result.setdefault("fiber_g", macros.get("fiber_g", 0.0))
    return result


@router.post("")
def log_meal(
    req: dict,
    current_user: AuthUser = Depends(get_current_user),
):
    """Enregistre définitivement un repas décomposé ou direct dans le journal alimentaire."""
    target_date = req.get("date", None)
    meal_type = req.get("meal_type", "lunch")

    if req.get("items"):
        items = req.get("items", [])
        saved = nutrition_engine.log_meal(
            date_val=target_date or "today",
            meal_type=meal_type,
            items=items,
            photo_data_url=req.get("photo_data_url"),
            user_id=current_user.id
        )
    elif req.get("total_calories_kcal") is not None:
        meal_name = req.get("meal_name", f"Repas direct ({meal_type})")
        items = [
            FoodItem(
                name=meal_name,
                calories_kcal=round(req.get("total_calories_kcal", 0.0), 1),
                protein_g=round(req.get("protein_g", 0.0), 1),
                carbs_g=round(req.get("carbs_g", 0.0), 1),
                fat_g=round(req.get("fat_g", 0.0), 1),
                fiber_g=round(req.get("fiber_g", 0.0), 1),
                confidence_score=1.0
            )
        ]
        from src.models import MealEntry
        entry = MealEntry(
            date_val=target_date or "today",
            meal_type=meal_type,
            items=items,
            photo_data_url=req.get("photo_data_url"),
            user_id=current_user.id
        )
        saved = nutrition_engine.log_meal(
            date_val=target_date or "today",
            meal_type=meal_type,
            items=items,
            photo_data_url=req.get("photo_data_url"),
            user_id=current_user.id
        )
    else:
        return JSONResponse(status_code=400, content={"detail": "Either items or total_calories_kcal must be provided"})

    return saved.model_dump() if hasattr(saved, 'model_dump') else saved