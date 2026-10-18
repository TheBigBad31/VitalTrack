"""Moteur de gestion des repas, d'agrégation quotidienne et de bilan métabolique.

Fournit :
- Gestion et persistance des repas (breakfast, lunch, dinner, snack)
- Agrégation nutritionnelle par jour (calories, macros en g et en %)
- Calcul du métabolisme de base (BMR Mifflin-St Jeor)
- Calcul de la dépense énergétique totale (TDEE = BMR + Pas + Exercice)
- Bilan énergétique net et projection de perte/gain de poids hebdomadaire
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional
from src.db import Database
from src.models import FoodItem, MealEntry, MealType


class NutritionEngine:
    """Moteur central pour le journal alimentaire et l'analyse métabolique."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()

    # ---------------------------------------------------------
    # 1. Gestion du Journal des Repas
    # ---------------------------------------------------------

    def log_meal(
        self,
        date_val: date,
        meal_type: MealType,
        items: List[FoodItem],
        photo_data_url: Optional[str] = None
    ) -> MealEntry:
        """Enregistre un repas complet calculé à partir d'une liste d'aliments."""
        total_cal = round(sum(i.calories_kcal for i in items), 1)
        total_prot = round(sum(i.protein_g for i in items), 1)
        total_carbs = round(sum(i.carbs_g for i in items), 1)
        total_fat = round(sum(i.fat_g for i in items), 1)
        total_fiber = round(sum(i.fiber_g or 0.0 for i in items), 1)

        entry = MealEntry(
            date=date_val,
            meal_type=meal_type,
            total_calories_kcal=total_cal,
            protein_g=total_prot,
            carbs_g=total_carbs,
            fat_g=total_fat,
            fiber_g=total_fiber,
            photo_data_url=photo_data_url,
            items=items
        )
        return self.db.insert_meal(entry)

    def get_meals_by_date(self, target_date: date) -> List[MealEntry]:
        """Récupère tous les repas enregistrés pour une date donnée."""
        return self.db.get_meals_for_date(target_date)

    def get_daily_nutrition_summary(self, target_date: date) -> Dict[str, Any]:
        """Agrège tous les repas du jour en totaux et pourcentages de macros."""
        meals = self.get_meals_by_date(target_date)

        total_calories = round(sum(m.total_calories_kcal for m in meals), 1)
        total_protein = round(sum(m.protein_g for m in meals), 1)
        total_carbs = round(sum(m.carbs_g for m in meals), 1)
        total_fat = round(sum(m.fat_g for m in meals), 1)
        total_fiber = round(sum(m.fiber_g or 0.0 for m in meals), 1)

        cal_prot = total_protein * 4.0
        cal_carbs = total_carbs * 4.0
        cal_fat = total_fat * 9.0
        macro_sum = cal_prot + cal_carbs + cal_fat

        if macro_sum > 0:
            pct_prot = round((cal_prot / macro_sum) * 100.0, 1)
            pct_carbs = round((cal_carbs / macro_sum) * 100.0, 1)
            pct_fat = round((cal_fat / macro_sum) * 100.0, 1)
        else:
            pct_prot, pct_carbs, pct_fat = 0.0, 0.0, 0.0

        # Regroupement par type de repas
        by_meal: Dict[str, Optional[Dict[str, Any]]] = {
            "breakfast": None,
            "lunch": None,
            "dinner": None,
            "snack": None,
        }
        for m in meals:
            by_meal[m.meal_type] = {
                "id": m.id,
                "total_calories_kcal": m.total_calories_kcal,
                "protein_g": m.protein_g,
                "carbs_g": m.carbs_g,
                "fat_g": m.fat_g,
                "fiber_g": m.fiber_g,
                "items_count": len(m.items),
                "items": [item.model_dump() for item in m.items],
            }

        return {
            "date": target_date.isoformat(),
            "meals_count": len(meals),
            "total_calories_kcal": total_calories,
            "macros": {
                "protein_g": total_protein,
                "protein_pct": pct_prot,
                "carbs_g": total_carbs,
                "carbs_pct": pct_carbs,
                "fat_g": total_fat,
                "fat_pct": pct_fat,
                "fiber_g": total_fiber,
            },
            "by_meal": by_meal,
        }

    # ---------------------------------------------------------
    # 2. Algorithmes Métaboliques & Bilan Énergétique
    # ---------------------------------------------------------

    @staticmethod
    def calculate_bmr_mifflin_st_jeor(
        weight_kg: float,
        height_cm: float,
        age: int,
        gender: Literal["male", "female"] = "male"
    ) -> float:
        """Calcule le Métabolisme de Base (BMR) selon la formule de Mifflin-St Jeor.
        
        Hommes : BMR = (10 x poids) + (6.25 x taille) - (5 x âge) + 5
        Femmes : BMR = (10 x poids) + (6.25 x taille) - (5 x âge) - 161
        """
        base = (10.0 * weight_kg) + (6.25 * height_cm) - (5.0 * age)
        if gender == "male":
            bmr = base + 5.0
        else:
            bmr = base - 161.0
        return round(max(bmr, 800.0), 1)

    @staticmethod
    def calculate_tdee(
        bmr_kcal: float,
        steps: int = 0,
        active_calories_kcal: float = 0.0
    ) -> float:
        """Calcule la Dépense Énergétique Totale (TDEE).
        
        TDEE = BMR + Calories des pas + Calories d'exercice actif.
        Si active_calories_kcal inclut déjà les pas, on évite le double comptage.
        """
        # Estimation calories pas si non incluses dans active_calories : ~0.04 kcal par pas
        step_calories = steps * 0.04
        # Si des calories actives d'entraînement sont présentes, on additionne
        extra_burn = max(active_calories_kcal, step_calories)
        return round(bmr_kcal + extra_burn, 1)

    def calculate_daily_energy_balance(
        self,
        target_date: date,
        user_weight_kg: float = 80.0,
        user_height_cm: float = 178.0,
        user_age: int = 35,
        gender: Literal["male", "female"] = "male"
    ) -> Dict[str, Any]:
        """Calcule le bilan énergétique net et la trajectoire de poids."""
        # 1. Calories ingérées (journal des repas)
        nutri_summary = self.get_daily_nutrition_summary(target_date)
        intake_kcal = nutri_summary["total_calories_kcal"]

        # 2. Dépense (table activities ou calcul BMR)
        activities = self.db.get_activities(limit=60)
        day_activity = next((a for a in activities if a.date == target_date), None)

        if day_activity and day_activity.total_burned_kcal > 0:
            burned_kcal = day_activity.total_burned_kcal
            bmr = day_activity.bmr_kcal
            steps = day_activity.steps
            active_cal = day_activity.active_calories_kcal
        else:
            bmr = self.calculate_bmr_mifflin_st_jeor(user_weight_kg, user_height_cm, user_age, gender)
            steps = day_activity.steps if day_activity else 8000
            active_cal = day_activity.active_calories_kcal if day_activity else 350.0
            burned_kcal = self.calculate_tdee(bmr, steps, active_cal)

        # 3. Solde net et impact poids
        # 1 kg de graisse corporelle correspond approximativement à 7700 kcal
        net_balance_kcal = round(intake_kcal - burned_kcal, 1)
        weekly_projected_weight_change_kg = round((net_balance_kcal * 7.0) / 7700.0, 3)

        if net_balance_kcal <= -250:
            status = "deficit"
            recommendation = "Déficit calorique optimal pour une perte de masse grasse progressive et durable."
        elif net_balance_kcal >= 250:
            status = "surplus"
            recommendation = "Surplus calorique propice à la prise de masse musculaire ou récupération."
        else:
            status = "maintenance"
            recommendation = "Équilibre énergétique stable, idéal pour le maintien du poids."

        return {
            "date": target_date.isoformat(),
            "calories_intake_kcal": intake_kcal,
            "calories_burned_kcal": burned_kcal,
            "bmr_kcal": bmr,
            "steps": steps,
            "active_calories_kcal": active_cal,
            "net_energy_balance_kcal": net_balance_kcal,
            "status": status,
            "weekly_projected_weight_change_kg": weekly_projected_weight_change_kg,
            "recommendation": recommendation,
            "macros": nutri_summary["macros"],
        }
