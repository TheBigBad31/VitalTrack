"""Tests unitaires pour le module de domaine pur src.domain.nutrition."""

from datetime import date
import pytest
from src.domain.nutrition import (
    calculate_bmr_mifflin_st_jeor,
    calculate_meal_totals,
    calculate_tdee,
    compute_daily_nutrition_summary,
    compute_energy_balance,
)
from src.models import FoodItem, MealEntry
from src.nutrition_engine import NutritionEngine


def test_calculate_meal_totals_empty():
    totals = calculate_meal_totals([])
    assert totals == {
        "calories_kcal": 0.0,
        "protein_g": 0.0,
        "carbs_g": 0.0,
        "fat_g": 0.0,
        "fiber_g": 0.0,
    }


def test_calculate_meal_totals_items():
    items = [
        FoodItem(name="Poulet", portion_g=150, calories_kcal=180.0, protein_g=39.0, carbs_g=0.0, fat_g=2.7, fiber_g=0.0),
        FoodItem(name="Riz", portion_g=180, calories_kcal=234.0, protein_g=4.9, carbs_g=50.4, fat_g=0.5, fiber_g=0.7),
        FoodItem(name="Pomme", portion_g=100, calories_kcal=52.0, protein_g=0.3, carbs_g=14.0, fat_g=0.2, fiber_g=2.4),
    ]
    totals = calculate_meal_totals(items)
    assert totals["calories_kcal"] == 466.0
    assert totals["protein_g"] == 44.2
    assert totals["carbs_g"] == 64.4
    assert totals["fat_g"] == 3.4
    assert totals["fiber_g"] == 3.1


def test_compute_daily_nutrition_summary_empty():
    summary = compute_daily_nutrition_summary("2026-11-07", [])
    assert summary["date"] == "2026-11-07"
    assert summary["meals_count"] == 0
    assert summary["total_calories_kcal"] == 0.0
    assert summary["macros"]["protein_pct"] == 0.0
    assert summary["macros"]["carbs_pct"] == 0.0
    assert summary["macros"]["fat_pct"] == 0.0
    assert summary["macros"]["fiber_g"] == 0.0
    assert summary["by_meal"]["breakfast"] is None


def test_compute_daily_nutrition_summary_with_meals():
    items = [FoodItem(name="Oeuf", portion_g=50, calories_kcal=70.0, protein_g=6.0, carbs_g=0.5, fat_g=5.0, fiber_g=0.0)]
    meal = MealEntry(
        id=1,
        date=date(2026, 11, 7),
        meal_type="breakfast",
        total_calories_kcal=70.0,
        protein_g=6.0,
        carbs_g=0.5,
        fat_g=5.0,
        fiber_g=0.0,
        items=items,
    )
    summary = compute_daily_nutrition_summary("2026-11-07", [meal])
    assert summary["meals_count"] == 1
    assert summary["total_calories_kcal"] == 70.0
    assert summary["by_meal"]["breakfast"] is not None
    assert summary["by_meal"]["breakfast"]["id"] == 1
    assert summary["macros"]["protein_g"] == 6.0


def test_calculate_bmr_mifflin_st_jeor():
    # Male
    bmr_m = calculate_bmr_mifflin_st_jeor(80.0, 178.0, 35, gender="male")
    assert bmr_m == 1742.5

    # Female
    bmr_f = calculate_bmr_mifflin_st_jeor(65.0, 165.0, 30, gender="female")
    assert 1369.0 < bmr_f < 1371.0

    # Min bound (800 kcal)
    bmr_low = calculate_bmr_mifflin_st_jeor(20.0, 100.0, 90, gender="female")
    assert bmr_low == 800.0


def test_calculate_tdee():
    tdee = calculate_tdee(bmr_kcal=1700.0, steps=10000, active_calories_kcal=450.0)
    assert tdee == 2150.0

    # Step burn exceeds active calories
    tdee_steps = calculate_tdee(bmr_kcal=1700.0, steps=15000, active_calories_kcal=200.0)
    assert tdee_steps == round(1700.0 + 15000 * 0.04, 1)


def test_compute_energy_balance_deficit():
    res = compute_energy_balance(
        date_iso="2026-11-07",
        intake_kcal=1800.0,
        burned_kcal=2300.0,
        bmr_kcal=1600.0,
        steps=8000,
        active_calories_kcal=400.0,
        macros={"protein_g": 120.0},
    )
    assert res["status"] == "deficit"
    assert res["net_energy_balance_kcal"] == -500.0
    assert res["weekly_projected_weight_change_kg"] == pytest.approx(-0.455, abs=0.01)


def test_compute_energy_balance_surplus():
    res = compute_energy_balance(
        date_iso="2026-11-07",
        intake_kcal=2800.0,
        burned_kcal=2200.0,
        bmr_kcal=1600.0,
        steps=6000,
        active_calories_kcal=300.0,
        macros={},
    )
    assert res["status"] == "surplus"
    assert res["net_energy_balance_kcal"] == 600.0


def test_compute_energy_balance_maintenance():
    res = compute_energy_balance(
        date_iso="2026-11-07",
        intake_kcal=2000.0,
        burned_kcal=2100.0,
        bmr_kcal=1600.0,
        steps=5000,
        active_calories_kcal=200.0,
        macros={},
    )
    assert res["status"] == "maintenance"
    assert res["net_energy_balance_kcal"] == -100.0


def test_nutrition_engine_with_repositories_di():
    """Vérifie que NutritionEngine peut recevoir directement des instances de repositories."""
    from unittest.mock import MagicMock

    mock_meals = MagicMock()
    mock_weights = MagicMock()

    engine = NutritionEngine(meals_repo=mock_meals, weights_repo=mock_weights)
    assert engine.meals_repo is mock_meals
    assert engine.weights_repo is mock_weights

    # get_meals_by_date
    mock_meals.get_meals_for_date.return_value = []
    meals = engine.get_meals_by_date(date(2026, 11, 7), user_id=42)
    assert meals == []
    mock_meals.get_meals_for_date.assert_called_once_with(date(2026, 11, 7), user_id=42)
