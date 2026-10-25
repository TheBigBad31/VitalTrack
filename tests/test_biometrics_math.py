"""Tests unitaires exhaustifs pour le moteur mathématique biométrique (`src.biometrics_math` & `src.analytics`).

Couvre :
1. Statistiques robustes (médiane, MAD, estimateur quasi-sigma, percentiles, Z-scores robustes)
2. Lissage EMA pour pesées Withings avec pas irréguliers
3. Bandes de normalité personnelles (couloirs μ ± kσ, robustes et percentiles 15e-85e)
4. Évaluation de l'architecture du sommeil (proportions N3, REM, léger, éveil, score clinique)
5. Calcul de la dette de sommeil cumulée glissante (avec atténuation physiologique)
6. Score de récupération journalier (Z-scores robustes, sigmoïde, gestion de données partielles)
7. Détection d'anomalies multi-variées (infection / fièvre, surmenage SNA, SpO2 basse)
8. Cas limites (données manquantes, historiques courts, valeurs nulles, zéros)
"""

import math
from datetime import date, timedelta
import pytest

from src.biometrics_math import (
    DailyBiometrics,
    calculate_mad,
    calculate_median,
    calculate_percentile,
    calculate_robust_stats,
    compute_baseline_corridor,
    compute_recovery_score,
    compute_sleep_debt,
    detect_biometric_anomalies,
    evaluate_sleep_architecture,
    exponential_moving_average,
    robust_z_score,
)
from src.analytics import BiometricsAnalyticsService


# ============================================================================
# 1. Tests Statistiques Robustes & Utilitaires Mathématiques
# ============================================================================

def test_calculate_median_odd_and_even():
    # Taille impaire
    assert calculate_median([1.0, 5.0, 2.0]) == 2.0
    # Taille paire
    assert calculate_median([1.0, 2.0, 3.0, 4.0]) == 2.5
    # Avec valeurs None ou NaN ignorées
    assert calculate_median([10.0, None, float("nan"), 20.0, 30.0]) == 20.0


def test_calculate_median_empty_raises():
    with pytest.raises(ValueError):
        calculate_median([])
    with pytest.raises(ValueError):
        calculate_median([None, float("nan")])


def test_calculate_mad():
    # Série symétrique simple : [1, 2, 3, 4, 5, 6, 7] -> médiane = 4
    # Écarts : [3, 2, 1, 0, 1, 2, 3] -> trié : [0, 1, 1, 2, 2, 3, 3] -> médiane = 2
    data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    assert calculate_mad(data) == 2.0


def test_calculate_robust_stats():
    # Données avec outlier massif pour prouver la robustesse
    # 7 valeurs normales autour de 50 + 1 outlier extrême à 500
    data = [48.0, 49.0, 50.0, 50.0, 51.0, 52.0, 500.0]
    stats = calculate_robust_stats(data)
    assert stats.count == 7
    assert stats.median == 50.0
    # MAD non influencée par l'outlier
    assert stats.mad == 1.0
    assert pytest.approx(stats.pseudo_sigma, 0.001) == 1.4826


def test_calculate_percentile():
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    # P0 = min, P100 = max, P50 = median
    assert calculate_percentile(data, 0.0) == 10.0
    assert calculate_percentile(data, 100.0) == 50.0
    assert calculate_percentile(data, 50.0) == 30.0
    # P15 et P85
    p15 = calculate_percentile(data, 15.0)
    p85 = calculate_percentile(data, 85.0)
    assert 10.0 < p15 < 20.0
    assert 40.0 < p85 < 50.0

    with pytest.raises(ValueError):
        calculate_percentile(data, -5.0)
    with pytest.raises(ValueError):
        calculate_percentile(data, 105.0)


