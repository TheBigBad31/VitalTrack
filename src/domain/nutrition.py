"""Module de logique métier pure pour la nutrition et le métabolisme.

Ne contient aucune dépendance vers des entrées/sorties (base de données, réseau, fichiers).
"""

from datetime import date, timedelta
import json
from typing import Any, Dict, List, Literal, Optional
from src.models import FoodItem, MealEntry


GOAL_PRESETS_CONFIG: Dict[str, Dict[str, Any]] = {
    "weight_loss": {
        "delta": -500.0,
        "steps": 10000,
        "protein_per_kg": 1.8,
        "rules": {
            "protein": {"mode": "min", "unit": "per_kg", "min": 1.8, "max": None},
            "calories": {"mode": "range", "source": "dynamic", "tolerance_low_pct": 10.0, "tolerance_high_pct": 8.0},
            "carbs": {"mode": "range", "source": "auto", "tolerance_low_pct": 15.0, "tolerance_high_pct": 15.0},
            "fat": {"mode": "range", "source": "auto", "tolerance_low_pct": 20.0, "tolerance_high_pct": 10.0},
        },
    },
    "maintenance": {
        "delta": 0.0,
        "steps": 8500,
        "protein_per_kg": 1.4,
        "rules": {
            "protein": {"mode": "min", "unit": "per_kg", "min": 1.4, "max": None},
            "calories": {"mode": "range", "source": "dynamic", "tolerance_low_pct": 10.0, "tolerance_high_pct": 8.0},
            "carbs": {"mode": "range", "source": "auto", "tolerance_low_pct": 15.0, "tolerance_high_pct": 15.0},
            "fat": {"mode": "range", "source": "auto", "tolerance_low_pct": 20.0, "tolerance_high_pct": 10.0},
        },
    },
    "recomposition": {
        "delta": -200.0,
        "steps": 10000,
        "protein_per_kg": 2.2,
        "rules": {
            "protein": {"mode": "min", "unit": "per_kg", "min": 2.2, "max": None},
            "calories": {"mode": "range", "source": "dynamic", "tolerance_low_pct": 10.0, "tolerance_high_pct": 8.0},
            "carbs": {"mode": "range", "source": "auto", "tolerance_low_pct": 15.0, "tolerance_high_pct": 15.0},
            "fat": {"mode": "range", "source": "auto", "tolerance_low_pct": 20.0, "tolerance_high_pct": 10.0},
        },
    },
    "muscle_gain": {
        "delta": 300.0,
        "steps": 8500,
        "protein_per_kg": 2.0,
        "rules": {
            "protein": {"mode": "min", "unit": "per_kg", "min": 2.0, "max": None},
            "calories": {"mode": "range", "source": "dynamic", "tolerance_low_pct": 5.0, "tolerance_high_pct": 12.0},
            "carbs": {"mode": "min", "source": "auto", "tolerance_low_pct": 10.0, "tolerance_high_pct": 20.0},
            "fat": {"mode": "range", "source": "auto", "tolerance_low_pct": 15.0, "tolerance_high_pct": 15.0},
        },
    },
}


def _safe_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        num = float(val)
        return num if num == num else None  # filtre NaN
    except (TypeError, ValueError):
        return None


