"""Tests unitaires et d'intégration API pour le suivi quotidien des objectifs nutritionnels (BALI-302)."""

from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.domain.nutrition import (
    compute_daily_macro_goals_history,
    evaluate_nutrient_day_status,
    resolve_nutrition_goals,
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
    assert "rules" in hist_data


def test_evaluate_nutrient_day_status_configurable_rules():
    """Vérifie l'évaluation selon les 3 modes configurables : plancher (min), plafond (max), fourchette (range)."""
    # 1. Mode plancher (>= 180 g)
    min_rule = {"mode": "min", "min": 180.0, "max": None, "target": 180.0}
    assert evaluate_nutrient_day_status("protein", 0, 180, rule=min_rule)["state"] == "empty"
    assert evaluate_nutrient_day_status("protein", 140, 180, rule=min_rule)["state"] == "below"
    assert evaluate_nutrient_day_status("protein", 160, 180, rule=min_rule)["state"] == "close"
    assert evaluate_nutrient_day_status("protein", 180, 180, rule=min_rule)["state"] == "reached"
    assert evaluate_nutrient_day_status("protein", 210, 180, rule=min_rule)["state"] == "reached"

    # 2. Mode plafond (<= 65 g)
    max_rule = {"mode": "max", "min": None, "max": 65.0, "target": 65.0}
    assert evaluate_nutrient_day_status("fat", 45, 65, rule=max_rule)["state"] == "reached"
    assert evaluate_nutrient_day_status("fat", 65, 65, rule=max_rule)["state"] == "reached"
    assert evaluate_nutrient_day_status("fat", 70, 65, rule=max_rule)["state"] == "close"
    assert evaluate_nutrient_day_status("fat", 80, 65, rule=max_rule)["state"] == "over"

    # 3. Mode fourchette ([1800, 2100] kcal)
    range_rule = {"mode": "range", "min": 1800.0, "max": 2100.0, "target": 1950.0}
    assert evaluate_nutrient_day_status("calories", 1400, 1950, rule=range_rule)["state"] == "below"
    assert evaluate_nutrient_day_status("calories", 1600, 1950, rule=range_rule)["state"] == "close"
    assert evaluate_nutrient_day_status("calories", 1900, 1950, rule=range_rule)["state"] == "reached"
    assert evaluate_nutrient_day_status("calories", 2200, 1950, rule=range_rule)["state"] == "close"
    assert evaluate_nutrient_day_status("calories", 2500, 1950, rule=range_rule)["state"] == "over"


def test_resolve_nutrition_goals_protein_per_kg_never_overridden_by_legacy_140g():
    """Régression BALI-303 : un profil à 1.8 g/kg pour 100 kg doit donner 180 g même si daily_protein_target_g=140 traîne en BDD."""
    legacy_profile = {
        "goal_profile_id": "weight_loss",
        "protein_target_per_kg": 1.8,
        "daily_protein_target_g": 140.0,
        "target_calories_intake": 2000.0,
        "current_weight_kg": 100.0,
        "nutrition_goals_config": None,
    }
    resolved = resolve_nutrition_goals(legacy_profile, weight_kg=100.0, target_calories_override=2100.0)
    assert resolved["protein_g"] == 180.0
    assert resolved["protein_per_kg"] == 1.8
    assert resolved["rules"]["protein"]["mode"] == "min"
    assert resolved["rules"]["protein"]["min"] == 180.0

    # Si l'utilisateur choisit explicitement le mode grammes fixes (unit="g"), sa valeur fixe est respectée
    fixed_profile = {
        **legacy_profile,
        "nutrition_goals_config": {
            "protein": {"mode": "range", "unit": "g", "min": 150.0, "max": 170.0},
            "calories": {"mode": "max", "source": "fixed", "max": 1950.0},
            "carbs": {"mode": "range", "source": "fixed", "min": 160.0, "max": 200.0},
            "fat": {"mode": "max", "source": "fixed", "max": 60.0},
        },
    }
    res_fixed = resolve_nutrition_goals(fixed_profile, weight_kg=100.0, target_calories_override=2400.0)
    assert res_fixed["protein_g"] == 160.0
    assert res_fixed["rules"]["protein"]["min"] == 150.0
    assert res_fixed["rules"]["protein"]["max"] == 170.0
    assert res_fixed["calories"] == 1950.0
    assert res_fixed["rules"]["calories"]["mode"] == "max"
    assert res_fixed["carbs_g"] == 180.0
    assert res_fixed["fat_g"] == 60.0


def test_api_goals_config_unified_across_all_endpoints(tmp_path):
    """Vérifie que les objectifs configurés via PUT /api/profile se propagent à /api/dashboard, /api/meals/journal et /api/nutrition/goals-history."""
    from src import app as app_module
    from src.db import Database
    from src.auth import create_access_token

    db_path = str(tmp_path / "bali303_goals.db")
    test_db = Database(db_path=db_path)
    user = test_db.get_or_create_user(email="goals@vitaltrack.local", name="Goals Tester")
    token = create_access_token(user["id"], user["uuid"], user["email"], user["name"])
    headers = {"Authorization": f"Bearer {token}"}

    old_db = app_module.db
    app_module.db = test_db
    app_module.invalidate_dashboard_cache()
    try:
        client = TestClient(app)

        # Configurer 2.0 g/kg pour 90 kg -> 180 g/j, calories fixes [1700, 1950], lipides plafond <= 60 g
        payload = {
            "current_weight_kg": 90.0,
            "goal_profile_id": "weight_loss",
            "protein_target_per_kg": 2.0,
            "daily_protein_target_g": None,
            "nutrition_goals_config": {
                "protein": {"mode": "min", "unit": "per_kg", "min": 2.0, "max": None},
                "calories": {"mode": "range", "source": "fixed", "min": 1700.0, "max": 1950.0},
                "carbs": {"mode": "range", "source": "fixed", "min": 150.0, "max": 210.0},
                "fat": {"mode": "max", "source": "fixed", "max": 60.0},
            },
        }
        res_put = client.put("/api/profile", json=payload, headers=headers)
        assert res_put.status_code == 200

        # Une mise à jour partielle ultérieure (poids cible) ne doit pas écraser nutrition_goals_config
        res_partial = client.put("/api/profile", json={"target_weight_kg": 82.0}, headers=headers)
        assert res_partial.status_code == 200

        res_dash = client.get("/api/dashboard", headers=headers)
        assert res_dash.status_code == 200
        dash = res_dash.json()
        assert dash["summary"]["targets"]["protein_g"] == 180.0
        assert dash["summary"]["targets"]["calories"] == 1825.0
        assert dash["summary"]["targets"]["fat_g"] == 60.0
        assert dash["summary"]["targets"]["rules"]["fat"]["mode"] == "max"
        assert dash["daily_goals_history"]["targets"]["protein_g"] == 180.0
        assert dash["daily_goals_history"]["rules"]["calories"]["min"] == 1700.0
        assert dash["daily_goals_history"]["rules"]["calories"]["max"] == 1950.0

        res_journal = client.get("/api/meals/journal", headers=headers)
        assert res_journal.status_code == 200
        journal = res_journal.json()
        assert journal["targets"]["protein_g"] == 180.0
        assert journal["targets"]["calories"] == 1825.0
        assert journal["targets"]["fat_g"] == 60.0

        res_hist = client.get("/api/nutrition/goals-history?days=7", headers=headers)
        assert res_hist.status_code == 200
        hist = res_hist.json()
        assert hist["targets"]["protein_g"] == 180.0
        assert hist["targets"]["calories"] == 1825.0
        assert hist["rules"]["fat"]["mode"] == "max"
    finally:
        app_module.db = old_db
        app_module.invalidate_dashboard_cache()
