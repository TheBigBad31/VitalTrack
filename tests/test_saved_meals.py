"""Tests complets pour la bibliothèque de plats réutilisables / sauvegardés."""

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
    user1 = test_db.get_or_create_user(email="user1@vitaltrack.local", name="User 1")
    user2 = test_db.get_or_create_user(email="user2@vitaltrack.local", name="User 2")

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


def test_saved_meals_crud(test_setup):
    """Vérifie la création, lecture, filtrage, mise à jour et suppression de plats sauvegardés."""
    client = test_setup["client"]
    token1 = test_setup["token1"]
    headers = {"Authorization": f"Bearer {token1}"}

    # 1. Création d'un plat de petit déjeuner
    meal_breakfast = {
        "name": "Bowl Flocons d'Avoine & Fruits Rouges",
        "meal_type": "breakfast",
        "serving_size": "1 bol (350g)",
        "quantity_grams": 350.0,
        "calories": 420.0,
        "protein_g": 22.0,
        "carbs_g": 58.0,
        "fat_g": 9.5,
        "fiber_g": 8.0,
        "ingredients": "Flocons d'avoine, fromage blanc 0%, myrtilles, graines de chia",
        "items": [
            {"name": "Flocons d'avoine", "portion_g": 60.0, "calories_kcal": 220.0, "protein_g": 8.0, "carbs_g": 38.0, "fat_g": 4.0},
            {"name": "Fromage blanc 0%", "portion_g": 200.0, "calories_kcal": 100.0, "protein_g": 14.0, "carbs_g": 8.0, "fat_g": 0.0},
            {"name": "Myrtilles", "portion_g": 90.0, "calories_kcal": 100.0, "protein_g": 0.0, "carbs_g": 12.0, "fat_g": 5.5}
        ],
        "photo_url": "data:image/jpeg;base64,mockphotodata",
        "is_favorite": True
    }

    res_post = client.post("/api/meals/saved", json=meal_breakfast, headers=headers)
    assert res_post.status_code == 200
    created = res_post.json()
    assert created["id"] is not None
    assert created["name"] == meal_breakfast["name"]
    assert created["calories"] == 420.0
    assert created["is_favorite"] is True
    assert len(created["items"]) == 3
    meal_id = created["id"]

    # 2. Création d'un plat de déjeuner
    meal_lunch = {
        "name": "Poulet Riz Basmati & Haricots Verts",
        "meal_type": "lunch",
        "serving_size": "1 assiette",
        "quantity_grams": 400.0,
        "calories": 520.0,
        "protein_g": 45.0,
        "carbs_g": 55.0,
        "fat_g": 10.0,
        "is_favorite": False
    }
    res_lunch = client.post("/api/meals/saved", json=meal_lunch, headers=headers)
    assert res_lunch.status_code == 200
    lunch_id = res_lunch.json()["id"]

    # 3. Récupération de tous les plats
    res_list = client.get("/api/meals/saved", headers=headers)
    assert res_list.status_code == 200
    all_meals = res_list.json()
    assert len(all_meals) == 2

    # 4. Filtrage par meal_type=breakfast
    res_filter = client.get("/api/meals/saved?meal_type=breakfast", headers=headers)
    assert res_filter.status_code == 200
    breakfast_only = res_filter.json()
    assert len(breakfast_only) == 1
    assert breakfast_only[0]["name"] == meal_breakfast["name"]

    # 5. Filtrage par favoris
    res_fav = client.get("/api/meals/saved?is_favorite=true", headers=headers)
    assert res_fav.status_code == 200
    fav_only = res_fav.json()
    assert len(fav_only) == 1
    assert fav_only[0]["id"] == meal_id

    # 6. Lecture d'un plat par son ID
    res_get = client.get(f"/api/meals/saved/{meal_id}", headers=headers)
    assert res_get.status_code == 200
    assert res_get.json()["name"] == meal_breakfast["name"]

    # 7. Mise à jour du plat
    res_put = client.put(f"/api/meals/saved/{meal_id}", json={"calories": 450.0, "serving_size": "Grand bol"}, headers=headers)
    assert res_put.status_code == 200
    assert res_put.json()["calories"] == 450.0
    assert res_put.json()["serving_size"] == "Grand bol"

    # 8. Suppression du plat déjeuner
    res_del = client.delete(f"/api/meals/saved/{lunch_id}", headers=headers)
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "success"

    # Vérification qu'il ne reste qu'un plat
    res_after = client.get("/api/meals/saved", headers=headers)
    assert len(res_after.json()) == 1


