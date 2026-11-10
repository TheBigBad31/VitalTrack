"""Tests unitaires et d'intégration pour le endpoint GET /api/devices/data-map (BALI-197)."""

import pytest
from datetime import date, timedelta, datetime, timezone
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database
from src.models import (
    DailyMetricsEntry,
    HydrationLogEntry,
    IntradaySampleEntry,
    SleepSessionEntry,
    WeightEntry,
    WorkoutEntry,
)


@pytest.fixture
def client(tmp_path):
    test_db_path = str(tmp_path / "test_data_map.db")
    app.state.db_instance = Database(db_path=test_db_path)
    
    import src.app as app_module
    import src.routers.devices as dev_module
    old_app_db = app_module.db
    old_engine_db = app_module.nutrition_engine.db
    app_module.db = app.state.db_instance
    app_module.nutrition_engine.db = app.state.db_instance
    dev_module._db_instance = app.state.db_instance
    
    with TestClient(app) as test_client:
        yield test_client
    
    app_module.db = old_app_db
    app_module.nutrition_engine.db = old_engine_db
    dev_module._db_instance = old_app_db


def test_devices_data_map_empty(client):
    """Vérifie le contrat initial sans données enregistrées."""
    resp = client.get("/api/devices/data-map")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "sources" in data
    assert "metrics" in data
    assert "recent_weights" in data
    assert "summary" in data
    assert data["summary"]["total_metrics"] == 17
    assert len(data["metrics"]) == 17


def test_devices_data_map_with_multi_source_fixtures(client):
    """Vérifie la cartographie complète avec données multi-sources (Withings vs Santé Connect)."""
    db = app.state.db_instance
    today = date.today()
    d1 = today - timedelta(days=2)
    d2 = today - timedelta(days=1)

    # 1. Ajouter deux pesées récentes de sources différentes (Withings & Santé Connect)
    w1 = WeightEntry(
        date=d1,
        weight_kg=79.2,
        body_fat_pct=18.5,
        muscle_mass_kg=39.0,
        source="withings",
        measured_at=f"{d1.isoformat()}T07:15:00Z"
    )
    w2 = WeightEntry(
        date=d2,
        weight_kg=78.7,
        body_fat_pct=18.1,
        muscle_mass_kg=39.3,
        source="health_connect",
        measured_at=f"{d2.isoformat()}T08:30:00Z"
    )
    db.insert_weight(w1, user_id=1)
    db.insert_weight(w2, user_id=1)

    # 2. Ajouter métriques journalières (incluant métriques non affichées dans l'UI)
    dm = DailyMetricsEntry(
        date=d2,
        source="health_connect",
        steps=9200,
        active_calories_kcal=410.0,
        resting_hr_bpm=57,
        hrv_rmssd_ms=64.0,
        hrv_sdnn_ms=71.0,
        spo2_pct=98.5,
        skin_temperature_c=36.4
    )
    db.insert_daily_metric(dm, user_id=1)

    # 3. Ajouter hydratation (non affichée dans l'UI)
    hy = HydrationLogEntry(
        date=d2,
        timestamp=f"{d2.isoformat()}T14:00:00Z",
        volume_ml=1750.0,
        source="health_connect"
    )
    db.insert_hydration_log(hy, user_id=1)

    # 4. Ajouter séance de sport et sommeil
    sl = SleepSessionEntry(
        date=d2,
        source="health_connect",
        start_time=f"{d1.isoformat()}T23:15:00Z",
        end_time=f"{d2.isoformat()}T07:00:00Z",
        duration_minutes=465,
        sleep_score=86
    )
    db.insert_sleep_session(sl, user_id=1)

    # 5. Connecter les devices
    db.update_user_device(device_id="health_connect", name="Xiaomi HyperOS", device_type="hub", connected=True, user_id=1)
    db.update_user_device(device_id="withings", name="Withings Body Scan", device_type="scale", connected=True, user_id=1)

    # Appel endpoint
    resp = client.get("/api/devices/data-map")
    assert resp.status_code == 200
    res = resp.json()

    # Vérification diagnostic pesées (Sébastien)
    recent = res["recent_weights"]
    assert len(recent) == 2
    assert recent[0]["weight_kg"] == 78.7
    assert recent[0]["source"] == "health_connect"
    assert "Santé Connect" in recent[0]["source_label"]
    assert recent[1]["weight_kg"] == 79.2
    assert recent[1]["source"] == "withings"
    assert "Withings" in recent[1]["source_label"]

    # Vérification statut métriques
    metric_map = {m["key"]: m for m in res["metrics"]}

    # Poids & Pas doivent être ingested_and_displayed
    assert metric_map["weight"]["status"] == "ingested_and_displayed"
    assert metric_map["weight"]["rendered_in_ui"] is True
    assert metric_map["weight"]["points_7d_count"] == 2

    assert metric_map["steps"]["status"] == "ingested_and_displayed"
    assert metric_map["steps"]["rendered_in_ui"] is True
    assert metric_map["steps"]["last_point"]["value"] == "9200 pas"

    # SpO2, Skin Temp, Hydratation, HRV SDNN doivent être ingested_not_displayed (colorés en rouge)
    assert metric_map["spo2"]["status"] == "ingested_not_displayed"
    assert metric_map["spo2"]["rendered_in_ui"] is False
    assert metric_map["spo2"]["last_point"]["value"] == "98.5 %"

    assert metric_map["skin_temperature"]["status"] == "ingested_not_displayed"
    assert metric_map["skin_temperature"]["rendered_in_ui"] is False
    assert metric_map["skin_temperature"]["last_point"]["value"] == "36.4 °C"

    assert metric_map["hydration"]["status"] == "ingested_not_displayed"
    assert metric_map["hydration"]["rendered_in_ui"] is False
    assert metric_map["hydration"]["last_point"]["value"] == "1750.0 ml"

    assert metric_map["hrv_sdnn"]["status"] == "ingested_not_displayed"
    assert metric_map["hrv_sdnn"]["rendered_in_ui"] is False

    # Résumé
    summary = res["summary"]
    assert summary["ingested_not_displayed"] >= 5
    assert summary["ingested_and_displayed"] >= 2
