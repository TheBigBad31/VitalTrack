# tests/test_biometrics_visualizations_palier3.py
# -*- coding: utf-8 -*-
"""Tests unitaires et d'intégration pour les visualisations biométriques avancées (Ticket 5 - Palier 3)."""

from datetime import date, datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database
from src.models import (
    DailyMetricsEntry,
    WorkoutEntry,
    SleepSessionEntry,
    SleepStageEntry,
    IntradaySampleEntry,
    WeightEntry,
    ActivityEntry
)


@pytest.fixture
def client():
    return TestClient(app)


def test_api_metrics_empty_state_contract(client):
    """Vérifie le contrat de l'API /api/metrics en l'absence de données réelles (état vide propre)."""
    resp = client.get("/api/metrics?days=30")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "success"
    assert "has_real_data" in data
    assert "rings" in data
    assert "steps" in data["rings"]
    assert "active_calories" in data["rings"]
    assert "sleep_recovery" in data["rings"]

    assert "trends" in data
    assert "intraday_hr" in data
    assert "workouts" in data
    assert "correlations" in data
    assert "weight_vs_calories" in data["correlations"]
    assert "sleep_vs_hrv" in data["correlations"]
    assert "heatmap" in data
    assert len(data["heatmap"]) == 30


def test_api_metrics_with_real_biometrics(client):
    """Vérifie l'agrégation complète avec données réelles (RingConn Gen 3, Withings, Workouts)."""
    from src.app import db
    user_id = 1
    today = date.today()

    # 1. Insérer un historique de métriques journalières (30j)
    for i in range(14):
        d_val = today - timedelta(days=14 - i)
        m_entry = DailyMetricsEntry(
            user_id=user_id,
            date=d_val,
            source="ringconn",
            steps=8000 + i * 200,
            active_calories_kcal=400.0 + i * 15.0,
            resting_hr_bpm=58 - (i % 3),
            hrv_rmssd_ms=52.0 + (i % 5),
            sleep_score=80 + (i % 8),
            recovery_score=78 + (i % 10)
        )
        db.insert_daily_metric(m_entry, user_id=user_id)

    # 2. Insérer une session de sommeil avec phases détaillées
    sleep_sess = SleepSessionEntry(
        user_id=user_id,
        source="ringconn",
        external_id="ringconn_sleep_test_101",
        date=today,
        start_time=f"{today.isoformat()}T23:00:00Z",
        end_time=f"{today.isoformat()}T07:00:00Z",
        duration_minutes=480,
        efficiency_pct=91.5,
        sleep_score=86,
        deep_minutes=110,
        rem_minutes=95,
        light_minutes=240,
        awake_minutes=35,
        stages=[
            SleepStageEntry(stage="deep", start_time="23:30", end_time="01:20", duration_seconds=6600),
            SleepStageEntry(stage="rem", start_time="01:20", end_time="02:55", duration_seconds=5700),
            SleepStageEntry(stage="light", start_time="02:55", end_time="06:55", duration_seconds=14400),
            SleepStageEntry(stage="awake", start_time="06:55", end_time="07:00", duration_seconds=300)
        ]
    )
    db.insert_sleep_session(sleep_sess, user_id=user_id)

    # 3. Insérer des échantillons intraday FC
    samples = [
        IntradaySampleEntry(source="ringconn", metric_type="hr", timestamp=f"{today.isoformat()}T08:{m:02d}:00Z", value=62.0 + (m % 10), unit="bpm")
        for m in range(0, 60, 5)
    ]
    db.insert_intraday_samples(samples, user_id=user_id)

    # 4. Insérer une séance sportive (workout)
    workout = WorkoutEntry(
        user_id=user_id,
        source="strava",
        external_id="strava_run_999",
        workout_type="running",
        start_time=f"{today.isoformat()}T18:00:00Z",
        end_time=f"{today.isoformat()}T18:45:00Z",
        duration_minutes=45,
        calories_kcal=480.0,
        avg_hr_bpm=148,
        max_hr_bpm=168,
        distance_meters=7500.0
    )
    db.insert_workout(workout, user_id=user_id)

    # Appel endpoint /api/metrics
    resp = client.get("/api/metrics?days=30")
    assert resp.status_code == 200
    res_data = resp.json()

    assert res_data["has_real_data"] is True
    # Anneaux
    rings = res_data["rings"]
    assert rings["steps"]["target"] > 0
    assert rings["active_calories"]["target"] > 0

    # Récupération & Sommeil
    assert res_data["recovery"] is not None
    assert "score" in res_data["recovery"]
    assert "category" in res_data["recovery"]

    assert res_data["sleep"] is not None
    assert len(res_data["sleep"]["latest_session"]["stages"]) == 4
    assert res_data["sleep"]["architecture"]["score"] > 0

    # Tendances & Intraday
    assert len(res_data["intraday_hr"]) >= 12
    assert len(res_data["trends"]) >= 14

    # Workouts
    assert len(res_data["workouts"]) >= 1
    assert res_data["workouts"][0]["workout_type"] == "running"

    # Heatmap
    assert any(h["has_workout"] for h in res_data["heatmap"])
