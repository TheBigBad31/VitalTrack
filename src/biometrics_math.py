"""Module mathématique et algorithmique biométrique pour VitalTrack.

Fournit un ensemble pur, déterministe et rigoureusement typé pour le traitement
et l'analyse des séries temporelles biométriques (RingConn Gen 3, Withings, Santé Connect, Oura, etc.) :
1. Score de récupération journalier (Recovery Score 0 - 100) avec Z-score robuste (médiane - MAD)
2. Bandes de normalité personnelles (Baselines dynamiques et couloirs μ ± kσ ou percentiles) + lissage EMA du poids
3. Dette de sommeil cumulée & analyse de l'architecture du sommeil (Profond, REM, Léger, Éveil)
4. Détection d'anomalies biométriques multi-variées explicables (dérive HRV, FC repos, température cutanée, SpO2)
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


# ============================================================================
# Modèles de données & Structures
# ============================================================================

@dataclass(frozen=True)
class DailyBiometrics:
    """Mesures biométriques journalières normalisées."""
    date: date
    hrv_rmssd_ms: Optional[float] = None
    resting_hr_bpm: Optional[float] = None
    sleep_duration_hours: Optional[float] = None
    sleep_efficiency_pct: Optional[float] = None  # 0 to 100
    sleep_score: Optional[float] = None          # 0 to 100
    deep_sleep_hours: Optional[float] = None
    rem_sleep_hours: Optional[float] = None
    light_sleep_hours: Optional[float] = None
    awake_hours: Optional[float] = None
    skin_temp_deviation_c: Optional[float] = None # écart p/r à la référence en °C (ex: +0.4)
    spo2_pct: Optional[float] = None              # 0 to 100
    weight_kg: Optional[float] = None
    activity_load: Optional[float] = None         # calories actives ou charge d'entraînement (ex: kcal)


@dataclass(frozen=True)
class RobustStats:
    """Statistiques descriptives robustes (médiane, MAD, quasi-écart-type)."""
    count: int
    median: float
    mad: float
    pseudo_sigma: float  # MAD * 1.4826 (estimateur sans biais de sigma pour loi normale)


@dataclass(frozen=True)
class BaselineCorridor:
    """Bande de normalité dynamique pour un biomarqueur."""
    metric_name: str
    sample_count: int
    median: float
    mean: float
    std_dev: float
    lower_bound: float
    upper_bound: float
    p15: float
    p85: float
    is_in_corridor: Optional[bool] = None
    current_value: Optional[float] = None


@dataclass(frozen=True)
class SleepArchitecture:
    """Analyse de l'architecture et composition du sommeil."""
    total_sleep_hours: float
    efficiency_pct: float
    deep_sleep_hours: float
    deep_sleep_pct: float
    rem_sleep_hours: float
    rem_sleep_pct: float
    light_sleep_hours: float
    light_sleep_pct: float
    awake_hours: float
    awake_pct: float
    architecture_score: float  # 0 à 100
    is_restorative: bool
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SleepDebtResult:
    """Résultat du calcul de la dette de sommeil cumulée."""
    target_sleep_hours: float
    rolling_days: int
    daily_effective_sleep: List[Tuple[date, float]]
    daily_debt_hours: List[Tuple[date, float]]
    cumulative_debt_hours: float
    debt_level: str  # 'optimal', 'moderate', 'elevated', 'critical'
    description: str


@dataclass(frozen=True)
class RecoveryScoreResult:
    """Résultat détaillé du score de récupération journalier."""
    score: float  # 0 to 100
    category: str # 'optimal', 'good', 'moderate', 'low'
    hrv_contribution: Optional[float]  # -1.0 to 1.0 (ou contribution normalisée)
    rhr_contribution: Optional[float]
    sleep_contribution: Optional[float]
    load_contribution: Optional[float]
    z_scores_robust: Dict[str, float]
    factors_summary: str
    confidence: float  # 0.0 to 1.0 basé sur les métriques disponibles


@dataclass(frozen=True)
class BiometricAnomaly:
    """Anomalie biométrique détectée avec explicabilité."""
    severity: str  # 'info', 'warning', 'critical'
    category: str  # 'recovery_drop', 'illness_risk', 'overreaching', 'cardiac_strain', 'respiratory'
    title: str
    explanation: str
    actionable_insight: str
    trigger_metrics: Dict[str, Any]


