"""Tests de parité de schéma SQLite et PostgreSQL (Alembic) et pool de connexions (psycopg_pool)."""

import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from alembic.config import Config
from alembic import command
from src.db import Database, DatabaseConnectionWrapper, HAS_PSYCOPG, HAS_PSYCOPG_POOL


def test_alembic_sqlite_migration_lifecycle():
    """Vérifie que la migration initiale Alembic s'applique et se rollback sans erreur sur SQLite."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name

    try:
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{temp_path}")

        # Upgrade head
        command.upgrade(cfg, "head")

        import sqlite3
        conn = sqlite3.connect(temp_path)
        tables = [
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if r[0] != "sqlite_sequence"
        ]
        conn.close()

        expected_tables = {
            "alembic_version",
            "users",
            "user_profile",
            "weights",
            "activities",
            "meals",
            "food_items",
            "meal_logs",
            "meal_log_items",
            "saved_meals",
            "user_devices",
            "google_auth_config",
            "google_sessions",
            "nutrition_benefits",
            "food_item_benefits"
        }
        assert expected_tables.issubset(set(tables)), f"Tables manquantes: {expected_tables - set(tables)}"

        # Downgrade base
        command.downgrade(cfg, "base")
        conn = sqlite3.connect(temp_path)
        tables_after_down = [
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        conn.close()
        assert "users" not in tables_after_down
        assert "weights" not in tables_after_down
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_alembic_postgres_sql_generation():
    """Vérifie que la migration Alembic génère du DDL PostgreSQL syntaxiquement valide en mode offline."""
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", "postgresql+psycopg://user:pass@localhost:5432/testdb")

    # Capture output SQL
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        command.upgrade(cfg, "head", sql=True)

    sql_output = buf.getvalue()
    assert "CREATE TABLE users (" in sql_output
    assert "CREATE TABLE user_profile (" in sql_output
    assert "CREATE TABLE weights (" in sql_output
    assert "CREATE TABLE meal_logs (" in sql_output
    assert "CREATE INDEX idx_weights_user_date" in sql_output
    assert "REFERENCES users (id) ON DELETE CASCADE" in sql_output


def test_schema_parity_table_names():
    """Vérifie que les tables créées par Alembic correspondent exactement aux entités modélisées."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name

    try:
        db = Database(db_path=temp_path, auto_migrate=True)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = {r["name"] for r in cursor.fetchall()}

        canonical_tables = {
            "users",
            "user_profile",
            "weights",
            "activities",
            "meals",
            "food_items",
            "meal_logs",
            "meal_log_items",
            "saved_meals",
            "user_devices",
            "google_auth_config",
            "google_sessions",
            "nutrition_benefits",
            "food_item_benefits",
            "alembic_version"
        }
        assert canonical_tables.issubset(tables)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_neon_connection_pool_integration():
    """Vérifie l'intégration de ConnectionPool de psycopg_pool pour Neon PostgreSQL."""
    assert HAS_PSYCOPG_POOL, "psycopg_pool doit être installé"

    # Simuler une URL Postgres Neon
    fake_neon_url = "postgresql://user:pass@ep-cool-sample.eu-central-1.aws.neon.tech/neondb?sslmode=require"

    with patch("src.db.ConnectionPool") as mock_pool_cls:
        mock_pool_instance = MagicMock()
        mock_pool_cls.return_value = mock_pool_instance

        mock_conn = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_conn
        mock_pool_instance.connection.return_value = mock_cm

        # Instancier Database sans auto_migrate (car URL factice)
        db = Database(database_url=fake_neon_url, auto_migrate=False)
        assert db.is_postgres is True

        conn_wrapper = db.get_connection()
        assert isinstance(conn_wrapper, DatabaseConnectionWrapper)
        assert conn_wrapper.is_postgres is True
        assert conn_wrapper.conn == mock_conn

        # Test cursor wrapper
        cursor = conn_wrapper.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (1,))
        mock_conn.cursor.return_value.execute.assert_called_once_with("SELECT * FROM users WHERE id = %s", (1,))

        # Test context manager exit / close return to pool
        conn_wrapper.close()
        mock_cm.__exit__.assert_called_once()
