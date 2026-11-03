"""Tests de sécurité renforcée pour les webhooks de santé VitalTrack (P0 BALI-182).

Couvre l'ensemble des exigences d'acceptation :
1. Token uniquement via header (X-Webhook-Token ou Authorization) — rejet 401 si query param ou body token.
2. Élimination de l'IDOR cross-user via WEBHOOK_SECRET.
3. Lookup device indexé via api_key_hash SHA-256.
4. Validation des plages physiologiques strictes (HTTP 422 si anomalie).
5. Idempotence garantie via contrainte UNIQUE(idempotency_key) sur raw_ingest et déduplication des métriques.
6. Rate limiting sur /api/webhooks/* (HTTP 429 si dépassement).
"""

import hashlib
import pytest
from datetime import date
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database
from src.rate_limit import limiter


@pytest.fixture
def client(tmp_path):
    test_db_path = str(tmp_path / "test_webhook_sec.db")
    app.state.db_instance = Database(db_path=test_db_path)
    limiter.reset()

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
    limiter.reset()


def test_auth_headers_only_and_rejection_query_body(client):
    """Vérifie que seuls les headers sont acceptés et que query param ?token= ou body token sont rejetés en 401."""
    tok_resp = client.post("/api/devices/ringconn/token", json={"name": "RingConn Secure"})
    assert tok_resp.status_code == 200
    token = tok_resp.json()["token"]

    valid_payload = {
        "source": "ringconn",
        "date": "2026-11-03",
        "weight_kg": 75.0,
        "steps": 8500
    }

    # 1. Header X-Webhook-Token -> 200
    res_x_token = client.post("/api/webhook/health", json=valid_payload, headers={"X-Webhook-Token": token})
    assert res_x_token.status_code == 200

    # 2. Header Authorization Bearer -> 200
    res_bearer = client.post("/api/webhook/health", json=valid_payload, headers={"Authorization": f"Bearer {token}"})
    assert res_bearer.status_code == 200

    # 3. Query param ?token= -> Rejet 401
    res_query = client.post(f"/api/webhook/health?token={token}", json=valid_payload)
    assert res_query.status_code == 401
    assert "Jeton d'authentification manquant ou non autorisé" in res_query.json()["detail"]

    # 4. Body JSON { "token": "..." } sans header -> Rejet 401
    payload_body_tok = dict(valid_payload)
    payload_body_tok["token"] = token
    res_body = client.post("/api/webhook/health", json=payload_body_tok)
    assert res_body.status_code == 401

    # 5. Body JSON { "api_key": "..." } sans header -> Rejet 401
    payload_body_key = dict(valid_payload)
    payload_body_key["api_key"] = token
    res_body_key = client.post("/api/webhook/health", json=payload_body_key)
    assert res_body_key.status_code == 401


def test_api_key_hash_indexing_and_lookup(client):
    """Vérifie que l'api_key_hash SHA-256 est calculé et stocké dans user_devices pour lookup direct."""
    import src.app as app_module
    test_db = app_module.db

    device_key = "secret_indexed_token_999"
    key_hash = hashlib.sha256(device_key.encode("utf-8")).hexdigest()

    test_db.update_user_device(
        device_id="withings_scale_test",
        name="Withings Scale Index Test",
        device_type="scale",
        connected=True,
        auth_type="webhook",
        api_key=device_key,
        user_id=1
    )

    # Vérification que le hash SHA-256 est présent en base
    with test_db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT api_key_hash FROM user_devices WHERE device_id = 'withings_scale_test' AND user_id = 1")
        row = cursor.fetchone()
        assert row is not None
        assert row["api_key_hash"] == key_hash

    # Vérification que le lookup retrouve bien l'utilisateur via son token
    match = test_db.find_user_by_device_token(device_key)
    assert match is not None
    assert match["user_id"] == 1
    assert match["device"]["device_id"] == "withings_scale_test"


