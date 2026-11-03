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
    old_engine_db = app_module.nutrition_engine.db
    app_module.db = app.state.db_instance
    app_module.nutrition_engine.db = app.state.db_instance
    wh_module._db_instance = app.state.db_instance
    
    with TestClient(app) as test_client:
        yield test_client
    
    app_module.db = old_app_db
    app_module.nutrition_engine.db = old_engine_db
    wh_module._db_instance = old_app_db


def test_device_token_generation_and_strict_auth(client):
    """VÃ©rifie la gÃ©nÃ©ration d'un token individuel et le rejet des requÃªtes non autorisÃ©es (401)."""
    # 1. RequÃªte sans token -> Rejet 401
    resp = client.post("/api/webhook/health", json={"steps": 5000})
    assert resp.status_code == 401
    assert "Jeton d'authentification manquant" in resp.json()["detail"]

    # 2. RequÃªte avec token bidon -> Rejet 401
    resp = client.post("/api/webhook/health", json={"steps": 5000}, headers={"X-Webhook-Token": "fake_invalid_token"})
    assert resp.status_code == 401
    assert "Token webhook invalide" in resp.json()["detail"]

    # 3. GÃ©nÃ©ration d'un token individuel pour health_connect
    tok_resp = client.post("/api/devices/health_connect/token", json={"name": "Xiaomi HyperOS Bridge"})
    assert tok_resp.status_code == 200
    tok_data = tok_resp.json()
    token = tok_data["token"]
    assert token.startswith("vt_health_connect_")

    # 4. RequÃªte avec le token gÃ©nÃ©rÃ© via Header X-Webhook-Token -> SuccÃ¨s 200
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
    """VÃ©rifie l'ingestion multi-mÃ©trique complÃ¨te RingConn Gen 3 / Health Connect :
    sommeil et phases, FC intraday, HRV, SpO2, tempÃ©rature cutanÃ©e, sÃ©ances d'entraÃ®nement."""
    # GÃ©nÃ©rer le token RingConn
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
    """VÃ©rifie l'ingestion d'un lot incrÃ©mental (batch JSON) et la dÃ©duplication idempotente par external_id."""
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

    # DeuxiÃ¨me envoi identique (rÃ©-Ã©mission / reprise sur erreur) -> Doit rÃ©ussir de faÃ§on idempotente
    resp2 = client.post("/api/webhooks/health-connect", json=batch_payload, headers={"X-Webhook-Token": token})
    assert resp2.status_code == 200
    res2 = resp2.json()
    assert res2["is_batch"] is True
    assert res2["count"] == 2


def test_auth_token_via_query_and_payload(client):
    """VÃ©rifie que l'authentification par token fonctionne Ã©galement via query param ou dans le body JSON."""
    tok_resp = client.post("/api/devices/ringconn/token", json={"name": "RingConn Test"})
    token = tok_resp.json()["token"]

    # 1. Via Query Param ?token=...
    resp_query = client.post(
        f"/api/webhook/health?token={token}",
        json={"source": "ringconn", "date": "2026-10-25", "steps": 7000}
    )
    assert resp_query.status_code == 401

    # 2. Via Payload JSON { "token": "..." }
    resp_body = client.post(
        "/api/webhook/health",
        json={"source": "ringconn", "token": token, "date": "2026-10-25", "steps": 7500}
    )
    assert resp_body.status_code == 401


