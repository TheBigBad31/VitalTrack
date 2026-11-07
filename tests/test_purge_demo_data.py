"""Tests unitaires pour la purge des données de démonstration via repositories typés (VTR-006)."""

import pytest
from datetime import date
from src.db import Database
from src.models import ActivityEntry, FoodItem, MealEntry, WeightEntry


def test_purge_demo_data_typed_repositories():
    db = Database()
    user_id = 9999
    db.clear_all_history(keep_profile=False, user_id=user_id)

    # 1. Insérer des données démo et réelles
    weight_demo = WeightEntry(
        date=date(2026, 11, 1),
        weight_kg=80.0,
        source="simulation",
        is_simulated=True,
        notes="Pesée automatique matinale (Balance Démo)"
    )
    weight_real = WeightEntry(
        date=date(2026, 11, 2),
        weight_kg=79.5,
        source="manual",
        is_simulated=False,
        notes="Pesée réelle"
    )
    db.insert_weight(weight_demo, user_id=user_id)
    db.insert_weight(weight_real, user_id=user_id)

    activity_demo = ActivityEntry(
        date=date(2026, 11, 1),
        steps=10000,
        active_calories_kcal=400.0,
        bmr_kcal=1700.0,
        total_burned_kcal=2100.0,
        source="simulation",
        is_simulated=True
    )
    activity_real = ActivityEntry(
        date=date(2026, 11, 2),
        steps=8000,
        active_calories_kcal=300.0,
        bmr_kcal=1700.0,
        total_burned_kcal=2000.0,
        source="ringconn",
        is_simulated=False
    )
    db.insert_activity(activity_demo, user_id=user_id)
    db.insert_activity(activity_real, user_id=user_id)

    meal_demo = MealEntry(
        date=date(2026, 11, 1),
        meal_type="breakfast",
        total_calories_kcal=430.0,
        protein_g=24.0,
        carbs_g=52.0,
        fat_g=14.0,
        fiber_g=7.5,
        items=[
            FoodItem(name="Flocons d'avoine", portion_g=60.0, calories_kcal=219.0, protein_g=8.1, carbs_g=34.8, fat_g=4.2, fiber_g=6.0, confidence_score=0.9),
            FoodItem(name="Myrtilles fraîches", portion_g=80.0, calories_kcal=45.0, protein_g=0.6, carbs_g=11.2, fat_g=0.3, fiber_g=2.0, confidence_score=0.85),
        ]
    )
    meal_real = MealEntry(
        date=date(2026, 11, 2),
        meal_type="lunch",
        total_calories_kcal=500.0,
        protein_g=30.0,
        carbs_g=40.0,
        fat_g=15.0,
        fiber_g=5.0,
        items=[
            FoodItem(name="Steak haché", portion_g=120.0, calories_kcal=250.0, protein_g=25.0, carbs_g=0.0, fat_g=15.0, fiber_g=0.0, confidence_score=0.95),
        ]
    )
    db.insert_meal(meal_demo, user_id=user_id)
    db.insert_meal(meal_real, user_id=user_id)

    # Créer un user de test/démo et un device démo
    db.get_or_create_user(email="sebastien.test@vitaltrack.io", name="Test Démo")
    db.generate_device_token(device_id="ringconn", name="RingConn Gen 3 Sébastien", user_id=user_id)

    # 2. Exécuter purge_demo_data
    res = db.purge_demo_data(user_id=user_id)
    assert isinstance(res, dict)
    assert res["weights"] >= 1
    assert res["activities"] >= 1
    assert res["meals"] >= 1
    assert res["users"] >= 1
    assert res["devices"] >= 1

    # 3. Vérifier que les données réelles sont toujours présentes
    weights = db.get_weights(user_id=user_id)
    assert len(weights) == 1
    assert weights[0].source == "manual"
    assert weights[0].weight_kg == 79.5

    activities = db.get_activities(user_id=user_id)
    assert len(activities) == 1
    assert activities[0].source == "ringconn"
    assert activities[0].steps == 8000

    meals = db.get_meals_for_date(date(2026, 11, 2), user_id=user_id)
    assert len(meals) == 1
    assert meals[0].total_calories_kcal == 500.0

    demo_user = db.get_user_by_email("sebastien.test@vitaltrack.io")
    assert demo_user is None

    # Nettoyage
    db.clear_all_history(keep_profile=False, user_id=user_id)
