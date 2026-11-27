"""Tests unitaires du référentiel NutritionScore (EFSA / ANSES)."""

from src.models import FoodItem
from src.nutrition_benefits import (
    NUTRITION_BENEFITS_REFERENTIAL,
    evaluate_nutrition_benefits,
    validate_and_normalize_benefits,
)
from src.vision_nutrition import PhotoCalorieEstimator


def test_referential_has_21_benefits():
    assert len(NUTRITION_BENEFITS_REFERENTIAL) == 21


def test_satiety_threshold_efsa():
    items = [FoodItem(name="Poulet et lentilles", portion_g=300, calories_kcal=400, protein_g=32.0, carbs_g=30.0, fat_g=5.0, fiber_g=7.0)]
    benefits = evaluate_nutrition_benefits(items, 400.0, 32.0, 30.0, 5.0, 7.0)
    tags = [b["tag"] for b in benefits]
    assert "Satiété et contrôle de l'appétit" in tags


def test_glycemic_regulation_ratio_threshold():
    # Ratio fibres / glucides > 0.15 (ex: 6g / 30g = 0.20)
    items = [FoodItem(name="Brocoli et avocat", portion_g=200, calories_kcal=200, protein_g=5.0, carbs_g=30.0, fat_g=10.0, fiber_g=6.0)]
    benefits = evaluate_nutrition_benefits(items, 200.0, 5.0, 30.0, 10.0, 6.0)
    tags = [b["tag"] for b in benefits]
    assert "Régulation glycémique" in tags
    assert "Transit et confort intestinal" in tags


def test_cardio_and_cholesterol_olive_oil():
    items = [FoodItem(name="Salade et huile d'olive", portion_g=150, calories_kcal=150, protein_g=2.0, carbs_g=5.0, fat_g=12.0, fiber_g=2.0)]
    benefits = evaluate_nutrition_benefits(items, 150.0, 2.0, 5.0, 12.0, 2.0)
    tags = [b["tag"] for b in benefits]
    assert "Protection cardiovasculaire" in tags
    assert "Régulation du cholestérol (Hypocholestérolémiant)" in tags
    assert "Hydratation cellulaire et tissulaire" in tags


def test_validate_and_normalize_benefits_filters_unknown():
    fallback = [{"tag": "Transit et confort intestinal", "category": "Digestion", "description": "..."}]
    res = validate_and_normalize_benefits(["Tag bidon inexistant", "Régulation glycémique"], fallback)
    assert len(res) == 1
    assert res[0]["tag"] == "Régulation glycémique"


def test_offline_estimator_returns_nutritionscore_fields():
    estimator = PhotoCalorieEstimator(api_key="")
    res = estimator.analyze_meal(description="Blanc de poulet 150g, brocoli 200g, avocat 80g", meal_type="lunch")
    assert "nutritional_quality" in res and len(res["nutritional_quality"]) > 10
    assert "key_benefits" in res and 1 <= len(res["key_benefits"]) <= 4
    assert "dietary_advice" in res
    assert "items" in res and len(res["items"]) >= 1
