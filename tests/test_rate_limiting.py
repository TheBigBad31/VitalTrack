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
from fastapi import Request
from fastapi.testclient import TestClient

from src.app import app
import src.app as app_module
from src.db import Database
from src.rate_limit import (
    RateLimiter,
    RateLimitExceeded,
    InMemoryBackend,
    UpstashRedisBackend,
    get_upstash_redis_credentials,
    limiter,
    parse_rate_limit,
)
import httpx


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


def test_get_upstash_redis_credentials(monkeypatch):
    """Vérifie l'extraction des identifiants Upstash et Vercel KV."""
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    monkeypatch.delenv("KV_REST_API_URL", raising=False)
    monkeypatch.delenv("KV_REST_API_TOKEN", raising=False)
    assert get_upstash_redis_credentials() == (None, None)

    # Via UPSTASH_REDIS_REST_*
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://my-upstash.upstash.io/")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "my-secret-token")
    assert get_upstash_redis_credentials() == ("https://my-upstash.upstash.io", "my-secret-token")

    # Via KV_REST_API_* (Vercel KV)
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    monkeypatch.setenv("KV_REST_API_URL", "https://kv.vercel-storage.com/")
    monkeypatch.setenv("KV_REST_API_TOKEN", "vercel-kv-token")
    assert get_upstash_redis_credentials() == ("https://kv.vercel-storage.com", "vercel-kv-token")


