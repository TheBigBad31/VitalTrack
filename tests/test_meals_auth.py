"""Tests d'authentification et de métriques sur les endpoints IA/OpenFoodFacts."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from src.app import app


def test_meals_ai_and_barcode_require_auth_in_strict_mode(monkeypatch):
    """POST /api/meals/analyze-photo, /estimate et GET /barcode/{barcode} renvoient 401 sans auth en mode strict."""
    monkeypatch.setenv("REQUIRE_STRICT_AUTH", "1")
    client = TestClient(app)

    r_photo = client.post("/api/meals/analyze-photo", json={"description": "poulet riz"})
    assert r_photo.status_code == 401

    r_estimate = client.post("/api/meals/estimate", json={"description": "poulet riz"})
    assert r_estimate.status_code == 401

    r_barcode = client.get("/api/meals/barcode/3017620422003")
    assert r_barcode.status_code == 401


def test_estimate_meal_reports_actual_source_metric(monkeypatch):
    """engine_used dans record_photo_analysis_metric reflète result['source'] réel."""
    monkeypatch.setenv("REQUIRE_STRICT_AUTH", "0")
    client = TestClient(app)

    fake_result = {
        "source": "local_database",
        "total_calories_kcal": 400.0,
        "calories": 400.0,
        "items": [],
        "macros": {"protein_g": 30.0, "carbs_g": 40.0, "fat_g": 10.0, "fiber_g": 5.0},
    }
    with (
        patch("src.app.calorie_estimator.analyze_meal", return_value=fake_result),
        patch("src.routers.meals.record_photo_analysis_metric") as mock_metric,
    ):
        res = client.post(
            "/api/meals/analyze-photo",
            json={
                "photo_data_url": "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
                "portion_scale": 1.0,
            },
        )
    assert res.status_code == 200
    mock_metric.assert_called_once_with(engine="local_database", status="success")