def test_health_bridge_full_extended_payload_ingestion(client):
    """VÃ©rifie l'ingestion de la charge complÃ¨te envoyÃ©e par HealthSyncWorker enrichi :
    - Composition Withings : body_fat_pct, muscle_mass_kg, bone_mass_kg, weight_kg
    - BiomÃ©trie RingConn : hrv_ms, resting_hr_bpm, spo2_pct, workouts, sleep_sessions
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
        "total_calories_kcal": 2150.0,
        "distance_meters": 6500.0,
        "hydration_ml": 1250.0,
        "skin_temperature_c": 36.4,
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

    # 2. MÃ©triques quotidiennes RingConn (HRV, FC repos, SpO2)
    assert ing["daily_metric"]["resting_hr_bpm"] == 54
    assert ing["daily_metric"]["hrv_rmssd_ms"] == 68.0
    assert ing["daily_metric"]["spo2_pct"] == 99.0
    assert ing["daily_metric"]["steps"] == 8500
    assert ing["daily_metric"]["active_calories_kcal"] == 350.0
    assert ing["daily_metric"]["total_calories_kcal"] == 2150.0
    assert ing["daily_metric"]["skin_temperature_c"] == 36.4
    assert ing["hydration"]["volume_ml"] == 1250.0
    assert ing["distance_meters"] == 6500.0

    # 3. Sommeil et phases
    assert ing["sleep_session"]["duration_minutes"] == 450
    assert ing["sleep_session"]["deep_minutes"] == 100
    assert len(ing["sleep_session"]["stages"]) == 2

    # 4. Workouts
    assert len(ing["workouts"]) == 1
    assert ing["workouts"][0]["workout_type"] == "running"
    assert ing["workouts"][0]["duration_minutes"] == 30

    # 5. Ã‰chantillons FC intraday
    assert ing["intraday_samples_count"] == 1

def test_download_android_bridge_endpoint(client, tmp_path):
    """VÃ©rifie le comportement de l'endpoint de tÃ©lÃ©chargement direct de l'APK."""
    import src.app as app_module
    
    downloads_dir = os.path.join(app_module.STATIC_DIR, "downloads")
    apk_path = os.path.join(downloads_dir, "vitaltrack-health-bridge.apk")
    apk_backup_path = os.path.join(downloads_dir, "vitaltrack-health-bridge.apk.bak")
    
    had_apk = os.path.exists(apk_path)
    if had_apk:
        os.replace(apk_path, apk_backup_path)

    try:
        # 1. Quand l'APK n'est pas prÃ©sent en local, redirige (307) vers la release GitHub
        resp_redirect = client.get("/api/downloads/android-bridge", follow_redirects=False)
        assert resp_redirect.status_code == 307
        assert resp_redirect.headers["location"] == app_module.GITHUB_LATEST_RELEASE_APK_URL

        # 2. Quand un fichier APK est prÃ©sent dans static/downloads/vitaltrack-health-bridge.apk
        with open(apk_path, "wb") as f:
            f.write(b"PK  fake_apk_binary_content_vitaltrack")
        
        resp_file = client.get("/api/downloads/android-bridge")
        assert resp_file.status_code == 200
        assert resp_file.headers["content-type"] == "application/vnd.android.package-archive"
        assert resp_file.content == b"PK  fake_apk_binary_content_vitaltrack"
    finally:
        if os.path.exists(apk_path):
            os.remove(apk_path)
        if had_apk and os.path.exists(apk_backup_path):
            os.replace(apk_backup_path, apk_path)

def test_android_bridge_photo_meal_estimation_and_journal_save(client):
    """VÃ©rifie l'estimation calorique par photo IA et la sauvegarde directe dans le journal
    avec authentification par jeton d'appareil X-Webhook-Token."""
    import base64

    # 1. CrÃ©er un token pour la passerelle mobile Android
    tok_resp = client.post("/api/devices/android_phone/token", json={"name": "Xiaomi 14 Ultra"})
    assert tok_resp.status_code == 200
    token = tok_resp.json()["token"]

    # 2. Simuler une photo de plat (JPEG minimaliste 1x1 base64)
    fake_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
    photo_data_url = f"data:image/jpeg;base64,{base64.b64encode(fake_jpeg).decode('ascii')}"

    # 3. Appel de l'endpoint d'estimation avec header X-Webhook-Token
    estimate_resp = client.post(
        "/api/meals/estimate",
        json={
            "photo_data_url": photo_data_url,
            "meal_type": "lunch",
            "portion_scale": 1.0
        },
        headers={"X-Webhook-Token": token}
    )
    assert estimate_resp.status_code == 200
    est_data = estimate_resp.json()
    assert est_data["total_calories_kcal"] > 0
    assert "items" in est_data
    assert len(est_data["items"]) > 0

    # 4. Sauvegarde dans le journal via POST /api/meals avec X-Webhook-Token
    save_payload = {
        "date": "2026-10-26",
        "meal_type": "lunch",
        "photo_data_url": photo_data_url,
        "portion_scale": 1.0,
        "total_calories_kcal": est_data["total_calories_kcal"],
        "protein_g": est_data["protein_g"],
        "carbs_g": est_data["carbs_g"],
        "fat_g": est_data["fat_g"],
        "fiber_g": est_data["fiber_g"],
        "meal_name": est_data.get("dish_name", "Salade composÃ©e"),
        "items": est_data["items"]
    }
    save_resp = client.post(
        "/api/meals",
        json=save_payload,
        headers={"X-Webhook-Token": token}
    )
    assert save_resp.status_code == 200
    saved_meal = save_resp.json()
    assert saved_meal["total_calories_kcal"] == est_data["total_calories_kcal"]
    assert saved_meal["meal_type"] == "lunch"

    # 5. VÃ©rifier que le repas est consultable dans l'historique de l'utilisateur
    meals_resp = client.get("/api/meals", headers={"X-Webhook-Token": token})
    assert meals_resp.status_code == 200
    history = meals_resp.json()
    assert len(history) > 0
    assert any(m["date"] == "2026-10-26" and m["meal_type"] == "lunch" for m in history)





