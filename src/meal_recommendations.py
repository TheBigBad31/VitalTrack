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


def get_daily_nutrition_targets(
    db: Any,
    user_id: int = 1,
    target_calories_override: Optional[float] = None,
    carbs_target_override: Optional[float] = None
) -> Dict[str, float]:
    """Récupère les objectifs nutritionnels quotidiens de l'utilisateur avec support d'override dynamique."""
    profile = db.get_user_profile(user_id=user_id) if hasattr(db, "get_user_profile") else None

    def _get_val(obj, key):
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    if target_calories_override is not None:
        target_cal = float(target_calories_override)
    else:
        target_cal = float(_get_val(profile, "target_calories_intake") or 2000.0)

    prot_target = _get_val(profile, "daily_protein_target_g")
    if prot_target is None:
        per_kg = _get_val(profile, "protein_target_per_kg")
        weight = _get_val(profile, "current_weight_kg") or _get_val(profile, "target_weight_kg")
        if per_kg and weight:
            prot_target = round(float(per_kg) * float(weight), 1)
        else:
            prot_target = round((target_cal * 0.25) / 4.0, 1)

    if carbs_target_override is not None:
        carbs_target = float(carbs_target_override)
    else:
        carbs_target = _get_val(profile, "daily_carbs_target_g")
        if carbs_target is None:
            carbs_target = round((target_cal * 0.45) / 4.0, 1)

    fat_target = _get_val(profile, "daily_fat_target_g")
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


def get_historical_meal_candidates(
    db: Any,
    user_id: int = 1,
    before_date: Optional[date] = None,
    lookback_days: int = 60,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Récupère les repas historiques récents avec leurs aliments pour suggérer un repas concret."""
    if not hasattr(db, "get_connection"):
        return []

    ref_date = before_date or date.today()
    start_date = ref_date - timedelta(days=lookback_days)
    ph = "%s" if getattr(db, "is_postgres", False) else "?"
    candidates: List[Dict[str, Any]] = []

    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT id, date, meal_type, total_calories, total_protein_g,
                       total_carbs_g, total_fat_g, COALESCE(total_fiber_g, 0) AS total_fiber_g
                FROM meal_logs
                WHERE user_id = {ph}
                  AND date >= {ph}
                  AND date < {ph}
                  AND total_calories > 0
                ORDER BY date DESC, id DESC
                LIMIT {ph}
                """,
                (user_id, start_date.isoformat(), ref_date.isoformat(), limit),
            )
            logs = cursor.fetchall()
            if not logs:
                return []

            log_map: Dict[int, Dict[str, Any]] = {}
            log_ids: List[int] = []
            for row in logs:
                if isinstance(row, dict):
                    lid = int(row["id"])
                    dt_val = row["date"]
                    mt = row["meal_type"]
                    cal = row["total_calories"]
                    prot = row["total_protein_g"]
                    carbs = row["total_carbs_g"]
                    fat = row["total_fat_g"]
                    fiber = row["total_fiber_g"]
                else:
                    lid, dt_val, mt, cal, prot, carbs, fat, fiber = row
                    lid = int(lid)
                log_ids.append(lid)
                log_map[lid] = {
                    "id": lid,
                    "date": dt_val.isoformat() if hasattr(dt_val, "isoformat") else str(dt_val),
                    "meal_type": mt,
                    "calories": round(float(cal or 0.0), 1),
                    "protein_g": round(float(prot or 0.0), 1),
                    "carbs_g": round(float(carbs or 0.0), 1),
                    "fat_g": round(float(fat or 0.0), 1),
                    "fiber_g": round(float(fiber or 0.0), 1),
                    "items": [],
                }

            placeholders = ", ".join(ph for _ in log_ids)
            cursor.execute(
                f"""
                SELECT meal_log_id, food_item_id, name, quantity, unit,
                       calories, protein_g, carbs_g, fat_g, COALESCE(fiber_g, 0) AS fiber_g
                FROM meal_log_items
                WHERE meal_log_id IN ({placeholders})
                ORDER BY id ASC
                """,
                tuple(log_ids),
            )
            for item_row in cursor.fetchall():
                if isinstance(item_row, dict):
                    ml_id = int(item_row["meal_log_id"])
                    item_dict = {
                        "food_item_id": item_row.get("food_item_id"),
                        "name": item_row.get("name") or "",
                        "quantity": float(item_row.get("quantity") or 0.0),
                        "unit": item_row.get("unit") or "g",
                        "calories": round(float(item_row.get("calories") or 0.0), 1),
                        "protein_g": round(float(item_row.get("protein_g") or 0.0), 1),
                        "carbs_g": round(float(item_row.get("carbs_g") or 0.0), 1),
                        "fat_g": round(float(item_row.get("fat_g") or 0.0), 1),
                        "fiber_g": round(float(item_row.get("fiber_g") or 0.0), 1),
                    }
                else:
                    ml_id, fid, name, qty, unit, cal, prot, carbs, fat, fiber = item_row
                    ml_id = int(ml_id)
                    item_dict = {
                        "food_item_id": fid,
                        "name": name or "",
                        "quantity": float(qty or 0.0),
                        "unit": unit or "g",
                        "calories": round(float(cal or 0.0), 1),
                        "protein_g": round(float(prot or 0.0), 1),
                        "carbs_g": round(float(carbs or 0.0), 1),
                        "fat_g": round(float(fat or 0.0), 1),
                        "fiber_g": round(float(fiber or 0.0), 1),
                    }
                if ml_id in log_map and item_dict["name"]:
                    log_map[ml_id]["items"].append(item_dict)

            candidates = [c for c in log_map.values() if c["items"]]
    except Exception:
        return []

    return candidates


