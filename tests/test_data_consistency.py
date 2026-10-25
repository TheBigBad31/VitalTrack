"""Tests de contrat : le resume du jour (dashboard), le journal alimentaire et les
graphiques (repartition par jour) doivent renvoyer les memes totaux pour une meme date."""

import os
import tempfile
from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.auth import create_access_token
from src.db import Database


@pytest.fixture
def ctx():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    os.remove(path)

    test_db = Database(db_path=path)
    user = test_db.get_or_create_user(email="contract@vitaltrack.local", name="Contract")
    token = create_access_token(user["id"], user["uuid"], user["email"], user["name"])

    from src import app as app_module
    old_db = app_module.db
    app_module.db = test_db
    # Le moteur nutritionnel garde sa propre reference a la base.
    engine = app_module.nutrition_engine
    old_engine_db = getattr(engine, "db", None)
    if old_engine_db is not None:
        engine.db = test_db

    yield {"client": TestClient(app), "headers": {"Authorization": f"Bearer {token}"}}

    app_module.db = old_db
    if old_engine_db is not None:
        engine.db = old_engine_db
    try:
        os.remove(path)
    except OSError:
        pass


def _add_food(client, headers, name, kcal, p, c, f):
    res = client.post("/api/catalog/items", json={
        "name": name, "item_type": "food", "default_unit": "g", "default_quantity": 100.0,
        "calories_per_unit": kcal, "protein_per_unit_g": p, "carbs_per_unit_g": c,
        "fat_per_unit_g": f, "fiber_per_unit_g": 0.0,
    }, headers=headers)
    assert res.status_code == 200
    return res.json()["id"]


def _log(client, headers, meal_type, food_id, qty, day):
    res = client.post(f"/api/meals/journal/{meal_type}/items", json={
        "date": day, "food_item_id": food_id, "quantity": qty, "unit": "g",
    }, headers=headers)
    assert res.status_code == 200


def _seed(client, headers, day):
    riz = _add_food(client, headers, "Riz", 130.0, 2.7, 28.0, 0.3)
    poulet = _add_food(client, headers, "Poulet", 120.0, 26.0, 0.0, 1.5)
    _log(client, headers, "breakfast", riz, 80.0, day)
    _log(client, headers, "lunch", riz, 150.0, day)
    _log(client, headers, "lunch", poulet, 120.0, day)
    _log(client, headers, "snack", poulet, 50.0, day)


def test_dashboard_journal_and_chart_totals_match(ctx):
    client, headers = ctx["client"], ctx["headers"]
    today = date.today().isoformat()
    _seed(client, headers, today)

    journal = client.get(f"/api/meals/journal?date={today}", headers=headers).json()
    dash = client.get("/api/dashboard", headers=headers).json()

    j = journal["day_summary"]
    assert j["total_calories"] > 0

    # Resume du jour (dashboard) vs journal
    assert dash["summary"]["calories_intake_kcal"] == pytest.approx(j["total_calories"], abs=0.5)

    # Graphique empile par jour vs journal
    chart_day = dash["meals_by_day_7d"][today]
    assert chart_day["total"] == pytest.approx(j["total_calories"], abs=0.5)
    by_type = {m["meal_type"]: m for m in journal["meals"]}
    for meal_type in ("breakfast", "lunch", "dinner", "snack"):
        expected = by_type[meal_type]["total_calories"] if meal_type in by_type else 0.0
        assert chart_day[meal_type] == pytest.approx(expected, abs=0.5)


def test_macros_donut_matches_journal_macros(ctx):
    client, headers = ctx["client"], ctx["headers"]
    today = date.today().isoformat()
    _seed(client, headers, today)

    j = client.get(f"/api/meals/journal?date={today}", headers=headers).json()["day_summary"]
    macros = client.get("/api/dashboard", headers=headers).json()["summary"]["macros"]

    assert macros["protein_g"] == pytest.approx(j["total_protein_g"], abs=0.5)
    assert macros["carbs_g"] == pytest.approx(j["total_carbs_g"], abs=0.5)
    assert macros["fat_g"] == pytest.approx(j["total_fat_g"], abs=0.5)


def test_other_day_does_not_leak_into_totals(ctx):
    client, headers = ctx["client"], ctx["headers"]
    today = date.today().isoformat()
    _seed(client, headers, "2020-01-01")

    j = client.get(f"/api/meals/journal?date={today}", headers=headers).json()["day_summary"]
    dash = client.get("/api/dashboard", headers=headers).json()
    assert j["total_calories"] == 0.0
    assert dash["summary"]["calories_intake_kcal"] == 0.0
    assert dash["meals_by_day_7d"][today]["total"] == 0.0