# ============================================================================
# Fonctions Statistiques Robustes & Utilitaires Pures
# ============================================================================

def calculate_median(values: Sequence[float]) -> float:
    """Calcule la médiane exacte d'une séquence de réels."""
    clean_vals = [v for v in values if v is not None and not math.isnan(v)]
    if not clean_vals:
        raise ValueError("Impossible de calculer la médiane d'une séquence vide ou ne contenant que des NaN.")
    return float(statistics.median(clean_vals))


def calculate_mad(values: Sequence[float], median_val: Optional[float] = None) -> float:
    """Calcule la Median Absolute Deviation (MAD) : median(|x_i - median(x)|)."""
    clean_vals = [v for v in values if v is not None and not math.isnan(v)]
    if not clean_vals:
        raise ValueError("Impossible de calculer la MAD d'une séquence vide.")
    med = median_val if median_val is not None else calculate_median(clean_vals)
    deviations = [abs(x - med) for x in clean_vals]
    return float(statistics.median(deviations))


def calculate_robust_stats(values: Sequence[float]) -> RobustStats:
    """Calcule les statistiques robustes : Médiane, MAD, et pseudo-écart-type σ_MAD.
    
    Pour une distribution normale, σ ≈ 1.4826 * MAD.
    """
    clean_vals = [v for v in values if v is not None and not math.isnan(v)]
    n = len(clean_vals)
    if n == 0:
        raise ValueError("Séquence vide pour les statistiques robustes.")
    med = calculate_median(clean_vals)
    mad = calculate_mad(clean_vals, med)
    pseudo_sigma = mad * 1.482602218505602
    return RobustStats(
        count=n,
        median=med,
        mad=mad,
        pseudo_sigma=pseudo_sigma
    )


def calculate_percentile(values: Sequence[float], p: float) -> float:
    """Calcule le percentile p (0 <= p <= 100) par interpolation linéaire standard."""
    clean_vals = sorted([v for v in values if v is not None and not math.isnan(v)])
    n = len(clean_vals)
    if n == 0:
        raise ValueError("Impossible de calculer un percentile sur une liste vide.")
    if p < 0 or p > 100:
        raise ValueError(f"Le percentile doit être compris entre 0 et 100, reçu: {p}")
    if n == 1:
        return float(clean_vals[0])
    
    # Rang virtuel (0-indexé)
    rank = (p / 100.0) * (n - 1)
    lower_idx = int(math.floor(rank))
    upper_idx = int(math.ceil(rank))
    weight = rank - lower_idx
    return clean_vals[lower_idx] * (1.0 - weight) + clean_vals[upper_idx] * weight


def robust_z_score(
    value: float,
    median: float,
    mad: float,
    min_sigma: float = 1e-4,
    fallback_std_dev: Optional[float] = None
) -> float:
    """Calcule le Z-score robuste : Z = (x - median) / (1.4826 * MAD).
    
    Si MAD == 0 (variabilité nulle ou échantillon très homogène) :
    utilise fallback_std_dev si fourni et > 0, sinon min_sigma.
    """
    scale = mad * 1.482602218505602
    if scale < min_sigma:
        if fallback_std_dev is not None and fallback_std_dev >= min_sigma:
            return (value - median) / fallback_std_dev
        elif abs(value - median) < min_sigma:
            return 0.0
        else:
            # S'il y a un écart réel alors que la dispersion était nulle,
            # utiliser l'écart absolu normalisé par rapport à la médiane ou 1.0
            norm_scale = max(abs(median) * 0.1, 1.0)
            return (value - median) / norm_scale
    return (value - median) / scale


