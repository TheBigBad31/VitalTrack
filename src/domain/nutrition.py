"""Module de logique métier pure pour la nutrition et le métabolisme.

Ne contient aucune dépendance vers des entrées/sorties (base de données, réseau, fichiers).
"""

from typing import Any, Dict, List, Literal, Optional
from src.models import FoodItem, MealEntry


def calculate_meal_totals(items: List[FoodItem]) -> Dict[str, float]:
    """Calcule les totaux de calories et macronutriments pour une liste d'aliments."""
    total_cal = round(sum(i.calories_kcal for i in items), 1)
    total_prot = round(sum(i.protein_g for i in items), 1)
    total_carbs = round(sum(i.carbs_g for i in items), 1)
    total_fat = round(sum(i.fat_g for i in items), 1)
    total_fiber = round(sum(i.fiber_g or 0.0 for i in items), 1)

    return {
        "calories_kcal": total_cal,
        "protein_g": total_prot,
        "carbs_g": total_carbs,
        "fat_g": total_fat,
        "fiber_g": total_fiber,
    }


def compute_daily_nutrition_summary(
    date_iso: str,
    meals: List[MealEntry]
) -> Dict[str, Any]:
    """Agrège une liste de MealEntry pour une journée en totaux et pourcentages de macros."""
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
        "date": date_iso,
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


def calculate_tdee(
    bmr_kcal: float,
    steps: int = 0,
    active_calories_kcal: float = 0.0
) -> float:
    """Calcule la Dépense Énergétique Totale (TDEE).
    
    TDEE = BMR + Calories des pas + Calories d'exercice actif.
    Si active_calories_kcal inclut déjà les pas, on évite le double comptage.
    """
    step_calories = steps * 0.04
    extra_burn = max(active_calories_kcal, step_calories)
    return round(bmr_kcal + extra_burn, 1)


def compute_energy_balance(
    date_iso: str,
    intake_kcal: float,
    burned_kcal: float,
    bmr_kcal: float,
    steps: int,
    active_calories_kcal: float,
    macros: Dict[str, Any]
) -> Dict[str, Any]:
    """Calcule le bilan énergétique net, l'impact sur le poids et la recommandation."""
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
        "date": date_iso,
        "calories_intake_kcal": intake_kcal,
        "calories_burned_kcal": burned_kcal,
        "bmr_kcal": bmr_kcal,
        "steps": steps,
        "active_calories_kcal": active_calories_kcal,
        "net_energy_balance_kcal": net_balance_kcal,
        "status": status,
        "weekly_projected_weight_change_kg": weekly_projected_weight_change_kg,
        "recommendation": recommendation,
        "macros": macros,
    }
