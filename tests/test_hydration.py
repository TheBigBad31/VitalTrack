# tests/test_hydration.py
# -*- coding: utf-8 -*-
"""Tests unitaires et d'intégration pour les métriques d'hydratation (BALI-293)."""

from datetime import date
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database


@pytest.fixture
def client():
    return TestClient(app)


def test_hydration_endpoints_lifecycle(client):
    """Teste la récupération et l'ajout d'entrées d'hydratation."""
    db = Database()
    user_id = 1
    today_str = date.today().isoformat()

    # 1. Vérifier l'état initial
    resp_init = client.get(f"/api/metrics/hydration?date={today_str}")
    assert resp_init.status_code == 200
    data_init = resp_init.json()
    assert data_init["status"] == "success"
    assert data_init["date"] == today_str
    assert "total_ml" in data_init
    assert "target_ml" in data_init
    assert "glasses_count" in data_init
    assert "percentage" in data_init

    initial_total = data_init["total_ml"]

    # 2. Ajouter 250 ml (1 verre)
    resp_add1 = client.post("/api/metrics/hydration", json={
        "volume_ml": 250.0,
        "date": today_str,
        "source": "manual_quick_add"
    })
    assert resp_add1.status_code == 200
    data_add1 = resp_add1.json()
    assert data_add1["status"] == "success"
    assert data_add1["total_ml"] == round(initial_total + 250.0, 1)
    assert data_add1["glasses_count"] == round((initial_total + 250.0) / 250.0, 1)

    # 3. Ajouter 500 ml (2 verres)
    resp_add2 = client.post("/api/metrics/hydration", json={
        "volume_ml": 500.0,
        "date": today_str,
        "source": "manual_quick_add"
    })
    assert resp_add2.status_code == 200
    data_add2 = resp_add2.json()
    assert data_add2["status"] == "success"
    assert data_add2["total_ml"] == round(initial_total + 750.0, 1)

    # 4. Vérifier que /api/metrics intègre le bloc hydration et has_real_data
    resp_metrics = client.get("/api/metrics?days=7")
    assert resp_metrics.status_code == 200
    data_metrics = resp_metrics.json()
    assert data_metrics["has_real_data"] is True
    assert "hydration" in data_metrics
    assert data_metrics["hydration"]["total_ml"] >= 750.0
    assert "current_biometrics" in data_metrics