def exponential_moving_average(
    series: Sequence[Tuple[date, float]],
    alpha: Optional[float] = None,
    half_life_days: Optional[float] = None
) -> List[Tuple[date, float]]:
    """Calcule la moyenne mobile exponentielle (EMA) temporelle sur une série chronologique.
    
    Idéal pour lisser le poids (Withings) tout en s'adaptant aux intervalles de temps irréguliers.
    Si half_life_days est spécifié : alpha = 1 - exp(-ln(2) * dt / half_life).
    """
    if not series:
        return []
    
    sorted_series = sorted(series, key=lambda x: x[0])
    result: List[Tuple[date, float]] = []
    
    ema = sorted_series[0][1]
    result.append((sorted_series[0][0], ema))
    prev_date = sorted_series[0][0]
    
    default_alpha = alpha if alpha is not None else 0.2
    
    for d, val in sorted_series[1:]:
        dt = (d - prev_date).days
        if dt <= 0:
            dt = 1
        
        if half_life_days is not None and half_life_days > 0:
            decay = math.exp(-math.log(2.0) * dt / half_life_days)
            curr_alpha = 1.0 - decay
        elif alpha is not None:
            # Adaptation exponentielle au nombre de jours écoulés
            curr_alpha = 1.0 - math.pow(1.0 - default_alpha, dt)
        else:
            curr_alpha = default_alpha
            
        ema = curr_alpha * val + (1.0 - curr_alpha) * ema
        result.append((d, round(ema, 3)))
        prev_date = d
        
    return result


# ============================================================================
# 1. Bandes de Normalité Personnelles (Dynamic Baseline Corridors)
# ============================================================================

def compute_baseline_corridor(
    metric_name: str,
    history_values: Sequence[float],
    current_value: Optional[float] = None,
    k_sigma: float = 1.5,
    use_robust: bool = True
) -> BaselineCorridor:
    """Calcule le couloir de normalité personnalisé d'un biomarqueur sur une fenêtre (ex: 14 à 30 jours).
    
    Args:
        metric_name: Nom du biomarqueur (ex: 'hrv', 'resting_hr', 'spo2', 'temp_deviation', 'weight')
        history_values: Historique des valeurs sur la période
        current_value: Valeur actuelle optionnelle pour vérifier l'appartenance au couloir
        k_sigma: Facteur multiplicateur pour le couloir μ ± kσ (défaut 1.5 pour ~87% sous loi normale)
        use_robust: Si True, utilise médiane et pseudo-sigma (MAD * 1.4826) pour résister aux outliers.
    """
    clean_vals = [float(v) for v in history_values if v is not None and not math.isnan(v)]
    n = len(clean_vals)
    if n == 0:
        raise ValueError(f"Aucune valeur valide fournie pour la baseline '{metric_name}'.")
    
    mean_val = float(statistics.mean(clean_vals))
    std_dev = float(statistics.stdev(clean_vals)) if n >= 2 else 0.0
    med_val = calculate_median(clean_vals)
    p15 = calculate_percentile(clean_vals, 15.0)
    p85 = calculate_percentile(clean_vals, 85.0)
    
    if use_robust and n >= 3:
        robust = calculate_robust_stats(clean_vals)
        center = robust.median
        spread = robust.pseudo_sigma if robust.pseudo_sigma > 1e-4 else std_dev
    else:
        center = mean_val
        spread = std_dev
        
    lower_bound = center - k_sigma * spread
    upper_bound = center + k_sigma * spread
    
    is_in_corridor = None
    if current_value is not None and not math.isnan(current_value):
        is_in_corridor = (lower_bound <= current_value <= upper_bound)
        
    return BaselineCorridor(
        metric_name=metric_name,
        sample_count=n,
        median=round(med_val, 3),
        mean=round(mean_val, 3),
        std_dev=round(std_dev, 3),
        lower_bound=round(lower_bound, 3),
        upper_bound=round(upper_bound, 3),
        p15=round(p15, 3),
        p85=round(p85, 3),
        is_in_corridor=is_in_corridor,
        current_value=round(current_value, 3) if current_value is not None else None
    )


# ============================================================================
# 2. Architecture du Sommeil & Dette de Sommeil Cumulée
# ============================================================================

