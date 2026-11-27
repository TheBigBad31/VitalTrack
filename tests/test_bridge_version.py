from fastapi.testclient import TestClient

from src.app import app


def test_get_bridge_version():
    client = TestClient(app)
    resp = client.get("/api/bridge/version")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["version_code"], int)
    assert data["version_code"] >= 1
    assert isinstance(data["version_name"], str) and data["version_name"]
    assert data["apk_url"] == "/static/downloads/vitaltrack-health-bridge.apk"
    assert isinstance(data["release_notes"], str) and data["release_notes"]
