"""Modles de donnǸes standardisǸs pour VitalTrack."""

from datetime import date as DateType, datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


WeightSource = Literal["withings", "garmin", "manual", "apple_health", "health_connect", "demo", "simulation"]
ActivitySource = Literal["oura", "ringconn", "health_connect", "apple_health", "strava", "demo", "simulation"]
MealType = Literal["breakfast", "lunch", "dinner", "snack"]


class WeightEntry(BaseModel):
    """EntrǸe de pesǸe et de composition corporelle."""
    id: Optional[int] = None
    date: DateType
    weight_kg: float = Field(..., description="Poids en kilogrammes")
    body_fat_pct: Optional[float] = Field(None, description="Masse grasse en pourcentage")
    muscle_mass_kg: Optional[float] = Field(None, description="Masse musculaire en kg")
    water_pct: Optional[float] = Field(None, description="Masse hydrique en pourcentage")
    bmi: Optional[float] = Field(None, description="Indice de Masse Corporelle (IMC)")
    trend_7d_kg: Optional[float] = Field(None, description="Tendance lissǸe sur 7 jours")
    source: WeightSource = "manual"
    is_simulated: bool = Field(False, description="Indique si la mesure provient d'une simulation/dǸmo")
    notes: Optional[str] = None
    external_id: Optional[str] = Field(None, description="Identifiant unique externe pour dǸduplication")
    measured_at: Optional[str] = Field(None, description="Horodatage ISO de la mesure (multi-pesǸes par jour)")
    idempotency_key: Optional[str] = Field(None, description="ClǸ d'idempotence composite")
    created_at: Optional[datetime] = None


class ActivityEntry(BaseModel):
    """RǸsumǸ quotidien d'activitǸ physique et biomǸtrie."""
    id: Optional[int] = None
    date: DateType
    steps: int = Field(0, description="Nombre de pas quotidiens")
    active_calories_kcal: float = Field(0.0, description="Calories actives brǯlǸes")
    bmr_kcal: float = Field(0.0, description="MǸtabolisme de base (BMR)")
    total_burned_kcal: float = Field(0.0, description="Calories totales dǸpensǸes")
    workout_minutes: int = Field(0, description="Minutes d'entraǩnement")
    workout_type: Optional[str] = Field(None, description="Type d'entraǩnement prǸdominant")
    resting_hr_bpm: Optional[int] = Field(None, description="FrǸquence cardiaque au repos")
    hrv_ms: Optional[float] = Field(None, description="VariabilitǸ de frǸquence cardiaque (RMSSD en ms)")
    sleep_score: Optional[int] = Field(None, description="Score de sommeil global (0-100)")
    source: ActivitySource = "demo"
    is_simulated: bool = Field(False, description="Indique si l'activitǸ provient d'une simulation/dǸmo")
    external_id: Optional[str] = Field(None, description="Identifiant unique externe pour dǸduplication")
    idempotency_key: Optional[str] = Field(None, description="ClǸ d'idempotence composite")
    created_at: Optional[datetime] = None


class DailyMetricsEntry(BaseModel):
    """MǸtriques biomǸtriques quotidiennes unifiǸes multi-sources (RingConn Gen 3, Withings, SantǸ Connect)."""
    id: Optional[int] = None
    user_id: Optional[int] = 1
    date: DateType
    source: str = Field(..., description="Source de donnǸes (ex: ringconn, withings, health_connect)")
    steps: int = Field(0, description="Nombre de pas")
    active_calories_kcal: float = Field(0.0, description="Calories actives brǯlǸes")
    total_calories_kcal: float = Field(0.0, description="Calories totales dǸpensǸes")
    resting_hr_bpm: Optional[int] = Field(None, description="FC repos en bpm")
    hrv_rmssd_ms: Optional[float] = Field(None, description="HRV RMSSD en ms")
    hrv_sdnn_ms: Optional[float] = Field(None, description="HRV SDNN en ms")
    spo2_pct: Optional[float] = Field(None, description="SpO2 en %")
    skin_temperature_c: Optional[float] = Field(None, description="TempǸrature cutanǸe en C")
    sleep_score: Optional[int] = Field(None, description="Score de sommeil (0-100)")
    recovery_score: Optional[int] = Field(None, description="Score de rǸcupǸration (0-100)")
    external_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class WorkoutEntry(BaseModel):
    """SǸance d'exercice physique ou entraǩnement spǸcifique."""
    id: Optional[int] = None
    user_id: Optional[int] = 1
    source: str = Field(..., description="Source (ex: strava, health_connect, apple_health)")
    external_id: Optional[str] = None
    workout_type: str = Field(..., description="Type de sport (running, cycling, swimming, strength, walking...)")
    start_time: str = Field(..., description="Horodatage ISO de dǸbut")
    end_time: str = Field(..., description="Horodatage ISO de fin")
    duration_minutes: int = Field(0, description="DurǸe de la sǸance en minutes")
    calories_kcal: float = Field(0.0, description="Calories dǸpensǸes pendant la sǸance")
    avg_hr_bpm: Optional[int] = Field(None, description="FrǸquence cardiaque moyenne")
    max_hr_bpm: Optional[int] = Field(None, description="FrǸquence cardiaque maximale")
    distance_meters: Optional[float] = Field(None, description="Distance parcourue en mtres")
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SleepStageEntry(BaseModel):
    """Phase de sommeil dǸtaillǸe (awake, light, rem, deep)."""
    id: Optional[int] = None
    sleep_session_id: Optional[int] = None
    stage: str = Field(..., description="Phase : 'awake', 'light', 'rem', 'deep'")
    start_time: str = Field(..., description="Horodatage ISO dǸbut de la phase")
    end_time: str = Field(..., description="Horodatage ISO fin de la phase")
    duration_seconds: int = Field(..., description="DurǸe en secondes")