def evaluate_sleep_architecture(
    total_hours: float,
    efficiency_pct: float,
    deep_hours: Optional[float] = None,
    rem_hours: Optional[float] = None,
    light_hours: Optional[float] = None,
    awake_hours: Optional[float] = None
) -> SleepArchitecture:
    """Analyse la composition du sommeil selon les recommandations cliniques du sommeil.
    
    Normes physiologiques adultes recommandées :
    - Sommeil profond (N3) : 15 - 25 % du sommeil total (restauration physique, immunité, GH)
    - Sommeil paradoxal (REM) : 20 - 25 % du sommeil total (consolidation mémoire, équilibre émotionnel)
    - Sommeil léger (N1+N2) : 50 - 60 % du sommeil total
    - Éveil intra-sommeil : < 10 - 15 %
    - Efficacité de sommeil : >= 85 %
    """
    if total_hours <= 0:
        return SleepArchitecture(
            total_sleep_hours=0.0,
            efficiency_pct=0.0,
            deep_sleep_hours=0.0,
            deep_sleep_pct=0.0,
            rem_sleep_hours=0.0,
            rem_sleep_pct=0.0,
            light_sleep_hours=0.0,
            light_sleep_pct=0.0,
            awake_hours=0.0,
            awake_pct=0.0,
            architecture_score=0.0,
            is_restorative=False,
            warnings=("Durée de sommeil nulle ou négative",)
        )
    
    warnings_list: List[str] = []
    
    # Imputation cohérente si des phases sont manquantes
    known_stages = [h for h in (deep_hours, rem_hours, light_hours) if h is not None]
    if len(known_stages) == 3:
        d_h, r_h, l_h = deep_hours, rem_hours, light_hours
    elif deep_hours is not None and rem_hours is not None:
        d_h, r_h = deep_hours, rem_hours
        l_h = max(0.0, total_hours - (d_h + r_h))
    else:
        # Distribution typique par défaut si les capteurs n'ont pas fourni le détail
        d_h = total_hours * 0.20
        r_h = total_hours * 0.22
        l_h = total_hours * 0.58
        warnings_list.append("Phases de sommeil estimées par distribution standard (données capteur partielles)")
        
    a_h = awake_hours if awake_hours is not None else max(0.0, total_hours * (100.0 - efficiency_pct) / max(efficiency_pct, 1.0))
    
    total_effective = max(d_h + r_h + l_h, 0.01)
    deep_pct = (d_h / total_effective) * 100.0
    rem_pct = (r_h / total_effective) * 100.0
    light_pct = (l_h / total_effective) * 100.0
    awake_pct = (a_h / (total_effective + a_h)) * 100.0
    
    # Score d'architecture (0 à 100)
    score = 100.0
    
    # Pénalité durée totale (idéal 7h - 9h)
    if total_hours < 7.0:
        score -= min(35.0, (7.0 - total_hours) * 15.0)
    elif total_hours > 9.5:
        score -= min(10.0, (total_hours - 9.5) * 5.0)
        
    # Pénalité efficacité (< 85%)
    if efficiency_pct < 85.0:
        score -= min(25.0, (85.0 - efficiency_pct) * 1.2)
        warnings_list.append(f"Efficacité du sommeil sous le seuil optimal ({efficiency_pct:.1f}% < 85%)")
        
    # Pénalité profond insuffisant (< 15%)
    if deep_pct < 15.0:
        score -= min(20.0, (15.0 - deep_pct) * 1.5)
        warnings_list.append(f"Sommeil profond réduit ({deep_pct:.1f}% < 15%) : récupération physique impactée")
        
    # Pénalité REM insuffisant (< 18%)
    if rem_pct < 18.0:
        score -= min(15.0, (18.0 - rem_pct) * 1.2)
        warnings_list.append(f"Sommeil paradoxal (REM) insuffisant ({rem_pct:.1f}% < 18%) : récupération cognitive altérée")
        
    final_score = max(0.0, min(100.0, score))
    is_restorative = (final_score >= 70.0 and deep_pct >= 13.0 and efficiency_pct >= 80.0)
    
    return SleepArchitecture(
        total_sleep_hours=round(total_hours, 2),
        efficiency_pct=round(efficiency_pct, 1),
        deep_sleep_hours=round(d_h, 2),
        deep_sleep_pct=round(deep_pct, 1),
        rem_sleep_hours=round(r_h, 2),
        rem_sleep_pct=round(rem_pct, 1),
        light_sleep_hours=round(l_h, 2),
        light_sleep_pct=round(light_pct, 1),
        awake_hours=round(a_h, 2),
        awake_pct=round(awake_pct, 1),
        architecture_score=round(final_score, 1),
        is_restorative=is_restorative,
        warnings=tuple(warnings_list)
    )


