"""Tests unitaires et d'intégration pour le connecteur Withings officiel (OAuth2, getmeas, sync)."""

import json
import time
from datetime import date, datetime, timedelta, timezone
import pytest
import httpx

from src.connectors.withings import WithingsScaleConnector, WithingsAPIError
from src.connectors.base import SimulationNotAllowedInProductionError
from src.crypto import encrypt_credentials, decrypt_credentials
from src.db import Database
from src.models import WeightEntry


@pytest.fixture
def temp_db(tmp_path):
    """Fixture créant une base de données isolée pour les tests."""
    db_file = tmp_path / "test_withings.db"
    db = Database(db_path=str(db_file))
    return db


def test_withings_authorization_url_builder():
    """Vérifie la construction d'URL d'autorisation OAuth2 Withings."""
    url = WithingsScaleConnector.build_authorization_url(
        client_id="withings_client_123",
        redirect_uri="https://vitaltrack.app/api/devices/withings/callback",
        state="secure_csrf_state_xyz",
        scope="user.metrics,user.info"
    )
    assert "https://account.withings.com/oauth2_user/authorize2" in url
    assert "client_id=withings_client_123" in url
    assert "response_type=code" in url
    assert "state=secure_csrf_state_xyz" in url
    assert "user.metrics" in url


