"""Tests d'architecture DI et de non-régression pour BALI-313.

Vérifie :
1. Zéro référence `src.app` dans `src/routers/` (aucun cycle d'import).
2. Aucune redéfinition locale de `get_db` / `get_current_user` / `get_strict_user` dans les routeurs.
3. Aucun module mort sous `src/` (tous les modules sont importés en production).
4. Identité d'objets entre `src.dependencies` et les ré-exports `src.app`.
5. Support natif complet de `app.dependency_overrides` pour `get_db`, `get_current_user`,
   `get_strict_user`, `get_device_registry`, `get_calorie_estimator`, `get_nutrition_engine`
   et les factories de repositories dédiés.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import Depends
from fastapi.testclient import TestClient

import src.app as app_module
from src.app import app
from src.auth import AuthUser
from src.db import Database
from src.dependencies import (
    get_calorie_estimator,
    get_current_user,
    get_db,
    get_device_registry,
    get_devices_repo,
    get_meals_repo,
    get_metrics_repo,
    get_nutrition_engine,
    get_strict_user,
    get_users_repo,
    get_weights_repo,
    invalidate_dashboard_cache,
)
from src.models import FoodItem, MealEntry, WeightEntry
from src.repositories import (
    DevicesRepository,
    MealsRepository,
    MetricsRepository,
    UsersRepository,
    WeightsRepository,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
ROUTERS_DIR = SRC_DIR / "routers"


def _fake_user(user_id: int = 1) -> AuthUser:
    return AuthUser(
        id=user_id,
        uuid=f"uuid-{user_id}",
        email=f"user{user_id}@vitaltrack.test",
        name="Arch Test User",
        auth_provider="email",
    )


def test_zero_src_app_references_in_routers():
    """Critère BALI-313 : `grep -r 'src.app' src/routers/` doit retourner 0 résultat."""
    offenders = []
    local_redefs = []
    forbidden_defs = {"get_db", "get_current_user", "get_strict_user", "get_nutrition_engine"}

    for py_file in sorted(ROUTERS_DIR.rglob("*.py")):
        content = py_file.read_text(encoding="utf-8")
        if "src.app" in content:
            offenders.append(str(py_file.relative_to(REPO_ROOT)))

        tree = ast.parse(content, filename=str(py_file))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in forbidden_defs:
                local_redefs.append(f"{py_file.relative_to(REPO_ROOT)}:{node.name}")

    assert offenders == [], f"Références circulaires src.app détectées dans les routeurs : {offenders}"
    assert local_redefs == [], f"Redéfinitions locales DI détectées dans les routeurs : {local_redefs}"


def test_no_dead_modules_in_src():
    """Critère BALI-313 : 0 module mort sous `src/` non importé en production."""
    all_modules: dict[str, Path] = {}
    for py_file in SRC_DIR.rglob("*.py"):
        rel = py_file.relative_to(REPO_ROOT).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            mod_name = ".".join(parts[:-1])
        else:
            mod_name = ".".join(parts)
        all_modules[mod_name] = py_file

    entrypoints = [
        REPO_ROOT / "api" / "index.py",
        SRC_DIR / "app.py",
        SRC_DIR / "daily_sync.py",
        REPO_ROOT / "scripts" / "seed_ciqual.py",
        REPO_ROOT / "scripts" / "seed_demo.py",
    ]

    visited_files: set[Path] = set()
    visited_modules: set[str] = set()
    queue: list[Path] = [p for p in entrypoints if p.is_file()]

    def _mark_module(mod_name: str) -> None:
        # Marquer le module ainsi que ses packages parents
        parts = mod_name.split(".")
        for i in range(1, len(parts) + 1):
            prefix = ".".join(parts[:i])
            if prefix in all_modules:
                visited_modules.add(prefix)
                path = all_modules[prefix]
                if path not in visited_files:
                    queue.append(path)

    while queue:
        current = queue.pop()
        if current in visited_files:
            continue
        visited_files.add(current)
        for mod_name, mod_path in all_modules.items():
            if mod_path == current:
                _mark_module(mod_name)

        tree = ast.parse(current.read_text(encoding="utf-8"), filename=str(current))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("src"):
                        _mark_module(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src"):
                _mark_module(node.module)
                for alias in node.names:
                    sub = f"{node.module}.{alias.name}"
                    if sub in all_modules:
                        _mark_module(sub)

    # Packages __init__.py vides ou simples marqueurs de package sont couverts dès qu'un sous-module est importé
    dead_modules = sorted(set(all_modules.keys()) - visited_modules)
    assert dead_modules == [], f"Modules morts détectés dans src/ : {dead_modules}"


def test_dependencies_identity_with_app_reexports():
    """Les ré-exports de `src.app` doivent pointer vers les mêmes objets que `src.dependencies`."""
    assert app_module.get_current_user is get_current_user
    assert app_module.get_strict_user is get_strict_user
    assert app_module.invalidate_dashboard_cache is invalidate_dashboard_cache


def test_dependency_overrides_db_and_current_user():
    """`app.dependency_overrides[get_db]` et `[get_current_user]` injectent directement les mocks."""
    mock_db = MagicMock(spec=Database)
    mock_db.get_user_profile.return_value = {"is_demo_profile": False}
    mock_db.get_weights.return_value = [
        WeightEntry(id=101, date=date(2026, 11, 20), weight_kg=74.2, source="manual")
    ]

    app.dependency_overrides[get_current_user] = lambda: _fake_user(99)
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        client = TestClient(app)
        resp_v1 = client.get("/api/weights")
        assert resp_v1.status_code == 200
        assert len(resp_v1.json()) == 1
        assert resp_v1.json()[0]["weight_kg"] == 74.2

        resp_v2 = client.get("/api/v2/weights")
        assert resp_v2.status_code == 200
        assert resp_v2.json()["meta"]["user_id"] == 99
        assert resp_v2.json()["data"][0]["weight_kg"] == 74.2
    finally:
        app.dependency_overrides.clear()


def test_dependency_overrides_device_registry():
    """`app.dependency_overrides[get_device_registry]` remplace le registre IoT dans les routeurs."""
    fake_connector = SimpleNamespace(
        id="fake_ring",
        name="Fake Ring Pro",
        device_type="ring",
        supported_features=["sync"],
    )
    mock_registry = MagicMock()
    mock_registry.list_all.return_value = [fake_connector]

    mock_db = MagicMock(spec=Database)
    mock_db.get_user_devices.return_value = []

    app.dependency_overrides[get_current_user] = lambda: _fake_user(12)
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_device_registry] = lambda: mock_registry
    try:
        client = TestClient(app)
        resp = client.get("/api/devices")
        assert resp.status_code == 200
        devices = resp.json()
        assert len(devices) == 1
        assert devices[0]["device_id"] == "fake_ring"
        assert devices[0]["name"] == "Fake Ring Pro"
    finally:
        app.dependency_overrides.clear()


def test_dependency_overrides_calorie_estimator():
    """`app.dependency_overrides[get_calorie_estimator]` remplace l'estimateur photo/OpenFoodFacts."""
    mock_estimator = MagicMock()
    mock_estimator.fetch_openfoodfacts_barcode.return_value = {
        "name": "Override Yogurt",
        "portion_g": 125.0,
        "cal_100g": 80.0,
        "protein_g": 5.0,
        "carbs_g": 10.0,
        "fat_g": 2.0,
        "fiber_g": 0.0,
    }

    app.dependency_overrides[get_current_user] = lambda: _fake_user(5)
    app.dependency_overrides[get_calorie_estimator] = lambda: mock_estimator
    try:
        client = TestClient(app)
        resp = client.get("/api/meals/barcode/3017620422003")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Override Yogurt"
        mock_estimator.fetch_openfoodfacts_barcode.assert_called_once_with("3017620422003")
    finally:
        app.dependency_overrides.clear()


