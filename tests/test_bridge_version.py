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
    assert data["apk_url"].startswith("https://github.com/TheBigBad31/VitalTrack/releases/")
    assert "sha256" in data and isinstance(data["sha256"], str)
    assert isinstance(data["release_notes"], str) and data["release_notes"]

    dl = client.get("/api/downloads/android-bridge", follow_redirects=False)
    assert dl.status_code == 307
    assert dl.headers["location"] == data["apk_url"]