def test_robust_z_score():
    median = 60.0
    mad = 5.0  # pseudo_sigma = 5 * 1.4826 = 7.413
    z = robust_z_score(67.413, median, mad)
    assert pytest.approx(z, 0.01) == 1.0

    # MAD nulle (série constante) -> Z score doit valoir 0 sans division par zéro
    assert robust_z_score(60.0, 60.0, 0.0) == 0.0


def test_exponential_moving_average_weight_smoothing():
    start = date(2026, 1, 1)
    # 5 jours de pesées fluctuantes autour de 75 kg avec pic de rétention d'eau
    series = [
        (start, 75.0),
        (start + timedelta(days=1), 75.2),
        (start + timedelta(days=2), 76.5),  # Pic hydrique
        (start + timedelta(days=3), 75.1),
        (start + timedelta(days=4), 74.9),
    ]
    ema_res = exponential_moving_average(series, half_life_days=3.0)
    assert len(ema_res) == 5
    # Première valeur inchangée
    assert ema_res[0][1] == 75.0
    # Le pic à 76.5 est fortement lissé
    assert ema_res[2][1] < 76.0
    assert ema_res[2][1] > 75.0


# ============================================================================
# 2. Tests Bandes de Normalité Personnelles (Baseline Corridors)
# ============================================================================

def test_compute_baseline_corridor_robust():
    # 20 jours d'historique de fréquence cardiaque au repos
    history = [55.0, 56.0, 54.0, 55.0, 57.0, 56.0, 55.0, 54.0, 58.0, 55.0,
               56.0, 55.0, 54.0, 57.0, 55.0, 56.0, 54.0, 55.0, 56.0, 55.0]
    
    # Valeur normale
    corridor = compute_baseline_corridor("resting_hr", history, current_value=56.0, k_sigma=1.5)
    assert corridor.metric_name == "resting_hr"
    assert corridor.sample_count == 20
    assert corridor.median == 55.0
    assert corridor.is_in_corridor is True
    assert corridor.lower_bound < corridor.median < corridor.upper_bound
    assert corridor.p15 < corridor.p85

    # Valeur anormale hors couloir
    out_corridor = compute_baseline_corridor("resting_hr", history, current_value=68.0, k_sigma=1.5)
    assert out_corridor.is_in_corridor is False


# ============================================================================
# 3. Tests Architecture et Dette de Sommeil
# ============================================================================

def test_evaluate_sleep_architecture_ideal():
    # 8h de sommeil équilibré : 1.8h profond (22.5%), 1.8h REM (22.5%), 4.4h léger, efficacité 90%
    arch = evaluate_sleep_architecture(
        total_hours=8.0,
        efficiency_pct=90.0,
        deep_hours=1.8,
        rem_hours=1.8,
        light_hours=4.4,
        awake_hours=0.5
    )
    assert arch.total_sleep_hours == 8.0
    assert arch.is_restorative is True
    assert arch.architecture_score >= 85.0
    assert len(arch.warnings) == 0


def test_evaluate_sleep_architecture_poor():
    # 5h de sommeil avec profond très faible (0.3h = 6%) et faible efficacité (70%)
    arch = evaluate_sleep_architecture(
        total_hours=5.0,
        efficiency_pct=70.0,
        deep_hours=0.3,
        rem_hours=0.7,
        light_hours=4.0
    )
    assert arch.is_restorative is False
    assert arch.architecture_score < 60.0
    assert any("profond" in w.lower() for w in arch.warnings)
    assert any("efficacité" in w.lower() for w in arch.warnings)


def test_compute_sleep_debt_accumulation_and_recovery():
    start = date(2026, 1, 1)
    target = 8.0
    # 4 nuits courtes de 6h (efficacité 90% -> 5.4h effectif)
    history = [
        (start + timedelta(days=i), 6.0, 90.0)
        for i in range(4)
    ]
    debt_res = compute_sleep_debt(history, target_sleep_hours=target, rolling_days=7)
    assert debt_res.cumulative_debt_hours > 4.0
    assert debt_res.debt_level in ("elevated", "critical")

    # Ajouter une nuit longue de récupération de 10h
    history.append((start + timedelta(days=4), 10.0, 95.0))
    debt_after_sleep_in = compute_sleep_debt(history, target_sleep_hours=target, rolling_days=7)
    # La dette doit avoir diminué
    assert debt_after_sleep_in.cumulative_debt_hours < debt_res.cumulative_debt_hours


