"""Application DTOs (Data Transfer Objects)."""
from typing import Optional, List
from datetime import date as DateType
from pydantic import BaseModel, Field


class WeightCreateDTO(BaseModel):
    date: DateType
    weight_kg: float = Field(..., gt=0)
    body_fat_pct: Optional[float] = None
    muscle_mass_kg: Optional[float] = None
    notes: Optional[str] = None
    measured_at: Optional[str] = None


class WeightResponseDTO(BaseModel):
    id: Optional[int] = None
    date: DateType
    weight_kg: float
    body_fat_pct: Optional[float] = None
    muscle_mass_kg: Optional[float] = None
    bmi: Optional[float] = None
    trend_7d_kg: Optional[float] = None
    source: str = "manual"


class MealCreateDTO(BaseModel):
    date: DateType
    meal_type: str
    total_calories_kcal: float
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    photo_data_url: Optional[str] = None


class DashboardSummaryDTO(BaseModel):
    user_id: int
    last_weight: Optional[WeightResponseDTO] = None
    today_calories_in: float = 0.0
    today_calories_out: float = 0.0
    net_calories: float = 0.0
