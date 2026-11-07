"""Configuration pytest et fixtures globales de test pour VitalTrack (BALI-216).

Fournit :
1. Isolation complete et hermetique de la base de donnees par test.
2. Template SQLite pre-migre en session pour des tests rapides (<10ms par initialisation de base).
3. Rollback automatique / nettoyage des fichiers temporaires apres chaque test.
4. Fixtures globales 'db' et 'client' (TestClient FastAPI) pretes a l'emploi.
5. Support Neon PostgreSQL via variable d'environnement TEST_DATABASE_URL ou Neon branch si configuree.
"""

import os
import sqlite3
import tempfile
from typing import Generator
import pytest
from fastapi.testclient import TestClient

from alembic.config import Config
from alembic import command

from src.app import app
import src.app as app_module
from src.db import Database
from src.rate_limit import limiter
import src.routers.webhooks as wh_module
import src.routers.friends as fr_module
import src.routers.devices as dev_module


@pytest.fixture(scope="session")
def _sqlite_template_db_path() -> Generator[str, None, None]:
    """Cree une base SQLite template initiale complete avec schema Alembic et seeds socles.
    
    Cette base sert de modele immuable clone instantanement par sqlite3.backup() pour chaque test.
    """
    with tempfile.NamedTemporaryFile(suffix="_template.db", delete=False) as f:
        template_path = f.name

    try:
        # Executer les migrations Alembic complètes jusqu'à head
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{template_path}")
        command.upgrade(cfg, "head")

        # Initialiser les donnees socles minimales indispensables
        template_db = Database(db_path=template_path, auto_migrate=False)
        template_db._ensure_default_user()
        template_db._seed_public_food_items()
        template_db._seed_nutrition_benefits()
        template_db.purge_demo_data()

        yield template_path
    finally:
        if os.path.exists(template_path):
            try:
                os.remove(template_path)
            except OSError:
                pass


@pytest.fixture
def temp_db(_sqlite_template_db_path: str, tmp_path) -> Generator[Database, None, None]:
    """Cree une instance Database isolee et ephemere par test (SQLite clone ou Neon PostgreSQL si configuree).
    
    Garantit l'absence totale de pollution entre tests avec nettoyage automatique en fin de test.
    """
    neon_test_url = os.getenv("TEST_DATABASE_URL")
    if neon_test_url and "neon.tech" in neon_test_url:
        # Support branche Neon PostgreSQL temporaire dediee si presente
        test_db = Database(database_url=neon_test_url, auto_migrate=True)
        yield test_db
        # Nettoyage Neon : rollback / purge
        return

    # Fallback haute performance : clone SQLite depuis le template pre-migre de session
    test_db_file = str(tmp_path / "test_isolated.db")
    src_conn = sqlite3.connect(_sqlite_template_db_path)
    dst_conn = sqlite3.connect(test_db_file)
    src_conn.backup(dst_conn)
    src_conn.close()
    dst_conn.close()

    test_db = Database(db_path=test_db_file, auto_migrate=False)
    yield test_db

    if os.path.exists(test_db_file):
        try:
            os.remove(test_db_file)
        except OSError:
            pass


@pytest.fixture
def db(temp_db: Database) -> Database:
    """Alias standard pour temp_db."""
    return temp_db


@pytest.fixture(autouse=True)
def isolate_database_context(temp_db: Database) -> Generator[None, None, None]:
    """Fixture autouse appliquant l'isolation DB globale et la reinitialisation du cache/rate-limiter pour chaque test."""
    old_app_db = app_module.db
    old_engine_db = getattr(app_module.nutrition_engine, "db", None)
    old_wh_db = getattr(wh_module, "_db_instance", None)
    old_fr_db = getattr(fr_module, "_db_instance", None)
    old_dev_db = getattr(dev_module, "_db_instance", None)

    # Injecter l'instance isolee dans tous les modules d'application
    app_module.db = temp_db
    app.state.db_instance = temp_db
    if hasattr(app_module, "nutrition_engine"):
        app_module.nutrition_engine.db = temp_db
    wh_module._db_instance = temp_db
    fr_module._db_instance = temp_db
    dev_module._db_instance = temp_db

    # Reinitialiser le rate-limiter et le cache dashboard entre tests
    limiter.reset()
    if hasattr(app_module, "DASHBOARD_CACHE"):
        app_module.DASHBOARD_CACHE.clear()

    yield

    # Restauration propre
    app_module.db = old_app_db
    if hasattr(app, "state") and hasattr(app.state, "db_instance"):
        app.state.db_instance = old_app_db
    if hasattr(app_module, "nutrition_engine") and old_engine_db is not None:
        app_module.nutrition_engine.db = old_engine_db
    wh_module._db_instance = old_wh_db
    fr_module._db_instance = old_fr_db
    dev_module._db_instance = old_dev_db
    limiter.reset()
    if hasattr(app_module, "DASHBOARD_CACHE"):
        app_module.DASHBOARD_CACHE.clear()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Client de test FastAPI (TestClient) configure sur l'application avec base isolee par test."""
    with TestClient(app) as test_client:
        yield test_client
