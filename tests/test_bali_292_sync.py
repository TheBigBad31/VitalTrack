"""Test d'intégration BALI-292 :
1. Pont Photo IA / Repas vers le journal par créneau (breakfast, lunch, snack, dinner)
2. Détermination automatique du créneau selon l'heure si non spécifié
3. Unicité de la source de vérité et synchronisation immédiate avec le journal et le dashboard
4. Non double-comptage dans le calcul des calories et macros
"""

import os
import tempfile
from datetime import date
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database
from src.auth import create_access_token
from src.routers.meals import determine_meal_type


@pytest.fixture
def sync_setup():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass

    test_db = Database(db_path=temp_path)
    user = test_db.get_or_create_user(email="sync_test@vitaltrack.local", name="Sync Tester")
    token = create_access_token(user["id"], user["uuid"], user["email"], user["name"])

    from src import app as app_module
    old_db = app_module.db
    app_module.db = test_db

    client = TestClient(app)

    yield {
        "db": test_db,
        "client": client,
        "user": user,
        "token": token,
    }

    app_module.db = old_db
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


def test_determine_meal_type_slots():
    """Vérifie la détection horaire des créneaux (slots)."""
    assert determine_meal_type(hour=7) == "breakfast"
    assert determine_meal_type(hour=10) == "breakfast"
    assert determine_meal_type(hour=12) == "lunch"
    assert determine_meal_type(hour=14) == "lunch"
    assert determine_meal_type(hour=16) == "snack"
    assert determine_meal_type(hour=17) == "snack"
    assert determine_meal_type(hour=19) == "dinner"
    assert determine_meal_type(hour=22) == "dinner"
    assert determine_meal_type(hour=2) == "snack"


def test_post_meals_bridges_to_journal_and_dashboard(sync_setup):
    """Vérifie qu'un repas posté sur POST /api/meals est visible immédiatement dans le journal et le dashboard sans double comptage."""
    client = sync_setup["client"]
    token = sync_setup["token"]
    headers = {"Authorization": f"Bearer {token}"}
    today_str = date.today().isoformat()

    # 1. Enregistrement d'un repas déjeuner avec items décomposés via POST /api/meals
    meal_payload = {
        "date": today_str,
        "meal_type": "lunch",
        "items": [
            {
                "name": "Filet de saumon",
                "portion_g": 150.0,
                "calories_kcal": 300.0,
                "protein_g": 30.0,
                "carbs_g": 0.0,
                "fat_g": 20.0,
                "fiber_g": 0.0,
                "confidence_score": 0.95
            },
            {
                "name": "Quinoa cuit",
                "portion_g": 100.0,
                "calories_kcal": 140.0,
                "protein_g": 4.5,
                "carbs_g": 25.0,
                "fat_g": 2.0,
                "fiber_g": 3.0,
                "confidence_score": 0.9
            }
        ]
    }
    res_post = client.post("/api/meals", json=meal_payload, headers=headers)
    assert res_post.status_code == 200
    saved_meal = res_post.json()
    assert saved_meal["total_calories_kcal"] == 440.0
    assert saved_meal["meal_type"] == "lunch"

    # 2. Vérification immédiate dans GET /api/meals/journal
    res_journal = client.get(f"/api/meals/journal?date={today_str}", headers=headers)
    assert res_journal.status_code == 200
    journal_data = res_journal.json()
    lunch_slot = next(m for m in journal_data["meals"] if m["meal_type"] == "lunch")
    assert lunch_slot["total_calories"] == 440.0
    assert len(lunch_slot["items"]) == 2
    assert {it["name"] for it in lunch_slot["items"]} == {"Filet de saumon", "Quinoa cuit"}
    assert journal_data["day_summary"]["total_calories"] == 440.0
    assert journal_data["day_summary"]["calories_consumed_kcal"] == 440.0

    # 3. Vérification dans GET /api/dashboard
    res_dash = client.get("/api/dashboard", headers=headers)
    assert res_dash.status_code == 200
    dash_data = res_dash.json()
    assert dash_data["summary"]["calories_intake_kcal"] == 440.0
    assert dash_data["summary"]["calories_consumed_kcal"] == 440.0
    assert dash_data["summary"]["macros"]["protein_g"] == 34.5
    assert dash_data["summary"]["macros"]["carbs_g"] == 25.0
    assert dash_data["summary"]["macros"]["fat_g"] == 22.0
    assert dash_data["summary"]["macros"]["fiber_g"] == 3.0

    # 4. Ajout d'un repas direct (calories directes) sans spécifier meal_type (déduit automatiquement)
    res_direct = client.post("/api/meals", json={
        "date": today_str,
        "total_calories_kcal": 250.0,
        "protein_g": 10.0,
        "carbs_g": 30.0,
        "fat_g": 5.0,
        "fiber_g": 2.0,
        "meal_name": "Collation Express"
    }, headers=headers)
    assert res_direct.status_code == 200
    auto_meal = res_direct.json()
    auto_slot = auto_meal["meal_type"]
    assert auto_slot in ["breakfast", "lunch", "snack", "dinner"]

    # 5. Vérification que le journal a été synchronisé et qu'il n'y a pas de double-comptage
    res_journal2 = client.get(f"/api/meals/journal?date={today_str}", headers=headers)
    assert res_journal2.status_code == 200
    j2_data = res_journal2.json()
    
    # Si le slot auto était "lunch", il a remplacé le lunch ou sinon il s'est ajouté dans son slot
    total_expected = sum(m["total_calories"] for m in j2_data["meals"])
    assert j2_data["day_summary"]["total_calories"] == total_expected
    assert j2_data["day_summary"]["calories_consumed_kcal"] == total_expected

    # Dashboard correspond exactement au total journalier
    res_dash2 = client.get("/api/dashboard", headers=headers)
    assert res_dash2.status_code == 200
    dash2_data = res_dash2.json()
    assert dash2_data["summary"]["calories_intake_kcal"] == total_expected