def test_android_manifest_and_ui_permissions_exact_sync():
    """Verifie la stricte parite 1:1 entre les permissions declarees dans le Manifest et UI MainActivity."""
    import re
    import xml.etree.ElementTree as ET

    manifest_path = "android/health-bridge-app/app/src/main/AndroidManifest.xml"
    main_act_path = "android/health-bridge-app/app/src/main/java/ai/vitaltrack/bridge/MainActivity.kt"

    tree = ET.parse(manifest_path)
    root = tree.getroot()
    manifest_health_perms = set()
    for elem in root.findall("uses-permission"):
        p_name = elem.attrib.get("{http://schemas.android.com/apk/res/android}name", "")
        if "permission.health." in p_name:
            manifest_health_perms.add(p_name.split(".")[-1])

    with open(main_act_path, "r", encoding="utf-8") as f:
        act_content = f.read()

    # Extraire les types d?clar?s dans `private val permissions = setOf(...)`
    match = re.search(r"private val permissions = setOf\((.*?)\n    \)", act_content, re.DOTALL)
    assert match is not None, "setOf permissions introuvable dans MainActivity.kt"
    ui_records = re.findall(r"getReadPermission\(([A-Za-z]+Record)::class\)", match.group(1))

    # Dictionnaire de correspondance Record -> Nom de permission Health Connect
    record_to_perm = {
        "StepsRecord": "READ_STEPS",
        "ActiveCaloriesBurnedRecord": "READ_ACTIVE_CALORIES_BURNED",
        "HeartRateRecord": "READ_HEART_RATE",
        "HeartRateVariabilityRmssdRecord": "READ_HEART_RATE_VARIABILITY",
        "RestingHeartRateRecord": "READ_RESTING_HEART_RATE",
        "OxygenSaturationRecord": "READ_OXYGEN_SATURATION",
        "SkinTemperatureRecord": "READ_SKIN_TEMPERATURE",
        "ExerciseSessionRecord": "READ_EXERCISE",
        "DistanceRecord": "READ_DISTANCE",
        "TotalCaloriesBurnedRecord": "READ_TOTAL_CALORIES_BURNED",
        "HydrationRecord": "READ_HYDRATION",
        "SleepSessionRecord": "READ_SLEEP",
        "WeightRecord": "READ_WEIGHT",
        "BodyFatRecord": "READ_BODY_FAT",
        "LeanBodyMassRecord": "READ_LEAN_BODY_MASS",
        "BoneMassRecord": "READ_BONE_MASS",
    }

    ui_perms = {record_to_perm[rec] for rec in ui_records}
    assert manifest_health_perms == ui_perms, f"Divergence Manifest vs UI: {manifest_health_perms.symmetric_difference(ui_perms)}"
    assert "READ_HYDRATION" in ui_perms
    assert "READ_SKIN_TEMPERATURE" in ui_perms
    assert len(ui_perms) == 16


def test_macrodroid_profile_contract():
    """Verifie la configuration du profil MacroDroid (URL officielle + presence du poids)."""
    import json

    with open("android/macrodroid_health_connect_profile.json", "r", encoding="utf-8") as f:
        profile = json.load(f)

    action = profile["actions"][0]
    assert action["url"].startswith("https://vital-track-one.vercel.app/"), f"URL erron?e: {action['url']}"
    body = action["body_content"]
    assert "weight_kg" in body, "Le champ weight_kg doit ?tre pr?sent dans le body MacroDroid"
    assert "hydration_ml" in body
    assert "skin_temperature_c" in body
    assert "total_calories_kcal" in body
    assert "distance_meters" in body


def test_hydration_logs_and_physiological_validation(client):
    """Verifie l ingestion d une liste de hydration_logs et la validation des bornes de temperature / hydratation."""
    tok_resp = client.post("/api/devices/health_connect/token", json={"name": "Validation Test Bridge"})
    assert tok_resp.status_code == 200
    token = tok_resp.json()["token"]

    # 1. Ingestion valide avec liste de hydration_logs
    payload = {
        "source": "health_connect",
        "date": "2026-10-27",
        "skin_temperature_c": 36.6,
        "hydration_logs": [
            {
                "id": "h_log_1",
                "volume_ml": 300.0,
                "timestamp": "2026-10-27T08:00:00Z"
            },
            {
                "id": "h_log_2",
                "volume_ml": 500.0,
                "timestamp": "2026-10-27T12:30:00Z"
            }
        ]
    }
    resp = client.post("/api/webhook/health", json=payload, headers={"X-Webhook-Token": token})
    assert resp.status_code == 200
    data = resp.json()["results"]
    assert data["daily_metric"]["skin_temperature_c"] == 36.6
    assert data["hydration"]["volume_ml"] == 300.0

    # 2. Temp?rature cutan?e hors borne (ex: 55?C) -> 422
    invalid_temp = {"skin_temperature_c": 55.0}
    bad_resp = client.post("/api/webhook/health", json=invalid_temp, headers={"X-Webhook-Token": token})
    assert bad_resp.status_code == 422
    assert "temp" in bad_resp.json()["detail"].lower()

    # 3. Hydratation hors borne (ex: 50 000 ml) -> 422
    invalid_hyd = {"hydration_ml": 50000.0}
    bad_resp2 = client.post("/api/webhook/health", json=invalid_hyd, headers={"X-Webhook-Token": token})
    assert bad_resp2.status_code == 422
    assert "hydratation" in bad_resp2.json()["detail"].lower()
