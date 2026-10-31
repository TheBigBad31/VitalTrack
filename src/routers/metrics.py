"""Routeur FastAPI pour les endpoints Métriques Biométriques & Visualisations."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from typing import Optional

from src.app import app, db, AuthUser, nutrition_engine, get_current_user
from src.models import DailyMetricsEntry

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/daily-metrics")
def get_daily_metrics_list(
    limit: int = 30,
    source: Optional[str] = None,
    user_id: Optional[int] = None,
    current_user: AuthUser = Depends(get_current_user),
):
    """Retourne la liste des métriques quotidiennes biométriques (pas, sommeil, HRV, etc.)."""
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    metrics = db.get_daily_metrics(limit=limit, source=source, user_id=target_uid)
    return [m.model_dump() for m in metrics]


@router.get("")
def get_biometrics_metrics(
    days: int = 30,
    user_id: Optional[int] = None,
    current_user: AuthUser = Depends(get_current_user),
):
    """Agrégat biométrique complet pour les visualisations."""
    target_uid = current_user.id if user_id is None else user_id
    verify_view_access(target_uid, current_user, database=db)
    profile = db.get_user_profile(user_id=target_uid)
    is_demo = bool(profile.get("is_demo_profile"))

    from src.analytics import BiometricsAnalyticsService

    daily_metrics_list = db.get_daily_metrics(limit=days, user_id=target_uid)
    from src.models import WorkoutEntry, SleepSessionEntry, DailyBiometrics

    workouts_list = db.get_workouts(limit=days, user_id=target_uid)
    sleep_sessions_list = db.get_sleep_sessions(limit=days, user_id=target_uid)

    # Convertir en DailyBiometrics pour le moteur mathématique
    bio_history = []
    weights_list = db.get_weights(limit=days, user_id=target_uid, exclude_simulation=not is_demo)
    activities_list = db.get_activities(limit=days, user_id=target_uid, exclude_simulation=not is_demo)

    weights_by_date = {w.date.isoformat(): w.weight_kg for w in weights_list}
    acts_by_date = {a.date.isoformat(): a for a in activities_list}

    for m in daily_metrics_list:
        d_str = m.date.isoformat()
        w_val = weights_by_date.get(d_str)
        act_val = acts_by_date.get(d_str)
        act_load = m.active_calories_kcal or (act_val.active_calories_kcal if act_val else None)

        bio_history.append(DailyBiometrics(
            date=m.date,
            hrv_rmssd_ms=m.hrv_rmssd_ms or (act_val.hrv_ms if act_val else None),
            resting_hr_bpm=float(m.resting_hr_bpm) if m.resting_hr_bpm is not None else (float(act_val.resting_hr_bpm) if act_val and act_val.resting_hr_bpm else None),
            sleep_score=float(m.sleep_score) if m.sleep_score is not None else (float(act_val.sleep_score) if act_val and act_val.sleep_score else None),
            spo2_pct=m.spo2_pct,
            skin_temp_deviation_c=m.skin_temperature_c,
            weight_kg=w_val,
            activity_load=act_load
        ))

    analytics_svc = BiometricsAnalyticsService(target_sleep_hours=float(profile.get("target_sleep_hours", 8.0) or 8.0))

    today_bio = bio_history[-1] if bio_history else None
    prior_history = bio_history[:-1] if len(bio_history) > 1 else bio_history

    recovery_data = None
    corridors_data = {}
    anomalies_data = []

    if today_bio and prior_history:
        rec_res = analytics_svc.analyze_recovery(today_bio, prior_history)
        recovery_data = {
            "score": round(rec_res.score, 1),
            "category": rec_res.category,
            "confidence": round(rec_res.confidence, 2),
            "factors_summary": rec_res.factors_summary,
            "hrv_contribution": rec_res.hrv_contribution,
            "rhr_contribution": rec_res.rhr_contribution,
            "sleep_contribution": rec_res.sleep_contribution,
            "load_contribution": rec_res.load_contribution
        }

        corrs = analytics_svc.compute_all_corridors(today_bio, prior_history)
        for k, c in corrs.items():
            corridors_data[k] = {
                "metric_name": c.metric_name,
                "median": round(c.median, 2),
                "lower_bound": round(c.lower_bound, 2),
                "upper_bound": round(c.upper_bound, 2),
                "p15": round(c.p15, 2),
                "p85": round(c.p85, 2),
                "current_value": round(c.current_value, 2) if c.current_value is not None else None,
                "is_in_corridor": c.is_in_corridor
            }

        anomalies_res = analytics_svc.detect_anomalies(today_bio, prior_history)
        anomalies_data = [
            {
                "severity": a.severity,
                "category": a.category,
                "title": a.title,
                "explanation": a.explanation,
                "actionable_insight": a.actionable_insight,
                "trigger_metrics": a.trigger_metrics
            }
            for a in anomalies_res
        ]
    elif today_bio:
        recovery_data = {
            "score": today_bio.sleep_score or 75.0,
            "category": "good",
            "confidence": 0.5,
            "factors_summary": "Données initiales enregistrées.",
            "hrv_contribution": 0.0,
            "rhr_contribution": 0.0,
            "sleep_contribution": 0.0,
            "load_contribution": 0.0
        }

    # Sommeil & Hypnogramme de la dernière session
    latest_sleep = sleep_sessions_list[-1] if sleep_sessions_list else None
    sleep_analysis = None
    if latest_sleep:
        total_h = (latest_sleep.duration_minutes or 0) / 60.0
        eff = latest_sleep.efficiency_pct or 85.0
        deep_h = (latest_sleep.deep_minutes or 0) / 60.0
        rem_h = (latest_sleep.rem_minutes or 0) / 60.0
        light_h = (latest_sleep.light_minutes or 0) / 60.0
        awake_h = (latest_sleep.awake_minutes or 0) / 60.0

        sleep_history_tuples = [
            (s.date, (s.duration_minutes or 0) / 60.0, s.efficiency_pct)
            for s in sleep_sessions_list
        ]
        curr_daily_sleep = DailyBiometrics(
            date=latest_sleep.date,
            sleep_duration_hours=total_h,
            sleep_efficiency_pct=eff,
            deep_sleep_hours=deep_h,
            rem_sleep_hours=rem_h,
            light_sleep_hours=light_h,
            awake_hours=awake_h
        )
        analyzed_sleep = analytics_svc.analyze_sleep(curr_daily_sleep, sleep_history_tuples)
        arch = analyzed_sleep["architecture"]
        debt = analyzed_sleep["debt"]

        sleep_analysis = {
            "latest_session": {
                "id": latest_sleep.id,
                "date": latest_sleep.date.isoformat(),
                "start_time": latest_sleep.start_time,
                "end_time": latest_sleep.end_time,
                "duration_minutes": latest_sleep.duration_minutes,
                "efficiency_pct": latest_sleep.efficiency_pct,
                "sleep_score": latest_sleep.sleep_score,
                "deep_minutes": latest_sleep.deep_minutes,
                "light_minutes": latest_sleep.light_minutes,
                "rem_minutes": latest_sleep.rem_minutes,
                "awake_minutes": latest_sleep.awake_minutes,
                "stages": [
                    {
                        "stage": st.stage,
                        "start_time": st.start_time,
                        "end_time": st.end_time,
                        "duration_seconds": st.duration_seconds
                    }
                    for st in latest_sleep.stages
                ]
            },
            "architecture": {
                "score": round(arch.architecture_score, 1),
                "is_restorative": arch.is_restorative,
                "deep_pct": round(arch.deep_sleep_pct, 1),
                "rem_pct": round(arch.rem_sleep_pct, 1),
                "light_pct": round(arch.light_sleep_pct, 1),
                "awake_pct": round(arch.awake_pct, 1),
                "warnings": list(arch.warnings)
            },
            "debt": {
                "target_hours": debt.target_sleep_hours,
                "cumulative_debt_hours": round(debt.cumulative_debt_hours, 2),
                "debt_level": debt.debt_level,
                "description": debt.description
            }
        }

    # Série temporelle Trends (RHR & HRV)
    trends = []
    for m in daily_metrics_list:
        d_iso = m.date.isoformat()
        act = acts_by_date.get(d_iso)
        rhr = m.resting_hr_bpm if m.resting_hr_bpm is not None else (act.resting_hr_bpm if act else None)
        hrv = m.hrv_rmssd_ms if m.hrv_rmssd_ms is not None else (act.hrv_ms if act else None)
        trends.append({
            "date": d_iso,
            "resting_hr_bpm": rhr,
            "hrv_rmssd_ms": hrv,
            "sleep_score": m.sleep_score or (act.sleep_score if act else None),
            "recovery_score": m.recovery_score
        })

    # Intraday FC 24h (données simplifiées)
    intraday_hr = []

    # Séances / Workouts
    workouts_data = [w.model_dump() for w in workouts_list]

    has_real_data = bool(
        daily_metrics_list or workouts_list or sleep_sessions_list or
        intraday_hr_samples or (weights_list and not is_demo) or (activities_list and not is_demo)
    )

    return {
        "status": "success",
        "has_real_data": has_real_data,
        "is_demo_profile": is_demo,
        "rings": {
            "steps": {"current": 0, "target": 10000, "pct": 0.0},
            "active_calories": {"current": 0.0, "target": 500.0, "pct": 0.0},
            "sleep_recovery": {"current_sleep_hours": 0.0, "target_sleep_hours": 8.0, "recovery_score": None, "pct": 0.0}
        },
        "recovery": recovery_data,
        "corridors": corridors_data,
        "anomalies": anomalies_data,
        "sleep": sleep_analysis,
        "trends": trends,
        "intraday_hr": intraday_hr,
        "workouts": workouts_data,
        "correlations": {
            "weight_vs_calories": [],
            "sleep_vs_hrv": []
        },
        "heatmap": [],
        "generated_at": "2026-10-31T00:00:00Z"
    }