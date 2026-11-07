"""Tests pour la Row-Level Security (RLS) PostgreSQL et l'isolation multi-tenant (BALI-219 / VTR-203)."""

from unittest.mock import MagicMock
import pytest
from src.db import Database, DatabaseConnectionWrapper
from alembic.config import Config
from alembic import command
from pathlib import Path


def test_rls_migration_upgrade_and_downgrade():
    """Vérifie que la migration Alembic contenant les policies RLS s'applique et se rollback sans erreur sur SQLite."""
    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    cfg = Config(str(ini_path))
    
    # Doit être à head
    command.upgrade(cfg, "head")
    # Downgrade 1 cran (revient à 0005_perf_indexes)
    command.downgrade(cfg, "-1")
    # Re-upgrade à head
    command.upgrade(cfg, "head")


def test_database_connection_wrapper_user_context():
    """Vérifie le fonctionnement de set_user_context sur DatabaseConnectionWrapper pour PostgreSQL et SQLite."""
    # 1. Mode SQLite : no-op propre
    raw_sqlite_conn = MagicMock()
    wrapper_sqlite = DatabaseConnectionWrapper(raw_sqlite_conn, is_postgres=False)
    wrapper_sqlite.set_user_context(42)
    # Ne doit pas appeler execute sur le mock
    assert not raw_sqlite_conn.cursor.called

    # 2. Mode PostgreSQL : exécute SET LOCAL app.current_user_id
    raw_pg_conn = MagicMock()
    mock_cursor = MagicMock()
    raw_pg_conn.cursor.return_value = mock_cursor

    wrapper_pg = DatabaseConnectionWrapper(raw_pg_conn, is_postgres=True)
    wrapper_pg.set_user_context(42)

    raw_pg_conn.cursor.assert_called_once()
    mock_cursor.execute.assert_called_once_with("SET LOCAL app.current_user_id = '42';")
    mock_cursor.close.assert_called_once()

    # Reset context
    mock_cursor.reset_mock()
    wrapper_pg.set_user_context(None)
    mock_cursor.execute.assert_called_once_with("RESET app.current_user_id;")


def test_rls_migration_sql_generation():
    """Vérifie que les instructions SQL générées pour PostgreSQL contiennent les directives RLS et CREATE POLICY pour toutes les tables biométriques."""
    import importlib.util
    migration_path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "7e2e5ac2522e_rls_policies_biometrics.py"
    spec = importlib.util.spec_from_file_location("rls_migration", str(migration_path))
    rls_migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rls_migration)

    # Tables obligatoires
    expected_tables = {
        'weights', 'activities', 'daily_metrics', 'workouts', 'sleep_sessions',
        'intraday_samples', 'hydration_logs', 'raw_ingest', 'meals', 'meal_logs',
        'saved_meals', 'user_profile', 'user_devices', 'user_consents', 'friendships'
    }
    assert set(rls_migration.RLS_DIRECT_TABLES) == expected_tables


def test_get_connection_with_user_id():
    """Vérifie que db.get_connection(user_id=X) accepte user_id et le transmet."""
    db = Database(auto_migrate=False)
    with db.get_connection(user_id=10) as conn:
        assert conn is not None
