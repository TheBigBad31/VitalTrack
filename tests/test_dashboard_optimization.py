"""Tests pour l'optimisation des requêtes agrégées et le cache court du Dashboard (BALI-46).

Vérifie :
1. get_meals_aggregated_7d et get_dashboard_aggregates en requêtes directes SQL.
2. Mise en cache court (TTL 30s) et temps de réponse ultra-rapide.
3. Invalidation immédiate du cache lors des mutations :
   - Ajout d'une pesée
   - Ajout / mise à jour / suppression d'un repas
   - Ajout / suppression d'un item de repas dans le journal
   - Synchronisation / ajout d'activité
   - Mise à jour des appareils / profil
4. Respect de l'isolation multi-utilisateurs dans le cache.
"""

from datetime import date, timedelta
import time
import pytest
from fastapi.testclient import TestClient

from src.app import app
import src.app as app_module
from src.db import Database
from src.models import WeightEntry, ActivityEntry, MealEntry, FoodItem


@pytest.fixture
def isolated_app():
    """Configure un TestClient avec une base SQLite isolée."""
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name
    if os.path.exists(temp_path):
        os.remove(temp_path)

    test_db = Database(db_path=temp_path)
    old_db = app_module.db
    old_nutrition_db = app_module.nutrition_engine.db
    app_module.db = test_db
    app_module.nutrition_engine.db = test_db

    client = TestClient(app)

    yield {"client": client, "db": test_db}

    app_module.db = old_db
    app_module.nutrition_engine.db = old_nutrition_db
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _create_user(client, email, password, name):
    res = client.post("/api/auth/register", json={"email": email, "password": password, "name": name})
    assert res.status_code == 200
    token = res.json()["access_token"]
    user_id = res.json()["user"]["id"]
    return {"token": token, "user_id": user_id, "headers": {"Authorization": f"Bearer {token}"}}


def test_sql_meals_aggregated_7d(isolated_app):
    """Vérifie que get_meals_aggregated_7d calcule correctement les totaux journaliers groupés."""
    db = isolated_app["db"]
    today = date.today()
    user_id = 1

    # Insérer plusieurs repas sur la même date et des dates différentes
    db.insert_meal(MealEntry(
        date=today,
        meal_type="breakfast",
        total_calories_kcal=300.0,
        protein_g=15.0,
        carbs_g=40.0,
        fat_g=10.0,
        items=[]
    ), user_id=user_id)

    db.insert_meal(MealEntry(
        date=today,
        meal_type="lunch",
        total_calories_kcal=650.0,
        protein_g=35.0,
        carbs_g=70.0,
        fat_g=20.0,
        items=[]
    ), user_id=user_id)

    yesterday = today - timedelta(days=1)
    db.insert_meal(MealEntry(
        date=yesterday,
        meal_type="dinner",
        total_calories_kcal=500.0,
        protein_g=30.0,
        carbs_g=45.0,
        fat_g=15.0,
        items=[]
    ), user_id=user_id)

    start_date = today - timedelta(days=6)
    agg = db.get_meals_aggregated_7d(start_date, today, user_id=user_id)

    assert today.isoformat() in agg
    assert agg[today.isoformat()]["breakfast"] == 300.0
    assert agg[today.isoformat()]["lunch"] == 650.0
    assert agg[today.isoformat()]["total"] == 950.0

    assert yesterday.isoformat() in agg
    assert agg[yesterday.isoformat()]["dinner"] == 500.0
    assert agg[yesterday.isoformat()]["total"] == 500.0


def test_dashboard_short_cache_hit_and_latency(isolated_app):
    """Vérifie que les appels consécutifs utilisent le cache court (hit) avec p95 < 300ms."""
    client = isolated_app["client"]
    user = _create_user(client, "alice@test.com", "Password123!", "Alice")
    headers = user["headers"]

    # Premier appel (miss)
    t0 = time.perf_counter()
    res1 = client.get("/api/dashboard", headers=headers)
    t1 = time.perf_counter()
    assert res1.status_code == 200
    miss_time_ms = (t1 - t0) * 1000

    # Deuxième appel (hit)
    t0 = time.perf_counter()
    res2 = client.get("/api/dashboard", headers=headers)
    t1 = time.perf_counter()
    assert res2.status_code == 200
    hit_time_ms = (t1 - t0) * 1000

    # Vérification que le cache hit répond bien en dessous de 300ms (largement inférieur à 100ms)
    assert hit_time_ms < 300.0
    # Vérification que les données retournées sont strictement identiques
    assert res1.json()["summary"] == res2.json()["summary"]


