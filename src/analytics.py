"""Module d'analyse biométrique et d'intégration des données de santé.

Ce module fait le pont entre le stockage VitalTrack (BDD, connecteurs RingConn, Withings, Google Health Connect)
et le moteur algorithmique pur `src.biometrics_math`.
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.biometrics_math import (
    BaselineCorridor,
    BiometricAnomaly,
    DailyBiometrics,
    RecoveryScoreResult,
    SleepArchitecture,
    SleepDebtResult,
    compute_baseline_corridor,
    compute_recovery_score,
    compute_sleep_debt,
    detect_biometric_anomalies,
    evaluate_sleep_architecture,
    exponential_moving_average,
)


class BiometricsAnalyticsService:
    """Service d'analyse biométrique pour l'utilisateur."""

    def __init__(self, target_sleep_hours: float = 8.0):
        self.target_sleep_hours = target_sleep_hours

    def analyze_recovery(
        self,
        today_data: DailyBiometrics,
        history: List[DailyBiometrics],
        weights: Optional[Dict[str, float]] = None
    ) -> RecoveryScoreResult:
        """Calcule le score de récupération pour la journée donnée."""
        return compute_recovery_score(today_data, history, weights=weights)

    def analyze_sleep(
        self,
        today_data: DailyBiometrics,
        history_sleep: List[Tuple[date, float, Optional[float]]],
        rolling_days: int = 7
    ) -> Dict[str, Any]:
        """Analyse complète du sommeil : architecture de la dernière nuit et dette cumulée."""
        total_hours = today_data.sleep_duration_hours or 0.0
        eff = today_data.sleep_efficiency_pct or 85.0
        
        arch = evaluate_sleep_architecture(
            total_hours=total_hours,
            efficiency_pct=eff,
            deep_hours=today_data.deep_sleep_hours,
            rem_hours=today_data.rem_sleep_hours,
            light_hours=today_data.light_sleep_hours,
            awake_hours=today_data.awake_hours
        )
        
        debt = compute_sleep_debt(
            history=history_sleep,
            target_sleep_hours=self.target_sleep_hours,
            rolling_days=rolling_days
        )
        
        return {
            "architecture": arch,
            "debt": debt
        }

    def compute_all_corridors(
        self,
        current: DailyBiometrics,
        history: List[DailyBiometrics],
        k_sigma: float = 1.5
    ) -> Dict[str, BaselineCorridor]:
        """Calcule les bandes de normalité pour tous les biomarqueurs disponibles."""
        corridors: Dict[str, BaselineCorridor] = {}
        
        # HRV
        hrv_hist = [b.hrv_rmssd_ms for b in history if b.hrv_rmssd_ms is not None]
        if hrv_hist:
            corridors["hrv_rmssd_ms"] = compute_baseline_corridor(
                "hrv_rmssd_ms", hrv_hist, current.hrv_rmssd_ms, k_sigma=k_sigma
            )
            
        # Resting Heart Rate
        rhr_hist = [b.resting_hr_bpm for b in history if b.resting_hr_bpm is not None]
        if rhr_hist:
            corridors["resting_hr_bpm"] = compute_baseline_corridor(
                "resting_hr_bpm", rhr_hist, current.resting_hr_bpm, k_sigma=k_sigma
            )
            
        # SpO2
        spo2_hist = [b.spo2_pct for b in history if b.spo2_pct is not None]
        if spo2_hist:
            corridors["spo2_pct"] = compute_baseline_corridor(
                "spo2_pct", spo2_hist, current.spo2_pct, k_sigma=k_sigma
            )
            
        # Skin Temperature Deviation
        temp_hist = [b.skin_temp_deviation_c for b in history if b.skin_temp_deviation_c is not None]
        if temp_hist:
            corridors["skin_temp_deviation_c"] = compute_baseline_corridor(
                "skin_temp_deviation_c", temp_hist, current.skin_temp_deviation_c, k_sigma=k_sigma
            )
            
        # Weight
        weight_hist = [b.weight_kg for b in history if b.weight_kg is not None]
        if weight_hist:
            corridors["weight_kg"] = compute_baseline_corridor(
                "weight_kg", weight_hist, current.weight_kg, k_sigma=k_sigma
            )
            
        return corridors

    def smooth_weight_series(
        self,
        weight_series: List[Tuple[date, float]],
        half_life_days: float = 7.0
    ) -> List[Tuple[date, float]]:
        """Lissage exponentiel des pesées Withings/manuelles (EMA adaptative)."""
        return exponential_moving_average(weight_series, half_life_days=half_life_days)

    def detect_anomalies(
        self,
        today_data: DailyBiometrics,
        history: List[DailyBiometrics]
    ) -> List[BiometricAnomaly]:
        """Détecte les anomalies et dérives physiologiques."""
        return detect_biometric_anomalies(today_data, history)


def _compute_bmr_mifflin_st_jeor(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: str,
) -> float:
    """Calcul déterministe du BMR via Mifflin-St Jeor."""
    base = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age
    return base + 5.0 if str(gender).lower() in ("male", "m", "homme", "h") else base - 161.0


def detect_metabolic_plateau(
    weights: List[Any],
    meals: List[Any],
    activities: List[Any],
    profile: Dict[str, Any],
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Détection déterministe de plateau métabolique sur 14 jours (sans appel LLM).

    Analyse la pente de la moyenne mobile 14 jours du poids (moving_avg_7d / 14d)
    croisée avec le déficit calorique moyen enregistré.
    Si |variation_14j| < 0.15 kg malgré un déficit théorique > 300 kcal/j,
    déclenche une recommandation contextuelle (NEAT +1 500 pas/j, refeed, TDEE).
    """
    ref_date = today or date.today()
    cutoff_14d = ref_date - timedelta(days=14)
    cutoff_7d = ref_date - timedelta(days=7)

    def _to_date(val: Any) -> Optional[date]:
        if isinstance(val, date):
            return val
        if isinstance(val, str):
            try:
                return date.fromisoformat(val[:10])
            except ValueError:
                return None
        return None

    # 1. Extraire les pesées sur les 14 derniers jours
    recent_weights: List[Tuple[date, float]] = []
    for w in weights or []:
        w_date = _to_date(getattr(w, "date", None) if not isinstance(w, dict) else w.get("date"))
        w_kg = getattr(w, "weight_kg", None) if not isinstance(w, dict) else w.get("weight_kg")
        if w_date and w_kg is not None and cutoff_14d <= w_date <= ref_date:
            recent_weights.append((w_date, float(w_kg)))

    recent_weights.sort(key=lambda x: x[0])

    first_7d = [kg for d, kg in recent_weights if d < cutoff_7d]
    last_7d = [kg for d, kg in recent_weights if d >= cutoff_7d]

    moving_avg_14d = round(sum(kg for _, kg in recent_weights) / len(recent_weights), 2) if recent_weights else None
    moving_avg_7d = round(sum(last_7d) / len(last_7d), 2) if last_7d else None
    earlier_avg_7d = round(sum(first_7d) / len(first_7d), 2) if first_7d else None

    weight_change_14d_kg: Optional[float] = None
    if moving_avg_7d is not None and earlier_avg_7d is not None:
        weight_change_14d_kg = round(moving_avg_7d - earlier_avg_7d, 2)
    elif len(recent_weights) >= 2 and (recent_weights[-1][0] - recent_weights[0][0]).days >= 7:
        weight_change_14d_kg = round(recent_weights[-1][1] - recent_weights[0][1], 2)

    # 2. Calculer le déficit calorique moyen sur les jours renseignés (14 derniers jours)
    intake_by_day: Dict[date, float] = {}
    for m in meals or []:
        m_date = _to_date(getattr(m, "date", None) if not isinstance(m, dict) else m.get("date"))
        m_kcal = getattr(m, "total_calories_kcal", None) if not isinstance(m, dict) else m.get("total_calories_kcal")
        if m_date and m_kcal is not None and cutoff_14d <= m_date <= ref_date:
            intake_by_day[m_date] = intake_by_day.get(m_date, 0.0) + float(m_kcal)

    activity_kcal_by_day: Dict[date, float] = {}
    for a in activities or []:
        a_date = _to_date(getattr(a, "date", None) if not isinstance(a, dict) else a.get("date"))
        a_kcal = getattr(a, "calories_burned_kcal", None) if not isinstance(a, dict) else a.get("calories_burned_kcal")
        if a_date and a_kcal is not None and cutoff_14d <= a_date <= ref_date:
            activity_kcal_by_day[a_date] = activity_kcal_by_day.get(a_date, 0.0) + float(a_kcal)

    ref_weight = moving_avg_7d or moving_avg_14d or float(profile.get("weight_kg") or 79.5)
    bmr = _compute_bmr_mifflin_st_jeor(
        weight_kg=ref_weight,
        height_cm=float(profile.get("height_cm") or 178.0),
        age=int(profile.get("age") or 35),
        gender=str(profile.get("gender") or "male"),
    )

    avg_deficit_kcal: Optional[float] = None
    if len(intake_by_day) >= 3:
        daily_deficits = []
        for d_day, intake in intake_by_day.items():
            # TDEE estimé = BMR * 1.2 (NEAT de base) + activité enregistrée (ou BMR * 1.375)
            burned_act = activity_kcal_by_day.get(d_day)
            tdee_day = (bmr * 1.2 + burned_act) if burned_act is not None else (bmr * 1.375)
            daily_deficits.append(tdee_day - intake)
        avg_deficit_kcal = round(sum(daily_deficits) / len(daily_deficits), 1)

    is_plateau = (
        weight_change_14d_kg is not None
        and avg_deficit_kcal is not None
        and abs(weight_change_14d_kg) < 0.15
        and avg_deficit_kcal > 300.0
    )

    recommendations: List[Dict[str, str]] = []
    message = ""
    if is_plateau:
        message = (
            f"Plateau métabolique détecté : variation de poids de {weight_change_14d_kg:+.2f} kg sur 14 jours "
            f"malgré un déficit moyen de {avg_deficit_kcal:.0f} kcal/j."
        )
        recommendations = [
            {
                "id": "neat_boost",
                "title": "Ajustement du NEAT (+1 500 pas/j)",
                "detail": "Augmentez votre activité quotidienne hors sport de 1 500 pas/jour (~60-80 kcal/j) pour relancer la dépense.",
            },
            {
                "id": "controlled_refeed",
                "title": "Refeed contrôlé (1 à 2 jours)",
                "detail": "Remontez temporairement vos apports au niveau de maintenance (glucides complexes) pour stimuler la leptine.",
            },
            {
                "id": "tdee_reevaluation",
                "title": "Réévaluation du TDEE",
                "detail": "Recalculez votre dépense énergétique totale (-100 à -150 kcal/j) suite à l'adaptation métabolique.",
            },
        ]

    return {
        "is_plateau": is_plateau,
        "moving_avg_7d_kg": moving_avg_7d,
        "moving_avg_14d_kg": moving_avg_14d,
        "weight_change_14d_kg": weight_change_14d_kg,
        "avg_deficit_kcal": avg_deficit_kcal,
        "days_analyzed": len(intake_by_day),
        "message": message,
        "recommendations": recommendations,
    }