def test_withings_exchange_authorization_code_success():
    """Vérifie l'échange du code d'autorisation contre les tokens via mock HTTP."""
    token_response_payload = {
        "status": 0,
        "body": {
            "access_token": "mock_access_token_abc",
            "refresh_token": "mock_refresh_token_def",
            "expires_in": 10800,
            "scope": "user.metrics,user.info",
            "userid": "123456",
            "token_type": "Bearer"
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(WithingsScaleConnector.TOKEN_URL)
        assert request.method == "POST"
        content = request.read().decode("utf-8")
        assert "action=requesttoken" in content
        assert "grant_type=authorization_code" in content
        assert "code=auth_code_789" in content
        return httpx.Response(200, json=token_response_payload)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        connector = WithingsScaleConnector(config={
            "client_id": "cid_test",
            "client_secret": "csec_test"
        })
        res = connector.exchange_authorization_code(
            code="auth_code_789",
            redirect_uri="https://vitaltrack.app/callback",
            client=client
        )
        assert res["access_token"] == "mock_access_token_abc"
        assert res["refresh_token"] == "mock_refresh_token_def"
        assert connector.is_configured is True
        assert connector.config["access_token"] == "mock_access_token_abc"
        assert connector.config["refresh_token"] == "mock_refresh_token_def"
        assert connector.config["withings_userid"] == "123456"
        assert not connector.is_token_expired()


def test_withings_token_expiration_and_refresh():
    """Vérifie la détection d'expiration et le rafraîchissement automatique réel."""
    refresh_response_payload = {
        "status": 0,
        "body": {
            "access_token": "new_refreshed_access_token",
            "refresh_token": "new_refresh_token_xyz",
            "expires_in": 7200,
            "token_type": "Bearer"
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        content = request.read().decode("utf-8")
        assert "grant_type=refresh_token" in content
        assert "refresh_token=old_refresh_token" in content
        return httpx.Response(200, json=refresh_response_payload)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        # Token déjà expiré
        connector = WithingsScaleConnector(config={
            "client_id": "cid_test",
            "client_secret": "csec_test",
            "access_token": "expired_access_token",
            "refresh_token": "old_refresh_token",
            "token_expiry": time.time() - 3600  # Expiré il y a 1h
        })
        assert connector.is_token_expired() is True

        new_token = connector.refresh_access_token_if_needed(client=client)
        assert new_token == "new_refreshed_access_token"
        assert connector.config["access_token"] == "new_refreshed_access_token"
        assert connector.config["refresh_token"] == "new_refresh_token_xyz"
        assert connector.is_token_expired() is False


def test_withings_encrypted_credentials_persistence(temp_db):
    """Vérifie que les tokens sont stockés de façon chiffrée au repos dans la base de données."""
    connector = WithingsScaleConnector(
        config={
            "client_id": "cid_sec",
            "client_secret": "csec_sec",
            "access_token": "secret_access_tok_456",
            "refresh_token": "secret_refresh_tok_789",
            "token_expiry": time.time() + 3600
        },
        db_instance=temp_db,
        user_id=1
    )
    connector.persist_credentials_to_db()

    # Lecture sans révélation des secrets (masquage)
    device_public = temp_db.get_user_device("withings", user_id=1, reveal_secrets=False)
    assert device_public is not None
    assert "access_token" not in device_public
    assert device_public["has_credentials"] is True

    # Lecture sécurisée interne
    device_internal = temp_db.get_user_device("withings", user_id=1, reveal_secrets=True)
    creds = device_internal.get("credentials", {})
    assert creds.get("client_id") == "cid_sec"
    assert creds.get("access_token") == "secret_access_tok_456"
    assert creds.get("refresh_token") == "secret_refresh_tok_789"


def test_withings_parse_all_body_composition_metrics():
    """Teste le parsing exhaustif : poids, masse grasse %, muscle, eau %, masse osseuse kg, IMC."""
    connector = WithingsScaleConnector(config={
        "client_id": "cid",
        "access_token": "tok",
        "user_height_m": 1.82
    })

    grp = {
        "date": 1735689600,  # 2025-01-01 00:00:00 UTC
        "category": 1,
        "measures": [
            {"value": 82450, "unit": -3, "type": 1},   # Poids 82.45 kg
            {"value": 1780, "unit": -2, "type": 6},    # Masse grasse 17.8 %
            {"value": 41200, "unit": -3, "type": 76},  # Masse musculaire 41.2 kg
            {"value": 5830, "unit": -2, "type": 77},   # Masse hydrique 58.3 %
            {"value": 3450, "unit": -3, "type": 88}    # Masse osseuse 3.45 kg
        ]
    }

    entry = connector.parse_withings_measure_group(grp)
    assert entry is not None
    assert entry.date == date(2025, 1, 1)
    assert entry.weight_kg == 82.45
    assert entry.body_fat_pct == 17.8
    assert entry.muscle_mass_kg == 41.2
    assert entry.water_pct == 58.3
    # IMC: 82.45 / (1.82^2) = 24.89... -> 24.9
    assert entry.bmi == 24.9
    assert "Masse osseuse: 3.45 kg" in entry.notes
    assert entry.source == "withings"
    assert entry.is_simulated is False


def test_withings_live_sync_incremental_cursor_and_idempotence():
    """Teste la synchronisation incrémentale avec curseur lastupdate et idempotence."""
    meas_response = {
        "status": 0,
        "body": {
            "updatetime": 1735695000,
            "more": 1735695000,
            "measuregrps": [
                {
                    "date": 1735689600,  # 2025-01-01
                    "category": 1,
                    "measures": [
                        {"value": 81500, "unit": -3, "type": 1},
                        {"value": 1820, "unit": -2, "type": 6}
                    ]
                },
                {
                    "date": 1735693200,  # 2025-01-01 plus tard dans la journée
                    "category": 1,
                    "measures": [
                        {"value": 81200, "unit": -3, "type": 1},  # Pesée retenue (dernière du jour)
                        {"value": 1810, "unit": -2, "type": 6}
                    ]
                },
                {
                    "date": 1735776000,  # 2025-01-02
                    "category": 1,
                    "measures": [
                        {"value": 80900, "unit": -3, "type": 1},
                        {"value": 1790, "unit": -2, "type": 6}
                    ]
                }
            ]
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        content = request.read().decode("utf-8")
        assert "action=getmeas" in content
        assert "lastupdate=1735600000" in content
        return httpx.Response(200, json=meas_response)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        connector = WithingsScaleConnector(config={
            "client_id": "cid",
            "access_token": "valid_token",
            "token_expiry": time.time() + 3600,
            "lastupdate": 1735600000
        })

        results = connector.sync_weights(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 2),
            client=client
        )
        assert len(results) == 2
        # Vérification dédoublonnage idempotent pour 2025-01-01 : la dernière pesée (81.2 kg) a prévalu
        assert results[0].date == date(2025, 1, 1)
        assert results[0].weight_kg == 81.2
        assert results[1].date == date(2025, 1, 2)
        assert results[1].weight_kg == 80.9
        # Curseur lastupdate mis à jour
        assert connector.config["lastupdate"] == 1735695000


def test_withings_rate_limit_and_error_recovery():
    """Teste la reprise sur rate limit Withings HTTP 429 et status 2555."""
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0.1"})
        elif attempts["count"] == 2:
            return httpx.Response(200, json={"status": 2555, "error": "Too many requests"})
        return httpx.Response(200, json={
            "status": 0,
            "body": {
                "measuregrps": [
                    {
                        "date": 1735689600,
                        "category": 1,
                        "measures": [{"value": 80000, "unit": -3, "type": 1}]
                    }
                ]
            }
        })

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        connector = WithingsScaleConnector(config={
            "client_id": "cid",
            "access_token": "valid_token",
            "token_expiry": time.time() + 3600
        })
        results = connector.sync_weights(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            client=client
        )
        assert len(results) == 1
        assert results[0].weight_kg == 80.0
        assert attempts["count"] == 3


def test_withings_no_simulated_data_in_production(monkeypatch):
    """Vérifie qu'en production, aucune donnée fictive n'est générée sans autorisation explicite."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    connector = WithingsScaleConnector()  # Non configuré
    assert not connector.is_configured

    with pytest.raises(SimulationNotAllowedInProductionError):
        connector.sync_weights(start_date=date.today() - timedelta(days=5), end_date=date.today())
