"""Modèles de données standardisés pour VitalTrack."""

from datetime import date as DateType, datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


WeightSource = Literal["withings", "garmin", "manual", "apple_health", "demo"]
ActivitySource = Literal["oura", "health_connect", "apple_health", "strava", "demo"]
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
