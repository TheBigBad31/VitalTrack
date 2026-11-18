"""Calcul des moyennes historiques par type de repas et recommandations pondérées pour les prochains repas."""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple


MEAL_TYPES: Tuple[str, ...] = ("breakfast", "lunch", "snack", "dinner")

DEFAULT_MEAL_SHARES: Dict[str, float] = {
    "breakfast": 0.25,
    "lunch": 0.35,
    "snack": 0.10,
    "dinner": 0.30,
}

DEFAULT_FIBER_TARGET_G = 25.0
RANGE_TOLERANCE = 0.10


def get_daily_nutrition_targets(db: Any, user_id: int = 1) -> Dict[str, float]:
    """Récupère les objectifs nutritionnels quotidiens de l'utilisateur."""
    profile = db.get_user_profile(user_id=user_id) if hasattr(db, "get_user_profile") else None

    target_cal = float(getattr(profile, "target_calories_intake", None) or 2000.0)

    prot_target = getattr(profile, "daily_protein_target_g", None)
    if prot_target is None:
        per_kg = getattr(profile, "protein_target_per_kg", None)
        weight = getattr(profile, "current_weight_kg", None) or getattr(profile, "target_weight_kg", None)
        if per_kg and weight:
            prot_target = round(float(per_kg) * float(weight), 1)
        else:
            prot_target = round((target_cal * 0.25) / 4.0, 1)

    carbs_target = getattr(profile, "daily_carbs_target_g", None)
    if carbs_target is None:
        carbs_target = round((target_cal * 0.45) / 4.0, 1)

    fat_target = getattr(profile, "daily_fat_target_g", None)
    if fat_target is None:
        fat_target = round((target_cal * 0.30) / 9.0, 1)

    return {
        "calories": round(float(target_cal), 1),
        "protein_g": round(float(prot_target), 1),
        "carbs_g": round(float(carbs_target), 1),
        "fat_g": round(float(fat_target), 1),
        "fiber_g": DEFAULT_FIBER_TARGET_G,
    }


def get_historical_meal_averages(
    db: Any,
    user_id: int = 1,
    before_date: Optional[date] = None,
    lookback_days: int = 30,
) -> Dict[str, Dict[str, Any]]:
    """Calcule la moyenne approximative par type de repas à partir de l'historique."""
    ref_date = before_date or date.today()
    start_date = ref_date - timedelta(days=lookback_days)

    averages: Dict[str, Dict[str, Any]] = {
        mt: {
            "calories": 0.0,
            "protein_g": 0.0,
            "carbs_g": 0.0,
            "fat_g": 0.0,
            "fiber_g": 0.0,
            "sample_count": 0,
        }
        for mt in MEAL_TYPES
    }

    if not hasattr(db, "get_connection"):
        return averages

    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            ph = "%s" if getattr(db, "is_postgres", False) else "?"
            query = f"""
                SELECT meal_type,
                       AVG(total_calories) AS avg_cal,
                       AVG(total_protein_g) AS avg_prot,
                       AVG(total_carbs_g) AS avg_carbs,
                       AVG(total_fat_g) AS avg_fat,
                       AVG(COALESCE(total_fiber_g, 0)) AS avg_fiber,
                       COUNT(*) AS cnt
                FROM meal_logs
                WHERE user_id = {ph}
                  AND date >= {ph}
                  AND date < {ph}
                  AND total_calories > 0
                GROUP BY meal_type
            """
            cursor.execute(query, (user_id, start_date.isoformat(), ref_date.isoformat()))
            rows = cursor.fetchall()
            for row in rows:
                if isinstance(row, dict):
                    mt = row.get("meal_type")
                    avg_cal = row.get("avg_cal")
                    avg_prot = row.get("avg_prot")
                    avg_carbs = row.get("avg_carbs")
                    avg_fat = row.get("avg_fat")
                    avg_fiber = row.get("avg_fiber")
                    cnt = row.get("cnt")
                else:
                    mt, avg_cal, avg_prot, avg_carbs, avg_fat, avg_fiber, cnt = row
                if mt in averages:
                    averages[mt] = {
                        "calories": round(float(avg_cal or 0.0), 1),
                        "protein_g": round(float(avg_prot or 0.0), 1),
                        "carbs_g": round(float(avg_carbs or 0.0), 1),
                        "fat_g": round(float(avg_fat or 0.0), 1),
                        "fiber_g": round(float(avg_fiber or 0.0), 1),
                        "sample_count": int(cnt or 0),
                    }
    except Exception:
        # En cas d'erreur ou de mock sans table meal_logs, on garde les valeurs par défaut
        pass

    return averages


def _make_range(value: float, tolerance: float = RANGE_TOLERANCE) -> Dict[str, float]:
    val = max(0.0, float(value))
    if val == 0.0:
        return {"min": 0.0, "max": 0.0, "target": 0.0}
    return {
        "min": round(val * (1.0 - tolerance), 1),
        "max": round(val * (1.0 + tolerance), 1),
        "target": round(val, 1),
    }


def compute_weighted_meal_recommendations(
    meals_response: List[Dict[str, Any]],
    day_summary: Dict[str, Any],
    targets: Dict[str, float],
    meal_averages: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Calcule les nutriments restants et les fourchettes conseillées pondérées pour les repas non remplis."""
    consumed = {
        "calories": float(day_summary.get("total_calories", 0.0) or 0.0),
        "protein_g": float(day_summary.get("total_protein_g", 0.0) or 0.0),
        "carbs_g": float(day_summary.get("total_carbs_g", 0.0) or 0.0),
        "fat_g": float(day_summary.get("total_fat_g", 0.0) or 0.0),
        "fiber_g": float(day_summary.get("total_fiber_g", 0.0) or 0.0),
    }

    remaining = {
        k: round(max(0.0, targets[k] - consumed[k]), 1)
        for k in ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")
    }

    unfilled_meals = [
        m["meal_type"]
        for m in meals_response
        if (float(m.get("total_calories", 0.0) or 0.0) == 0.0 and len(m.get("items") or []) == 0)
    ]

    recommendations: Dict[str, Dict[str, Any]] = {}
    if not unfilled_meals:
        return {
            "targets": targets,
            "remaining": remaining,
            "meal_averages": meal_averages,
            "unfilled_meals": [],
            "recommendations": recommendations,
        }

    nutrients = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")
    for mt in unfilled_meals:
        avg_info = meal_averages.get(mt, {})
        has_history = int(avg_info.get("sample_count", 0) or 0) > 0 and float(avg_info.get("calories", 0.0) or 0.0) > 0
        recommendations[mt] = {
            "meal_type": mt,
            "based_on": "history" if has_history else "default_share",
            "sample_count": int(avg_info.get("sample_count", 0) or 0),
        }

    for k in nutrients:
        weights: Dict[str, float] = {}
        for mt in unfilled_meals:
            avg_val = float(meal_averages.get(mt, {}).get(k, 0.0) or 0.0)
            if avg_val > 0.0:
                weights[mt] = avg_val
            else:
                weights[mt] = DEFAULT_MEAL_SHARES.get(mt, 0.25) * max(targets[k], 1.0)

        total_weight = sum(weights.values())
        for mt in unfilled_meals:
            share = (weights[mt] / total_weight) if total_weight > 0 else (1.0 / len(unfilled_meals))
            rec_val = remaining[k] * share
            recommendations[mt][k] = _make_range(rec_val)

    return {
        "targets": targets,
        "remaining": remaining,
        "meal_averages": meal_averages,
        "unfilled_meals": unfilled_meals,
        "recommendations": recommendations,
    }
