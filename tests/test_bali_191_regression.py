"""Tests de régression pour BALI-191 : ingestion pesées serveur, vraie date, multi-pesées, unités et validation."""

import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database
from src.daily_sync import run_daily_sync


@pytest.fixture
def client(tmp_path):
    test_db_path = str(tmp_path / "test_bali_191.db")
    app.state.db_instance = Database(db_path=test_db_path)
    import src.app as app_module
    import src.routers.webhooks as wh_module
    old_app_db = app_module.db
    old_engine_db = app_module.nutrition_engine.db
    app_module.db = app.state.db_instance
    app_module.nutrition_engine.db = app.state.db_instance
    wh_module._db_instance = app.state.db_instance

    with TestClient(app) as test_client:
        yield test_client

    app_module.db = old_app_db
    app_module.nutrition_engine.db = old_engine_db
    wh_module._db_instance = old_app_db


def test_weight_date_at_night_and_measured_at(client):
    """Vérifie qu'une pesée prise à 23h30 la veille (02/11) lors d'un sync le 03/11 apparaît bien au 02/11."""
    tok_resp = client.post("/api/devices/health_connect/token", json={"name": "Health Connect Phone"})
    assert tok_resp.status_code == 200
    token = tok_resp.json()["token"]

    payload = {
        "source": "health_connect",
        "date": "2026-11-03",  # Jour du sync
        "weight_date": "2026-11-02",  # Vraie date de pesée
        "weight_kg": 76.4,
        "weight_external_id": "hc_weight_rec_02nov_2330",
        "measured_at": "2026-11-02T23:30:00Z"
    }

    res = client.post("/api/webhook/health", json=payload, headers={"X-Webhook-Token": token})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    w_res = data["results"]["weight"]
    assert w_res["date"] == "2026-11-02"
    assert w_res["weight_kg"] == 76.4
    assert w_res["external_id"] == "hc_weight_rec_02nov_2330"
    assert w_res["measured_at"] == "2026-11-02T23:30:00Z"


def test_weight_unit_conversions_and_bounds(client):
    """Vérifie la conversion lb / stone vers kg et le rejet HTTP 422 hors bornes 20-300kg."""
    tok_resp = client.post("/api/devices/health_connect/token", json={"name": "Smart Scale"})
    assert tok_resp.status_code == 200
    token = tok_resp.json()["token"]

    # 1. Conversion lb -> kg (165.35 lb ~= 75.0 kg)
    res_lb = client.post(
        "/api/webhook/health",
        json={"source": "health_connect", "weight": 165.35, "unit": "lb", "weight_date": "2026-11-01"},
        headers={"X-Webhook-Token": token}
    )
    assert res_lb.status_code == 200
    assert abs(res_lb.json()["results"]["weight"]["weight_kg"] - 75.0) < 0.1

    # 2. Conversion stone -> kg (11 stone ~= 69.85 kg)
    res_st = client.post(
        "/api/webhook/health",
        json={"source": "health_connect", "weight": 11.0, "unit": "stone", "weight_date": "2026-11-01"},
        headers={"X-Webhook-Token": token}
    )
    assert res_st.status_code == 200
    assert abs(res_st.json()["results"]["weight"]["weight_kg"] - 69.85) < 0.1

    # 3. Poids trop faible < 20 kg -> 422
    res_low = client.post(
        "/api/webhook/health",
        json={"source": "health_connect", "weight_kg": 15.0},
        headers={"X-Webhook-Token": token}
    )
    assert res_low.status_code == 422
    assert "20 et 300 kg" in res_low.json()["detail"]

    # 4. Poids trop élevé > 300 kg -> 422
    res_high = client.post(
        "/api/webhook/health",
        json={"source": "health_connect", "weight_kg": 350.0},
        headers={"X-Webhook-Token": token}
    )
    assert res_high.status_code == 422
    assert "20 et 300 kg" in res_high.json()["detail"]


def test_weight_overwrite_and_multi_pesee_tracing(client):
    """Vérifie le traçage d'écrasement dans raw_ingest en cas de multi-pesées même jour/source."""
    tok_resp = client.post("/api/devices/health_connect/token", json={"name": "Smart Scale"})
    assert tok_resp.status_code == 200
    token = tok_resp.json()["token"]

    # Pesée matin
    res1 = client.post(
        "/api/webhook/health",
        json={
            "source": "health_connect",
            "date": "2026-11-02",
            "weight_kg": 75.0,
            "weight_external_id": "morning_w",
            "measured_at": "2026-11-02T07:00:00Z"
        },
        headers={"X-Webhook-Token": token}
    )
    assert res1.status_code == 200

    # Pesée soir (même date et source, poids et external_id différents)
    res2 = client.post(
        "/api/webhook/health",
        json={
            "source": "health_connect",
            "date": "2026-11-02",
            "weight_kg": 75.8,
            "weight_external_id": "evening_w",
            "measured_at": "2026-11-02T20:00:00Z"
        },
        headers={"X-Webhook-Token": token}
    )
    assert res2.status_code == 200
    assert res2.json()["results"]["weight"]["weight_kg"] == 75.8

    # Vérification audit raw_ingest pour la trace de l'écrasement
    db = app.state.db_instance
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM raw_ingest WHERE source = 'health_connect:overwrite' AND user_id = 1")
        row = cursor.fetchone()
        assert row is not None
        assert "weight_overwritten" in row["payload_json"]


def test_weights_array_support(client):
    """Vérifie l'ingestion d'un lot de pesées dans le champ 'weights' (BALI-191 / BALI-193)."""
    tok_resp = client.post("/api/devices/health_connect/token", json={"name": "Smart Scale"})
    assert tok_resp.status_code == 200
    token = tok_resp.json()["token"]

    payload = {
        "source": "health_connect",
        "date": "2026-11-03",
        "weights": [
            {
                "weight_date": "2026-11-01",
                "weight_kg": 76.0,
                "external_id": "w_batch_1",
                "measured_at": "2026-11-01T08:00:00Z"
            },
            {
                "weight_date": "2026-11-02",
                "weight_kg": 75.8,
                "external_id": "w_batch_2",
                "measured_at": "2026-11-02T08:00:00Z"
            }
        ]
    }

    res = client.post("/api/webhook/health", json=payload, headers={"X-Webhook-Token": token})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"

    db = app.state.db_instance
    weights = db.get_weights(limit=10, user_id=1)
    dates = [w.date.isoformat() for w in weights]
    assert "2026-11-01" in dates
    assert "2026-11-02" in dates


def test_daily_sync_window_7_days(tmp_path):
    """Vérifie que la fenêtre de daily_sync est bien de 7 jours."""
    from unittest.mock import patch
    test_db = Database(db_path=str(tmp_path / "sync.db"))

    captured_start_date = None

    def fake_sync(db, user_id, start_date, today):
        nonlocal captured_start_date
        captured_start_date = start_date
        return True

    with patch.object(test_db, "get_all_users", return_value=[]):
        with patch("src.daily_sync._sync_user_default_env", side_effect=fake_sync):
            run_daily_sync(db=test_db)

    assert captured_start_date is not None
    assert captured_start_date == date.today() - timedelta(days=7)
