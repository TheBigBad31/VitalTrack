"""Tests unitaires et d'intégration pour le Référentiel des Bienfaits Nutritionnels et le Moteur EFSA/ANSES (Stage 13)."""

import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database
from src.nutrition_rules import evaluate_dish_benefits, EXPERT_BENEFITS_CATALOG
from src.models import CatalogItem


client = TestClient(app)


def test_expert_benefits_catalog_structure():
    """Vérifie la présence des 8 catégories d'experts dans le catalogue."""
    category_ids = {b["category_id"] for b in EXPERT_BENEFITS_CATALOG}
    assert category_ids == {1, 2, 3, 4, 5, 6, 7, 8}
    assert len(EXPERT_BENEFITS_CATALOG) >= 15


def test_evaluate_dish_benefits_rules():
    """Teste les différentes règles EFSA / ANSES du moteur de détection."""
    # 1. Transit et confort intestinal (Fibres >= 3g/100g ou >= 6g/portion)
    high_fiber_food = {
        "name": "Pain complet aux graines",
        "default_quantity": 100.0,
        "fiber_per_unit_g": 6.5,
        "protein_per_unit_g": 9.0,
        "carbs_per_unit_g": 45.0,
        "fat_per_unit_g": 3.0,
    }
    results = evaluate_dish_benefits(high_fiber_food)
    benefit_ids = [r.benefit_id for r in results]
    assert "gut_transit" in benefit_ids

    # 2. Protection cardiovasculaire & régulation du cholestérol (Acides gras insaturés >= 50% ou oléagineux)
    olive_oil_dish = {
        "name": "Salade méditerranéenne à l'huile d'olive et noix",
        "default_quantity": 250.0,
        "fat_per_unit_g": 18.0,
        "unsaturated_fat_g": 14.0,
        "saturated_fat_g": 2.0,
        "fiber_per_unit_g": 4.0,
        "protein_per_unit_g": 5.0,
        "carbs_per_unit_g": 10.0,
    }
    results = evaluate_dish_benefits(olive_oil_dish)
    benefit_ids = [r.benefit_id for r in results]
    assert "cardio_protection" in benefit_ids
    assert "cholesterol_regulation" in benefit_ids

    # 3. Contrôle de la pression artérielle (Sodium < 120 mg / 100g)
    low_sodium_dish = {
        "name": "Purée d'épinards et patate douce",
        "default_quantity": 200.0,
        "sodium_mg": 45.0,
        "protein_per_unit_g": 4.0,
        "carbs_per_unit_g": 22.0,
        "fat_per_unit_g": 1.0,
        "fiber_per_unit_g": 4.5,
    }
    results = evaluate_dish_benefits(low_sodium_dish)
    benefit_ids = [r.benefit_id for r in results]
    assert "blood_pressure" in benefit_ids

    # 4. Hydratation cellulaire (Eau > 85%)
    cucumber_dish = {
        "name": "Gaspacho de concombre et menthe",
        "default_quantity": 200.0,
        "water_pct": 92.0,
        "calories_per_unit": 35.0,
        "protein_per_unit_g": 1.0,
        "carbs_per_unit_g": 4.0,
        "fat_per_unit_g": 0.5,
        "fiber_per_unit_g": 1.0,
    }
    results = evaluate_dish_benefits(cucumber_dish)
    benefit_ids = [r.benefit_id for r in results]
    assert "cellular_hydration" in benefit_ids

    # 5. Régulation glycémique (Fibres / Glucides > 0.15)
    lentils_dish = {
        "name": "Salade de lentilles vertes",
        "default_quantity": 150.0,
        "carbs_per_unit_g": 24.0,
        "fiber_per_unit_g": 6.0,  # 6 / 24 = 0.25 > 0.15
        "protein_per_unit_g": 12.0,
        "fat_per_unit_g": 1.5,
    }
    results = evaluate_dish_benefits(lentils_dish)
    benefit_ids = [r.benefit_id for r in results]
    assert "glycemic_regulation" in benefit_ids

    # 6. Satiété et contrôle de l'appétit (Fibres > 5g ET Protéines > 15g par portion)
    fitness_bowl = {
        "name": "Bowl poulet, quinoa et avocat",
        "default_quantity": 300.0,
        "protein_per_unit_g": 32.0,
        "fiber_per_unit_g": 7.5,
        "carbs_per_unit_g": 40.0,
        "fat_per_unit_g": 12.0,
        "unsaturated_fat_g": 9.0,
    }
    results = evaluate_dish_benefits(fitness_bowl)
    benefit_ids = [r.benefit_id for r in results]
    assert "satiety_control" in benefit_ids
    assert "muscle_function" in benefit_ids

    # 7. Santé osseuse (Calcium >= 120 mg/100g)
    parmesan_dish = {
        "name": "Copeaux de parmesan AOP",
        "default_quantity": 100.0,
        "calcium_mg": 850.0,
        "protein_per_unit_g": 32.0,
        "fat_per_unit_g": 28.0,
        "carbs_per_unit_g": 0.0,
    }
    results = evaluate_dish_benefits(parmesan_dish)
    benefit_ids = [r.benefit_id for r in results]
    assert "bone_health" in benefit_ids


