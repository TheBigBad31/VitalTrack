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
