"""Tests unitaires pour les correctifs BALI-311."""

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from src.app import app, general_exception_handler
from src.auth import AuthUser
from src.db import Database


def _mock_user(user_id: int = 42) -> AuthUser:
    return AuthUser(id=user_id, uuid=f"uuid-{user_id}", email=f"user{user_id}@example.com", name="Test User", role="user")


def test_v2_dashboard_returns_200_and_v2_envelope():
    app.dependency_overrides.clear()
    from src.app import get_current_user

    app.dependency_overrides[get_current_user] = lambda: _mock_user(42)
    try:
        with patch("src.routers.dashboard.get_dashboard_data", return_value={"ok": True}):
            client = TestClient(app)
            resp = client.get("/api/v2/dashboard")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == {"ok": True}
        assert body["meta"]["version"] == "2.0.0"
        assert body["meta"]["user_id"] == 42
    finally:
        app.dependency_overrides.clear()


def test_v2_weight_uses_profile_height_cm():
    app.dependency_overrides.clear()
    from src.app import get_current_user

    app.dependency_overrides[get_current_user] = lambda: _mock_user(7)
    mock_db = MagicMock()
    mock_db.get_user_profile.return_value = {"height_cm": 200.0}
    mock_db.insert_weight.side_effect = lambda entry, user_id=None: entry
    try:
        with patch("src.app.db", mock_db), patch("src.app.invalidate_dashboard_cache") as inv:
            client = TestClient(app)
            resp = client.post("/api/v2/weights", json={"weight_kg": 80.0})
        assert resp.status_code == 200
        assert resp.json()["data"]["bmi"] == 20.0
        inv.assert_called_once_with(7)
    finally:
        app.dependency_overrides.clear()


def test_hydration_invalidates_dashboard_cache():
    app.dependency_overrides.clear()
    from src.app import get_current_user

    app.dependency_overrides[get_current_user] = lambda: _mock_user(11)
    mock_db = MagicMock()
    mock_db.insert_hydration_log.side_effect = lambda entry, user_id=None: entry
    mock_db.get_daily_hydration_total.return_value = 500.0
    mock_db.get_user_profile.return_value = {"daily_water_target_ml": 2000.0}
    try:
        with patch("src.app.db", mock_db), patch("src.app.invalidate_dashboard_cache") as inv:
            client = TestClient(app)
            resp = client.post("/api/metrics/hydration", json={"volume_ml": 250})
        assert resp.status_code == 200
        inv.assert_called_once_with(11)
    finally:
        app.dependency_overrides.clear()


def test_find_user_by_withings_id_and_webhook_multitenant():
    from src.repositories.devices import DevicesRepository

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [{"id": 1, "user_id": 9, "device_id": "withings"}]
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor

    mock_db = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    repo = DevicesRepository(mock_db)
    with patch.object(
        repo,
        "_format_device_row",
        return_value={"user_id": 9, "device_id": "withings", "credentials": {"withings_user_id": "998877"}},
    ):
        found = repo.find_user_by_withings_id("998877")
        assert found is not None
        assert found["user_id"] == 9
        assert repo.find_user_by_withings_id("000000") is None


def test_general_exception_handler_hides_details_in_prod(monkeypatch):
    import asyncio
    from starlette.requests import Request

    monkeypatch.setenv("ENVIRONMENT", "production")
    scope = {"type": "http", "method": "GET", "path": "/boom", "headers": []}
    req = Request(scope)
    resp = asyncio.run(general_exception_handler(req, RuntimeError("secret-db-password")))
    assert resp.status_code == 500
    import json
    payload = json.loads(resp.body.decode("utf-8"))
    assert "type" not in payload
    assert "secret-db-password" not in payload["detail"]