# ============================================================================
# 4. Tests Score de Récupération Journalier
# ============================================================================

def test_compute_recovery_score_optimal():
    today_date = date(2026, 2, 1)
    # Historique de référence stable sur 14 jours
    # Baseline : HRV ~ 50ms, RHR ~ 58 bpm, Sommeil 8h
    baseline = []
    for i in range(14):
        d = today_date - timedelta(days=14 - i)
        baseline.append(DailyBiometrics(
            date=d,
            hrv_rmssd_ms=50.0 + (i % 3) - 1.0,
            resting_hr_bpm=58.0 + (i % 2),
            sleep_duration_hours=8.0,
            sleep_score=85.0,
            activity_load=400.0
        ))

    # Aujourd'hui : excellente HRV (65ms, +15ms), FC basse (54 bpm), sommeil réparateur (90)
    today = DailyBiometrics(
        date=today_date,
        hrv_rmssd_ms=65.0,
        resting_hr_bpm=54.0,
        sleep_duration_hours=8.2,
        sleep_score=90.0,
        activity_load=300.0
    )

    rec = compute_recovery_score(today, baseline)
    assert rec.score >= 80.0
    assert rec.category == "optimal"
    assert rec.confidence == 1.0
    assert rec.z_scores_robust["hrv"] > 0
    assert rec.z_scores_robust["resting_hr"] > 0  # inversé donc positif car FC basse


def test_compute_recovery_score_degraded():
    today_date = date(2026, 2, 1)
    baseline = [
        DailyBiometrics(
            date=today_date - timedelta(days=14 - i),
            hrv_rmssd_ms=55.0,
            resting_hr_bpm=55.0,
            sleep_score=85.0
        )
        for i in range(14)
    ]

    # Aujourd'hui : HRV écroulée (28ms), FC repos élevée (68 bpm), nuit agitée
    today = DailyBiometrics(
        date=today_date,
        hrv_rmssd_ms=28.0,
        resting_hr_bpm=68.0,
        sleep_score=45.0
    )

    rec = compute_recovery_score(today, baseline)
    assert rec.score < 50.0
    assert rec.category in ("moderate", "low")
    assert rec.z_scores_robust["hrv"] < -1.5


def test_compute_recovery_score_partial_data():
    # Seulement la HRV est disponible aujourd'hui (ex: bague portée la nuit mais pas de score de sommeil)
    today_date = date(2026, 2, 1)
    baseline = [
        DailyBiometrics(
            date=today_date - timedelta(days=10 - i),
            hrv_rmssd_ms=50.0
        )
        for i in range(10)
    ]
    today = DailyBiometrics(
        date=today_date,
        hrv_rmssd_ms=52.0
    )
    rec = compute_recovery_score(today, baseline)
    assert 0.0 <= rec.score <= 100.0
    assert rec.confidence < 1.0  # Moins confiant car métriques partielles
    assert rec.hrv_contribution is not None
    assert rec.rhr_contribution is None


# ============================================================================
# 5. Tests Détection d'Anomalies Biométriques Multi-variées
# ============================================================================