def test_no_idor_with_global_secret(client, monkeypatch):
    """Vérifie que WEBHOOK_SECRET n'autorise plus d'IDOR cross-user via un champ user_id dans le payload."""
    monkeypatch.setenv("WEBHOOK_SECRET", "system_admin_secret_key_123")

    payload = {
        "source": "health_connect",
        "date": "2026-11-03",
        "weight_kg": 70.0,
        "steps": 9000,
        "user_id": 999  # tentative d'IDOR
    }

    res = client.post(
        "/api/webhook/health",
        json=payload,
        headers={"X-Webhook-Token": "system_admin_secret_key_123"}
    )
    assert res.status_code == 200
    # Doit être attribué exclusivement au compte système par défaut (1), jamais au user_id 999
    assert res.json()["user_id"] == 1


@pytest.mark.parametrize("absurd_field,value,field_name", [
    ("weight_kg", 5000.0, "poids"),
    ("weight_kg", 15.0, "poids"),
    ("weight", 305.0, "poids"),
    ("resting_hr_bpm", 25, "fréquence cardiaque"),
    ("resting_hr_bpm", 240, "fréquence cardiaque"),
    ("steps", -10, "pas"),
    ("steps", 150_000, "pas"),
    ("spo2_pct", 40.0, "SpO2"),
    ("spo2_pct", 105.0, "SpO2"),
])
def test_physiological_ranges_rejection(client, absurd_field, value, field_name):
    """Vérifie le rejet HTTP 422 sur toute valeur physiologique aberrante."""
    tok_resp = client.post("/api/devices/ringconn/token", json={"name": "RingConn Bio"})
    token = tok_resp.json()["token"]

    payload = {
        "source": "ringconn",
        "date": "2026-11-03",
        absurd_field: value
    }

    res = client.post(
        "/api/webhook/health",
        json=payload,
        headers={"X-Webhook-Token": token}
    )
    assert res.status_code == 422
    assert "physiologique invalide" in res.json()["detail"].lower()


def test_idempotency_raw_ingest_no_duplicates(client):
    """Vérifie qu'un rejeu du même payload avec external_id ne crée aucun doublon dans raw_ingest ni en base."""
    import src.app as app_module
    test_db = app_module.db

    tok_resp = client.post("/api/devices/health_connect/token", json={"name": "HC Idempotence"})
    token = tok_resp.json()["token"]

    item = {
        "source": "health_connect",
        "external_id": "unique_sync_uuid_9999",
        "date": "2026-11-03",
        "weight_kg": 74.2,
        "steps": 10500,
        "resting_hr_bpm": 62
    }

    # 1. Première ingestion
    res1 = client.post("/api/webhook/health", json=item, headers={"X-Webhook-Token": token})
    assert res1.status_code == 200

    # 2. Rejeu identique immédiat (même payload, même external_id)
    res2 = client.post("/api/webhook/health", json=item, headers={"X-Webhook-Token": token})
    assert res2.status_code == 200

    # 3. Vérification en base de données : exactement 1 seule entrée dans raw_ingest
    with test_db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS count FROM raw_ingest WHERE idempotency_key = 'health_connect:unique_sync_uuid_9999'")
        row = cursor.fetchone()
        assert row["count"] == 1

        # Et exactement 1 seule entrée dans weights
        cursor.execute("SELECT COUNT(*) AS count FROM weights WHERE external_id = 'unique_sync_uuid_9999'")
        row_w = cursor.fetchone()
        assert row_w["count"] == 1


def test_webhook_rate_limiting(client, monkeypatch):
    """Vérifie le rate limiting HTTP 429 par device/IP sur l'ingestion webhook."""
    # Configurer un seuil bas pour tester le rate limiting (ex: 3 requêtes par minute)
    monkeypatch.setenv("RATE_LIMIT_WEBHOOK", "3/minute")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")

    tok_resp = client.post("/api/devices/ringconn/token", json={"name": "RingConn RateLimit"})
    token = tok_resp.json()["token"]

    payload = {
        "source": "ringconn",
        "date": "2026-11-03",
        "steps": 5000
    }

    # 3 requêtes acceptées
    for i in range(3):
        r = client.post("/api/webhook/health", json=payload, headers={"X-Webhook-Token": token})
        assert r.status_code == 200

    # La 4ème requête doit lever HTTP 429 Too Many Requests
    r_blocked = client.post("/api/webhook/health", json=payload, headers={"X-Webhook-Token": token})
    assert r_blocked.status_code == 429
    assert "Retry-After" in r_blocked.headers
    assert "Limite de requêtes dépassée" in r_blocked.json()["detail"]
