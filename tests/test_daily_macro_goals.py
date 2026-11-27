"""Tests unitaires et d'intégration API pour le suivi quotidien des objectifs nutritionnels (BALI-302)."""

from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.domain.nutrition import (
    compute_daily_macro_goals_history,
    evaluate_nutrient_day_status,
)
from src.models import FoodItem, MealEntry


def test_evaluate_nutrient_day_status_protein_floor_semantics():
    # Protéines : objectif plancher prioritaire (>= 95% atteint, 80-95% proche, < 80% insuffisant)
    assert evaluate_nutrient_day_status("protein", 0, 140)["state"] == "empty"
    assert evaluate_nutrient_day_status("protein", 100, 140)["state"] == "below"
    assert evaluate_nutrient_day_status("protein", 120, 140)["state"] == "close"
    assert evaluate_nutrient_day_status("protein", 134, 140)["state"] == "reached"
    # Dépasser la cible protéines reste atteint (pas une alerte rouge)
    res_high = evaluate_nutrient_day_status("protein", 175, 140)
    assert res_high["state"] == "reached"
    assert res_high["diff"] == 35.0


def test_evaluate_nutrient_day_status_calories_carbs_fat_ranges():
    # Calories : [90%, 108%] atteint, > 115% dépassé
    assert evaluate_nutrient_day_status("calories", 2000, 2000)["state"] == "reached"
    assert evaluate_nutrient_day_status("calories", 2400, 2000)["state"] == "over"
    assert evaluate_nutrient_day_status("calories", 1200, 2000)["state"] == "below"

    # Glucides : [85%, 115%] atteint, > 125% dépassé
    assert evaluate_nutrient_day_status("carbs", 200, 200)["state"] == "reached"
    assert evaluate_nutrient_day_status("carbs", 270, 200)["state"] == "over"

    # Lipides : [80%, 110%] atteint, > 120% dépassé
    assert evaluate_nutrient_day_status("fat", 65, 65)["state"] == "reached"
    assert evaluate_nutrient_day_status("fat", 90, 65)["state"] == "over"


def test_compute_daily_macro_goals_history_streak_and_adherence():
    today = date(2026, 11, 27)
    targets = {"protein_g": 140.0, "calories": 2000.0, "carbs_g": 220.0, "fat_g": 65.0}

    meals = [
        # J-2 : objectif protéines atteint (145g)
        MealEntry(
            id=1,
            date=today - timedelta(days=2),
            meal_type="lunch",
            total_calories_kcal=1980.0,
            protein_g=145.0,
            carbs_g=215.0,
            fat_g=64.0,
            items=[FoodItem(name="Poulet Riz", portion_g=400, calories_kcal=1980.0, protein_g=145.0, carbs_g=215.0, fat_g=64.0)],
        ),
        # J-1 : objectif protéines atteint (150g)
        MealEntry(
            id=2,
            date=today - timedelta(days=1),
            meal_type="dinner",
            total_calories_kcal=2050.0,
            protein_g=150.0,
            carbs_g=225.0,
            fat_g=66.0,
            items=[FoodItem(name="Saumon Quinoa", portion_g=450, calories_kcal=2050.0, protein_g=150.0, carbs_g=225.0, fat_g=66.0)],
        ),
        # Aujourd'hui : objectif protéines atteint en 2 repas (70 + 72 = 142g)
        MealEntry(
            id=3,
            date=today,
            meal_type="breakfast",
            total_calories_kcal=900.0,
            protein_g=70.0,
            carbs_g=100.0,
            fat_g=30.0,
            items=[FoodItem(name="Omelette", portion_g=250, calories_kcal=900.0, protein_g=70.0, carbs_g=100.0, fat_g=30.0)],
        ),
        MealEntry(
            id=4,
            date=today,
            meal_type="lunch",
            total_calories_kcal=1080.0,
            protein_g=72.0,
            carbs_g=115.0,
            fat_g=33.0,
            items=[FoodItem(name="Steak", portion_g=300, calories_kcal=1080.0, protein_g=72.0, carbs_g=115.0, fat_g=33.0)],
        ),
    ]

    history = compute_daily_macro_goals_history(
        meals=meals,
        targets=targets,
        today=today,
        days=7,
        weight_kg=78.0,
    )

    assert history["days"] == 7
    assert len(history["daily"]) == 7
    assert history["daily"][-1]["date"] == "2026-11-27"
    assert history["daily"][-1]["protein_g"] == 142.0
    assert history["daily"][-1]["protein_per_kg"] == pytest.approx(142.0 / 78.0, abs=0.02)

    prot_metrics = history["metrics"]["protein"]
    assert prot_metrics["logged_days"] == 3
    assert prot_metrics["days_reached"] == 3
    assert prot_metrics["adherence_pct"] == 100.0
    assert prot_metrics["current_streak"] == 3
    assert prot_metrics["today_state"] == "reached"
    assert prot_metrics["today_remaining"] == 0.0
    assert prot_metrics["target_per_kg"] == pytest.approx(140.0 / 78.0, abs=0.02)


def test_api_dashboard_and_goals_history_endpoint():
    client = TestClient(app)

    res_dash = client.get("/api/dashboard")
    assert res_dash.status_code == 200
    dash_data = res_dash.json()
    assert "daily_goals_history" in dash_data
    dgh = dash_data["daily_goals_history"]
    assert dgh["days"] == 30
    assert len(dgh["daily"]) == 30
    assert set(dgh["metrics"].keys()) == {"protein", "calories", "carbs", "fat"}

    res_hist = client.get("/api/nutrition/goals-history?days=14")
    assert res_hist.status_code == 200
    hist_data = res_hist.json()
    assert hist_data["days"] == 14
    assert len(hist_data["daily"]) == 14
    assert "protein" in hist_data["metrics"]
    assert "calories" in hist_data["metrics"]
    assert "carbs" in hist_data["metrics"]
    assert "fat" in hist_data["metrics"]