def test_detect_biometric_anomalies_illness_signature():
    # Détection de la signature infectieuse typique :
    # HRV qui chute brutalement + RHR qui s'envole + Hausse de la température cutanée
    today_date = date(2026, 2, 10)
    history = [
        DailyBiometrics(
            date=today_date - timedelta(days=14 - i),
            hrv_rmssd_ms=60.0 + (i % 2),
            resting_hr_bpm=52.0,
            skin_temp_deviation_c=0.0
        )
        for i in range(14)
    ]

    sick_day = DailyBiometrics(
        date=today_date,
        hrv_rmssd_ms=30.0,              # Grosse chute
        resting_hr_bpm=64.0,             # +12 bpm
        skin_temp_deviation_c=+0.65      # Fièvre / inflammation
    )

    anomalies = detect_biometric_anomalies(sick_day, history)
    assert len(anomalies) >= 1
    illness_alert = [a for a in anomalies if a.category == "illness_risk"]
    assert len(illness_alert) == 1
    assert illness_alert[0].severity == "critical"
    assert "infection" in illness_alert[0].title.lower() or "infectieuse" in illness_alert[0].title.lower()


def test_detect_biometric_anomalies_spo2_drop():
    today_date = date(2026, 2, 10)
    history = [
        DailyBiometrics(
            date=today_date - timedelta(days=7 - i),
            hrv_rmssd_ms=55.0,
            resting_hr_bpm=56.0,
            spo2_pct=98.0
        )
        for i in range(7)
    ]

    desat_day = DailyBiometrics(
        date=today_date,
        hrv_rmssd_ms=54.0,
        resting_hr_bpm=57.0,
        spo2_pct=89.5  # Hypoxie notable
    )

    anomalies = detect_biometric_anomalies(desat_day, history)
    spo2_alert = [a for a in anomalies if a.category == "respiratory"]
    assert len(spo2_alert) == 1
    assert spo2_alert[0].severity == "critical"


# ============================================================================
# 6. Tests Service Analytics de Haut Niveau
# ============================================================================

def test_biometrics_analytics_service_orchestration():
    service = BiometricsAnalyticsService(target_sleep_hours=8.0)
    today_date = date(2026, 3, 1)
    
    history = [
        DailyBiometrics(
            date=today_date - timedelta(days=10 - i),
            hrv_rmssd_ms=50.0 + i,
            resting_hr_bpm=58.0 - (i * 0.2),
            sleep_duration_hours=7.8,
            sleep_score=82.0,
            spo2_pct=97.5,
            skin_temp_deviation_c=0.05,
            weight_kg=78.5 - (i * 0.1)
        )
        for i in range(10)
    ]
    
    current = DailyBiometrics(
        date=today_date,
        hrv_rmssd_ms=58.0,
        resting_hr_bpm=56.0,
        sleep_duration_hours=8.0,
        sleep_efficiency_pct=92.0,
        deep_sleep_hours=1.9,
        rem_sleep_hours=1.7,
        light_sleep_hours=4.4,
        awake_hours=0.4,
        sleep_score=88.0,
        spo2_pct=98.0,
        skin_temp_deviation_c=-0.1,
        weight_kg=77.4
    )
    
    # 1. Analyse récupération
    rec = service.analyze_recovery(current, history)
    assert rec.score >= 75.0
    
    # 2. Analyse sommeil
    # 7 nuits de sommeil proche de la cible (8h à 95% d'efficacité)
    sleep_hist = [(b.date, 8.0, 95.0) for b in history]
    sleep_analysis = service.analyze_sleep(current, sleep_hist)
    assert sleep_analysis["architecture"].is_restorative is True
    assert sleep_analysis["debt"].cumulative_debt_hours <= 2.5
    
    # 3. Bandes de normalité
    corridors = service.compute_all_corridors(current, history)
    assert "hrv_rmssd_ms" in corridors
    assert "resting_hr_bpm" in corridors
    assert "weight_kg" in corridors
    assert corridors["hrv_rmssd_ms"].is_in_corridor is True
    
    # 4. Lissage poids
    w_series = [(b.date, b.weight_kg) for b in history]
    smoothed_w = service.smooth_weight_series(w_series)
    assert len(smoothed_w) == len(w_series)
    
    # 5. Détection anomalies (aucune sur sujet sain)
    anomalies = service.detect_anomalies(current, history)
    assert len(anomalies) == 0