def compute_sleep_debt(
    history: Sequence[Tuple[date, float, Optional[float]]],
    target_sleep_hours: float = 8.0,
    rolling_days: int = 7,
    decay_factor: float = 0.90
) -> SleepDebtResult:
    """Calcule la dette de sommeil cumulée glissante sur N jours (défaut 7 jours).
    
    Chaque jour apporte :
      sommeil_effectif = sleep_hours * (efficiency_pct / 100) si efficacité disponible, sinon sleep_hours
      deficit_jour = max(0, target - sommeil_effectif) - surplus_compensation
    La dette s'atténue naturellement au fil des jours via un facteur de mémoire physiologique `decay_factor`.
    
    Args:
        history: Liste ordonnée de (date, sleep_hours, optional efficiency_pct)
        target_sleep_hours: Besoin cible journalier (ex: 8.0h)
        rolling_days: Fenêtre glissante de calcul (défaut 7 jours)
        decay_factor: Facteur d'amortissement journalier de la dette (0.85 à 0.95)
    """
    if not history:
        return SleepDebtResult(
            target_sleep_hours=target_sleep_hours,
            rolling_days=rolling_days,
            daily_effective_sleep=[],
            daily_debt_hours=[],
            cumulative_debt_hours=0.0,
            debt_level="optimal",
            description="Aucun historique de sommeil disponible."
        )
    
    sorted_history = sorted(history, key=lambda x: x[0])
    recent_history = sorted_history[-rolling_days:]
    
    daily_effective: List[Tuple[date, float]] = []
    daily_debts: List[Tuple[date, float]] = []
    
    accumulated_debt = 0.0
    
    for d, hours, eff in recent_history:
        hours_val = max(0.0, hours) if hours is not None else 0.0
        # Sommeil effectif pondéré par l'efficacité
        if eff is not None and eff > 0:
            eff_norm = min(1.0, max(0.5, eff / 100.0))
            effective = hours_val * eff_norm
        else:
            effective = hours_val
            
        daily_effective.append((d, round(effective, 2)))
        
        # Déficit journalier (positif si manque, négatif si surplus)
        deficit = target_sleep_hours - effective
        
        # Le surplus de sommeil ne rembourse la dette qu'à 50% d'efficacité physiologique
        if deficit < 0:
            effective_repayment = deficit * 0.50
            accumulated_debt = max(0.0, (accumulated_debt * decay_factor) + effective_repayment)
        else:
            accumulated_debt = (accumulated_debt * decay_factor) + deficit
            
        daily_debts.append((d, round(accumulated_debt, 2)))
        
    cum_debt = round(accumulated_debt, 2)
    
    if cum_debt <= 1.0:
        debt_level = "optimal"
        desc = "Dette de sommeil négligeable : vigilance et performances cognitives au sommet."
    elif cum_debt <= 3.0:
        debt_level = "moderate"
        desc = f"Légère dette de sommeil ({cum_debt}h) : facilement récupérable avec une nuit complète."
    elif cum_debt <= 5.5:
        debt_level = "elevated"
        desc = f"Dette de sommeil notable ({cum_debt}h) : baisse de vigilance et récupération musculaire ralentie."
    else:
        debt_level = "critical"
        desc = f"Dette de sommeil critique ({cum_debt}h) : risque élevé de fatigue chronique, perturbations immunitaires et métaboliques."
        
    return SleepDebtResult(
        target_sleep_hours=target_sleep_hours,
        rolling_days=rolling_days,
        daily_effective_sleep=daily_effective,
        daily_debt_hours=daily_debts,
        cumulative_debt_hours=cum_debt,
        debt_level=debt_level,
        description=desc
    )


# ============================================================================
# 3. Score de Récupération Journalier (Recovery Score 0 - 100)
# ============================================================================

