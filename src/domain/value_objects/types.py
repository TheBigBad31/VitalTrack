"""Value Objects & Domain Types for VitalTrack."""
from typing import Literal

WeightSource = Literal["withings", "garmin", "manual", "apple_health", "health_connect", "demo", "simulation"]
ActivitySource = Literal["oura", "ringconn", "health_connect", "apple_health", "strava", "demo", "simulation"]
MealType = Literal["breakfast", "lunch", "dinner", "snack"]

CatalogItemType = Literal["food", "dish"]
CatalogUnit = Literal["g", "portion", "ml", "piece", "pièce"]
MealSlot = Literal["breakfast", "lunch", "snack", "dinner"]

ScoreCategory = Literal["optimal", "good", "fair", "poor"]
TrendDirection = Literal["improving", "stable", "declining"]
AnomalySeverity = Literal["info", "warning", "critical"]

__all__ = [
    "WeightSource",
    "ActivitySource",
    "MealType",
    "CatalogItemType",
    "CatalogUnit",
    "MealSlot",
    "ScoreCategory",
    "TrendDirection",
    "AnomalySeverity",
]
