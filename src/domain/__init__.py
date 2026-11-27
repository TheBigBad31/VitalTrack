"""Couche domaine métier pur de VitalTrack (règles nutritionnelles et calculs énergétiques)."""

from src.domain.nutrition import (
    calculate_bmr_mifflin_st_jeor,
    calculate_dynamic_tdee_target,
    compute_daily_macro_goals_history,
    resolve_nutrition_goals,
)

__all__ = [
    "calculate_bmr_mifflin_st_jeor",
    "calculate_dynamic_tdee_target",
    "compute_daily_macro_goals_history",
    "resolve_nutrition_goals",
]
