import os
import time
from datetime import date
import pytest
from starlette.testclient import TestClient

import src.app as app_module
from src.app import app, DASHBOARD_CACHE, invalidate_dashboard_cache
from src.auth import AuthUser
from src.db import Database
from src.models import CatalogItem
from src.daily_sync import run_daily_sync


@pytest.fixture
def test_setup(tmp_path, monkeypatch):
    test_db_path = str(tmp_path / "test_perf.db")
    test_db = Database(db_path=test_db_path, auto_migrate=True)
    monkeypatch.setattr(app_module, "db", test_db)

    user = test_db.get_or_create_user("perf_user@example.com", name="Perf User")
    return test_db, user


def test_batch_add_items_to_meal_log_perf(test_setup):
    """Test performance of batch adding 200 meal log items in 1 transaction (< 1.0 s)."""
    test_db, test_user = test_setup
    user_id = test_user["id"]

    # Create a reference food item
    food = test_db.insert_food_item(
        CatalogItem(
            name="Superfood Batch",
            calories_per_unit=150.0,
            protein_per_unit_g=10.0,
            carbs_per_unit_g=20.0,
            fat_per_unit_g=3.0,
            default_quantity=100.0,
            default_unit="g",
        ),
        user_id=user_id,
    )

    items = [
        {
            "food_item_id": food.id,
            "name": "Superfood Batch",
            "quantity": 100.0,
            "unit": "g",
            "calories": 150.0,
            "protein_g": 10.0,
            "carbs_g": 20.0,
            "fat_g": 3.0,
            "fiber_g": 1.0,
        }
        for _ in range(200)
    ]

    t0 = time.perf_counter()
    updated_log = test_db.batch_add_items_to_meal_log(
        date(2026, 11, 3), "lunch", items, user_id=user_id
    )
    duration = time.perf_counter() - t0

    assert len(updated_log.items) == 200
    assert duration < 1.0, f"Batch insert of 200 items took {duration:.3f}s (must be < 1s)"

    # Verify recalculation of parent log
    assert updated_log.total_calories == 150.0 * 200


def test_food_items_pagination(test_setup):
    """Test catalog search and pagination."""
    test_db, test_user = test_setup
    user_id = test_user["id"]
    for i in range(15):
        test_db.insert_food_item(
            CatalogItem(
                name=f"PaginItem {i:02d}",
                calories_per_unit=100.0 + i,
                protein_per_unit_g=5.0,
                carbs_per_unit_g=10.0,
                fat_per_unit_g=2.0,
                default_quantity=100.0,
                default_unit="g",
            ),
            user_id=user_id,
        )

    page1 = test_db.get_food_items(query="PaginItem", user_id=user_id, limit=5, offset=0)
    page2 = test_db.get_food_items(query="PaginItem", user_id=user_id, limit=5, offset=5)

    assert len(page1) == 5
    assert len(page2) == 5
    names1 = [it.name for it in page1]
    names2 = [it.name for it in page2]
    assert set(names1).isdisjoint(set(names2))


def test_dashboard_cache_and_invalidation(test_setup):
    """Test dashboard in-memory caching and invalidation on write."""
    test_db, test_user = test_setup
    user_id = test_user["id"]
    invalidate_dashboard_cache(user_id)

    auth_user = AuthUser(
        id=user_id,
        uuid=test_user["uuid"],
        email=test_user["email"],
        name=test_user.get("name", "Perf User"),
    )

    client = TestClient(app)

    # Monkeypatch auth to return test_user
    app.dependency_overrides[app_module.get_current_user] = lambda: auth_user

    try:
        # Call 1: Populates cache
        r1 = client.get("/api/dashboard")
        assert r1.status_code == 200
        cache_key = (user_id, False)
        assert cache_key in DASHBOARD_CACHE

        cached_ts, cached_payload = DASHBOARD_CACHE[cache_key]
        assert cached_payload == r1.json()

        # Call 2: Hit cache
        r2 = client.get("/api/dashboard")
        assert r2.status_code == 200
        assert r2.json() == cached_payload

        # Invalidate cache
        invalidate_dashboard_cache(user_id)
        assert cache_key not in DASHBOARD_CACHE

    finally:
        app.dependency_overrides.clear()


def test_daily_sync_error_handling(test_setup, monkeypatch):
    """Test daily sync returns False when a device sync fails."""
    test_db, test_user = test_setup
    user_id = test_user["id"]

    # Register a device for user
    test_db.update_user_device(
        device_id="withings",
        name="Withings Scale",
        device_type="scale",
        connected=True,
        api_key="dummy_key",
        user_id=user_id,
    )

    # Force connector to fail
    from src.connectors.withings import WithingsScaleConnector
    monkeypatch.setattr(
        WithingsScaleConnector,
        "sync_weights",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("API Network Timeout")),
    )

    success = run_daily_sync(test_db)
    assert success is False
