"""Modèles de données standardisés pour VitalTrack."""

from datetime import date as DateType, datetime
from typing import Any, Dict, List, Literal, Optional
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
    """Entrée de repas (préparée pour Stage 2 - Photo IA & OpenFoodFacts)."""
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
CatalogUnit = Literal["g", "portion", "ml", "piece", "pièce"]
MealSlot = Literal["breakfast", "lunch", "snack", "dinner"]


class NutritionBenefitItem(BaseModel):
    """Bienfait nutritionnel issu du référentiel expert."""
    id: str
    category: str
    category_id: int
    title: str
    description: str
    icon: str
    rule_config: Optional[Dict[str, Any]] = None


class AssociatedBenefit(BaseModel):
    """Bienfait associé à un aliment ou plat."""
    benefit_id: str
    category: str
    category_id: int
    title: str
    description: str
    icon: str
    source: str = "manual"  # 'auto_rule' ou 'manual'
    explanation: Optional[str] = None


class BenefitEvaluationResult(BaseModel):
    """Résultat d'évaluation d'un bienfait par le moteur de règles."""
    benefit_id: str
    category: str
    category_id: int
    title: str
    description: str
    icon: str
    explanation: str
    matched: bool = True


class CatalogItem(BaseModel):
    """Aliment simple ou plat/recette réutilisable du catalogue personnel."""
    id: Optional[int] = None
    user_id: Optional[int] = 1
    name: str = Field(..., min_length=1, description="Nom de l'aliment ou du plat")
    item_type: CatalogItemType = Field("food", description="'food' pour aliment simple, 'dish' pour plat/recette")
    default_unit: str = Field("g", description="Unité de référence (g, portion, ml, pièce)")
    default_quantity: float = Field(100.0, gt=0, description="Quantité de référence")
    calories_per_unit: float = Field(..., ge=0.0, description="Calories (kcal) pour la quantité de référence")
    protein_per_unit_g: float = Field(0.0, ge=0.0, description="Protéines en grammes")
    carbs_per_unit_g: float = Field(0.0, ge=0.0, description="Glucides en grammes")
    fat_per_unit_g: float = Field(0.0, ge=0.0, description="Lipides en grammes")
    fiber_per_unit_g: Optional[float] = Field(0.0, ge=0.0, description="Fibres en grammes")
    photo_url: Optional[str] = Field(None, description="Photo ou image de référence")
    benefits: List[AssociatedBenefit] = Field(default_factory=list, description="Bienfaits associés")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MealLogItem(BaseModel):
    """Ligne d'aliment ou de plat consommé au sein d'un repas donné."""
    id: Optional[int] = None
    meal_log_id: Optional[int] = None
    food_item_id: Optional[int] = None
    name: str = Field(..., min_length=1, description="Nom de l'aliment/plat consommé")
    quantity: float = Field(..., gt=0, description="Quantité consommé")
    unit: str = Field("g", description="Unité consommé")
    calories: float = Field(..., ge=0.0, description="Calories calculées au prorata")
    protein_g: float = Field(0.0, ge=0.0, description="Protéines calculées")
    carbs_g: float = Field(0.0, ge=0.0, description="Glucides calculées")
    fat_g: float = Field(0.0, ge=0.0, description="Lipides calculées")
    fiber_g: Optional[float] = Field(0.0, ge=0.0, description="Fibres calculées")
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
