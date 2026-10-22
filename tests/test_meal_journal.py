"""Tests unitaires et d'intégration pour le Journal Quotidien des Repas (Stage 12)."""

import os
import tempfile
from datetime import date
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database
from src.auth import create_access_token


@pytest.fixture
def journal_setup():
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


def test_meal_journal_workflow_and_scaling(journal_setup):
    """Teste le journal des 4 repas, l'ajout d'aliments du catalogue avec prorata, la suppression et le save-as-dish."""
    client = journal_setup["client"]
    token1 = journal_setup["token1"]
    headers = {"Authorization": f"Bearer {token1}"}
    today_str = "2026-10-22"

    # 1. Création d'aliments dans le catalogue
    # Riz: 100g = 130 kcal, 2.7g P, 28g G, 0.3g L, 0.4g F
    res_riz = client.post("/api/catalog/items", json={
        "name": "Riz Basmati cuit",
        "item_type": "food",
        "default_unit": "g",
        "default_quantity": 100.0,
        "calories_per_unit": 130.0,
        "protein_per_unit_g": 2.7,
        "carbs_per_unit_g": 28.0,
        "fat_per_unit_g": 0.3,
        "fiber_per_unit_g": 0.4
    }, headers=headers)
    assert res_riz.status_code == 200
    riz_id = res_riz.json()["id"]

    # Poulet: 100g = 120 kcal, 26g P, 0g G, 1.5g L, 0g F
    res_poulet = client.post("/api/catalog/items", json={
        "name": "Blanc de poulet",
        "item_type": "food",
        "default_unit": "g",
        "default_quantity": 100.0,
        "calories_per_unit": 120.0,
        "protein_per_unit_g": 26.0,
        "carbs_per_unit_g": 0.0,
        "fat_per_unit_g": 1.5,
        "fiber_per_unit_g": 0.0
    }, headers=headers)
    assert res_poulet.status_code == 200
    poulet_id = res_poulet.json()["id"]

    # 2. Consultation initiale du journal pour today
    res_j0 = client.get(f"/api/meals/journal?date={today_str}", headers=headers)
    assert res_j0.status_code == 200
    data_j0 = res_j0.json()
    assert data_j0["date"] == today_str
    assert len(data_j0["meals"]) == 4
    assert data_j0["day_summary"]["total_calories"] == 0.0

    # 3. Ajout de 150g de riz au déjeuner (prorata 1.5x)
    # 130 * 1.5 = 195 kcal
    # 2.7 * 1.5 = 4.05 -> 4.0g ou 4.1g P
    # 28 * 1.5 = 42.0g G
    # 0.3 * 1.5 = 0.45 -> 0.4g ou 0.5g L
    res_add1 = client.post("/api/meals/journal/lunch/items", json={
        "date": today_str,
        "food_item_id": riz_id,
        "quantity": 150.0,
        "unit": "g"
    }, headers=headers)
    assert res_add1.status_code == 200
    lunch_log1 = res_add1.json()["meal_log"]
    assert len(lunch_log1["items"]) == 1
    item_riz = lunch_log1["items"][0]
    assert item_riz["name"] == "Riz Basmati cuit"
    assert item_riz["quantity"] == 150.0
    assert item_riz["calories"] == 195.0
    assert pytest.approx(item_riz["carbs_g"], abs=0.1) == 42.0

    # 4. Ajout de 120g de poulet au déjeuner (prorata 1.2x)
    # 120 * 1.2 = 144 kcal
    # 26 * 1.2 = 31.2g P
    # 1.5 * 1.2 = 1.8g L
    res_add2 = client.post("/api/meals/journal/lunch/items", json={
        "date": today_str,
        "food_item_id": poulet_id,
        "quantity": 120.0,
        "unit": "g"
    }, headers=headers)
    assert res_add2.status_code == 200
    lunch_log2 = res_add2.json()["meal_log"]
    assert len(lunch_log2["items"]) == 2
    # Total calories = 195 + 144 = 339 kcal
    assert lunch_log2["total_calories"] == 339.0

    # 5. Vérification du journal du jour
    res_j1 = client.get(f"/api/meals/journal?date={today_str}", headers=headers)
    assert res_j1.status_code == 200
    data_j1 = res_j1.json()
    assert data_j1["day_summary"]["total_calories"] == 339.0
    assert data_j1["day_summary"]["total_protein_g"] > 30.0
    assert data_j1["day_summary"]["macros_pct"]["protein_pct"] > 0.0

    # 6. Transformation du déjeuner en plat du catalogue (save-as-dish)
    res_dish = client.post("/api/meals/journal/lunch/save-as-dish", json={
        "name": "Assiette Poulet & Riz Déjeuner",
        "date": today_str
    }, headers=headers)
    assert res_dish.status_code == 200
    dish_created = res_dish.json()["dish"]
    assert dish_created["name"] == "Assiette Poulet & Riz Déjeuner"
    assert dish_created["item_type"] == "dish"
    assert dish_created["default_unit"] == "portion"
    assert dish_created["calories_per_unit"] == 339.0

    # Vérification que le plat apparaît bien dans le catalogue
    res_cat = client.get("/api/catalog/items?type=dish", headers=headers)
    assert any(d["name"] == "Assiette Poulet & Riz Déjeuner" for d in res_cat.json())

    # 7. Suppression d'une ligne d'aliment dans le repas (retrait du riz)
    item_riz_id = item_riz["id"]
    res_del_item = client.delete(f"/api/meals/journal/items/{item_riz_id}", headers=headers)
    assert res_del_item.status_code == 200
    updated_lunch = res_del_item.json()["meal_log"]
    assert len(updated_lunch["items"]) == 1
    # Il ne reste que le poulet (144 kcal)
    assert updated_lunch["total_calories"] == 144.0

    # Vérification du total journalier après suppression
    res_j2 = client.get(f"/api/meals/journal?date={today_str}", headers=headers)
    assert res_j2.json()["day_summary"]["total_calories"] == 144.0


