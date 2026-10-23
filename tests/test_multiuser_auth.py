"""Tests unitaires et d'intégration pour l'architecture multi-utilisateurs et JWT."""

import os
import tempfile
import pytest
from datetime import date
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database
from src.models import WeightEntry, ActivityEntry, MealEntry, FoodItem
from src.auth import create_access_token, decode_access_token, hash_password, verify_password
import src.app as app_module


@pytest.fixture
def isolated_app():
    """Fournit un client de test avec une base SQLite isolée."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name
    if os.path.exists(temp_path):
        os.remove(temp_path)

    test_db = Database(db_path=temp_path)
    old_db = app_module.db
    old_nutri_db = app_module.nutrition_engine.db
    app_module.db = test_db
    app_module.nutrition_engine.db = test_db

    client = TestClient(app)
    yield client, test_db

    app_module.db = old_db
    app_module.nutrition_engine.db = old_nutri_db
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


def test_password_hashing():
    """Vérifie le hashage PBKDF2 et la vérification des mots de passe."""
    pwd = "MonSuperMotDePasse123!"
    hashed = hash_password(pwd)
    assert hashed != pwd
    assert "$" in hashed
    assert verify_password(pwd, hashed) is True
    assert verify_password("MauvaisPasse", hashed) is False


def test_jwt_generation_and_validation():
    """Vérifie la création et validation du token JWT."""
    token = create_access_token(user_id=42, user_uuid="uuid-42", email="test@example.com", name="Test User")
    decoded = decode_access_token(token)
    assert decoded is not None
    assert decoded["user_id"] == 42
    assert decoded["uuid"] == "uuid-42"
    assert decoded["email"] == "test@example.com"
    assert decoded["name"] == "Test User"


def test_multi_user_isolation(isolated_app):
    """Vérifie que deux utilisateurs distincts ont des données totalement étanches."""
    client, test_db = isolated_app

    # Inscription de Alice
    res_alice = client.post("/api/auth/register", json={
        "email": "alice@example.com",
        "password": "PasswordAlice123!",
        "name": "Alice Dupont"
    })
    assert res_alice.status_code == 200
    token_alice = res_alice.json()["access_token"]
    user_alice = res_alice.json()["user"]

    # Inscription de Bob
    res_bob = client.post("/api/auth/register", json={
        "email": "bob@example.com",
        "password": "PasswordBob123!",
        "name": "Bob Martin"
    })
    assert res_bob.status_code == 200
    token_bob = res_bob.json()["access_token"]
    user_bob = res_bob.json()["user"]

    assert user_alice["id"] != user_bob["id"]

    # Alice enregistre une pesée (72.5 kg)
    headers_alice = {"Authorization": f"Bearer {token_alice}"}
    p_alice = client.post("/api/weights", json={
        "date": "2026-10-19",
        "weight_kg": 72.5,
        "body_fat_pct": 18.0,
        "source": "manual"
    }, headers=headers_alice)
    assert p_alice.status_code == 200

    # Bob enregistre une pesée (85.0 kg) le même jour
    headers_bob = {"Authorization": f"Bearer {token_bob}"}
    p_bob = client.post("/api/weights", json={
        "date": "2026-10-19",
        "weight_kg": 85.0,
        "body_fat_pct": 22.0,
        "source": "manual"
    }, headers=headers_bob)
    assert p_bob.status_code == 200

    # Alice lit son historique : elle ne voit QUE 72.5 kg
    alice_weights = client.get("/api/weights", headers=headers_alice).json()
    assert len(alice_weights) >= 1
    today_w_alice = [w for w in alice_weights if w["date"] == "2026-10-19"]
    assert len(today_w_alice) == 1
    assert today_w_alice[0]["weight_kg"] == 72.5

    # Bob lit son historique : il ne voit QUE 85.0 kg
    bob_weights = client.get("/api/weights", headers=headers_bob).json()
    assert len(bob_weights) >= 1
    today_w_bob = [w for w in bob_weights if w["date"] == "2026-10-19"]
    assert len(today_w_bob) == 1
    assert today_w_bob[0]["weight_kg"] == 85.0


def test_auth_login_endpoint(isolated_app):
    """Teste la connexion par email et mot de passe via /api/auth/login."""
    client, _ = isolated_app

    # Création du compte
    client.post("/api/auth/register", json={
        "email": "charlie@vitaltrack.io",
        "password": "CharliePassword2026",
        "name": "Charlie"
    })

    # Test avec mauvais mot de passe
    bad_res = client.post("/api/auth/login", json={
        "email": "charlie@vitaltrack.io",
        "password": "WrongPassword"
    })
    assert bad_res.status_code == 401

    # Test avec bon mot de passe
    good_res = client.post("/api/auth/login", json={
        "email": "charlie@vitaltrack.io",
        "password": "CharliePassword2026"
    })
    assert good_res.status_code == 200
    data = good_res.json()
    assert data["status"] == "success"
    assert "access_token" in data
    assert data["user"]["email"] == "charlie@vitaltrack.io"


def test_webhook_multiuser_device_token_isolation(isolated_app):
    """Vérifie que les webhooks associent strictement les données au compte de l'appareil via le token."""
    client, test_db = isolated_app

    # Inscription de User 1 et User 2
    res1 = client.post("/api/auth/register", json={
        "email": "user1_webhook@vitaltrack.io",
        "password": "Password123!",
        "name": "Utilisateur 1 Webhook"
    })
    token1 = res1.json()["access_token"]
    u1_id = res1.json()["user"]["id"]

    res2 = client.post("/api/auth/register", json={
        "email": "user2_webhook@vitaltrack.io",
        "password": "Password123!",
        "name": "Utilisateur 2 Webhook"
    })
    token2 = res2.json()["access_token"]
    u2_id = res2.json()["user"]["id"]

    # Associer un appareil avec token spécifique pour User 1 (Health Connect)
    client.post("/api/devices/connect", json={
        "device_id": "health_connect",
        "name": "Health Connect de User 1",
        "device_type": "mobile_aggregator",
        "auth_type": "webhook",
        "api_key": "secret_token_user_1",
        "connected": True
    }, headers={"Authorization": f"Bearer {token1}"})

    # Associer un appareil avec token spécifique pour User 2 (RingConn)
    client.post("/api/devices/connect", json={
        "device_id": "ringconn",
        "name": "RingConn de User 2",
        "device_type": "ring",
        "auth_type": "webhook",
        "api_key": "secret_token_user_2",
        "connected": True
    }, headers={"Authorization": f"Bearer {token2}"})

    # 1. Envoi sans token -> Doit échouer en 401
    bad_req = client.post("/api/webhook/health", json={"weight_kg": 75.0, "steps": 8000})
    assert bad_req.status_code == 401

    # 2. Envoi avec un token inconnu -> Doit échouer en 401
    unknown_req = client.post("/api/webhook/health?token=token_inexistant", json={"weight_kg": 75.0, "steps": 8000})
    assert unknown_req.status_code == 401

    # 3. Envoi d'une pesée (71.2 kg) et activité (9500 pas) via le token de User 1
    resp1 = client.post("/api/webhook/health?token=secret_token_user_1", json={
        "date": "2026-10-22",
        "source": "health_connect",
        "weight_kg": 71.2,
        "steps": 9500,
        "active_calories_kcal": 420.0
    })
    assert resp1.status_code == 200
    assert resp1.json()["user_id"] == u1_id

    # 4. Envoi d'une pesée (84.6 kg) et activité (12500 pas) via le token de User 2
    resp2 = client.post("/api/webhooks/ringconn?token=secret_token_user_2", json={
        "date": "2026-10-22",
        "source": "ringconn",
        "weight_kg": 84.6,
        "steps": 12500,
        "active_calories_kcal": 580.0
    })
    assert resp2.status_code == 200
    assert resp2.json()["user_id"] == u2_id

    # 5. Vérifier l'isolation stricte des données
    weights_u1 = client.get("/api/weights", headers={"Authorization": f"Bearer {token1}"}).json()
    weights_u2 = client.get("/api/weights", headers={"Authorization": f"Bearer {token2}"}).json()

    assert any(w["weight_kg"] == 71.2 for w in weights_u1)
    assert not any(w["weight_kg"] == 84.6 for w in weights_u1)

    assert any(w["weight_kg"] == 84.6 for w in weights_u2)
    assert not any(w["weight_kg"] == 71.2 for w in weights_u2)

    acts_u1 = client.get("/api/activities", headers={"Authorization": f"Bearer {token1}"}).json()
    acts_u2 = client.get("/api/activities", headers={"Authorization": f"Bearer {token2}"}).json()

    assert any(a["steps"] == 9500 for a in acts_u1)
    assert not any(a["steps"] == 12500 for a in acts_u1)

    assert any(a["steps"] == 12500 for a in acts_u2)
    assert not any(a["steps"] == 9500 for a in acts_u2)