def test_saved_meal_logging_to_journal(test_setup):
    """Vérifie le logging direct d'un plat sauvegardé dans le journal avec facteur de portion."""
    client = test_setup["client"]
    token1 = test_setup["token1"]
    headers = {"Authorization": f"Bearer {token1}"}

    # Création plat
    meal_data = {
        "name": "Collation Protéinée Banane Beurre de Cacahuète",
        "meal_type": "snack",
        "serving_size": "1 portion",
        "quantity_grams": 200.0,
        "calories": 300.0,
        "protein_g": 15.0,
        "carbs_g": 35.0,
        "fat_g": 10.0,
        "fiber_g": 5.0,
        "photo_url": "mock_photo_url",
        "items": [
            {"name": "Banane", "portion_g": 120.0, "calories_kcal": 110.0, "protein_g": 1.0, "carbs_g": 26.0, "fat_g": 0.0},
            {"name": "Beurre de cacahuète", "portion_g": 30.0, "calories_kcal": 190.0, "protein_g": 8.0, "carbs_g": 6.0, "fat_g": 16.0}
        ]
    }
    res_post = client.post("/api/meals/saved", json=meal_data, headers=headers)
    meal_id = res_post.json()["id"]

    # Logging avec facteur portion 1.5
    res_log = client.post(f"/api/meals/saved/{meal_id}/log", json={"portion_factor": 1.5, "meal_type": "snack"}, headers=headers)
    assert res_log.status_code == 200
    log_data = res_log.json()
    assert log_data["status"] == "success"

    logged = log_data["logged_meal"]
    assert logged["total_calories_kcal"] == 450.0  # 300 * 1.5
    assert logged["protein_g"] == 22.5  # 15 * 1.5
    assert logged["meal_type"] == "snack"
    assert logged["photo_data_url"] == "mock_photo_url"
    assert len(logged["items"]) == 2
    assert logged["items"][0]["calories_kcal"] == 165.0  # 110 * 1.5

    # Vérification que le repas apparaît bien dans GET /api/meals
    res_meals = client.get("/api/meals", headers=headers)
    assert res_meals.status_code == 200
    meals_list = res_meals.json()
    assert any(m["id"] == logged["id"] for m in meals_list)


def test_saved_meals_isolation(test_setup):
    """Vérifie l'étanchéité multi-utilisateurs (User 1 ne voit pas les plats de User 2)."""
    client = test_setup["client"]
    token1 = test_setup["token1"]
    token2 = test_setup["token2"]

    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}

    # User 1 crée un plat
    res1 = client.post("/api/meals/saved", json={"name": "Plat Secret User 1", "meal_type": "dinner", "calories": 600.0}, headers=headers1)
    meal1_id = res1.json()["id"]

    # User 2 crée un plat
    res2 = client.post("/api/meals/saved", json={"name": "Plat Public User 2", "meal_type": "dinner", "calories": 700.0}, headers=headers2)
    meal2_id = res2.json()["id"]

    # User 1 ne liste que son plat
    list1 = client.get("/api/meals/saved", headers=headers1).json()
    assert len(list1) == 1
    assert list1[0]["id"] == meal1_id

    # User 2 ne liste que son plat
    list2 = client.get("/api/meals/saved", headers=headers2).json()
    assert len(list2) == 1
    assert list2[0]["id"] == meal2_id

    # User 1 ne peut pas accéder au plat de User 2
    get_fail = client.get(f"/api/meals/saved/{meal2_id}", headers=headers1)
    assert get_fail.status_code == 404

    # User 1 ne peut pas modifier ni supprimer le plat de User 2
    put_fail = client.put(f"/api/meals/saved/{meal2_id}", json={"name": "Hacked"}, headers=headers1)
    assert put_fail.status_code == 404
    del_fail = client.delete(f"/api/meals/saved/{meal2_id}", headers=headers1)
    assert del_fail.status_code == 404
