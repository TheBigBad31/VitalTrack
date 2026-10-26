"""Tests complets pour l'ingestion Webhook enrichie et la passerelle Android Health Connect / RingConn Gen 3."""

import os
import pytest
from datetime import date, datetime, timezone
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database


@pytest.fixture
def client(tmp_path):
    test_db_path = str(tmp_path / "test_webhook_bridge.db")
    app.state.db_instance = Database(db_path=test_db_path)
    # Remplacer temporairement l'instance globale
    import src.app as app_module
    import src.routers.webhooks as wh_module
    old_app_db = app_module.db
    app_module.db = app.state.db_instance
    wh_module._db_instance = app.state.db_instance
    
    with TestClient(app) as test_client:
        yield test_client
    
    app_module.db = old_app_db
    wh_module._db_instance = old_app_db


def test_device_token_generation_and_strict_auth(client):
    """Vérifie la génération d'un token individuel et le rejet des requêtes non autorisées (401)."""
    # 1. Requête sans token -> Rejet 401
    resp = client.post("/api/webhook/health", json={"steps": 5000})
    assert resp.status_code == 401
    assert "Jeton d'authentification manquant" in resp.json()["detail"]

    # 2. Requête avec token bidon -> Rejet 401
    resp = client.post("/api/webhook/health", json={"steps": 5000}, headers={"X-Webhook-Token": "fake_invalid_token"})
    assert resp.status_code == 401
    assert "Token webhook invalide" in resp.json()["detail"]

    # 3. Génération d'un token individuel pour health_connect
    tok_resp = client.post("/api/devices/health_connect/token", json={"name": "Xiaomi HyperOS Bridge"})
    assert tok_resp.status_code == 200
    tok_data = tok_resp.json()
    token = tok_data["token"]
    assert token.startswith("vt_health_connect_")

    # 4. Requête avec le token généré via Header X-Webhook-Token -> Succès 200
    payload = {
        "source": "health_connect",
        "date": "2026-10-25",
        "steps": 10500,
        "active_calories_kcal": 420.0,
        "resting_hr_bpm": 58,
        "hrv_ms": 62.0,
        "sleep_score": 88
    }
    ok_resp = client.post("/api/webhook/health", json=payload, headers={"X-Webhook-Token": token})
    assert ok_resp.status_code == 200
    res_json = ok_resp.json()
    assert res_json["status"] == "success"
    assert res_json["device_id"] == "health_connect"
    assert res_json["results"]["activity"]["steps"] == 10500
    assert res_json["results"]["daily_metric"]["resting_hr_bpm"] == 58