def test_daily_sync_multiuser_iteration(isolated_app):
    """Vérifie que daily_sync itère sur chaque utilisateur et synchronise avec ses identifiants propres."""
    from src.daily_sync import run_daily_sync
    client, test_db = isolated_app

    # Inscription de User A et User B
    res_a = client.post("/api/auth/register", json={
        "email": "userA_sync@vitaltrack.io",
        "password": "Password123!",
        "name": "User A Sync"
    })
    token_a = res_a.json()["access_token"]
    u_a_id = res_a.json()["user"]["id"]

    res_b = client.post("/api/auth/register", json={
        "email": "userB_sync@vitaltrack.io",
        "password": "Password123!",
        "name": "User B Sync"
    })
    token_b = res_b.json()["access_token"]
    u_b_id = res_b.json()["user"]["id"]

    # Connecter Withings pour User A avec un mock_payload
    mock_withings_payload = {
        "body": {
            "measuregrps": [
                {
                    "date": 1792656000,
                    "measures": [
                        {"value": 73200, "unit": -3, "type": 1},
                        {"value": 17800, "unit": -3, "type": 6}
                    ]
                }
            ]
        }
    }
    test_db.update_user_device(
        device_id="withings",
        name="Withings de A",
        device_type="scale",
        connected=True,
        is_active=True,
        credentials={"client_id": "test_cid_a", "access_token": "test_tok_a", "mock_payload": mock_withings_payload},
        user_id=u_a_id
    )

    # Connecter Oura pour User B avec des mock_payloads
    mock_oura_payloads = {
        "activity": [{"day": "2026-10-22", "steps": 10500, "active_calories": 500, "total_calories": 2300}],
        "readiness": [{"day": "2026-10-22", "contributors": {"resting_heart_rate": 58}}],
        "sleep": []
    }
    test_db.update_user_device(
        device_id="oura",
        name="Oura de B",
        device_type="ring",
        connected=True,
        is_active=True,
        credentials={"personal_access_token": "test_oura_tok_b", "mock_payloads": mock_oura_payloads},
        user_id=u_b_id
    )

    # Exécution de la synchronisation journalière sur la base de test isolée
    run_daily_sync(db=test_db)

    # Vérification que l'appareil de A a synchronisé pour user A
    weights_a = client.get("/api/weights", headers={"Authorization": f"Bearer {token_a}"}).json()
    assert len(weights_a) > 0

    # Vérification que l'appareil de B a synchronisé pour user B
    acts_b = client.get("/api/activities", headers={"Authorization": f"Bearer {token_b}"}).json()
    assert len(acts_b) > 0


