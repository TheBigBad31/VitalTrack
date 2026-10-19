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
