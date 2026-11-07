"""Moteur de gestion des repas, d'agrégation quotidienne et de bilan métabolique.

Fournit :
- Gestion et persistance des repas (breakfast, lunch, dinner, snack)
- Orchestration de l'agrégation nutritionnelle quotidienne via domain.nutrition
- Calculs métaboliques (BMR, TDEE, bilan net) délégués au domaine pur
"""

from datetime import date
from typing import Any, Dict, List, Literal, Optional
from src.db import Database
from src.domain import nutrition as nutrition_domain
from src.models import FoodItem, MealEntry, MealType
from src.repositories.meals import MealsRepository
from src.repositories.weights import WeightsRepository


class NutritionEngine:
    """Moteur applicatif/orchestrateur pour le journal alimentaire et l'analyse métabolique."""

    def __init__(
        self,
        db: Optional[Database] = None,
        meals_repo: Optional[MealsRepository] = None,
        weights_repo: Optional[WeightsRepository] = None,
    ):
        self.db = db if (db is not None or (meals_repo is None and weights_repo is None)) else None
        self._meals_repo = meals_repo
        self._weights_repo = weights_repo

    @property
    def meals_repo(self) -> MealsRepository:
        if self._meals_repo is not None:
            return self._meals_repo
        if self.db is not None:
            return self.db.meals
        self.db = Database()
        return self.db.meals

    @property
    def weights_repo(self) -> WeightsRepository:
        if self._weights_repo is not None:
            return self._weights_repo
        if self.db is not None:
            return self.db.weights
        self.db = Database()
        return self.db.weights

    # ---------------------------------------------------------
    # 1. Gestion du Journal des Repas
    # ---------------------------------------------------------

    def log_meal(
        self,
        date_val: date,
        meal_type: MealType,
        items: List[FoodItem],
        photo_data_url: Optional[str] = None,
        user_id: int = 1
    ) -> MealEntry:
        """Enregistre un repas complet calculé à partir d'une liste d'aliments."""
        totals = nutrition_domain.calculate_meal_totals(items)

        entry = MealEntry(
            date=date_val,
            meal_type=meal_type,
            total_calories_kcal=totals["calories_kcal"],
            protein_g=totals["protein_g"],
            carbs_g=totals["carbs_g"],
            fat_g=totals["fat_g"],
            fiber_g=totals["fiber_g"],
            photo_data_url=photo_data_url,
            items=items
        )
        return self.meals_repo.insert_meal(entry, user_id=user_id)

    def get_meals_by_date(self, target_date: date, user_id: int = 1) -> List[MealEntry]:
        """Récupère tous les repas enregistrés pour une date donnée."""
        return self.meals_repo.get_meals_for_date(target_date, user_id=user_id)

    def get_daily_nutrition_summary(self, target_date: date, user_id: int = 1) -> Dict[str, Any]:
        """Agrège tous les repas du jour en totaux et pourcentages de macros."""
        meals = self.get_meals_by_date(target_date, user_id=user_id)
        return nutrition_domain.compute_daily_nutrition_summary(
            date_iso=target_date.isoformat(),
            meals=meals
        )

    # ---------------------------------------------------------
    # 2. Algorithmes Métaboliques & Bilan Énergétique (Délégation domain)
    # ---------------------------------------------------------

    @staticmethod
    def calculate_bmr_mifflin_st_jeor(
        weight_kg: float,
        height_cm: float,
        age: int,
        gender: Literal["male", "female"] = "male"
    ) -> float:
        """Délégation vers domain.nutrition.calculate_bmr_mifflin_st_jeor."""
        return nutrition_domain.calculate_bmr_mifflin_st_jeor(
            weight_kg=weight_kg,
            height_cm=height_cm,
            age=age,
            gender=gender
        )

    @staticmethod
    def calculate_tdee(
        bmr_kcal: float,
        steps: int = 0,
        active_calories_kcal: float = 0.0
    ) -> float:
        """Délégation vers domain.nutrition.calculate_tdee."""
        return nutrition_domain.calculate_tdee(
            bmr_kcal=bmr_kcal,
            steps=steps,
            active_calories_kcal=active_calories_kcal
        )

    def calculate_daily_energy_balance(
        self,
        target_date: date,
        user_weight_kg: float = 80.0,
        user_height_cm: float = 178.0,
        user_age: int = 35,
        gender: Literal["male", "female"] = "male",
        user_id: int = 1
    ) -> Dict[str, Any]:
        """Calcule le bilan énergétique net et la trajectoire de poids via le domaine."""
        # 1. Calories ingérées (journal des repas)
        nutri_summary = self.get_daily_nutrition_summary(target_date, user_id=user_id)
        intake_kcal = nutri_summary["total_calories_kcal"]

        # 2. Dépense (table activities via weights_repo ou calcul BMR)
        activities = self.weights_repo.get_activities(limit=60, user_id=user_id)
        day_activity = next((a for a in activities if a.date == target_date), None)

        if day_activity and day_activity.total_burned_kcal > 0:
            burned_kcal = day_activity.total_burned_kcal
            bmr = day_activity.bmr_kcal
            steps = day_activity.steps
            active_cal = day_activity.active_calories_kcal
        else:
            bmr = nutrition_domain.calculate_bmr_mifflin_st_jeor(user_weight_kg, user_height_cm, user_age, gender)
            steps = day_activity.steps if day_activity else 0
            active_cal = day_activity.active_calories_kcal if day_activity else 0.0
            burned_kcal = nutrition_domain.calculate_tdee(bmr, steps, active_cal)

        # 3. Solde net et impact poids calculés par le domaine pur
        return nutrition_domain.compute_energy_balance(
            date_iso=target_date.isoformat(),
            intake_kcal=intake_kcal,
            burned_kcal=burned_kcal,
            bmr_kcal=bmr,
            steps=steps,
            active_calories_kcal=active_cal,
            macros=nutri_summary["macros"],
        )
