from datetime import date
from fastapi.testclient import TestClient

from src.app import app, get_current_user
from src.auth import AuthUser
from src.dependencies import get_db
from src.models import WorkoutEntry
from src.repositories.metrics import workout_local_date


def test_workout_local_date_europe_paris():
    # 23:30 UTC on Nov 26 is 00:30 CET on Nov 27 in Europe/Paris
    assert workout_local_date("2026-11-26T23:30:00Z", "Europe/Paris") == date(2026, 11, 27)
    assert workout_local_date("2026-11-26T23:30:00+00:00", "Europe/Paris") == date(2026, 11, 27)
    assert workout_local_date("2026-11-26T22:30:00Z", "Europe/Paris") == date(2026, 11, 26)
    assert workout_local_date(None, "Europe/Paris") is None


def test_get_workouts_orders_most_recent_first():
    db = get_db()
    w_old = WorkoutEntry(
        workout_type="running",
        start_time="2026-11-20T08:00:00Z",
        end_time="2026-11-20T08:30:00Z",
        duration_minutes=30,
        calories_kcal=250.0,
        source="health_connect",
        external_id="test-old-1",
    )
    w_new = WorkoutEntry(
        workout_type="cycling",
        start_time="2026-11-27T08:00:00Z",
        end_time="2026-11-27T08:45:00Z",
        duration_minutes=45,
        calories_kcal=420.0,
        source="health_connect",
        external_id="test-new-1",
    )
    db.insert_workout(w_old, user_id=1)
    db.insert_workout(w_new, user_id=1)

    workouts = db.get_workouts(limit=10, user_id=1)
    times = [w.start_time for w in workouts]
    assert times.index("2026-11-27T08:00:00Z") < times.index("2026-11-20T08:00:00Z")


def test_health_connect_diagnostics_endpoint():
    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=1, uuid="test-uuid-1", email="test@example.com", role="user")
    try:
        client = TestClient(app)
        res_diag = client.get("/api/devices/health-connect/diagnostics")
        assert res_diag.status_code == 200
        data = res_diag.json()
        assert "recent_ingests" in data
        assert "total_workouts_stored" in data
        assert "latest_workout" in data
    finally:
        app.dependency_overrides.pop(get_current_user, None)
