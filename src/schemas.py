"""Modèles Pydantic de requêtes de l'API VitalTrack."""

import datetime as dt_module
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from src.models import FoodItem, MealType
from src.auth import AuthUser  # noqa: F401

class WeightInput(BaseModel):
    date: Optional[dt_module.date] = None
    weight_kg: float = Field(..., gt=20.0, lt=350.0, description="Poids en kg")
    body_fat_pct: Optional[float] = Field(None, ge=3.0, le=60.0, description="% masse grasse")
    muscle_mass_kg: Optional[float] = Field(None, ge=10.0, le=150.0, description="Masse musculaire en kg")
    water_pct: Optional[float] = Field(None, ge=30.0, le=80.0, description="% eau")
    bmi: Optional[float] = Field(None, ge=10.0, le=70.0, description="IMC")
    notes: Optional[str] = None
    source: Literal["manual", "withings", "garmin", "apple_health", "demo"] = "manual"


class ActivityInput(BaseModel):
    date: Optional[dt_module.date] = None
    steps: int = Field(0, ge=0, description="Nombre de pas")
    active_calories_kcal: float = Field(0.0, ge=0.0, description="Calories actives en exercice")
    workout_minutes: int = Field(0, ge=0, description="Minutes d'activité physique")
    workout_type: Optional[str] = Field(None, description="Type d'entraînement")
    resting_hr_bpm: Optional[int] = Field(None, ge=30, le=220, description="Fréquence cardiaque au repos")
    hrv_ms: Optional[float] = Field(None, ge=0.0, description="Variabilité cardiaque (HRV en ms)")
    sleep_score: Optional[int] = Field(None, ge=0, le=100, description="Score de sommeil")
    source: Literal["oura", "health_connect", "apple_health", "strava", "demo"] = "health_connect"


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


class DeviceSyncRequest(BaseModel):
    device_id: str


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


class DeviceConnectInput(BaseModel):
    device_id: str
    name: Optional[str] = None
    device_type: Optional[str] = None
    auth_type: Optional[str] = "connected"  # "cloud_api", "google_health", "bluetooth", "connected", "ringconn_openapi", "withings_oauth", "oura_bearer_token"
    api_key: Optional[str] = None
    token: Optional[str] = None
    credentials: Optional[Dict[str, Any]] = None
    account_email: Optional[str] = None
    connected: bool = True


# =====================================================================
# Endpoints Catalogue d'Aliments & Plats (Stage 12)
# =====================================================================

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


# =====================================================================
# Endpoints Sauvegarde / Restauration & Persistance Anti-Perte Vercel
# =====================================================================

class BackupRestoreInput(BaseModel):
    data: Dict[str, Any]
    overwrite: bool = False
