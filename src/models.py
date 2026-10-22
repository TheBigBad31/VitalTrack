"""Modèles de données standardisés pour VitalTrack."""

from datetime import date as DateType, datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


WeightSource = Literal["withings", "garmin", "manual", "apple_health", "demo"]
ActivitySource = Literal["oura", "ringconn", "health_connect", "apple_health", "strava", "demo"]
MealType = Literal["breakfast", "lunch", "dinner", "snack"]


class WeightEntry(BaseModel):
    """Entrée de pesée et de composition corporelle."""
    id: Optional[int] = None
    date: DateType
    weight_kg: float = Field(..., description="Poids en kilogrammes")
    body_fat_pct: Optional[float] = Field(None, description="Masse grasse en pourcentage")
    muscle_mass_kg: Optional[float] = Field(None, description="Masse musculaire en kg")
    water_pct: Optional[float] = Field(None, description="Masse hydrique en pourcentage")
    bmi: Optional[float] = Field(None, description="Indice de Masse Corporelle (IMC)")
    trend_7d_kg: Optional[float] = Field(None, description="Tendance lissée sur 7 jours")
    source: WeightSource = "manual"
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class ActivityEntry(BaseModel):
    """Résumé quotidien d'activité physique et biométrie."""
    id: Optional[int] = None
    date: DateType
    steps: int = Field(0, description="Nombre de pas quotidiens")
    active_calories_kcal: float = Field(0.0, description="Calories actives brûlées")
    bmr_kcal: float = Field(0.0, description="Métabolisme de base (BMR)")
    total_burned_kcal: float = Field(0.0, description="Calories totales dépensées")
    workout_minutes: int = Field(0, description="Minutes d'entraînement")
    workout_type: Optional[str] = Field(None, description="Type d'entraînement prédominant")
    resting_hr_bpm: Optional[int] = Field(None, description="Fréquence cardiaque au repos")
    hrv_ms: Optional[float] = Field(None, description="Variabilité de fréquence cardiaque (RMSSD en ms)")
    sleep_score: Optional[int] = Field(None, description="Score de sommeil global (0-100)")
    source: ActivitySource = "demo"
    created_at: Optional[datetime] = None


class FoodItem(BaseModel):
    """Aliment individuel détecté ou saisi."""
    name: str
    portion_g: Optional[float] = None
    calories_kcal: float
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: Optional[float] = 0.0
    confidence_score: Optional[float] = None


class MealEntry(BaseModel):
    """Entrée de repas (préparée pour Stage 2 - Photo IA \u0026 OpenFoodFacts)."""
    id: Optional[int] = None
    date: DateType
    meal_type: MealType
    total_calories_kcal: float
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: Optional[float] = 0.0
    photo_data_url: Optional[str] = None
    items: List[FoodItem] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class SavedMeal(BaseModel):
    """Plat type ou favori réutilisable pour la bibliothèque de repas."""
    id: Optional[int] = None
    user_id: Optional[int] = 1
    name: str = Field(..., description="Nom du plat réutilisable")
    meal_type: MealType = Field("lunch", description="Type de repas (breakfast, lunch, snack, dinner)")
    serving_size: Optional[str] = Field("1 portion", description="Taille de portion ou description")
    quantity_grams: Optional[float] = Field(None, description="Poids de la portion en grammes")
    calories: float = Field(..., ge=0.0, description="Calories totales (kcal)")
    protein_g: float = Field(0.0, ge=0.0, description="Protéines en grammes")
    carbs_g: float = Field(0.0, ge=0.0, description="Glucides en grammes")
    fat_g: float = Field(0.0, ge=0.0, description="Lipides en grammes")
    fiber_g: Optional[float] = Field(0.0, ge=0.0, description="Fibres en grammes")
    ingredients: Optional[str] = Field(None, description="Description ou composition détaillée en ingrédients")
    items: List[FoodItem] = Field(default_factory=list, description="Liste décomposée des aliments")
    photo_url: Optional[str] = Field(None, description="URL de la photo ou data-url de l'image")
    is_favorite: bool = Field(False, description="Marqué comme plat favori")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


CatalogItemType = Literal["food", "dish"]
CatalogUnit = Literal["g", "portion", "ml", "piece", "pi\u00e8ce"]
MealSlot = Literal["breakfast", "lunch", "snack", "dinner"]


class CatalogItem(BaseModel):
    """Aliment simple ou plat/recette r\u00e9utilisable du catalogue personnel."""
    id: Optional[int] = None
    user_id: Optional[int] = 1
    name: str = Field(..., min_length=1, description="Nom de l'aliment ou du plat")
    item_type: CatalogItemType = Field("food", description="'food' pour aliment simple, 'dish' pour plat/recette")
    default_unit: str = Field("g", description="Unit\u00e9 de r\u00e9f\u00e9rence (g, portion, ml, pi\u00e8ce)")
    default_quantity: float = Field(100.0, gt=0, description="Quantit\u00e9 de r\u00e9f\u00e9rence")
    calories_per_unit: float = Field(..., ge=0.0, description="Calories (kcal) pour la quantit\u00e9 de r\u00e9f\u00e9rence")
    protein_per_unit_g: float = Field(0.0, ge=0.0, description="Prot\u00e9ines en grammes")
    carbs_per_unit_g: float = Field(0.0, ge=0.0, description="Glucides en grammes")
    fat_per_unit_g: float = Field(0.0, ge=0.0, description="Lipides en grammes")
    fiber_per_unit_g: Optional[float] = Field(0.0, ge=0.0, description="Fibres en grammes")
    photo_url: Optional[str] = Field(None, description="Photo ou image de r\u00e9f\u00e9rence")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MealLogItem(BaseModel):
    """Ligne d'aliment ou de plat consomm\u00e9 au sein d'un repas donn\u00e9."""
    id: Optional[int] = None
    meal_log_id: Optional[int] = None
    food_item_id: Optional[int] = None
    name: str = Field(..., min_length=1, description="Nom de l'aliment/plat consomm\u00e9")
    quantity: float = Field(..., gt=0, description="Quantit\u00e9 consomm\u00e9")
    unit: str = Field("g", description="Unit\u00e9 consomm\u00e9")
    calories: float = Field(..., ge=0.0, description="Calories calcul\u00e9es au prorata")
    protein_g: float = Field(0.0, ge=0.0, description="Prot\u00e9ines calcul\u00e9es")
    carbs_g: float = Field(0.0, ge=0.0, description="Glucides calcul\u00e9es")
    fat_g: float = Field(0.0, ge=0.0, description="Lipides calcul\u00e9es")
    fiber_g: Optional[float] = Field(0.0, ge=0.0, description="Fibres calcul\u00e9es")
    created_at: Optional[datetime] = None


class MealLog(BaseModel):
    """Instance d'un des 4 repas quotidiens (breakfast, lunch, snack, dinner)."""
    id: Optional[int] = None
    user_id: Optional[int] = 1
    date: DateType
    meal_type: MealSlot
    photo_url: Optional[str] = None
    total_calories: float = 0.0
    total_protein_g: float = 0.0
    total_carbs_g: float = 0.0
    total_fat_g: float = 0.0
    total_fiber_g: Optional[float] = 0.0
    items: List[MealLogItem] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