def test_ringconn_multi_metric_payload_ingestion(client):
    """Vérifie l'ingestion multi-métrique complète RingConn Gen 3 / Health Connect :
    sommeil et phases, FC intraday, HRV, SpO2, température cutanée, séances d'entraînement."""
    # Générer le token RingConn
    tok_resp = client.post("/api/devices/ringconn/token", json={"name": "RingConn Gen 3 Ring"})
    assert tok_resp.status_code == 200
    token = tok_resp.json()["token"]

    full_payload = {
        "source": "ringconn",
        "date": "2026-10-25",
        "external_id": "rc_sample_sync_1001",
        "steps": 11450,
        "active_calories_kcal": 485.0,
        "total_burned_kcal": 2250.0,
        "resting_hr_bpm": 56,
        "hrv_rmssd_ms": 65.5,
        "hrv_sdnn_ms": 72.0,
        "spo2_pct": 98.5,
        "skin_temperature_c": 36.2,
        "sleep_score": 89,
        "recovery_score": 92,
        "weight_kg": 78.5,
        "body_fat_pct": 18.2,
        "muscle_mass_kg": 39.1,
        "water_pct": 58.0,
        "sleep_sessions": [
            {
                "external_id": "rc_sleep_night_1",
                "start_time": "2026-10-24T23:00:00Z",
                "end_time": "2026-10-25T07:15:00Z",
                "duration_minutes": 495,
                "deep_minutes": 110,
                "light_minutes": 240,
                "rem_minutes": 105,
                "awake_minutes": 40,
                "sleep_score": 89,
                "efficiency_pct": 92.0,
                "stages": [
                    {
                        "stage": "light",
                        "start_time": "2026-10-24T23:00:00Z",
                        "end_time": "2026-10-24T23:45:00Z",
                        "duration_seconds": 2700
                    },
                    {
                        "stage": "deep",
                        "start_time": "2026-10-24T23:45:00Z",
                        "end_time": "2026-10-25T01:15:00Z",
                        "duration_seconds": 5400
                    },
                    {
                        "stage": "rem",
                        "start_time": "2026-10-25T01:15:00Z",
                        "end_time": "2026-10-25T02:30:00Z",
                        "duration_seconds": 4500
                    }
                ]
            }
        ],
        "workouts": [
            {
                "external_id": "rc_workout_run_1",
                "workout_type": "running",
                "start_time": "2026-10-25T08:00:00Z",
                "end_time": "2026-10-25T08:45:00Z",
                "duration_minutes": 45,
                "calories_kcal": 410.0,
                "avg_hr_bpm": 148,
                "max_hr_bpm": 168,
                "distance_meters": 7500.0
            }
        ],
        "intraday_samples": [
            {
                "metric_type": "hr",
                "timestamp": "2026-10-25T08:15:00Z",
                "value": 152.0,
                "unit": "bpm"
            },
            {
                "metric_type": "spo2",
                "timestamp": "2026-10-25T04:30:00Z",
                "value": 98.0,
                "unit": "%"
            }
        ],
        "hydration_ml": 750.0
    }

    resp = client.post("/api/webhooks/ringconn", json=full_payload, headers={"X-Webhook-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["device_id"] == "ringconn"

    ing = data["results"]
    assert ing["weight"]["weight_kg"] == 78.5
    assert ing["activity"]["steps"] == 11450
    assert ing["daily_metric"]["hrv_rmssd_ms"] == 65.5
    assert ing["daily_metric"]["spo2_pct"] == 98.5
    assert ing["daily_metric"]["skin_temperature_c"] == 36.2
    assert ing["sleep_session"]["sleep_score"] == 89
    assert len(ing["sleep_session"]["stages"]) == 3
    assert len(ing["workouts"]) == 1
    assert ing["workouts"][0]["workout_type"] == "running"
    assert ing["intraday_samples_count"] == 2
    assert ing["hydration"]["volume_ml"] == 750.0


def test_batch_incremental_ingestion_and_idempotency(client):
    """Vérifie l'ingestion d'un lot incrémental (batch JSON) et la déduplication idempotente par external_id."""
    tok_resp = client.post("/api/devices/health_connect/token", json={"name": "Batch Sync"})
    token = tok_resp.json()["token"]

    batch_payload = [
        {
            "external_id": "hc_batch_entry_1",
            "source": "health_connect",
            "date": "2026-10-24",
            "steps": 9200,
            "resting_hr_bpm": 60,
            "sleep_score": 82
        },
        {
            "external_id": "hc_batch_entry_2",
            "source": "health_connect",
            "date": "2026-10-25",
            "steps": 12800,
            "resting_hr_bpm": 56,
            "sleep_score": 90
        }
    ]

    # Premier envoi du lot
    resp1 = client.post("/api/webhooks/health-connect", json=batch_payload, headers={"X-Webhook-Token": token})
    assert resp1.status_code == 200
    res1 = resp1.json()
    assert res1["is_batch"] is True
    assert res1["count"] == 2

    # Deuxième envoi identique (ré-émission / reprise sur erreur) -> Doit réussir de façon idempotente
    resp2 = client.post("/api/webhooks/health-connect", json=batch_payload, headers={"X-Webhook-Token": token})
    assert resp2.status_code == 200
    res2 = resp2.json()
    assert res2["is_batch"] is True
    assert res2["count"] == 2


def test_auth_token_via_query_and_payload(client):
    """Vérifie que l'authentification par token fonctionne également via query param ou dans le body JSON."""
    tok_resp = client.post("/api/devices/ringconn/token", json={"name": "RingConn Test"})
    token = tok_resp.json()["token"]

    # 1. Via Query Param ?token=...
    resp_query = client.post(
        f"/api/webhook/health?token={token}",
        json={"source": "ringconn", "date": "2026-10-25", "steps": 7000}
    )
    assert resp_query.status_code == 200

    # 2. Via Payload JSON { "token": "..." }
    resp_body = client.post(
        "/api/webhook/health",
        json={"source": "ringconn", "token": token, "date": "2026-10-25", "steps": 7500}
    )
    assert resp_body.status_code == 200


def test_health_bridge_full_extended_payload_ingestion(client):
    """Vérifie l'ingestion de la charge complète envoyée par HealthSyncWorker enrichi :
    - Composition Withings : body_fat_pct, muscle_mass_kg, bone_mass_kg, weight_kg
    - Biométrie RingConn : hrv_ms, resting_hr_bpm, spo2_pct, workouts, sleep_sessions
    - Catch-up 7 jours flag is_catchup
    """
    tok_resp = client.post("/api/devices/health_connect/token", json={"name": "Xiaomi Bridge Full Payload"})
    assert tok_resp.status_code == 200
    token = tok_resp.json()["token"]

    extended_payload = {
        "source": "health_connect",
        "synced_at": "2026-10-26T08:30:00Z",
        "date": "2026-10-26",
        "is_catchup": True,
        "steps": 8500,
        "active_calories_kcal": 350.0,
        "weight_kg": 77.2,
        "weight_external_id": "hc_weight_uuid_101",
        "body_fat_pct": 17.8,
        "muscle_mass_kg": 39.5,
        "bone_mass_kg": 3.2,
        "hrv_ms": 68.0,
        "hrv_rmssd_ms": 68.0,
        "resting_hr_bpm": 54,
        "spo2_pct": 99.0,
        "sleep_sessions": [
            {
                "id": "hc_sleep_uuid_101",
                "external_id": "hc_sleep_uuid_101",
                "date": "2026-10-26",
                "start_time": "2026-10-25T23:30:00Z",
                "end_time": "2026-10-26T07:00:00Z",
                "duration_minutes": 450,
                "deep_minutes": 100,
                "light_minutes": 230,
                "rem_minutes": 90,
                "awake_minutes": 30,
                "stages": [
                    {
                        "stage": "light",
                        "start_time": "2026-10-25T23:30:00Z",
                        "end_time": "2026-10-26T00:30:00Z",
                        "duration_seconds": 3600
                    },
                    {
                        "stage": "deep",
                        "start_time": "2026-10-26T00:30:00Z",
                        "end_time": "2026-10-26T02:10:00Z",
                        "duration_seconds": 6000
                    }
                ]
            }
        ],
        "workouts": [
            {
                "id": "hc_workout_uuid_101",
                "external_id": "hc_workout_uuid_101",
                "workout_type": "running",
                "start_time": "2026-10-26T07:15:00Z",
                "end_time": "2026-10-26T07:45:00Z",
                "duration_minutes": 30,
                "calories_kcal": 280.0,
                "notes": "Course matinale"
            }
        ],
        "intraday_samples": [
            {
                "metric_type": "hr",
                "timestamp": "2026-10-26T07:30:00Z",
                "value": 145.0,
                "unit": "bpm"
            }
        ]
    }

    resp = client.post("/api/webhook/health", json=extended_payload, headers={"X-Webhook-Token": token})
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["status"] == "success"

    ing = res_data["results"]
    # 1. Poids et composition Withings
    assert ing["weight"]["weight_kg"] == 77.2
    assert ing["weight"]["body_fat_pct"] == 17.8
    assert ing["weight"]["muscle_mass_kg"] == 39.5
    assert ing["weight"]["source"] == "health_connect"

    # 2. Métriques quotidiennes RingConn (HRV, FC repos, SpO2)
    assert ing["daily_metric"]["resting_hr_bpm"] == 54
    assert ing["daily_metric"]["hrv_rmssd_ms"] == 68.0
    assert ing["daily_metric"]["spo2_pct"] == 99.0
    assert ing["daily_metric"]["steps"] == 8500
    assert ing["daily_metric"]["active_calories_kcal"] == 350.0

    # 3. Sommeil et phases
    assert ing["sleep_session"]["duration_minutes"] == 450
    assert ing["sleep_session"]["deep_minutes"] == 100
    assert len(ing["sleep_session"]["stages"]) == 2

    # 4. Workouts
    assert len(ing["workouts"]) == 1
    assert ing["workouts"][0]["workout_type"] == "running"
    assert ing["workouts"][0]["duration_minutes"] == 30

    # 5. Échantillons FC intraday
    assert ing["intraday_samples_count"] == 1

def test_download_android_bridge_endpoint(client, tmp_path):
    """Vérifie le comportement de l'endpoint de téléchargement direct de l'APK."""
    import src.app as app_module
    
    # 1. Quand l'APK n'est pas présent en local, redirige (307) vers la release GitHub
    resp_redirect = client.get("/api/downloads/android-bridge", follow_redirects=False)
    assert resp_redirect.status_code == 307
    assert resp_redirect.headers["location"] == app_module.GITHUB_LATEST_RELEASE_APK_URL

    # 2. Quand un fichier APK est présent dans static/downloads/vitaltrack-health-bridge.apk
    downloads_dir = os.path.join(app_module.STATIC_DIR, "downloads")
    os.makedirs(downloads_dir, exist_ok=True)
    fake_apk_path = os.path.join(downloads_dir, "vitaltrack-health-bridge.apk")
    
    try:
        with open(fake_apk_path, "wb") as f:
            f.write(b"PKfake_apk_binary_content_vitaltrack")
        
        resp_file = client.get("/api/downloads/android-bridge")
        assert resp_file.status_code == 200
        assert resp_file.headers["content-type"] == "application/vnd.android.package-archive"
        assert resp_file.content == b"PKfake_apk_binary_content_vitaltrack"
    finally:
        if os.path.exists(fake_apk_path):
            os.remove(fake_apk_path)
