import os
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database


@pytest.fixture
def client_with_db(tmp_path):
    test_db_path = str(tmp_path / "test_bali_291.db")
    test_db = Database(db_path=test_db_path)
    app.state.db_instance = test_db

    import src.app as app_module
    import src.routers.webhooks as wh_module
    old_app_db = app_module.db
    old_engine_db = app_module.nutrition_engine.db
    app_module.db = test_db
    app_module.nutrition_engine.db = test_db
    wh_module._db_instance = test_db

    with TestClient(app) as test_client:
        yield test_client, test_db

    app_module.db = old_app_db
    app_module.nutrition_engine.db = old_engine_db
    wh_module._db_instance = old_app_db


def test_device_sync_with_start_date_and_since_last_sync(client_with_db):
    client, test_db = client_with_db

    # 1. Tester sync avec query parameter start_date
    res1 = client.post("/api/devices/health_connect/sync?start_date=2026-05-01")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] in ["synced", "demo_mode", "success"]
    assert data1["start_date"] == "2026-05-01"
    assert "synced_at" in data1

    # 2. Tester sync avec JSON body start_date et since_last_sync
    res2 = client.post(
        "/api/devices/health_connect/sync",
        json={"start_date": "2026-06-15", "since_last_sync": False}
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["start_date"] == "2026-06-15"
    assert data2["since_last_sync"] is False

    # 3. Tester sync avec since_last_sync=True
    res3 = client.post(
        "/api/devices/health_connect/sync",
        json={"since_last_sync": True}
    )
    assert res3.status_code == 200
    data3 = res3.json()
    assert data3["since_last_sync"] is True
    assert "start_date" in data3


def test_webhook_health_updates_last_sync_at(client_with_db):
    client, test_db = client_with_db

    # Generer token pour health_connect
    tok_resp = client.post("/api/devices/health_connect/token", json={"name": "Health Connect Xiaomi"})
    assert tok_resp.status_code == 200
    token = tok_resp.json()["token"]

    payload = {
        "source": "health_connect",
        "date": "2026-11-22",
        "steps": 6000,
        "weight_kg": 73.8
    }
    res = client.post("/api/webhook/health", json=payload, headers={"X-Webhook-Token": token})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"

    # Verifier que user_devices a bien last_sync_at a jour
    devices = test_db.devices.get_user_devices(user_id=1)
    hc_dev = next((d for d in devices if d.get("device_id") == "health_connect"), None)
    assert hc_dev is not None
    assert hc_dev.get("last_sync_at") is not None
    assert hc_dev.get("sync_status") in ["synced", "online", "connected"]


def test_update_device_sync_status_persists_custom_timestamp(client_with_db):
    client, test_db = client_with_db
    user_id = 1
    device_id = "health_connect"
    custom_ts = "2026-11-20T14:30:00Z"

    # S'assurer que le device existe dans user_devices
    tok_resp = client.post("/api/devices/health_connect/token", json={"name": "Health Connect Device"})
    assert tok_resp.status_code == 200

    updated = test_db.devices.update_device_sync_status(
        device_id=device_id,
        sync_status="synced",
        user_id=user_id,
        synced_at=custom_ts
    )
    assert updated is not None

    devices = test_db.devices.get_user_devices(user_id=user_id)
    hc_dev = next((d for d in devices if d.get("device_id") == device_id), None)
    assert hc_dev is not None
    assert hc_dev.get("last_sync_at") == custom_ts
