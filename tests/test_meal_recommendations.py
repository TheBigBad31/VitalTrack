"""Tests unitaires pour les moyennes par repas et recommandations pondérées."""

from datetime import date
from src.meal_recommendations import (
    compute_weighted_meal_recommendations,
    get_daily_nutrition_targets,
)


def test_compute_weighted_recommendations_with_history():
    """Si le déjeuner est rempli, les recommandations pour goûter et dîner sont pondérées selon leurs moyennes."""
    meals_response = [
        {"meal_type": "breakfast", "total_calories": 400.0, "items": [{"name": "Avoine"}]},
        {"meal_type": "lunch", "total_calories": 700.0, "items": [{"name": "Poulet riz"}]},
        {"meal_type": "snack", "total_calories": 0.0, "items": []},
        {"meal_type": "dinner", "total_calories": 0.0, "items": []},
    ]
    day_summary = {
        "total_calories": 1100.0,
        "total_protein_g": 80.0,
        "total_carbs_g": 120.0,
        "total_fat_g": 30.0,
        "total_fiber_g": 12.0,
    }
    targets = {
        "calories": 2100.0,
        "protein_g": 150.0,
        "carbs_g": 220.0,
        "fat_g": 70.0,
        "fiber_g": 25.0,
    }
    # Historique : goûter = 250 kcal, dîner = 750 kcal (ratio 1:3)
    meal_averages = {
        "breakfast": {"calories": 400.0, "protein_g": 20.0, "carbs_g": 50.0, "fat_g": 10.0, "fiber_g": 5.0, "sample_count": 5},
        "lunch": {"calories": 700.0, "protein_g": 50.0, "carbs_g": 70.0, "fat_g": 20.0, "fiber_g": 7.0, "sample_count": 5},
        "snack": {"calories": 250.0, "protein_g": 10.0, "carbs_g": 30.0, "fat_g": 10.0, "fiber_g": 3.0, "sample_count": 4},
        "dinner": {"calories": 750.0, "protein_g": 60.0, "carbs_g": 70.0, "fat_g": 30.0, "fiber_g": 10.0, "sample_count": 5},
    }

    res = compute_weighted_meal_recommendations(meals_response, day_summary, targets, meal_averages)

    assert res["remaining"]["calories"] == 1000.0
    assert res["remaining"]["protein_g"] == 70.0
    assert res["unfilled_meals"] == ["snack", "dinner"]

    # Snack doit recevoir 250 / (250 + 750) = 25% de 1000 = 250 kcal (fourchette 225 - 275)
    snack_cal = res["recommendations"]["snack"]["calories"]
    assert snack_cal["target"] == 250.0
    assert snack_cal["min"] == 225.0
    assert snack_cal["max"] == 275.0
    assert res["recommendations"]["snack"]["based_on"] == "history"

    # Dinner doit recevoir 750 / 1000 = 75% de 1000 = 750 kcal (fourchette 675 - 825)
    dinner_cal = res["recommendations"]["dinner"]["calories"]
    assert dinner_cal["target"] == 750.0
    assert dinner_cal["min"] == 675.0
    assert dinner_cal["max"] == 825.0