def find_best_matching_meal(
    slot: str,
    target_rec: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Trouve le repas historique le plus proche des besoins cibles du créneau."""
    target_cal = float((target_rec.get("calories") or {}).get("target", 0.0) or 0.0)
    if target_cal <= 0.0 or not candidates:
        return None

    target_prot = float((target_rec.get("protein_g") or {}).get("target", 0.0) or 0.0)
    target_carbs = float((target_rec.get("carbs_g") or {}).get("target", 0.0) or 0.0)
    target_fat = float((target_rec.get("fat_g") or {}).get("target", 0.0) or 0.0)

    best_score: Optional[float] = None
    best_cand: Optional[Dict[str, Any]] = None

    for cand in candidates:
        cand_cal = float(cand.get("calories", 0.0) or 0.0)
        items = cand.get("items") or []
        if cand_cal <= 0.0 or not items:
            continue

        cal_diff = abs(cand_cal - target_cal) / max(target_cal, 100.0)
        prot_diff = abs(float(cand.get("protein_g", 0.0) or 0.0) - target_prot) / max(target_prot, 10.0)
        carbs_diff = abs(float(cand.get("carbs_g", 0.0) or 0.0) - target_carbs) / max(target_carbs, 10.0)
        fat_diff = abs(float(cand.get("fat_g", 0.0) or 0.0) - target_fat) / max(target_fat, 10.0)
        macro_diff = (prot_diff + carbs_diff + fat_diff) / 3.0

        score = 0.55 * cal_diff + 0.45 * macro_diff
        if cand.get("meal_type") != slot:
            score += 0.25

        if best_score is None or score < best_score:
            best_score = score
            best_cand = cand

    if best_cand is None:
        return None

    item_names = [it["name"] for it in best_cand["items"] if it.get("name")]
    title = ", ".join(item_names[:3])
    if len(item_names) > 3:
        title += f" (+{len(item_names) - 3})"

    return {
        "meal_log_id": best_cand.get("id"),
        "date": best_cand.get("date"),
        "meal_type": best_cand.get("meal_type"),
        "title": title,
        "calories": round(float(best_cand.get("calories", 0.0) or 0.0), 1),
        "protein_g": round(float(best_cand.get("protein_g", 0.0) or 0.0), 1),
        "carbs_g": round(float(best_cand.get("carbs_g", 0.0) or 0.0), 1),
        "fat_g": round(float(best_cand.get("fat_g", 0.0) or 0.0), 1),
        "fiber_g": round(float(best_cand.get("fiber_g", 0.0) or 0.0), 1),
        "items": best_cand["items"],
    }


def compute_weighted_meal_recommendations(
    meals_response: List[Dict[str, Any]],
    day_summary: Dict[str, Any],
    targets: Dict[str, float],
    meal_averages: Dict[str, Dict[str, Any]],
    historical_meals: Optional[List[Dict[str, Any]]] = None,
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

    if historical_meals:
        for mt in unfilled_meals:
            suggested = find_best_matching_meal(mt, recommendations[mt], historical_meals)
            if suggested:
                recommendations[mt]["suggested_meal"] = suggested

    return {
        "targets": targets,
        "remaining": remaining,
        "meal_averages": meal_averages,
        "unfilled_meals": unfilled_meals,
        "recommendations": recommendations,
    }
