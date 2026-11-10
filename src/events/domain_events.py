"""Définition des événements de domaine pour le système Event Sourcing de VitalTrack."""

from datetime import date as DateType, datetime, timezone
import uuid
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class DomainEvent(BaseModel):
    """Événement de domaine de base immuable."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Identifiant unique d'événement")
    event_type: str = Field(..., description="Nom d'événement (ex: WeightRecorded)")
    aggregate_id: str = Field(..., description="Identifiant d'agrégat (ex: user_1)")
    user_id: int = Field(..., description="ID de l'utilisateur concerné")
    version: int = Field(1, description="Version du schéma d'événement")
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Horodatage UTC de survenue"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées d'observabilité ou traçabilité")


class WeightRecorded(DomainEvent):
    """Événement déclenché lors de l'enregistrement ou de la pesée d'un utilisateur."""
    event_type: str = "WeightRecorded"
    date: DateType
    weight_kg: float
    body_fat_pct: Optional[float] = None
    muscle_mass_kg: Optional[float] = None
    bone_mass_kg: Optional[float] = None
    water_pct: Optional[float] = None
    bmi: Optional[float] = None
    source: str = "manual"
    measured_at: Optional[str] = None
    is_simulated: bool = False


class MealLogged(DomainEvent):
    """Événement déclenché lors de la journalisation d'un repas."""
    event_type: str = "MealLogged"
    meal_id: Optional[int] = None
    date: DateType
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"]
    total_calories_kcal: float
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: float = 0.0
    items: List[Dict[str, Any]] = Field(default_factory=list)


class ActivitySynced(DomainEvent):
    """Événement déclenché lors de la synchronisation d'activités/workouts."""
    event_type: str = "ActivitySynced"
    date: DateType
    steps: int = 0
    active_calories_kcal: float = 0.0
    bmr_kcal: float = 0.0
    total_burned_kcal: float = 0.0
    workout_minutes: int = 0
    workout_type: Optional[str] = None
    resting_hr_bpm: Optional[int] = None
    hrv_ms: Optional[float] = None
    sleep_score: Optional[int] = None
    source: str = "demo"
    is_simulated: bool = False


class MetricsSynced(DomainEvent):
    """Événement déclenché lors de la synchronisation de biométriques unifiées multi-capteurs."""
    event_type: str = "MetricsSynced"
    date: DateType
    source: str
    steps: int = 0
    active_calories_kcal: float = 0.0
    total_calories_kcal: float = 0.0
    resting_hr_bpm: Optional[int] = None
    hrv_rmssd_ms: Optional[float] = None
    hrv_sdnn_ms: Optional[float] = None
    spo2_pct: Optional[float] = None
    skin_temperature_c: Optional[float] = None
    sleep_score: Optional[int] = None
    recovery_score: Optional[int] = None