def test_dependency_overrides_nutrition_engine():
    """`app.dependency_overrides[get_nutrition_engine]` injecte le moteur nutritionnel dans POST /api/meals."""
    mock_db = MagicMock(spec=Database)
    mock_engine = MagicMock()
    mock_engine.log_meal.return_value = MealEntry(
        id=77,
        date=date(2026, 11, 27),
        meal_type="lunch",
        total_calories_kcal=510.0,
        protein_g=42.0,
        carbs_g=50.0,
        fat_g=14.0,
        fiber_g=6.0,
        items=[FoodItem(name="Poulet Riz", calories_kcal=510.0, protein_g=42.0, carbs_g=50.0, fat_g=14.0)],
    )

    app.dependency_overrides[get_current_user] = lambda: _fake_user(8)
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_nutrition_engine] = lambda: mock_engine
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/meals",
            json={
                "date": "2026-11-27",
                "meal_type": "lunch",
                "items": [
                    {
                        "name": "Poulet Riz",
                        "calories_kcal": 510.0,
                        "protein_g": 42.0,
                        "carbs_g": 50.0,
                        "fat_g": 14.0,
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == 77
        mock_engine.log_meal.assert_called_once()
        mock_db.sync_meal_items_to_meal_log.assert_called_once()
    finally:
        app.dependency_overrides.clear()


def test_dependency_overrides_strict_user():
    """`app.dependency_overrides[get_strict_user]` fonctionne sur PUT /api/auth/config."""
    mock_db = MagicMock(spec=Database)
    mock_db.set_google_client_id.return_value = {"google_client_id": "test-client-id.apps.googleusercontent.com"}

    app.dependency_overrides[get_strict_user] = lambda: _fake_user(1)
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        client = TestClient(app)
        resp = client.put(
            "/api/auth/config",
            json={"google_client_id": "test-client-id.apps.googleusercontent.com"},
        )
        assert resp.status_code == 200
        mock_db.set_google_client_id.assert_called_once_with("test-client-id.apps.googleusercontent.com")
    finally:
        app.dependency_overrides.clear()


def test_repository_dependency_providers(temp_db):
    """Les factories de repositories de `src.dependencies` retournent les repositories liés à `db`."""
    assert isinstance(get_weights_repo(temp_db), WeightsRepository)
    assert isinstance(get_meals_repo(temp_db), MealsRepository)
    assert isinstance(get_devices_repo(temp_db), DevicesRepository)
    assert isinstance(get_users_repo(temp_db), UsersRepository)
    assert isinstance(get_metrics_repo(temp_db), MetricsRepository)
    assert get_weights_repo(temp_db) is temp_db.weights
    assert get_meals_repo(temp_db) is temp_db.meals
    assert get_devices_repo(temp_db) is temp_db.devices
    assert get_users_repo(temp_db) is temp_db.users
    assert get_metrics_repo(temp_db) is temp_db.metrics