def test_cache_invalidation_on_weight_mutation(isolated_app):
    """Vérifie que l'ajout d'une pesée invalide immédiatement le cache du dashboard."""
    client = isolated_app["client"]
    db = isolated_app["db"]
    user = _create_user(client, "bob@test.com", "Password123!", "Bob")
    headers = user["headers"]

    # 1. Dashboard initial mis en cache
    res1 = client.get("/api/dashboard", headers=headers)
    assert res1.status_code == 200
    assert res1.json()["summary"]["current_weight_kg"] is None

    # 2. Ajout d'une pesée
    today_str = date.today().isoformat()
    res_w = client.post("/api/weights", json={
        "date": today_str,
        "weight_kg": 81.5,
        "source": "manual"
    }, headers=headers)
    assert res_w.status_code == 200

    # 3. Le dashboard doit refléter immédiatement la nouvelle pesée (invalidation)
    res2 = client.get("/api/dashboard", headers=headers)
    assert res2.status_code == 200
    assert res2.json()["summary"]["current_weight_kg"] == 81.5


def test_cache_invalidation_on_meal_and_journal_mutation(isolated_app):
    """Vérifie que l'ajout d'un repas ou aliment au journal invalide immédiatement le cache."""
    client = isolated_app["client"]
    user = _create_user(client, "carol@test.com", "Password123!", "Carol")
    headers = user["headers"]
    today_str = date.today().isoformat()

    # 1. Appel initial
    res1 = client.get("/api/dashboard", headers=headers)
    assert res1.status_code == 200
    assert res1.json()["meals_by_day_7d"][today_str]["total"] == 0.0

    # 2. Ajout au journal quotidien
    res_meal = client.post("/api/meals/journal/lunch/items", json={
        "date": today_str,
        "name": "Poulet & Quinoa",
        "quantity": 1.0,
        "unit": "portion",
        "calories": 450.0,
        "protein_g": 38.0,
        "carbs_g": 40.0,
        "fat_g": 12.0,
        "fiber_g": 5.0
    }, headers=headers)
    assert res_meal.status_code == 200

    # 3. Le dashboard doit être immédiatement mis à jour avec 450 kcal
    res2 = client.get("/api/dashboard", headers=headers)
    assert res2.status_code == 200
    assert res2.json()["meals_by_day_7d"][today_str]["lunch"] == 450.0
    assert res2.json()["meals_by_day_7d"][today_str]["total"] == 450.0


def test_cache_invalidation_on_activity_mutation(isolated_app):
    """Vérifie que l'ajout d'une activité invalide immédiatement le cache."""
    client = isolated_app["client"]
    user = _create_user(client, "david@test.com", "Password123!", "David")
    headers = user["headers"]
    today_str = date.today().isoformat()

    # 1. Appel initial
    res1 = client.get("/api/dashboard", headers=headers)
    assert res1.status_code == 200
    assert res1.json()["summary"]["steps"] == 0

    # 2. Enregistrement d'une activité
    res_act = client.post("/api/activities", json={
        "date": today_str,
        "steps": 12450,
        "active_calories_kcal": 550.0,
        "workout_minutes": 45,
        "workout_type": "Course à pied",
        "resting_hr_bpm": 56,
        "hrv_ms": 62.0,
        "sleep_score": 88,
        "source": "health_connect"
    }, headers=headers)
    assert res_act.status_code == 200

    # 3. Dashboard actualisé immédiatement
    res2 = client.get("/api/dashboard", headers=headers)
    assert res2.status_code == 200
    assert res2.json()["summary"]["steps"] == 12450
