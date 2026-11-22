"""Tests unitaires pour la détection déterministe de plateau métabolique."""

from datetime import date, timedelta
from types import SimpleNamespace

from src.analytics import detect_metabolic_plateau


def test_detect_metabolic_plateau_triggers_when_weight_stagnates_with_deficit():
    today = date(2026, 11, 22)
    # 14 jours de pesées quasi-identiques (~80.0 kg, variation < 0.15 kg)
    weights = [
        SimpleNamespace(date=today - timedelta(days=i), weight_kg=80.0)
        for i in range(14, -1, -1)
    ]
    # Apport quotidien de 1500 kcal (déficit > 300 kcal/j vs TDEE ~2400 kcal)
    meals = [
        SimpleNamespace(date=today - timedelta(days=i), total_calories_kcal=1500.0)
        for i in range(10)
    ]
    profile = {"height_cm": 178.0, "age": 35, "gender": "male"}

    res = detect_metabolic_plateau(weights=weights, meals=meals, activities=[], profile=profile, today=today)

    assert res["is_plateau"] is True
    assert abs(res["weight_change_14d_kg"]) < 0.15
    assert res["avg_deficit_kcal"] > 300.0
    assert len(res["recommendations"]) == 3
    titles = [r["title"] for r in res["recommendations"]]
    assert any("NEAT" in t for t in titles)


def test_detect_metabolic_plateau_no_trigger_when_losing_weight():
    today = date(2026, 11, 22)
    weights = [
        SimpleNamespace(date=today - timedelta(days=i), weight_kg=80.0 - (14 - i) * 0.08)
        for i in range(14, -1, -1)
    ]
    meals = [
        SimpleNamespace(date=today - timedelta(days=i), total_calories_kcal=1500.0)
        for i in range(10)
    ]
    profile = {"height_cm": 178.0, "age": 35, "gender": "male"}

    res = detect_metabolic_plateau(weights=weights, meals=meals, activities=[], profile=profile, today=today)

    assert res["is_plateau"] is False
    assert res["recommendations"] == []