class SleepSessionEntry(BaseModel):
    """Session globale de sommeil nocturne ou sieste."""
    id: Optional[int] = None
    user_id: Optional[int] = 1
    source: str = Field(..., description="Source (ex: ringconn, oura, health_connect)")
    external_id: Optional[str] = None
    date: DateType = Field(..., description="Date du rǸveil")
    start_time: str = Field(..., description="Horodatage ISO coucher")
    end_time: str = Field(..., description="Horodatage ISO rǸveil")
    duration_minutes: int = Field(0, description="DurǸe totale de sommeil en minutes")
    efficiency_pct: Optional[float] = Field(None, description="EfficacitǸ du sommeil en %")
    sleep_debt_minutes: Optional[int] = Field(None, description="Dette de sommeil estimǸe en minutes")
    sleep_score: Optional[int] = Field(None, description="Score global de sommeil")
    deep_minutes: Optional[int] = Field(0, description="Minutes en sommeil profond")
    light_minutes: Optional[int] = Field(0, description="Minutes en sommeil lǸger")
    rem_minutes: Optional[int] = Field(0, description="Minutes en sommeil paradoxal (REM)")
    awake_minutes: Optional[int] = Field(0, description="Minutes d'Ǹveil")
    stages: List[SleepStageEntry] = Field(default_factory=list, description="Phases de sommeil dǸtaillǸes")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class IntradaySampleEntry(BaseModel):
    """%chantillon biomǸtrique haute frǸquence (FC, pas horaires, SpO2)."""
    id: Optional[int] = None
    user_id: Optional[int] = 1
    source: str = Field(..., description="Source de mesure")
    metric_type: str = Field(..., description="Type de mǸtrique: 'hr', 'steps_hourly', 'spo2'")
    timestamp: str = Field(..., description="Horodatage ISO de l'Ǹchantillon")
    value: float = Field(..., description="Valeur numǸrique")
    unit: Optional[str] = Field(None, description="UnitǸ de mesure (bpm, pas, %)")
    created_at: Optional[datetime] = None


class HydrationLogEntry(BaseModel):
    """Suivi de la consommation hydrique."""
    id: Optional[int] = None
    user_id: Optional[int] = 1
    date: DateType
    timestamp: str = Field(..., description="Horodatage ISO")
    volume_ml: float = Field(..., gt=0, description="Volume d'eau consommǸ en millilitres")
    source: str = Field("manual", description="Source (manual, smart_bottle, health_connect)")
    external_id: Optional[str] = None
    created_at: Optional[datetime] = None


class RawIngestEntry(BaseModel):
    """Journal d'audit des payloads bruts ingǸrǸs pour traabilitǸ et rejeu."""
    id: Optional[int] = None
    user_id: Optional[int] = 1
    source: str
    endpoint: Optional[str] = None
    idempotency_key: Optional[str] = None
    payload_json: str
    status: str = "received"
    received_at: Optional[str] = None


class UserConsentItem(BaseModel):
    """Consentement utilisateur par catǸgorie de donnǸes RGPD."""
    category: str = Field(..., description="CatǸgorie (biometrics, nutrition, analytics, devices)")
    consented: bool = Field(True, description="Statut de consentement")
    updated_at: Optional[str] = None


class FoodItem(BaseModel):
    """Aliment individuel dǸtectǸ ou saisi."""
    name: str
    portion_g: Optional[float] = None
    calories_kcal: float
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: Optional[float] = 0.0
    confidence_score: Optional[float] = None