def compute_recovery_score(
    today: DailyBiometrics,
    baseline_history: Sequence[DailyBiometrics],
    weights: Optional[Dict[str, float]] = None
) -> RecoveryScoreResult:
    """Calcule le score de récupération journalier (0 - 100) par Z-score robuste.
    
    Algorithme :
    1. Calcule la baseline robuste (médiane, MAD) de chaque biomarqueur sur l'historique (14-28j) :
       - HRV (RMSSD) : Z_hrv = (hrv - med) / (1.4826 * MAD)  --> un Z positif est favorable
       - Fréquence Cardiaque de repos (RHR) : Z_rhr = -(rhr - med) / (1.4826 * MAD) --> un RHR bas est favorable
       - Sommeil (durée / score) : normalisé p/r à la médiane et objectif 8h
       - Charge d'activité veille : pénalise si surentraînement aigu (aigu/chronique > 1.4)
    2. Conversion des Z-scores en composantes bornées par fonction sigmoïde / logistique centrée :
       S_k = 1 / (1 + exp(-Z_k))
    3. Combinaison pondérée normalisée selon la disponibilité des capteurs.
    """
    clean_history = [b for b in baseline_history if b.date < today.date]
    
    # Poids par défaut
    w_default = {
        "hrv": 0.40,
        "resting_hr": 0.25,
        "sleep": 0.25,
        "activity_load": 0.10
    }
    w = dict(w_default) if weights is None else dict(weights)
    
    z_scores: Dict[str, float] = {}
    contributions: Dict[str, float] = {}
    active_weights: Dict[str, float] = {}
    
    # 1. HRV
    hrv_history = [b.hrv_rmssd_ms for b in clean_history if b.hrv_rmssd_ms is not None]
    if today.hrv_rmssd_ms is not None:
        if len(hrv_history) >= 3:
            stats_hrv = calculate_robust_stats(hrv_history)
            hrv_std = float(statistics.stdev(hrv_history)) if len(hrv_history) >= 2 else None
            z_hrv = robust_z_score(today.hrv_rmssd_ms, stats_hrv.median, stats_hrv.mad, fallback_std_dev=hrv_std)
        else:
            # Référence absolue de repli (ex: médiane population 45ms)
            z_hrv = (today.hrv_rmssd_ms - 45.0) / 15.0
        
        # Clamp Z-score entre -3.0 et +3.0
        z_hrv = max(-3.0, min(3.0, z_hrv))
        z_scores["hrv"] = round(z_hrv, 3)
        # Normalisation sigmoïde 0 - 100
        hrv_comp = 100.0 / (1.0 + math.exp(-0.9 * z_hrv))
        contributions["hrv"] = hrv_comp
        active_weights["hrv"] = w.get("hrv", 0.40)
        
    # 2. Resting Heart Rate (RHR) : une FC basse indique une meilleure récupération parasympathique
    rhr_history = [b.resting_hr_bpm for b in clean_history if b.resting_hr_bpm is not None]
    if today.resting_hr_bpm is not None:
        if len(rhr_history) >= 3:
            stats_rhr = calculate_robust_stats(rhr_history)
            rhr_std = float(statistics.stdev(rhr_history)) if len(rhr_history) >= 2 else None
            # Inversion : une hausse de FC de repos est un stress, donc signe négatif
            z_rhr = -robust_z_score(today.resting_hr_bpm, stats_rhr.median, stats_rhr.mad, fallback_std_dev=rhr_std)
        else:
            z_rhr = -(today.resting_hr_bpm - 60.0) / 8.0
            
        z_rhr = max(-3.0, min(3.0, z_rhr))
        z_scores["resting_hr"] = round(z_rhr, 3)
        rhr_comp = 100.0 / (1.0 + math.exp(-0.9 * z_rhr))
        contributions["resting_hr"] = rhr_comp
        active_weights["resting_hr"] = w.get("resting_hr", 0.25)
        
    # 3. Sommeil (Durée & Score)
    sleep_score_val = today.sleep_score
    sleep_hours_val = today.sleep_duration_hours
    if sleep_score_val is not None:
        contributions["sleep"] = float(max(0.0, min(100.0, sleep_score_val)))
        active_weights["sleep"] = w.get("sleep", 0.25)
    elif sleep_hours_val is not None:
        # Score calculé d'après la durée
        if sleep_hours_val >= 7.5:
            s_comp = min(100.0, 85.0 + (sleep_hours_val - 7.5) * 10.0)
        else:
            s_comp = max(0.0, (sleep_hours_val / 7.5) * 85.0)
        contributions["sleep"] = s_comp
        active_weights["sleep"] = w.get("sleep", 0.25)
        
    # 4. Charge d'activité de la veille (fatigue résiduelle)
    load_history = [b.activity_load for b in clean_history if b.activity_load is not None]
    if today.activity_load is not None and len(load_history) >= 3:
        stats_load = calculate_robust_stats(load_history)
        # Un dépassement extrême de charge (> +2 Z) diminue la récupération immédiate
        z_load = robust_z_score(today.activity_load, stats_load.median, stats_load.mad)
        z_scores["activity_load"] = round(z_load, 3)
        # Z négatif ou proche de 0 = pas de fatigue excessive -> score haut
        if z_load > 1.0:
            load_comp = max(20.0, 100.0 - (z_load - 1.0) * 35.0)
        else:
            load_comp = 95.0
        contributions["activity_load"] = load_comp
        active_weights["activity_load"] = w.get("activity_load", 0.10)
        
    if not active_weights:
        return RecoveryScoreResult(
            score=50.0,
            category="moderate",
            hrv_contribution=None,
            rhr_contribution=None,
            sleep_contribution=None,
            load_contribution=None,
            z_scores_robust={},
            factors_summary="Aucune métrique physiologique disponible aujourd'hui.",
            confidence=0.0
        )
        
    # Combinaison normalisée
    total_w = sum(active_weights.values())
    raw_score = sum(contributions[k] * (active_weights[k] / total_w) for k in active_weights)
    final_score = round(max(0.0, min(100.0, raw_score)), 1)
    
    # Catégorie
    if final_score >= 85.0:
        category = "optimal"
        summary = "Récupération excellente : système nerveux équilibré, prêt pour un effort soutenu."
    elif final_score >= 70.0:
        category = "good"
        summary = "Bonne récupération : biomarqueurs stables dans leurs couloirs habituels."
    elif final_score >= 50.0:
        category = "moderate"
        summary = "Récupération modérée : légère fatigue ou stress physiologique détecté."
    else:
        category = "low"
        summary = "Récupération faible : repos ou activité très légère fortement recommandés."
        
    # Indice de confiance (proportion de poids activés p/r aux poids théoriques)
    theoretical_max_w = sum(w_default.values())
    confidence = round(min(1.0, total_w / theoretical_max_w), 2)
    
    return RecoveryScoreResult(
        score=final_score,
        category=category,
        hrv_contribution=round(contributions.get("hrv", 0.0), 1) if "hrv" in contributions else None,
        rhr_contribution=round(contributions.get("resting_hr", 0.0), 1) if "resting_hr" in contributions else None,
        sleep_contribution=round(contributions.get("sleep", 0.0), 1) if "sleep" in contributions else None,
        load_contribution=round(contributions.get("activity_load", 0.0), 1) if "activity_load" in contributions else None,
        z_scores_robust=z_scores,
        factors_summary=summary,
        confidence=confidence
    )