def _parse_goals_config(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def resolve_nutrition_goals(
    profile: Optional[Any],
    weight_kg: Optional[float] = None,
    target_calories_override: Optional[float] = None,
    carbs_target_override: Optional[float] = None,
) -> Dict[str, Any]:
    """Source unique de vérité des cibles et règles nutritionnelles (plancher / plafond / fourchette).

    Priorité protéines :
    - Si `nutrition_goals_config.protein.unit == "g"` : mode grammes fixes explicitement choisi par l'utilisateur.
    - Sinon : calcul dynamique `protein_target_per_kg * poids` (jamais écrasé par un ancien `daily_protein_target_g` résiduel).
    - Fallback : `daily_protein_target_g` uniquement si aucun `protein_target_per_kg` ou aucun poids n'est disponible.
    """
    def _get(key: str) -> Any:
        if profile is None:
            return None
        if isinstance(profile, dict):
            return profile.get(key)
        return getattr(profile, key, None)

    goal_id = _get("goal_profile_id") or "weight_loss"
    preset = GOAL_PRESETS_CONFIG.get(goal_id, GOAL_PRESETS_CONFIG["weight_loss"])
    preset_rules = preset["rules"]
    cfg_all = _parse_goals_config(_get("nutrition_goals_config"))

    eff_weight = _safe_float(weight_kg)
    if not eff_weight or eff_weight <= 0:
        eff_weight = _safe_float(_get("current_weight_kg")) or _safe_float(_get("target_weight_kg"))
    if eff_weight is not None and eff_weight <= 0:
        eff_weight = None

    # --- 1. CALORIES ---
    cal_cfg = cfg_all.get("calories") if isinstance(cfg_all.get("calories"), dict) else {}
    cal_preset = preset_rules["calories"]
    cal_mode = cal_cfg.get("mode") if cal_cfg.get("mode") in ("min", "max", "range") else cal_preset["mode"]
    cal_source = cal_cfg.get("source") if cal_cfg.get("source") in ("dynamic", "fixed") else (
        "dynamic" if target_calories_override is not None else "fixed"
    )
    tol_lo_cal = _safe_float(cal_cfg.get("tolerance_low_pct"))
    if tol_lo_cal is None:
        tol_lo_cal = cal_preset["tolerance_low_pct"]
    tol_hi_cal = _safe_float(cal_cfg.get("tolerance_high_pct"))
    if tol_hi_cal is None:
        tol_hi_cal = cal_preset["tolerance_high_pct"]

    profile_cal = _safe_float(_get("target_calories_intake")) or 2000.0
    if cal_source == "fixed":
        cfg_min = _safe_float(cal_cfg.get("min"))
        cfg_max = _safe_float(cal_cfg.get("max"))
        cfg_tgt = _safe_float(cal_cfg.get("target"))
        if cal_mode == "min":
            cal_min = round(cfg_min or cfg_tgt or profile_cal, 1)
            cal_max = None
            target_cal = cal_min
        elif cal_mode == "max":
            cal_max = round(cfg_max or cfg_tgt or profile_cal, 1)
            cal_min = None
            target_cal = cal_max
        else:
            cal_min = round(cfg_min if cfg_min is not None else (cfg_tgt or profile_cal) * (1.0 - tol_lo_cal / 100.0), 1)
            cal_max = round(cfg_max if cfg_max is not None else (cfg_tgt or profile_cal) * (1.0 + tol_hi_cal / 100.0), 1)
            if cal_min > cal_max:
                cal_min, cal_max = cal_max, cal_min
            target_cal = round(cfg_tgt if cfg_tgt is not None else (cal_min + cal_max) / 2.0, 1)
    else:
        base_cal = round(float(target_calories_override) if target_calories_override is not None else profile_cal, 1)
        target_cal = base_cal
        if cal_mode == "min":
            cal_min = base_cal
            cal_max = None
        elif cal_mode == "max":
            cal_min = None
            cal_max = base_cal
        else:
            cal_min = round(base_cal * (1.0 - tol_lo_cal / 100.0), 1)
            cal_max = round(base_cal * (1.0 + tol_hi_cal / 100.0), 1)

    calories_rule = {
        "mode": cal_mode,
        "target": target_cal,
        "min": cal_min,
        "max": cal_max,
        "unit": "kcal",
        "source": cal_source,
        "tolerance_low_pct": tol_lo_cal,
        "tolerance_high_pct": tol_hi_cal,
    }

    # --- 2. PROTÉINES ---
    prot_cfg = cfg_all.get("protein") if isinstance(cfg_all.get("protein"), dict) else {}
    prot_preset = preset_rules["protein"]
    prot_mode = prot_cfg.get("mode") if prot_cfg.get("mode") in ("min", "max", "range") else prot_preset["mode"]
    prot_input_unit = prot_cfg.get("unit") if prot_cfg.get("unit") in ("per_kg", "g") else None

    profile_per_kg = _safe_float(_get("protein_target_per_kg"))
    profile_fixed_g = _safe_float(_get("daily_protein_target_g"))

    prot_min: Optional[float] = None
    prot_max: Optional[float] = None
    prot_min_per_kg: Optional[float] = None
    prot_max_per_kg: Optional[float] = None
    prot_per_kg: Optional[float] = None

    if prot_input_unit == "g":
        cfg_min = _safe_float(prot_cfg.get("min"))
        cfg_max = _safe_float(prot_cfg.get("max"))
        cfg_tgt = _safe_float(prot_cfg.get("target")) or _safe_float(prot_cfg.get("value"))
        fallback_g = profile_fixed_g or (round(profile_per_kg * eff_weight, 1) if (profile_per_kg and eff_weight) else round((target_cal * 0.25) / 4.0, 1))
        if prot_mode == "min":
            prot_min = round(cfg_min or cfg_tgt or fallback_g, 1)
            target_prot = prot_min
        elif prot_mode == "max":
            prot_max = round(cfg_max or cfg_tgt or fallback_g, 1)
            target_prot = prot_max
        else:
            prot_min = round(cfg_min if cfg_min is not None else (cfg_tgt or fallback_g) * 0.9, 1)
            prot_max = round(cfg_max if cfg_max is not None else (cfg_tgt or fallback_g) * 1.15, 1)
            if prot_min > prot_max:
                prot_min, prot_max = prot_max, prot_min
            target_prot = round(cfg_tgt if cfg_tgt is not None else (prot_min + prot_max) / 2.0, 1)
        if eff_weight:
            prot_per_kg = round(target_prot / eff_weight, 2)
            prot_min_per_kg = round(prot_min / eff_weight, 2) if prot_min is not None else None
            prot_max_per_kg = round(prot_max / eff_weight, 2) if prot_max is not None else None
    else:
        # Mode g/kg par défaut : priorité absolue à protein_target_per_kg * poids
        resolved_per_kg = (
            _safe_float(prot_cfg.get("value"))
            or _safe_float(prot_cfg.get("target"))
            or _safe_float(prot_cfg.get("min"))
            or profile_per_kg
        )
        if resolved_per_kg and eff_weight:
            prot_input_unit = "per_kg"
            if prot_mode == "min":
                prot_min_per_kg = round(_safe_float(prot_cfg.get("min")) or resolved_per_kg, 2)
                prot_min = round(prot_min_per_kg * eff_weight, 1)
                target_prot = prot_min
                prot_per_kg = prot_min_per_kg
            elif prot_mode == "max":
                prot_max_per_kg = round(_safe_float(prot_cfg.get("max")) or resolved_per_kg, 2)
                prot_max = round(prot_max_per_kg * eff_weight, 1)
                target_prot = prot_max
                prot_per_kg = prot_max_per_kg
            else:
                prot_min_per_kg = round(_safe_float(prot_cfg.get("min")) or resolved_per_kg, 2)
                prot_max_per_kg = round(_safe_float(prot_cfg.get("max")) or (prot_min_per_kg + 0.4), 2)
                if prot_min_per_kg > prot_max_per_kg:
                    prot_min_per_kg, prot_max_per_kg = prot_max_per_kg, prot_min_per_kg
                prot_min = round(prot_min_per_kg * eff_weight, 1)
                prot_max = round(prot_max_per_kg * eff_weight, 1)
                target_prot = round((prot_min + prot_max) / 2.0, 1)
                prot_per_kg = round((prot_min_per_kg + prot_max_per_kg) / 2.0, 2)
        else:
            prot_input_unit = "g"
            base_prot = profile_fixed_g or round((target_cal * 0.25) / 4.0, 1)
            target_prot = round(base_prot, 1)
            if prot_mode == "min":
                prot_min = target_prot
            elif prot_mode == "max":
                prot_max = target_prot
            else:
                prot_min = round(target_prot * 0.9, 1)
                prot_max = round(target_prot * 1.15, 1)

    protein_rule = {
        "mode": prot_mode,
        "target": target_prot,
        "min": prot_min,
        "max": prot_max,
        "unit": "g",
        "input_unit": prot_input_unit,
        "per_kg": prot_per_kg,
        "min_per_kg": prot_min_per_kg,
        "max_per_kg": prot_max_per_kg,
    }

    # --- 3. GLUCIDES ---
    carbs_cfg = cfg_all.get("carbs") if isinstance(cfg_all.get("carbs"), dict) else {}
    carbs_preset = preset_rules["carbs"]
    carbs_mode = carbs_cfg.get("mode") if carbs_cfg.get("mode") in ("min", "max", "range") else carbs_preset["mode"]
    carbs_has_fixed_cfg = carbs_cfg.get("source") == "fixed" or (
        carbs_cfg.get("source") != "auto"
        and any(_safe_float(carbs_cfg.get(k)) is not None for k in ("min", "max", "target"))
    )
    carbs_source = "fixed" if carbs_has_fixed_cfg else "auto"
    tol_lo_carbs = _safe_float(carbs_cfg.get("tolerance_low_pct"))
    if tol_lo_carbs is None:
        tol_lo_carbs = carbs_preset["tolerance_low_pct"]
    tol_hi_carbs = _safe_float(carbs_cfg.get("tolerance_high_pct"))
    if tol_hi_carbs is None:
        tol_hi_carbs = carbs_preset["tolerance_high_pct"]

    profile_carbs = _safe_float(_get("daily_carbs_target_g"))
    if carbs_source == "fixed":
        cfg_min = _safe_float(carbs_cfg.get("min"))
        cfg_max = _safe_float(carbs_cfg.get("max"))
        cfg_tgt = _safe_float(carbs_cfg.get("target"))
        fallback_carbs = profile_carbs or round((target_cal * 0.45) / 4.0, 1)
        if carbs_mode == "min":
            carbs_min = round(cfg_min or cfg_tgt or fallback_carbs, 1)
            carbs_max = None
            target_carbs = carbs_min
        elif carbs_mode == "max":
            carbs_max = round(cfg_max or cfg_tgt or fallback_carbs, 1)
            carbs_min = None
            target_carbs = carbs_max
        else:
            carbs_min = round(cfg_min if cfg_min is not None else (cfg_tgt or fallback_carbs) * (1.0 - tol_lo_carbs / 100.0), 1)
            carbs_max = round(cfg_max if cfg_max is not None else (cfg_tgt or fallback_carbs) * (1.0 + tol_hi_carbs / 100.0), 1)
            if carbs_min > carbs_max:
                carbs_min, carbs_max = carbs_max, carbs_min
            target_carbs = round(cfg_tgt if cfg_tgt is not None else (carbs_min + carbs_max) / 2.0, 1)
    else:
        if carbs_target_override is not None and cal_source == "dynamic":
            base_carbs = round(float(carbs_target_override), 1)
        elif profile_carbs is not None and carbs_cfg.get("source") != "auto":
            base_carbs = round(profile_carbs, 1)
        else:
            base_carbs = round((target_cal * 0.45) / 4.0, 1)
        target_carbs = base_carbs
        if carbs_mode == "min":
            carbs_min = base_carbs
            carbs_max = None
        elif carbs_mode == "max":
            carbs_min = None
            carbs_max = base_carbs
        else:
            carbs_min = round(base_carbs * (1.0 - tol_lo_carbs / 100.0), 1)
            carbs_max = round(base_carbs * (1.0 + tol_hi_carbs / 100.0), 1)

    carbs_rule = {
        "mode": carbs_mode,
        "target": target_carbs,
        "min": carbs_min,
        "max": carbs_max,
        "unit": "g",
        "source": carbs_source,
        "tolerance_low_pct": tol_lo_carbs,
        "tolerance_high_pct": tol_hi_carbs,
    }

    # --- 4. LIPIDES ---
    fat_cfg = cfg_all.get("fat") if isinstance(cfg_all.get("fat"), dict) else {}
    fat_preset = preset_rules["fat"]
    fat_mode = fat_cfg.get("mode") if fat_cfg.get("mode") in ("min", "max", "range") else fat_preset["mode"]
    fat_has_fixed_cfg = fat_cfg.get("source") == "fixed" or (
        fat_cfg.get("source") != "auto"
        and any(_safe_float(fat_cfg.get(k)) is not None for k in ("min", "max", "target"))
    )
    fat_source = "fixed" if fat_has_fixed_cfg else "auto"
    tol_lo_fat = _safe_float(fat_cfg.get("tolerance_low_pct"))
    if tol_lo_fat is None:
        tol_lo_fat = fat_preset["tolerance_low_pct"]
    tol_hi_fat = _safe_float(fat_cfg.get("tolerance_high_pct"))
    if tol_hi_fat is None:
        tol_hi_fat = fat_preset["tolerance_high_pct"]

    profile_fat = _safe_float(_get("daily_fat_target_g"))
    if fat_source == "fixed":
        cfg_min = _safe_float(fat_cfg.get("min"))
        cfg_max = _safe_float(fat_cfg.get("max"))
        cfg_tgt = _safe_float(fat_cfg.get("target"))
        fallback_fat = profile_fat or round((target_cal * 0.30) / 9.0, 1)
        if fat_mode == "min":
            fat_min = round(cfg_min or cfg_tgt or fallback_fat, 1)
            fat_max = None
            target_fat = fat_min
        elif fat_mode == "max":
            fat_max = round(cfg_max or cfg_tgt or fallback_fat, 1)
            fat_min = None
            target_fat = fat_max
        else:
            fat_min = round(cfg_min if cfg_min is not None else (cfg_tgt or fallback_fat) * (1.0 - tol_lo_fat / 100.0), 1)
            fat_max = round(cfg_max if cfg_max is not None else (cfg_tgt or fallback_fat) * (1.0 + tol_hi_fat / 100.0), 1)
            if fat_min > fat_max:
                fat_min, fat_max = fat_max, fat_min
            target_fat = round(cfg_tgt if cfg_tgt is not None else (fat_min + fat_max) / 2.0, 1)
    else:
        if profile_fat is not None and fat_cfg.get("source") != "auto":
            base_fat = round(profile_fat, 1)
        else:
            base_fat = round((target_cal * 0.30) / 9.0, 1)
        target_fat = base_fat
        if fat_mode == "min":
            fat_min = base_fat
            fat_max = None
        elif fat_mode == "max":
            fat_min = None
            fat_max = base_fat
        else:
            fat_min = round(base_fat * (1.0 - tol_lo_fat / 100.0), 1)
            fat_max = round(base_fat * (1.0 + tol_hi_fat / 100.0), 1)

    fat_rule = {
        "mode": fat_mode,
        "target": target_fat,
        "min": fat_min,
        "max": fat_max,
        "unit": "g",
        "source": fat_source,
        "tolerance_low_pct": tol_lo_fat,
        "tolerance_high_pct": tol_hi_fat,
    }

    return {
        "calories": target_cal,
        "protein_g": target_prot,
        "carbs_g": target_carbs,
        "fat_g": target_fat,
        "fiber_g": 25.0,
        "protein_per_kg": prot_per_kg,
        "weight_kg": round(eff_weight, 1) if eff_weight else None,
        "rules": {
            "protein": protein_rule,
            "calories": calories_rule,
            "carbs": carbs_rule,
            "fat": fat_rule,
        },
    }


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
    weight_kg: float = 80.0,
    target_steps: int = 0,
    activity_level: str = "moderately_active",
) -> Dict[str, float]:
    """Calcule le budget calorique et de macronutriments dynamique ajusté au profil, aux pas et séances.

    Formule de budget :
      base_neat_kcal = bmr_kcal * neat_factor(activity_level)
      effective_steps = max(steps, target_steps)
      neat_steps_kcal = effective_steps * 0.0005 * weight_kg
      target_calories_intake = max(min_calories, bmr_kcal + base_neat_kcal + neat_steps_kcal + workout_calories_kcal + goal_delta)
    """
    neat_factors = {
        "sedentary": 0.10,
        "lightly_active": 0.15,
        "light": 0.15,
        "moderately_active": 0.20,
        "moderate": 0.20,
        "very_active": 0.25,
        "active": 0.25,
        "extra_active": 0.30,
    }
    act_key = str(activity_level or "moderately_active").strip().lower()
    neat_factor = neat_factors.get(act_key, 0.20)
    base_neat_kcal = round(bmr_kcal * neat_factor, 1)

    eff_weight = float(weight_kg) if (weight_kg is not None and float(weight_kg) > 0) else 80.0
    effective_steps = max(max(0, int(steps or 0)), max(0, int(target_steps or 0)))
    neat_steps_kcal = round(effective_steps * 0.0005 * eff_weight, 1)
    workout_cals = round(max(0.0, float(workout_calories_kcal or 0.0)), 1)

    dynamic_tdee = round(bmr_kcal + base_neat_kcal + neat_steps_kcal + workout_cals, 1)
    base_target = round(max(min_calories, bmr_kcal + base_neat_kcal + neat_steps_kcal + goal_delta), 1)
    raw_target = bmr_kcal + base_neat_kcal + neat_steps_kcal + workout_cals + goal_delta
    target_cals = round(max(min_calories, raw_target), 1)

    # Répartition glucidique ajustée : les calories de séance débloquent principalement des glucides pour la récupération
    # Protéines 25% (4 kcal/g), Lipides 25-30% (9 kcal/g), Glucides 45-50% (4 kcal/g)
    prot_g = round((target_cals * 0.25) / 4.0, 1)
    carbs_g = round((target_cals * 0.45) / 4.0, 1)
    fat_g = round((target_cals * 0.30) / 9.0, 1)

    return {
        "bmr_kcal": round(bmr_kcal, 1),
        "base_neat_kcal": base_neat_kcal,
        "neat_steps_kcal": neat_steps_kcal,
        "effective_steps": effective_steps,
        "weight_kg": round(eff_weight, 1),
        "activity_level": act_key,
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
    rule: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Évalue l'atteinte d'un objectif quotidien selon la règle configurée (plancher, plafond, fourchette).

    Si `rule` est fourni (`{"mode": "min"|"max"|"range", "min": ..., "max": ..., "target": ...}`) :
    - `min` (seuil plancher) : atteint si `>= min`, proche si `[85 % * min, min[`, sinon `below`.
    - `max` (plafond) : atteint si `<= max`, proche si `]max, 110 % * max]`, sinon `over`.
    - `range` (fourchette) : atteint si `[min, max]`, proche si `[85 % * min, min[` ou `]max, 110 % * max]`, sinon `below` / `over`.

    Si `rule` est omis (rétrocompatibilité) : utilise les pourcentages par défaut de chaque nutriment.
    """
    val = round(max(0.0, float(value or 0.0)), 1)
    tgt = round(max(0.0, float((rule.get("target") if isinstance(rule, dict) and rule.get("target") is not None else target) or 0.0)), 1)
    diff = round(val - tgt, 1)

    if isinstance(rule, dict) and rule.get("mode") in ("min", "max", "range"):
        mode = rule["mode"]
        min_v = _safe_float(rule.get("min"))
        max_v = _safe_float(rule.get("max"))
        ref_val = tgt
        if mode == "min" and min_v is not None:
            ref_val = min_v
            diff = round(val - min_v, 1)
        elif mode == "max" and max_v is not None:
            ref_val = max_v
            diff = round(val - max_v, 1)

        if val <= 0.0:
            return {"pct": 0.0, "diff": diff, "state": "empty", "mode": mode, "min": min_v, "max": max_v}

        pct = round((val / ref_val) * 100.0, 1) if ref_val > 0.0 else 0.0

        if mode == "min":
            floor = min_v if min_v is not None else tgt
            if val >= floor:
                state = "reached"
            elif val >= floor * 0.85:
                state = "close"
            else:
                state = "below"
        elif mode == "max":
            ceil_v = max_v if max_v is not None else tgt
            if val <= ceil_v:
                state = "reached"
            elif val <= ceil_v * 1.10:
                state = "close"
            else:
                state = "over"
        else:  # range
            lo = min_v if min_v is not None else round(tgt * 0.9, 1)
            hi = max_v if max_v is not None else round(tgt * 1.1, 1)
            if lo > hi:
                lo, hi = hi, lo
            if lo <= val <= hi:
                state = "reached"
            elif (lo * 0.85 <= val < lo) or (hi < val <= hi * 1.10):
                state = "close"
            elif val > hi * 1.10:
                state = "over"
            else:
                state = "below"

        return {"pct": pct, "diff": diff, "state": state, "mode": mode, "min": min_v, "max": max_v}

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
    targets: Dict[str, Any],
    today: Optional[date] = None,
    days: int = 30,
    weight_kg: Optional[float] = None,
    rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Construit l'historique quotidien des objectifs (protéines, calories, glucides, lipides) et leurs KPIs."""
    ref_day = today or date.today()
    safe_days = max(1, min(int(days or 30), 90))

    effective_rules = rules if isinstance(rules, dict) else (targets.get("rules") if isinstance(targets.get("rules"), dict) else None)

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
                    "protein": evaluate_nutrient_day_status("protein", prot, target_protein, rule=(effective_rules or {}).get("protein")),
                    "calories": evaluate_nutrient_day_status("calories", cals, target_calories, rule=(effective_rules or {}).get("calories")),
                    "carbs": evaluate_nutrient_day_status("carbs", carbs, target_carbs, rule=(effective_rules or {}).get("carbs")),
                    "fat": evaluate_nutrient_day_status("fat", fat, target_fat, rule=(effective_rules or {}).get("fat")),
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
        if effective_rules and nutrient in effective_rules:
            entry_metric["rule"] = effective_rules[nutrient]
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
        "rules": effective_rules,
        "daily": daily_rows,
        "metrics": metrics,
    }