def test_webhook_security_fail_closed_and_no_fallback(isolated_app, monkeypatch):
    """Vérifie la sécurité fail-closed (503 en prod sans WEBHOOK_SECRET) et le rejet des tokens sans utilisateur lié."""
    client, test_db = isolated_app

    # Inscription d'un utilisateur
    res = client.post("/api/auth/register", json={
        "email": "failclosed@vitaltrack.io",
        "password": "Password123!",
        "name": "Fail Closed User"
    })
    token_auth = res.json()["access_token"]
    user_id = res.json()["user"]["id"]

    sample_payload = {
        "date": "2026-10-25",
        "weight_kg": 76.5,
        "steps": 10000
    }

    # 1. En environnement VERCEL=1 ou ENV=production, si WEBHOOK_SECRET est absent, rejet HTTP 503
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)

    res_prod_no_secret = client.post(
        "/api/webhook/health",
        json=sample_payload,
        headers={"X-Webhook-Token": "some_random_token"}
    )
    assert res_prod_no_secret.status_code == 503
    assert "non configuré en production" in res_prod_no_secret.json()["detail"]

    # Même chose avec ENV=production
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv("ENV", "production")
    res_prod_no_secret2 = client.post(
        "/api/webhook/health",
        json=sample_payload,
        headers={"X-Webhook-Token": "some_random_token"}
    )
    assert res_prod_no_secret2.status_code == 503

    # 2. Hors production sans WEBHOOK_SECRET : un token inconnu doit être rejeté en 401 (aucun fallback silencieux sur user_id=1)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)

    res_unknown_token = client.post(
        "/api/webhook/health",
        json=sample_payload,
        headers={"X-Webhook-Token": "vitaltrack_secure_webhook_key_sample"}
    )
    assert res_unknown_token.status_code == 401
    assert "aucun compte utilisateur ou appareil associé" in res_unknown_token.json()["detail"]

    # 3. Avec WEBHOOK_SECRET configuré et user_id explicite dans le payload
    monkeypatch.setenv("WEBHOOK_SECRET", "super_secret_webhook_admin")
    res_with_global_secret = client.post(
        "/api/webhook/health",
        json={**sample_payload, "user_id": user_id},
        headers={"X-Webhook-Token": "super_secret_webhook_admin"}
    )
    assert res_with_global_secret.status_code == 200
    assert res_with_global_secret.json()["user_id"] == user_id

    # Vérifier que les poids ont bien été ingérés pour cet utilisateur
    weights = client.get("/api/weights", headers={"Authorization": f"Bearer {token_auth}"}).json()
    assert any(w["weight_kg"] == 76.5 for w in weights)