# ============================================================================
# 4. Détection d'Anomalies Biométriques Multi-variées & Insights
# ============================================================================

def detect_biometric_anomalies(
    today: DailyBiometrics,
    history: Sequence[DailyBiometrics],
    min_history_days: int = 5
) -> List[BiometricAnomaly]:
    """Détecte les anomalies et dérives biométriques significatives avec explicabilité.
    
    Patterns surveillés :
    1. Risque infectieux / État inflammatoire aigu :
       - Chute brutale de la HRV (Z < -1.8)
       - Hausse de la FC de repos (Z > +1.8 ou +7 bpm)
       - Hausse anormale de la température cutanée (écart > +0.5 °C)
    2. Surentraînement & Épuisement (Sympathic / Parasympathic Overreaching) :
       - FC de repos anormalement haute + HRV effondrée sur plusieurs jours
    3. Désaturation nocturne (SpO2 < 92%) :
       - Alerte sur suspicion d'apnée ou hypoxie nocturne
    4. Dette de sommeil aiguë associée à une chute de récupération
    """
    clean_history = [b for b in history if b.date < today.date]
    anomalies: List[BiometricAnomaly] = []
    
    if len(clean_history) < min_history_days:
        return anomalies
        
    # Calcul des baselines
    hrv_vals = [b.hrv_rmssd_ms for b in clean_history if b.hrv_rmssd_ms is not None]
    rhr_vals = [b.resting_hr_bpm for b in clean_history if b.resting_hr_bpm is not None]
    temp_vals = [b.skin_temp_deviation_c for b in clean_history if b.skin_temp_deviation_c is not None]
    
    z_hrv = None
    if today.hrv_rmssd_ms is not None and len(hrv_vals) >= 3:
        st_hrv = calculate_robust_stats(hrv_vals)
        hrv_std = float(statistics.stdev(hrv_vals)) if len(hrv_vals) >= 2 else None
        z_hrv = robust_z_score(today.hrv_rmssd_ms, st_hrv.median, st_hrv.mad, fallback_std_dev=hrv_std)
        
    z_rhr = None
    delta_rhr = 0.0
    if today.resting_hr_bpm is not None and len(rhr_vals) >= 3:
        st_rhr = calculate_robust_stats(rhr_vals)
        rhr_std = float(statistics.stdev(rhr_vals)) if len(rhr_vals) >= 2 else None
        z_rhr = robust_z_score(today.resting_hr_bpm, st_rhr.median, st_rhr.mad, fallback_std_dev=rhr_std)
        delta_rhr = today.resting_hr_bpm - st_rhr.median
        
    # 1. Détection trithérapie de l'infection (HRV chute + RHR grimpe + Température augmente)
    temp_dev = today.skin_temp_deviation_c
    is_fever_trend = temp_dev is not None and temp_dev >= 0.45
    
    if z_hrv is not None and z_rhr is not None:
        if z_hrv <= -1.8 and z_rhr >= 1.8 and is_fever_trend:
            anomalies.append(BiometricAnomaly(
                severity="critical",
                category="illness_risk",
                title="Dérive biométrique aiguë : Signaux précurseurs d'infection",
                explanation=(
                    f"Votre organisme présente une réponse au stress aiguë : chute de la HRV (Z = {z_hrv:.1f}), "
                    f"hausse de la fréquence cardiaque au repos (+{delta_rhr:.1f} bpm, Z = +{z_rhr:.1f}) et élévation "
                    f"de la température cutanée (+{temp_dev:.2f}°C)."
                ),
                actionable_insight=(
                    "Privilégiez le repos complet, une hydratation abondante et évitez toute séance d'entraînement intense."
                ),
                trigger_metrics={
                    "hrv_z": z_hrv,
                    "rhr_z": z_rhr,
                    "skin_temp_deviation_c": temp_dev
                }
            ))
        elif z_hrv <= -2.0 and z_rhr >= 1.5:
            anomalies.append(BiometricAnomaly(
                severity="warning",
                category="overreaching",
                title="Surcharge du système nerveux autonome (SNA)",
                explanation=(
                    f"Forte dominante sympathique : votre HRV est très basse (Z = {z_hrv:.1f}) avec une FC de repos "
                    f"sensiblement augmentée (+{delta_rhr:.1f} bpm)."
                ),
                actionable_insight=(
                    "Une accumulation de fatigue ou un stress important est présent. Réduisez l'intensité des efforts aujourd'hui."
                ),
                trigger_metrics={"hrv_z": z_hrv, "rhr_z": z_rhr}
            ))
            
    # 2. SpO2 anormale
    if today.spo2_pct is not None and today.spo2_pct < 93.0:
        anomalies.append(BiometricAnomaly(
            severity="warning" if today.spo2_pct >= 90.0 else "critical",
            category="respiratory",
            title="Saturation en oxygène (SpO2) sous la normale",
            explanation=f"La saturation moyenne enregistrée cette nuit est de {today.spo2_pct:.1f}% (seuil de référence >= 94%).",
            actionable_insight="Si cette baisse se répète sans encombrement nasal passager, parlez-en à un professionnel de santé.",
            trigger_metrics={"spo2_pct": today.spo2_pct}
        ))
        
    # 3. Chute isolée de HRV majeure
    if z_hrv is not None and z_hrv <= -2.5 and not any(a.category in ("illness_risk", "overreaching") for a in anomalies):
        anomalies.append(BiometricAnomaly(
            severity="warning",
            category="recovery_drop",
            title="Chute inhabituelle de la variabilité cardiaque (HRV)",
            explanation=f"Votre HRV (RMSSD) a chuté significativement (Z = {z_hrv:.1f}) par rapport à votre moyenne habituelle.",
            actionable_insight="Considérez les facteurs récents : dîner tardif, alcool, séance éprouvante ou manque de sommeil.",
            trigger_metrics={"hrv_z": z_hrv, "today_hrv": today.hrv_rmssd_ms}
        ))
        
    return anomalies