def test_api_nutrition_benefits_referential():
    """Teste le point de terminaison GET /api/nutrition/benefits."""
    response = client.get("/api/nutrition/benefits")
    assert response.status_code == 200
    data = response.json()
    assert "count" in data
    assert data["count"] >= 15
    assert "categories" in data
    assert "Santé Cardiovasculaire & Vasculaire" in data["categories"]
    assert "Métabolisme & Glycémie" in data["categories"]
    assert "Digestion, Microbiote & Foie" in data["categories"]


def test_api_nutrition_evaluate():
    """Teste le point de terminaison POST /api/nutrition/evaluate."""
    payload = {
        "name": "Porridge flocons d'avoine, graines de chia et fruits rouges",
        "portion_g": 250.0,
        "protein_g": 18.0,
        "fiber_g": 8.0,
        "carbs_g": 42.0,
        "fat_g": 7.0,
        "unsaturated_fat_g": 5.0,
        "water_pct": 75.0,
        "sodium_mg": 10.0,
    }
    response = client.post("/api/nutrition/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["matched_count"] > 0
    matched_ids = [r["benefit_id"] for r in data["results"]]
    assert "gut_transit" in matched_ids
    assert "satiety_control" in matched_ids
    assert "glycemic_regulation" in matched_ids


def test_api_catalog_item_benefits_lifecycle():
    """Teste l'association, la lecture et la mise à jour des bienfaits sur un plat du catalogue."""
    # 1. Création d'un plat dans le catalogue
    create_payload = {
        "name": "Tartine Saumon Fumé et Avocat Test",
        "item_type": "dish",
        "default_unit": "portion",
        "default_quantity": 180.0,
        "calories_per_unit": 380.0,
        "protein_per_unit_g": 22.0,
        "carbs_per_unit_g": 26.0,
        "fat_per_unit_g": 19.0,
        "fiber_per_unit_g": 6.0,
    }
    res_create = client.post("/api/catalog/items", json=create_payload)
    assert res_create.status_code == 200
    item = res_create.json()
    item_id = item["id"]

    try:
        # 2. Vérification des bienfaits initiaux
        res_b = client.get(f"/api/catalog/items/{item_id}/benefits")
        assert res_b.status_code == 200
        initial_benefits = res_b.json()
        assert isinstance(initial_benefits, list)

        # 3. Association de bienfaits (auto ou manuelle)
        update_payload = {
            "benefits": [
                {
                    "benefit_id": "cardio_protection",
                    "source": "auto_rule",
                    "explanation": "Riche en oméga-3 et lipides insaturés protecteurs"
                },
                {
                    "benefit_id": "satiety_control",
                    "source": "manual",
                    "explanation": "Association fibres et protéines de haute satiété"
                }
            ]
        }
        res_put = client.put(f"/api/catalog/items/{item_id}/benefits", json=update_payload)
        assert res_put.status_code == 200
        saved_benefits = res_put.json()
        assert len(saved_benefits) == 2
        saved_ids = [b["benefit_id"] for b in saved_benefits]
        assert "cardio_protection" in saved_ids
        assert "satiety_control" in saved_ids

        # 4. Vérification que l'item du catalogue embarque bien ses bienfaits dans GET /api/catalog/items
        res_catalog = client.get("/api/catalog/items")
        assert res_catalog.status_code == 200
        catalog_items = res_catalog.json()
        matched = next((x for x in catalog_items if x["id"] == item_id), None)
        assert matched is not None
        assert "benefits" in matched
        assert len(matched["benefits"]) == 2

    finally:
        # Nettoyage
        client.delete(f"/api/catalog/items/{item_id}")
