"""Tests de validation pour l'API Versioning (VTR-205 / BALI-221).

Vérifie :
- Présence de /api/v1/ (endpoints répliqués et supportés)
- Présence de /api/v2/ (nouveaux endpoints enveloppés et standardisés)
- Headers RFC de dépréciation (Deprecation, Sunset, Link, X-API-Version)
- Spécifications OpenAPI distinctes (/api/v1/openapi.json, /api/v2/openapi.json)
"""

import tempfile
import os
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database
import src.app as app_module


@pytest.fixture
def client():
    """Client de test FastAPI avec base temporaire isolée."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name
    if os.path.exists(temp_path):
        os.remove(temp_path)

    test_db = Database(db_path=temp_path)
    old_db = app_module.db
    old_nutrition_db = app_module.nutrition_engine.db
    app_module.db = test_db
    app_module.nutrition_engine.db = test_db

    yield TestClient(app)

    app_module.db = old_db
    app_module.nutrition_engine.db = old_nutrition_db
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


def test_api_version_headers_legacy(client):
    """Vérifie que les endpoints historiques reçoivent les en-têtes de dépréciation RFC 8594."""
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.headers.get("X-API-Version") == "v1-legacy"
    assert res.headers.get("Deprecation") == "true"
    assert "Sunset" in res.headers
    assert "Link" in res.headers
    assert 'rel="successor-version"' in res.headers["Link"]


def test_api_version_headers_v1(client):
    """Vérifie que /api/v1/ est annoté en X-API-Version: v1 sans dépréciation active mais avec lien v2."""
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.headers.get("X-API-Version") == "v1"
    assert "Deprecation" not in res.headers
    assert 'rel="successor-version"' in res.headers.get("Link", "")


def test_api_version_headers_v2(client):
    """Vérifie que /api/v2/ porte X-API-Version: v2."""
    res = client.get("/api/v2/health")
    assert res.status_code == 200
    assert res.headers.get("X-API-Version") == "v2"
    assert "Deprecation" not in res.headers
    data = res.json()
    assert data["version"] == "v2"
    assert data["status"] == "success"
    assert data["data"]["service"] == "VitalTrack API v2"


def test_api_v1_endpoints_availability(client):
    """Vérifie la disponibilité des endpoints essentiels sous /api/v1/."""
    # Health
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # Dashboard
    res = client.get("/api/v1/dashboard")
    assert res.status_code == 200
    assert "summary" in res.json()

    # Weights
    res = client.get("/api/v1/weights")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # Config
    res = client.get("/api/v1/config")
    assert res.status_code == 200
    assert "kcal_per_kg" in res.json()


def test_api_v2_weights_workflow(client):
    """Vérifie le workflow complet création et lecture sous /api/v2/ avec enveloppe standardisée."""
    # Création pesée v2
    entry_payload = {
        "weight_kg": 76.5,
        "body_fat_pct": 14.8,
        "muscle_mass_kg": 62.0,
        "water_pct": 59.2,
        "source": "manual",
        "notes": "Pesée de test v2",
    }
    create_res = client.post("/api/v2/weights", json=entry_payload)
    assert create_res.status_code == 200
    res_data = create_res.json()
    assert res_data["version"] == "v2"
    assert res_data["status"] == "success"
    assert res_data["data"]["weight_kg"] == 76.5
    assert res_data["meta"]["created"] is True

    # Récupération pesée v2
    get_res = client.get("/api/v2/weights")
    assert get_res.status_code == 200
    list_data = get_res.json()
    assert list_data["version"] == "v2"
    assert list_data["meta"]["count"] >= 1
    assert any(w["weight_kg"] == 76.5 for w in list_data["data"])


def test_openapi_specs_v1_and_v2(client):
    """Vérifie que les spécifications OpenAPI dédiées sont correctement générées."""
    # OpenAPI v1
    v1_res = client.get("/api/v1/openapi.json")
    assert v1_res.status_code == 200
    v1_spec = v1_res.json()
    assert v1_spec["info"]["title"] == "VitalTrack API v1 (Legacy & LTS)"
    assert "/api/v1/weights" in v1_spec["paths"]

    # OpenAPI v2
    v2_res = client.get("/api/v2/openapi.json")
    assert v2_res.status_code == 200
    v2_spec = v2_res.json()
    assert v2_spec["info"]["title"] == "VitalTrack API v2 (Next-Gen)"
    assert "/api/v2/weights" in v2_spec["paths"]
    assert "/api/v1/weights" not in v2_spec["paths"]

    # Docs Swagger UI
    docs_v1 = client.get("/api/v1/docs")
    assert docs_v1.status_code == 200
    assert "VitalTrack API v1" in docs_v1.text

    docs_v2 = client.get("/api/v2/docs")
    assert docs_v2.status_code == 200
    assert "VitalTrack API v2" in docs_v2.text