def test_upstash_redis_backend_eval_allowed(monkeypatch):
    """Vérifie le comportement de UpstashRedisBackend quand le quota n'est pas dépassé."""
    backend = UpstashRedisBackend(url="https://mock-redis.upstash.io", token="tok123")

    def mock_post(url, json=None, **kwargs):
        assert json[0] == "EVAL"
        return httpx.Response(200, json={"result": [1, 4, 0]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(backend._get_client(), "post", mock_post)

    allowed, remaining, retry_after = backend.check("ratelimit:test:ip1", max_requests=5, window_seconds=60)
    assert allowed is True
    assert remaining == 4
    assert retry_after == 0


def test_upstash_redis_backend_eval_exceeded(monkeypatch):
    """Vérifie le comportement de UpstashRedisBackend quand la limite est dépassée."""
    backend = UpstashRedisBackend(url="https://mock-redis.upstash.io", token="tok123")

    def mock_post(url, json=None, **kwargs):
        assert json[0] == "EVAL"
        return httpx.Response(200, json={"result": [0, 5, 23]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(backend._get_client(), "post", mock_post)

    allowed, remaining, retry_after = backend.check("ratelimit:test:ip1", max_requests=5, window_seconds=60)
    assert allowed is False
    assert remaining == 5
    assert retry_after == 23


def test_upstash_redis_backend_pipeline_fallback(monkeypatch):
    """Vérifie le repli sur le pipeline REST standard si EVAL retourne une erreur."""
    backend = UpstashRedisBackend(url="https://mock-redis.upstash.io", token="tok123")

    calls = []

    def mock_post(url, json=None, **kwargs):
        calls.append((url, json))
        # Premier appel EVAL -> Erreur
        if json and json[0] == "EVAL":
            return httpx.Response(200, json={"error": "ERR EVAL not allowed"}, request=httpx.Request("POST", url))
        # Pipeline check
        if "/pipeline" in str(url) and len(json) == 3:
            return httpx.Response(
                200,
                json=[
                    {"result": 0},
                    {"result": 2},
                    {"result": ["hit1", "1700000000.0"]},
                ],
                request=httpx.Request("POST", url),
            )
        # Pipeline add
        if "/pipeline" in str(url) and len(json) == 2:
            return httpx.Response(
                200,
                json=[{"result": 1}, {"result": 1}],
                request=httpx.Request("POST", url),
            )
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(backend._get_client(), "post", mock_post)

    allowed, remaining, retry_after = backend.check("ratelimit:test:ip1", max_requests=5, window_seconds=60)
    assert allowed is True
    assert remaining == 2  # 5 - 2 - 1 = 2
    assert retry_after == 0
    assert len(calls) == 3


def test_upstash_redis_backend_network_error_fallback_to_memory(monkeypatch):
    """Vérifie qu'en cas de panne réseau avec Upstash, le backend bascule gracieusement en mémoire."""
    backend = UpstashRedisBackend(url="https://mock-redis.upstash.io", token="tok123")

    def mock_post_fail(url, **kwargs):
        raise httpx.ConnectError("Network unreachable")

    monkeypatch.setattr(backend._get_client(), "post", mock_post_fail)

    # Le fallback in-memory prend le relais sans faire planter la requête
    allowed, remaining, retry_after = backend.check("ratelimit:test:ip1", max_requests=2, window_seconds=60)
    assert allowed is True

    allowed2, remaining2, retry_after2 = backend.check("ratelimit:test:ip1", max_requests=2, window_seconds=60)
    assert allowed2 is True

    # 3e requête dépasse le quota dans le fallback mémoire
    allowed3, remaining3, retry_after3 = backend.check("ratelimit:test:ip1", max_requests=2, window_seconds=60)
    assert allowed3 is False
    assert retry_after3 > 0


def test_upstash_redis_backend_reset(monkeypatch):
    """Vérifie que reset() supprime les clés touchées via pipeline DEL."""
    backend = UpstashRedisBackend(url="https://mock-redis.upstash.io", token="tok123")
    backend._touched_keys.add("ratelimit:bucket1:ip1")
    backend._touched_keys.add("ratelimit:bucket2:ip2")

    posted_pipeline = []

    def mock_post(url, json=None, **kwargs):
        posted_pipeline.append(json)
        return httpx.Response(200, json=[{"result": 1}, {"result": 1}], request=httpx.Request("POST", url))

    monkeypatch.setattr(backend._get_client(), "post", mock_post)

    backend.reset()
    assert len(backend._touched_keys) == 0
    assert len(posted_pipeline) == 1
    del_commands = posted_pipeline[0]
    assert len(del_commands) == 2
    for cmd in del_commands:
        assert cmd[0] == "DEL"


def test_rate_limiter_switches_backend_on_env(monkeypatch):
    """Vérifie que RateLimiter adapte dynamiquement son backend selon les variables d'environnement."""
    test_limiter = RateLimiter()

    # Sans identifiants -> InMemoryBackend
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    monkeypatch.delenv("KV_REST_API_URL", raising=False)
    monkeypatch.delenv("KV_REST_API_TOKEN", raising=False)
    assert isinstance(test_limiter.backend, InMemoryBackend)

    # Avec identifiants -> UpstashRedisBackend
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://upstash.io")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "token123")
    assert isinstance(test_limiter.backend, UpstashRedisBackend)
    assert test_limiter.backend.url == "https://upstash.io"


def test_rate_limiter_with_upstash_raises_429(monkeypatch):
    """Vérifie que check_request lève RateLimitExceeded (HTTP 429) lorsque Upstash signale un dépassement."""
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://upstash.io")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "token123")

    test_limiter = RateLimiter()
    assert isinstance(test_limiter.backend, UpstashRedisBackend)

    def mock_post(url, json=None, **kwargs):
        return httpx.Response(200, json={"result": [0, 10, 42]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(test_limiter.backend._get_client(), "post", mock_post)

    scope = {"type": "http", "headers": [(b"x-forwarded-for", b"203.0.113.199")]}
    request = Request(scope=scope)

    with pytest.raises(RateLimitExceeded) as exc_info:
        test_limiter.check_request(request, bucket="test_bucket", rate_str="5/minute")

    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after == 42
    assert "Retry-After" in exc_info.value.headers
    assert exc_info.value.headers["Retry-After"] == "42"