class MealEntry(BaseModel):
    """EntrǸe de repas (prǸparǸe pour Stage 2 - Photo IA & OpenFoodFacts)."""
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
    """Plat type ou favori rǸutilisable pour la bibliothque de repas."""
    id: Optional[int] = None
    user_id: Optional[int] = 1
    name: str = Field(..., description="Nom du plat rǸutilisable")
    meal_type: MealType = Field("lunch", description="Type de repas (breakfast, lunch, snack, dinner)")
    serving_size: Optional[str] = Field("1 portion", description="Taille de portion ou description")
    quantity_grams: Optional[float] = Field(None, description="Poids de la portion en grammes")
    calories: float = Field(..., ge=0.0, description="Calories totales (kcal)")
    protein_g: float = Field(0.0, ge=0.0, description="ProtǸines en grammes")
    carbs_g: float = Field(0.0, ge=0.0, description="Glucides en grammes")
    fat_g: float = Field(0.0, ge=0.0, description="Lipides en grammes")
    fiber_g: Optional[float] = Field(0.0, ge=0.0, description="Fibres en grammes")
    ingredients: Optional[str] = Field(None, description="Description ou composition dǸtaillǸe en ingrǸdients")
    items: List[FoodItem] = Field(default_factory=list, description="Liste dǸcomposǸe des aliments")
    photo_url: Optional[str] = Field(None, description="URL de la photo ou data-url de l'image")
    is_favorite: bool = Field(False, description="MarquǸ comme plat favori")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


CatalogItemType = Literal["food", "dish"]
CatalogUnit = Literal["g", "portion", "ml", "piece", "pice"]
MealSlot = Literal["breakfast", "lunch", "snack", "dinner"]


class NutritionBenefitItem(BaseModel):
    """Bienfait nutritionnel issu du rǸfǸrentiel expert."""
    id: str
    category: str
    category_id: int
    title: str
    description: str
    icon: str
    rule_config: Optional[Dict[str, Any]] = None


class AssociatedBenefit(BaseModel):
    """Bienfait associǸ  un aliment ou plat."""
    benefit_id: str
    category: str
    category_id: int
    title: str
    description: str
    icon: str
    source: str = "manual"  # 'auto_rule' ou 'manual'
    explanation: Optional[str] = None


class BenefitEvaluationResult(BaseModel):
    """RǸsultat d'Ǹvaluation d'un bienfait par le moteur de rgles."""
    benefit_id: str
    category: str
    category_id: int
    title: str
    description: str
    icon: str
    explanation: str
    matched: bool = True


class CatalogItem(BaseModel):
    """Aliment simple ou plat/recette rǸutilisable du catalogue personnel."""
    id: Optional[int] = None
    user_id: Optional[int] = 1
    name: str = Field(..., min_length=1, description="Nom de l'aliment ou du plat")
    item_type: CatalogItemType = Field("food", description="'food' pour aliment simple, 'dish' pour plat/recette")
    default_unit: str = Field("g", description="UnitǸ de rǸfǸrence (g, portion, ml, pice)")
    default_quantity: float = Field(100.0, gt=0, description="QuantitǸ de rǸfǸrence")
    calories_per_unit: float = Field(..., ge=0.0, description="Calories (kcal) pour la quantitǸ de rǸfǸrence")
    protein_per_unit_g: float = Field(0.0, ge=0.0, description="ProtǸines en grammes")
    carbs_per_unit_g: float = Field(0.0, ge=0.0, description="Glucides en grammes")
    fat_per_unit_g: float = Field(0.0, ge=0.0, description="Lipides en grammes")
    fiber_per_unit_g: Optional[float] = Field(0.0, ge=0.0, description="Fibres en grammes")
    photo_url: Optional[str] = Field(None, description="Photo ou image de rǸfǸrence")
    recipe_items: List[Dict[str, Any]] = Field(default_factory=list, description="IngrǸdients composant le plat avec quantitǸs et macros")
    benefits: List[AssociatedBenefit] = Field(default_factory=list, description="Bienfaits associǸs")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MealLogItem(BaseModel):
    """Ligne d'aliment ou de plat consommǸ au sein d'un repas donnǸ."""
    id: Optional[int] = None
    meal_log_id: Optional[int] = None
    food_item_id: Optional[int] = None
    name: str = Field(..., min_length=1, description="Nom de l'aliment/plat consommǸ")
    quantity: float = Field(..., gt=0, description="QuantitǸ consommǸ")
    unit: str = Field("g", description="UnitǸ consommǸ")
    calories: float = Field(..., ge=0.0, description="Calories calculǸes au prorata")
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: Optional[float] = 0.0
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