def test_saved_meal_log_bridges_to_journal(sync_setup):
    """Vérifie que POST /api/meals/saved/{meal_id}/log synchronise également meal_logs."""
    client = sync_setup["client"]
    token = sync_setup["token"]
    headers = {"Authorization": f"Bearer {token}"}
    today_str = date.today().isoformat()

    # Créer un plat favori
    res_saved = client.post("/api/meals/saved", json={
        "name": "Omelette Champignons & Fromage",
        "meal_type": "dinner",
        "serving_size": "1 assiette",
        "quantity_grams": 250.0,
        "calories": 320.0,
        "protein_g": 24.0,
        "carbs_g": 4.0,
        "fat_g": 22.0,
        "fiber_g": 2.0,
        "items": [
            {"name": "Oeufs", "portion_g": 150.0, "calories_kcal": 210.0, "protein_g": 18.0, "carbs_g": 1.0, "fat_g": 15.0},
            {"name": "Champignons & Fromage", "portion_g": 100.0, "calories_kcal": 110.0, "protein_g": 6.0, "carbs_g": 3.0, "fat_g": 7.0}
        ]
    }, headers=headers)
    assert res_saved.status_code == 200
    saved_dish_id = res_saved.json()["id"]

    # Loguer le plat sauvegardé pour le dîner avec portion x1.0
    res_log = client.post(f"/api/meals/saved/{saved_dish_id}/log", json={
        "date": today_str,
        "meal_type": "dinner",
        "portion_factor": 1.0
    }, headers=headers)
    assert res_log.status_code == 200

    # Vérifier que le dîner apparaît dans le journal
    res_j = client.get(f"/api/meals/journal?date={today_str}", headers=headers)
    assert res_j.status_code == 200
    dinner_slot = next(m for m in res_j.json()["meals"] if m["meal_type"] == "dinner")
    assert dinner_slot["total_calories"] == 320.0
    assert len(dinner_slot["items"]) == 2