def test_meal_journal_multi_user_isolation(journal_setup):
    """Vérifie l'étanchéité stricte des journaux de repas entre utilisateurs."""
    client = journal_setup["client"]
    token1 = journal_setup["token1"]
    token2 = journal_setup["token2"]
    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}
    today_str = "2026-10-22"

    # Alice ajoute un aliment au petit-déjeuner
    client.post("/api/meals/journal/breakfast/items", json={
        "date": today_str,
        "name": "Oeufs brouillés Alice",
        "quantity": 100.0,
        "unit": "g",
        "calories": 150.0,
        "protein_g": 12.0
    }, headers=headers1)

    # Bob ajoute un aliment au petit-déjeuner
    client.post("/api/meals/journal/breakfast/items", json={
        "date": today_str,
        "name": "Pancakes Bob",
        "quantity": 200.0,
        "unit": "g",
        "calories": 500.0,
        "protein_g": 10.0
    }, headers=headers2)

    # Alice consulte son journal
    alice_journal = client.get(f"/api/meals/journal?date={today_str}", headers=headers1).json()
    alice_bfast = next(m for m in alice_journal["meals"] if m["meal_type"] == "breakfast")
    assert alice_bfast["total_calories"] == 150.0
    assert len(alice_bfast["items"]) == 1
    assert alice_bfast["items"][0]["name"] == "Oeufs brouillés Alice"

    # Bob consulte son journal
    bob_journal = client.get(f"/api/meals/journal?date={today_str}", headers=headers2).json()
    bob_bfast = next(m for m in bob_journal["meals"] if m["meal_type"] == "breakfast")
    assert bob_bfast["total_calories"] == 500.0
    assert len(bob_bfast["items"]) == 1
    assert bob_bfast["items"][0]["name"] == "Pancakes Bob"

    # Bob ne peut pas supprimer l'aliment d'Alice
    alice_item_id = alice_bfast["items"][0]["id"]
    res_bad_del = client.delete(f"/api/meals/journal/items/{alice_item_id}", headers=headers2)
    assert res_bad_del.status_code == 404
