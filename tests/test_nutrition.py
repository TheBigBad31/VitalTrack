"""Tests unitaires pour l'estimateur de calories par photo IA et le journal alimentaire."""

import os
import tempfile
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
import pytest

from src.db import Database
from src.models import FoodItem, MealEntry
from src.nutrition_engine import NutritionEngine
from src.vision_nutrition import LOCAL_NUTRITION_DATABASE, PhotoCalorieEstimator


@pytest.fixture
def temp_db():
    """CrÃ©e une base de donnÃ©es temporaire pour chaque test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass

    db = Database(db_path=temp_path)
    yield db

    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


def test_photo_calorie_estimator_local_lookup():
    """VÃ©rifie la rÃ©solution locale des ingrÃ©dients et calculs nutritionnels."""
    estimator = PhotoCalorieEstimator(api_key=None)
    assert not estimator.has_gemini_api

    # Recherche directe
    poulet = estimator.lookup_ingredient("blanc de poulet")
    assert poulet is not None
    assert poulet["cal_100g"] == 120.0
    assert poulet["p"] == 26.0

    # Recherche avec sous-chaÃ®ne
    riz = estimator.lookup_ingredient("riz")
    assert riz is not None
    assert riz["c"] == 28.0


def test_photo_calorie_estimator_description_and_scaling():
    """VÃ©rifie le dÃ©coupage de texte et le multiplicateur de portion (0.5x Ã  2.0x)."""
    estimator = PhotoCalorieEstimator(api_key=None)

    # 1. Portion 1.0x
    desc = "Blanc de poulet 150g, riz basmati 180g, brocoli 150g"
    res_1x = estimator.estimate_from_description(desc, portion_scale=1.0, meal_type="lunch")

    assert res_1x["meal_type"] == "lunch"
    assert res_1x["portion_scale"] == 1.0
    assert len(res_1x["items"]) == 3
    assert res_1x["total_calories_kcal"] > 350.0
    assert res_1x["macros"]["protein_g"] > 35.0
    assert res_1x["macros"]["protein_pct"] > 0.0

    # 2. Multiplicateur 1.5x
    res_1_5x = estimator.estimate_from_description(desc, portion_scale=1.5, meal_type="lunch")
    assert res_1_5x["portion_scale"] == 1.5
    # Les calories doivent Ãªtre proportionnelles (~1.5x)
    assert pytest.approx(res_1_5x["total_calories_kcal"], rel=0.05) == res_1x["total_calories_kcal"] * 1.5
    assert pytest.approx(res_1_5x["macros"]["protein_g"], rel=0.05) == res_1x["macros"]["protein_g"] * 1.5

    # 3. Multiplicateur 0.5x
    res_0_5x = estimator.estimate_from_description(desc, portion_scale=0.5, meal_type="lunch")
    assert res_0_5x["portion_scale"] == 0.5
    assert pytest.approx(res_0_5x["total_calories_kcal"], rel=0.05) == res_1x["total_calories_kcal"] * 0.5

    # 4. Bornage au-delÃ  des limites (doit Ãªtre bornÃ© entre 0.5 et 2.0)
    res_min = estimator.estimate_from_description(desc, portion_scale=0.1)
    assert res_min["portion_scale"] == 0.5
    res_max = estimator.estimate_from_description(desc, portion_scale=5.0)
    assert res_max["portion_scale"] == 2.0


def test_photo_calorie_estimator_openfoodfacts_fallback():
    """VÃ©rifie le mock de l'API OpenFoodFacts lors d'une recherche d'aliment inconnu en local."""
    estimator = PhotoCalorieEstimator(api_key=None)

    mock_off_response = {
        "products": [
            {
                "product_name_fr": "Granola Bio Avoine & Graines",
                "nutriments": {
                    "energy-kcal_100g": 420.0,
                    "proteins_100g": 11.5,
                    "carbohydrates_100g": 55.0,
                    "fat_100g": 16.0,
                    "fiber_100g": 8.0
                },
                "serving_quantity": 45.0
            }
        ]
    }

    with patch("src.vision_nutrition.urlopen") as mock_urlopen:
        mock_ctx = MagicMock()
        mock_ctx.read.return_value = bytes(__import__("json").dumps(mock_off_response), "utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_ctx

        result = estimator.search_openfoodfacts("granola bio")
        assert result is not None
        assert result["name"] == "Granola Bio Avoine & Graines"
        assert result["cal_100g"] == 420.0
        assert result["p"] == 11.5


def test_photo_calorie_estimator_gemini_vision_mock():
    """VÃ©rifie le flux multimodal Gemini Vision avec simulation de rÃ©ponse structurÃ©e."""
    estimator = PhotoCalorieEstimator(api_key="mock_gemini_api_key_valid_12345")
    assert estimator.has_gemini_api

    mock_gemini_response_json = """
    {
      "items": [
        {"name": "Saumon grillÃ©", "portion_g": 140, "calories_kcal": 290, "protein_g": 28, "carbs_g": 0, "fat_g": 18, "fiber_g": 0, "confidence_score": 0.95},
        {"name": "Quinoa cuit", "portion_g": 150, "calories_kcal": 180, "protein_g": 6.5, "carbs_g": 32, "fat_g": 2.8, "fiber_g": 4.2, "confidence_score": 0.90},
        {"name": "Asperges vertes", "portion_g": 100, "calories_kcal": 20, "protein_g": 2.2, "carbs_g": 3.8, "fat_g": 0.2, "fiber_g": 2.1, "confidence_score": 0.88}
      ],
      "dietary_advice": "Excellente source d'acides gras omÃ©ga-3 et de protÃ©ines complÃ¨tes.",
      "overall_confidence": 0.92
    }
    """

    mock_model_response = MagicMock()
    mock_model_response.text = mock_gemini_response_json

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_model_response

    mock_genai_module = MagicMock()
    mock_genai_module.Client.return_value = mock_client
    mock_types = MagicMock()
    mock_genai_module.types = mock_types

    mock_google = MagicMock()
    mock_google.genai = mock_genai_module

    with patch.dict("sys.modules", {
        "google": mock_google,
        "google.genai": mock_genai_module,
        "google.genai.types": mock_types
    }):
        result = estimator.estimate_from_gemini_vision(
            image_data=b"fake_jpeg_bytes",
            portion_scale=1.0,
            meal_type="dinner"
        )

        assert result is not None
        assert result["source"] == "gemini_vision"
        assert result["meal_type"] == "dinner"
        assert len(result["items"]) == 3
        assert result["total_calories_kcal"] == 490.0
        assert result["macros"]["protein_g"] == 36.7
        assert "omÃ©ga-3" in result["dietary_advice"]


def test_nutrition_engine_log_and_daily_summary(temp_db):
    """VÃ©rifie l'enregistrement et l'agrÃ©gation quotidienne du journal des repas."""
    engine = NutritionEngine(db=temp_db)
    today = date.today()

    # Ajout d'un petit-dÃ©jeuner
    breakfast_items = [
        FoodItem(name="Oeufs", portion_g=110, calories_kcal=157.0, protein_g=13.8, carbs_g=0.8, fat_g=10.4, fiber_g=0.0),
        FoodItem(name="Pain de campagne", portion_g=60, calories_kcal=159.0, protein_g=5.4, carbs_g=30.0, fat_g=0.9, fiber_g=2.4)
    ]
    meal_1 = engine.log_meal(today, "breakfast", breakfast_items, user_id=1)
    assert meal_1.id is not None
    assert meal_1.total_calories_kcal == 316.0

    # Ajout d'un dÃ©jeuner
    lunch_items = [
        FoodItem(name="Blanc de poulet", portion_g=150, calories_kcal=180.0, protein_g=39.0, carbs_g=0.0, fat_g=2.7, fiber_g=0.0),
        FoodItem(name="Riz basmati", portion_g=180, calories_kcal=234.0, protein_g=4.9, carbs_g=50.4, fat_g=0.5, fiber_g=0.7)
    ]
    meal_2 = engine.log_meal(today, "lunch", lunch_items, user_id=1)
    assert meal_2.id is not None

    # RÃ©cupÃ©ration et rÃ©sumÃ©
    summary = engine.get_daily_nutrition_summary(today, user_id=1)
    # temp_db auto-seede dÃ©jÃ  des repas pour today (si i<=6)
    # vÃ©rifions que les totaux incluent nos ajouts
    assert summary["meals_count"] >= 2
    assert summary["total_calories_kcal"] > 550.0
    assert summary["macros"]["protein_pct"] > 0.0
    assert summary["macros"]["carbs_pct"] > 0.0


def test_nutrition_engine_metabolic_bmr_and_tdee():
    """VÃ©rifie la formule Mifflin-St Jeor et le calcul du TDEE."""
    # Homme: 80 kg, 178 cm, 35 ans
    # BMR = (10 * 80) + (6.25 * 178) - (5 * 35) + 5 = 800 + 1112.5 - 175 + 5 = 1742.5 kcal
    bmr_m = NutritionEngine.calculate_bmr_mifflin_st_jeor(80.0, 178.0, 35, gender="male")
    assert bmr_m == 1742.5

    # Femme: 65 kg, 165 cm, 30 ans
    # BMR = (10 * 65) + (6.25 * 165) - (5 * 30) - 161 = 650 + 1031.25 - 150 - 161 = 1370.25 -> 1370.2/1370.3
    bmr_f = NutritionEngine.calculate_bmr_mifflin_st_jeor(65.0, 165.0, 30, gender="female")
    assert 1369.0 < bmr_f < 1371.0

    # TDEE
    tdee = NutritionEngine.calculate_tdee(bmr_kcal=1742.5, steps=10000, active_calories_kcal=450.0)
    assert tdee == round(1742.5 + 450.0, 1)


def test_nutrition_engine_energy_balance(temp_db):
    """VÃ©rifie le calcul du bilan Ã©nergÃ©tique net et de la projection de poids."""
    engine = NutritionEngine(db=temp_db)
    today = date.today()

    balance = engine.calculate_daily_energy_balance(
        target_date=today,
        user_weight_kg=80.0,
        user_height_cm=178.0,
        user_age=35,
        gender="male",
        user_id=1
    )

    assert "calories_intake_kcal" in balance
    assert "calories_burned_kcal" in balance
    assert "net_energy_balance_kcal" in balance
    assert balance["status"] in ["deficit", "surplus", "maintenance"]
    assert "weekly_projected_weight_change_kg" in balance
    assert "recommendation" in balance
    assert balance["calories_burned_kcal"] > 1500.0


def test_db_meals_seed(temp_db):
    """VÃ©rifie que la base dÃ©marre vierge et que reset_demo_data charge les repas de test."""
    assert len(temp_db.get_meals(limit=50, user_id=1)) == 0
    temp_db.reset_demo_data(user_id=1)
    meals = temp_db.get_meals(limit=50, user_id=1)
    assert len(meals) > 0
    # VÃ©rifie que les 4 types de repas sont reprÃ©sentÃ©s
    meal_types = {m.meal_type for m in meals}
    assert {"breakfast", "lunch", "dinner", "snack"}.issubset(meal_types)

    # VÃ©rifie qu'on peut rÃ©cupÃ©rer les repas pour aujourd'hui
    today_meals = temp_db.get_meals_for_date(date.today(), user_id=1)
    assert len(today_meals) == 4
    total_day_cal = sum(m.total_calories_kcal for m in today_meals)
    assert 1500.0 < total_day_cal < 2500.0