def test_compute_weighted_recommendations_without_history_uses_default_shares():
    """Sans historique, les parts par défaut (snack=10%, dinner=30%) pondèrent les repas restants."""
    meals_response = [
        {"meal_type": "breakfast", "total_calories": 500.0, "items": [{"name": "Oeufs"}]},
        {"meal_type": "lunch", "total_calories": 700.0, "items": [{"name": "Salade"}]},
        {"meal_type": "snack", "total_calories": 0.0, "items": []},
        {"meal_type": "dinner", "total_calories": 0.0, "items": []},
    ]
    day_summary = {
        "total_calories": 1200.0,
        "total_protein_g": 80.0,
        "total_carbs_g": 100.0,
        "total_fat_g": 40.0,
        "total_fiber_g": 10.0,
    }
    targets = {
        "calories": 2000.0,
        "protein_g": 140.0,
        "carbs_g": 200.0,
        "fat_g": 70.0,
        "fiber_g": 25.0,
    }
    empty_averages = {
        mt: {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fiber_g": 0.0, "sample_count": 0}
        for mt in ("breakfast", "lunch", "snack", "dinner")
    }

    res = compute_weighted_meal_recommendations(meals_response, day_summary, targets, empty_averages)

    # Restant = 800 kcal. Parts par défaut: snack=0.10, dinner=0.30 -> ratio 1:3 -> 200 et 600 kcal
    assert res["recommendations"]["snack"]["calories"]["target"] == 200.0
    assert res["recommendations"]["dinner"]["calories"]["target"] == 600.0
    assert res["recommendations"]["snack"]["based_on"] == "default_share"


def test_compute_weighted_recommendations_all_filled():
    """Si tous les repas sont remplis, aucune recommandation n'est générée."""
    meals_response = [
        {"meal_type": mt, "total_calories": 500.0, "items": [{"name": "Repas"}]}
        for mt in ("breakfast", "lunch", "snack", "dinner")
    ]
    day_summary = {"total_calories": 2000.0, "total_protein_g": 140.0, "total_carbs_g": 200.0, "total_fat_g": 70.0, "total_fiber_g": 25.0}
    targets = {"calories": 2000.0, "protein_g": 140.0, "carbs_g": 200.0, "fat_g": 70.0, "fiber_g": 25.0}

    res = compute_weighted_meal_recommendations(meals_response, day_summary, targets, {})
    assert res["unfilled_meals"] == []
    assert res["recommendations"] == {}


def test_compute_weighted_recommendations_suggests_matching_historical_meal():
    """Suggère le repas historique le plus proche des besoins du créneau (en privilégiant le même meal_type)."""
    meals_response = [
        {"meal_type": "breakfast", "total_calories": 400.0, "items": [{"name": "Avoine"}]},
        {"meal_type": "lunch", "total_calories": 700.0, "items": [{"name": "Poulet riz"}]},
        {"meal_type": "snack", "total_calories": 0.0, "items": []},
        {"meal_type": "dinner", "total_calories": 0.0, "items": []},
    ]
    day_summary = {
        "total_calories": 1100.0,
        "total_protein_g": 80.0,
        "total_carbs_g": 120.0,
        "total_fat_g": 30.0,
        "total_fiber_g": 12.0,
    }
    targets = {
        "calories": 2100.0,
        "protein_g": 150.0,
        "carbs_g": 220.0,
        "fat_g": 70.0,
        "fiber_g": 25.0,
    }
    meal_averages = {
        "breakfast": {"calories": 400.0, "protein_g": 20.0, "carbs_g": 50.0, "fat_g": 10.0, "fiber_g": 5.0, "sample_count": 5},
        "lunch": {"calories": 700.0, "protein_g": 50.0, "carbs_g": 70.0, "fat_g": 20.0, "fiber_g": 7.0, "sample_count": 5},
        "snack": {"calories": 250.0, "protein_g": 10.0, "carbs_g": 30.0, "fat_g": 10.0, "fiber_g": 3.0, "sample_count": 4},
        "dinner": {"calories": 750.0, "protein_g": 60.0, "carbs_g": 70.0, "fat_g": 30.0, "fiber_g": 10.0, "sample_count": 5},
    }
    historical_meals = [
        {
            "id": 10,
            "date": "2026-11-10",
            "meal_type": "snack",
            "calories": 240.0,
            "protein_g": 12.0,
            "carbs_g": 28.0,
            "fat_g": 9.0,
            "fiber_g": 3.0,
            "items": [{"food_item_id": 1, "name": "Yaourt grec", "quantity": 150.0, "unit": "g", "calories": 140.0}],
        },
        {
            "id": 11,
            "date": "2026-11-11",
            "meal_type": "dinner",
            "calories": 740.0,
            "protein_g": 58.0,
            "carbs_g": 68.0,
            "fat_g": 28.0,
            "fiber_g": 9.0,
            "items": [
                {"food_item_id": 2, "name": "Saumon", "quantity": 180.0, "unit": "g", "calories": 380.0},
                {"food_item_id": 3, "name": "Quinoa", "quantity": 200.0, "unit": "g", "calories": 360.0},
            ],
        },
    ]

    res = compute_weighted_meal_recommendations(
        meals_response, day_summary, targets, meal_averages, historical_meals=historical_meals
    )

    snack_sug = res["recommendations"]["snack"]["suggested_meal"]
    assert snack_sug["meal_log_id"] == 10
    assert snack_sug["title"] == "Yaourt grec"

    dinner_sug = res["recommendations"]["dinner"]["suggested_meal"]
    assert dinner_sug["meal_log_id"] == 11
    assert dinner_sug["title"] == "Saumon, Quinoa"
