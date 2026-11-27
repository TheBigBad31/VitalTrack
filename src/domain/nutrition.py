"""Module de logique métier pure pour la nutrition et le métabolisme.

Ne contient aucune dépendance vers des entrées/sorties (base de données, réseau, fichiers).
"""

from datetime import date, timedelta
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


def calculate_dynamic_tdee_target(
    bmr_kcal: float,
    steps: int = 0,
    workout_calories_kcal: float = 0.0,
    goal_delta: float = 0.0,
    min_calories: float = 1200.0,
) -> Dict[str, float]:
    """Calcule le budget calorique et de macronutriments dynamique ajusté aux pas et séances.

    Formule de budget :
      neat_steps_kcal = steps * 0.04
      target_calories_intake = max(min_calories, bmr_kcal + neat_steps_kcal + workout_calories_kcal + goal_delta)
    """
    neat_steps_kcal = round(max(0, steps) * 0.04, 1)
    workout_cals = round(max(0.0, float(workout_calories_kcal or 0.0)), 1)
    dynamic_tdee = round(bmr_kcal + neat_steps_kcal + workout_cals, 1)
    base_target = round(max(min_calories, bmr_kcal + neat_steps_kcal + goal_delta), 1)
    raw_target = bmr_kcal + neat_steps_kcal + workout_cals + goal_delta
    target_cals = round(max(min_calories, raw_target), 1)

    # Répartition glucidique ajustée : les calories de séance débloquent principalement des glucides pour la récupération
    # Protéines 25% (4 kcal/g), Lipides 25-30% (9 kcal/g), Glucides 45-50% (4 kcal/g)
    prot_g = round((target_cals * 0.25) / 4.0, 1)
    carbs_g = round((target_cals * 0.45) / 4.0, 1)
    fat_g = round((target_cals * 0.30) / 9.0, 1)

    return {
        "bmr_kcal": round(bmr_kcal, 1),
        "neat_steps_kcal": neat_steps_kcal,
        "workout_calories_kcal": workout_cals,
        "dynamic_tdee": dynamic_tdee,
        "base_target_calories_intake": base_target,
        "goal_delta": round(goal_delta, 1),
        "target_calories_intake": target_cals,
        "daily_carbs_target_g": carbs_g,
        "daily_protein_target_g": prot_g,
        "daily_fat_target_g": fat_g,
    }


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


def evaluate_nutrient_day_status(
    nutrient: Literal["protein", "calories", "carbs", "fat"],
    value: float,
    target: float,
) -> Dict[str, Any]:
    """Évalue l'atteinte d'un objectif quotidien selon la sémantique propre à chaque nutriment.

    - Protéines : objectif plancher prioritaire (>= 95 % atteint, 80-95 % proche, < 80 % insuffisant).
    - Calories : fourchette cible [90 %, 108 %], proche [75 %, 90 %[ ou ]108 %, 115 %], sinon insuffisant/dépassé.
    - Glucides : fourchette cible [85 %, 115 %], proche [70 %, 85 %[ ou ]115 %, 125 %], sinon insuffisant/dépassé.
    - Lipides : fourchette cible [80 %, 110 %], proche [65 %, 80 %[ ou ]110 %, 120 %], sinon insuffisant/dépassé.
    """
    val = round(max(0.0, float(value or 0.0)), 1)
    tgt = round(max(0.0, float(target or 0.0)), 1)
    diff = round(val - tgt, 1)

    if val <= 0.0:
        return {"pct": 0.0, "diff": diff, "state": "empty"}

    pct = round((val / tgt) * 100.0, 1) if tgt > 0.0 else 0.0

    if nutrient == "protein":
        if pct >= 95.0:
            state = "reached"
        elif pct >= 80.0:
            state = "close"
        else:
            state = "below"
    elif nutrient == "calories":
        if 90.0 <= pct <= 108.0:
            state = "reached"
        elif 75.0 <= pct < 90.0 or 108.0 < pct <= 115.0:
            state = "close"
        elif pct > 115.0:
            state = "over"
        else:
            state = "below"
    elif nutrient == "carbs":
        if 85.0 <= pct <= 115.0:
            state = "reached"
        elif 70.0 <= pct < 85.0 or 115.0 < pct <= 125.0:
            state = "close"
        elif pct > 125.0:
            state = "over"
        else:
            state = "below"
    else:  # fat
        if 80.0 <= pct <= 110.0:
            state = "reached"
        elif 65.0 <= pct < 80.0 or 110.0 < pct <= 120.0:
            state = "close"
        elif pct > 120.0:
            state = "over"
        else:
            state = "below"

    return {"pct": pct, "diff": diff, "state": state}


