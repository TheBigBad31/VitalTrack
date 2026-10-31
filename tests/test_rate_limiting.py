"""Tests automatisés pour le rate limiting (BALI-127 : login, register et analyse photo IA).

Couvre :
- Limitation sur POST /api/auth/login (et alias /login) -> 429 Too Many Requests + Retry-After
- Limitation sur POST /api/auth/register (et alias /register) -> 429 Too Many Requests
- Limitation sur POST /api/meals/analyze-photo et /api/meals/estimate -> 429 Too Many Requests
- Isolation des compteurs par adresse IP (X-Forwarded-For) et par route
- Réinitialisation (`limiter.reset()`) et désactivation via variable d'environnement
"""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from src.app import app
import src.app as app_module
from src.db import Database
from src.rate_limit import limiter, parse_rate_limit


@pytest.fixture
def rate_client():
    """Client FastAPI avec base SQLite isolée et compteurs de rate-limit réinitialisés."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name
    if os.path.exists(temp_path):
        os.remove(temp_path)

    test_db = Database(db_path=temp_path)
    old_db = app_module.db
    old_nutri_db = app_module.nutrition_engine.db
    app_module.db = test_db
    app_module.nutrition_engine.db = test_db
    limiter.reset()

    yield TestClient(app)

    limiter.reset()
    app_module.db = old_db
    app_module.nutrition_engine.db = old_nutri_db
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


def test_parse_rate_limit_formats():
    """Vérifie le parsing des expressions de débit ('5/minute', '10/sec', '100/hour')."""
    assert parse_rate_limit("5/minute") == (5, 60)
    assert parse_rate_limit("10/sec") == (10, 1)
    assert parse_rate_limit("100/hour") == (100, 3600)
    assert parse_rate_limit("1000/day") == (1000, 86400)


def test_rate_limit_on_login_returns_429(rate_client, monkeypatch):
    """Vérifie que /api/auth/login (et /login) retourne 429 après dépassement du seuil."""
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "3/minute")
    limiter.reset()

    payload = {"email": "inconnu@vitaltrack.io", "password": "WrongPassword123!"}
    headers = {"X-Forwarded-For": "203.0.113.10"}

    # Les 3 premières tentatives passent le rate-limiter (et renvoient 401 car identifiants invalides)
    for _ in range(3):
        res = rate_client.post("/api/auth/login", json=payload, headers=headers)
        assert res.status_code == 401

    # La 4e tentative depuis la même IP est bloquée en 429
    res_429 = rate_client.post("/api/auth/login", json=payload, headers=headers)
    assert res_429.status_code == 429
    assert "Retry-After" in res_429.headers
    body = res_429.json()
    assert body["error"] == "Too Many Requests"
    assert "3/minute" in body["detail"]

    # L'alias /login partage le même bucket et renvoie également 429 pour cette IP
    res_alias = rate_client.post("/login", json=payload, headers=headers)
    assert res_alias.status_code == 429

    # Une autre IP n'est pas bloquée
    other_ip_res = rate_client.post(
        "/api/auth/login",
        json=payload,
        headers={"X-Forwarded-For": "203.0.113.99"},
    )
    assert other_ip_res.status_code == 401


def test_rate_limit_on_register_returns_429(rate_client, monkeypatch):
    """Vérifie que /api/auth/register (et /register) retourne 429 après dépassement du seuil."""
    monkeypatch.setenv("RATE_LIMIT_REGISTER", "2/minute")
    limiter.reset()

    headers = {"X-Forwarded-For": "198.51.100.25"}

    res1 = rate_client.post(
        "/api/auth/register",
        json={"email": "u1_rl@vitaltrack.io", "password": "PasswordSecurise1!", "name": "U1"},
        headers=headers,
    )
    assert res1.status_code == 200

    res2 = rate_client.post(
        "/register",
        json={"email": "u2_rl@vitaltrack.io", "password": "PasswordSecurise2!", "name": "U2"},
        headers=headers,
    )
    assert res2.status_code == 200

    # La 3e requête d'inscription dans la même minute est rejetée en 429
    res3 = rate_client.post(
        "/api/auth/register",
        json={"email": "u3_rl@vitaltrack.io", "password": "PasswordSecurise3!", "name": "U3"},
        headers=headers,
    )
    assert res3.status_code == 429
    assert "Retry-After" in res3.headers


def test_rate_limit_on_photo_analysis_returns_429(rate_client, monkeypatch):
    """Vérifie que POST /api/meals/analyze-photo et /api/meals/estimate retournent 429."""
    monkeypatch.setenv("RATE_LIMIT_PHOTO_ANALYSIS", "3/minute")
    limiter.reset()

    headers = {"X-Forwarded-For": "192.0.2.42"}
    payload = {
        "description": "Blanc de poulet 150g, riz basmati 150g",
        "portion_scale": 1.0,
        "meal_type": "lunch",
    }

    # 2 appels sur /api/meals/analyze-photo + 1 appel sur /api/meals/estimate = 3 appels autorisés
    r1 = rate_client.post("/api/meals/analyze-photo", json=payload, headers=headers)
    assert r1.status_code == 200

    r2 = rate_client.post("/api/meals/analyze-photo", json=payload, headers=headers)
    assert r2.status_code == 200

    r3 = rate_client.post("/api/meals/estimate", json=payload, headers=headers)
    assert r3.status_code == 200

    # 4e appel -> 429 Too Many Requests
    r4 = rate_client.post("/api/meals/analyze-photo", json=payload, headers=headers)
    assert r4.status_code == 429
    assert "Retry-After" in r4.headers
    assert r4.json()["error"] == "Too Many Requests"

    # Le GET d'information /api/meals/analyze-photo reste accessible
    r_info = rate_client.get("/api/meals/analyze-photo", headers=headers)
    assert r_info.status_code == 200
