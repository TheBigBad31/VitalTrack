"""Tests de persistance intégrale du profil utilisateur en base de données."""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database
from src.auth import create_access_token


@pytest.fixture
def test_setup():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass

    test_db = Database(db_path=temp_path)
    user1 = test_db.get_or_create_user(email="alice@vitaltrack.local", name="Alice")
    user2 = test_db.get_or_create_user(email="bob@vitaltrack.local", name="Bob")

    token1 = create_access_token(user1["id"], user1["uuid"], user1["email"], user1["name"])
    token2 = create_access_token(user2["id"], user2["uuid"], user2["email"], user2["name"])

    # Patch database in app
    from src import app as app_module
    old_db = app_module.db
    app_module.db = test_db

    client = TestClient(app)

    yield {
        "db": test_db,
        "client": client,
        "user1": user1,
        "user2": user2,
        "token1": token1,
        "token2": token2,
    }

    app_module.db = old_db
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


def test_profile_default_creation(test_setup):
    """Vérifie la création automatique d'un profil par défaut pour un utilisateur."""
    client = test_setup["client"]
    token1 = test_setup["token1"]

    headers = {"Authorization": f"Bearer {token1}"}
    res = client.get("/api/profile", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert "profile" in data
    prof = data["profile"]
    assert prof["user_id"] == test_setup["user1"]["id"]
    assert prof["target_steps"] == 10000
    assert prof["target_calories_intake"] == 2000.0


def test_profile_update_and_persistence(test_setup):
    """Vérifie la mise à jour complète et la persistance des objectifs BMR/TDEE/macros."""
    client = test_setup["client"]
    token1 = test_setup["token1"]
    test_db = test_setup["db"]
    user1_id = test_setup["user1"]["id"]

    headers = {"Authorization": f"Bearer {token1}"}
    update_payload = {
        "name": "Alice Super",
        "gender": "female",
        "age": 28,
        "height_cm": 165.0,
        "target_weight_kg": 58.0,
        "current_weight_kg": 63.5,
        "goal_profile_id": "weight_loss",
        "goal_type": "fat_loss",
        "activity_level": "very_active",
        "target_steps": 12500,
        "target_calories_intake": 1850.0,
        "protein_target_per_kg": 2.0,
        "daily_protein_target_g": 130.0,
        "daily_carbs_target_g": 190.0,
        "daily_fat_target_g": 55.0,
        "daily_water_target_ml": 2500.0,
        "meal_distribution": {"breakfast": 25, "lunch": 35, "snack": 10, "dinner": 30}
    }

    # Test via PUT /api/profile
    res = client.put("/api/profile", json=update_payload, headers=headers)
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["status"] == "success"

    # Vérification en BDD directement via Database instance
    prof_db = test_db.get_user_profile(user_id=user1_id)
    assert prof_db["name"] == "Alice Super"
    assert prof_db["gender"] == "female"
    assert prof_db["age"] == 28
    assert prof_db["height_cm"] == 165.0
    assert prof_db["target_weight_kg"] == 58.0
    assert prof_db["current_weight_kg"] == 63.5
    assert prof_db["target_steps"] == 12500
    assert prof_db["target_calories_intake"] == 1850.0
    assert prof_db["daily_protein_target_g"] == 130.0
    assert prof_db["daily_carbs_target_g"] == 190.0
    assert prof_db["daily_fat_target_g"] == 55.0
    assert prof_db["daily_water_target_ml"] == 2500.0
    assert prof_db["goal_type"] == "fat_loss"


def test_profile_multiuser_isolation(test_setup):
    """Vérifie l'isolation stricte des profils entre utilisateurs différents."""
    client = test_setup["client"]
    token1 = test_setup["token1"]
    token2 = test_setup["token2"]

    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}

    client.put("/api/profile", json={"name": "Alice Modified", "target_steps": 15000}, headers=headers1)
    client.put("/api/profile", json={"name": "Bob Modified", "target_steps": 8000}, headers=headers2)

    res1 = client.get("/api/profile", headers=headers1)
    assert res1.status_code == 200
    prof1 = res1.json()["profile"]
    assert prof1["name"] == "Alice Modified"
    assert prof1["target_steps"] == 15000

    res2 = client.get("/api/profile", headers=headers2)
    assert res2.status_code == 200
    prof2 = res2.json()["profile"]
    assert prof2["name"] == "Bob Modified"
    assert prof2["target_steps"] == 8000