def compute_daily_macro_goals_history(
    meals: List[MealEntry],
    targets: Dict[str, float],
    today: Optional[date] = None,
    days: int = 30,
    weight_kg: Optional[float] = None,
) -> Dict[str, Any]:
    """Construit l'historique quotidien des objectifs (protéines, calories, glucides, lipides) et leurs KPIs."""
    ref_day = today or date.today()
    safe_days = max(1, min(int(days or 30), 90))

    target_protein = round(float(targets.get("protein_g") or 140.0), 1)
    target_calories = round(float(targets.get("calories") or 2000.0), 1)
    target_carbs = round(float(targets.get("carbs_g") or 225.0), 1)
    target_fat = round(float(targets.get("fat_g") or 67.0), 1)

    target_map: Dict[str, float] = {
        "protein": target_protein,
        "calories": target_calories,
        "carbs": target_carbs,
        "fat": target_fat,
    }

    totals_by_date: Dict[str, Dict[str, float]] = {}
    for m in meals or []:
        d_iso = m.date.isoformat() if isinstance(m.date, date) else str(m.date)[:10]
        bucket = totals_by_date.setdefault(
            d_iso,
            {"calories_kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fiber_g": 0.0},
        )
        bucket["calories_kcal"] += float(m.total_calories_kcal or 0.0)
        bucket["protein_g"] += float(m.protein_g or 0.0)
        bucket["carbs_g"] += float(m.carbs_g or 0.0)
        bucket["fat_g"] += float(m.fat_g or 0.0)
        bucket["fiber_g"] += float(m.fiber_g or 0.0)

    date_keys = [(ref_day - timedelta(days=i)).isoformat() for i in range(safe_days - 1, -1, -1)]
    daily_rows: List[Dict[str, Any]] = []

    for d_iso in date_keys:
        b = totals_by_date.get(d_iso) or {
            "calories_kcal": 0.0,
            "protein_g": 0.0,
            "carbs_g": 0.0,
            "fat_g": 0.0,
            "fiber_g": 0.0,
        }
        cals = round(b["calories_kcal"], 1)
        prot = round(b["protein_g"], 1)
        carbs = round(b["carbs_g"], 1)
        fat = round(b["fat_g"], 1)
        fiber = round(b["fiber_g"], 1)
        prot_per_kg = round(prot / float(weight_kg), 2) if (weight_kg and weight_kg > 0 and prot > 0) else None

        daily_rows.append(
            {
                "date": d_iso,
                "calories_kcal": cals,
                "protein_g": prot,
                "carbs_g": carbs,
                "fat_g": fat,
                "fiber_g": fiber,
                "protein_per_kg": prot_per_kg,
                "status": {
                    "protein": evaluate_nutrient_day_status("protein", prot, target_protein),
                    "calories": evaluate_nutrient_day_status("calories", cals, target_calories),
                    "carbs": evaluate_nutrient_day_status("carbs", carbs, target_carbs),
                    "fat": evaluate_nutrient_day_status("fat", fat, target_fat),
                },
            }
        )

    value_field_map = {
        "protein": "protein_g",
        "calories": "calories_kcal",
        "carbs": "carbs_g",
        "fat": "fat_g",
    }

    metrics: Dict[str, Dict[str, Any]] = {}
    for nutrient, field in value_field_map.items():
        tgt = target_map[nutrient]
        today_row = daily_rows[-1]
        today_val = today_row[field]
        today_st = today_row["status"][nutrient]

        logged = [r for r in daily_rows if r[field] > 0.0]
        reached = [r for r in logged if r["status"][nutrient]["state"] == "reached"]
        logged_days = len(logged)
        days_reached = len(reached)
        avg_logged = round(sum(r[field] for r in logged) / logged_days, 1) if logged_days > 0 else 0.0
        adherence_pct = round((days_reached / logged_days) * 100.0, 1) if logged_days > 0 else 0.0

        # Série en cours : compte les jours consécutifs atteints en remontant depuis aujourd'hui
        # (si aujourd'hui est encore vide ou en cours non atteint, démarre depuis hier)
        streak = 0
        start_idx = len(daily_rows) - 1
        if start_idx >= 0 and daily_rows[start_idx]["status"][nutrient]["state"] != "reached":
            start_idx -= 1
        while start_idx >= 0 and daily_rows[start_idx]["status"][nutrient]["state"] == "reached":
            streak += 1
            start_idx -= 1

        entry_metric: Dict[str, Any] = {
            "target": tgt,
            "today": today_val,
            "today_pct": today_st["pct"],
            "today_remaining": round(max(0.0, tgt - today_val), 1),
            "today_diff": today_st["diff"],
            "today_state": today_st["state"],
            "avg_logged_days": avg_logged,
            "logged_days": logged_days,
            "days_reached": days_reached,
            "adherence_pct": adherence_pct,
            "current_streak": streak,
        }
        if nutrient == "protein":
            entry_metric["today_per_kg"] = today_row["protein_per_kg"]
            entry_metric["avg_per_kg"] = (
                round(avg_logged / float(weight_kg), 2) if (weight_kg and weight_kg > 0 and avg_logged > 0) else None
            )
            entry_metric["target_per_kg"] = (
                round(tgt / float(weight_kg), 2) if (weight_kg and weight_kg > 0 and tgt > 0) else None
            )
        metrics[nutrient] = entry_metric

    return {
        "days": safe_days,
        "weight_kg": round(float(weight_kg), 1) if weight_kg else None,
        "targets": {
            "protein_g": target_protein,
            "calories": target_calories,
            "carbs_g": target_carbs,
            "fat_g": target_fat,
        },
        "daily": daily_rows,
        "metrics": metrics,
    }
