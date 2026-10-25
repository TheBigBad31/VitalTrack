"""Gestion de la base de données universelle pour VitalTrack.

Supporte une architecture hybride :
1. PostgreSQL Serverless (Neon) :
   - Détection automatique via DATABASE_URL ou POSTGRES_URL
   - Connexions résilientes avec SSL (sslmode=require)
   - Support PGBouncer et cold-starts Vercel
2. Fallback SQLite local :
   - Détection si aucune variable PostgreSQL n'est fournie
   - Persistance dans data/vitaltrack.db ou /tmp/vitaltrack.db (Vercel)
   - 100% compatible avec l'environnement de développement et pytest

Modélisation multi-utilisateurs :
- Table users (id, uuid, email, password_hash, auth_provider, google_sub, name, picture, created_at, updated_at)
- Table user_profile (user_id REFERENCES users(id) ON DELETE CASCADE)
- Table weights (user_id, date, ...) avec contrainte UNIQUE(user_id, date)
- Table activities (user_id, date, ...) avec contrainte UNIQUE(user_id, date)
- Table meals (user_id, date, ...)
- Table user_devices (user_id, device_id, ...) avec contrainte UNIQUE(user_id, device_id)
- Table google_auth_config & google_sessions
"""

import json
import math
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

from src.models import (
    ActivityEntry, AssociatedBenefit, CatalogItem, FoodItem, MealEntry,
    MealLog, MealLogItem, NutritionBenefitItem, SavedMeal, WeightEntry,
    DailyMetricsEntry, WorkoutEntry, SleepSessionEntry, SleepStageEntry,
    IntradaySampleEntry, HydrationLogEntry, RawIngestEntry, UserConsentItem
)
from src.crypto import encrypt_data, decrypt_data, encrypt_credentials, decrypt_credentials

# Essai d'import de psycopg et psycopg_pool pour le support Neon PostgreSQL
try:
    import psycopg
    from psycopg.rows import dict_row
    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False

try:
    import psycopg_pool
    from psycopg_pool import ConnectionPool
    HAS_PSYCOPG_POOL = True
except ImportError:
    HAS_PSYCOPG_POOL = False


class DatabaseServiceUnavailableError(RuntimeError):
    """Exception levée lorsque PostgreSQL/Neon est inaccessible en environnement de production."""
    pass


def is_production_environment() -> bool:
    """Détermine si l'application s'exécute en environnement hébergé / production."""
    if os.getenv("VERCEL") == "1" or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return True
    env_name = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("NODE_ENV") or ""
    if env_name.lower() in ("production", "prod", "staging"):
        return True
    if os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("NEON_DATABASE_URL"):
        return True
    return False


def get_database_url() -> Optional[str]:
    """Récupère l'URL de connexion PostgreSQL si configurée."""
    url = (
        os.getenv("DATABASE_URL")
        or os.getenv("POSTGRES_URL")
        or os.getenv("POSTGRES_URL_NON_POOLING")
        or os.getenv("POSTGRES_PRISMA_URL")
        or os.getenv("NEON_DATABASE_URL")
    )
    if url:
        # Assurer la compatibilité avec le driver psycopg
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        # Gestion du SSL si absent
        if "sslmode=" not in url and ("neon.tech" in url or "vercel" in url or "ssl=true" in url):
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}sslmode=require"
    return url


def get_db_path() -> str:
    """Détermine le chemin optimal pour la base SQLite selon l'environnement."""
    if os.getenv("VERCEL") == "1" or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        tmp_path = Path("/tmp") / "vitaltrack.db"
        return str(tmp_path)

    local_dir = Path(__file__).resolve().parent.parent / "data"
    try:
        local_dir.mkdir(parents=True, exist_ok=True)
        return str(local_dir / "vitaltrack.db")
    except (OSError, PermissionError):
        tmp_path = Path("/tmp") / "vitaltrack.db"
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        return str(tmp_path)


class DatabaseCursorWrapper:
    """Wrapper unifié pour curseurs SQLite et PostgreSQL."""

    def __init__(self, raw_cursor: Any, is_postgres: bool):
        self.cursor = raw_cursor
        self.is_postgres = is_postgres

    def execute(self, sql: str, params: Optional[Union[tuple, list, dict]] = None):
        if self.is_postgres:
            # En PostgreSQL, remplacer le placeholder '?' par '%s'
            pg_sql = sql.replace("?", "%s")
            if params is None:
                return self.cursor.execute(pg_sql)
            return self.cursor.execute(pg_sql, tuple(params) if isinstance(params, list) else params)
        else:
            if params is None:
                return self.cursor.execute(sql)
            return self.cursor.execute(sql, tuple(params) if isinstance(params, list) else params)

    def fetchone(self) -> Optional[Dict[str, Any]]:
        row = self.cursor.fetchone()
        if row is None:
            return None
        if self.is_postgres:
            return dict(row)
        return dict(row)

    def fetchall(self) -> List[Dict[str, Any]]:
        rows = self.cursor.fetchall()
        if self.is_postgres:
            return [dict(r) for r in rows]
        return [dict(r) for r in rows]

    @property
    def rowcount(self) -> int:
        return getattr(self.cursor, "rowcount", -1)

    @property
    def lastrowid(self) -> Optional[int]:
        if not self.is_postgres:
            return self.cursor.lastrowid
        # Sur Postgres, lastrowid n'est pas standardisé de la même manière, géré par RETURNING
        return getattr(self.cursor, "lastrowid", None)


class DatabaseConnectionWrapper:
    """Wrapper unifié pour connexions SQLite et PostgreSQL."""

    def __init__(self, raw_conn: Any, is_postgres: bool, pool_conn_cm: Any = None):
        self.conn = raw_conn
        self.is_postgres = is_postgres
        self.pool_conn_cm = pool_conn_cm

    def cursor(self) -> DatabaseCursorWrapper:
        if self.is_postgres:
            return DatabaseCursorWrapper(self.conn.cursor(row_factory=dict_row), is_postgres=True)
        else:
            return DatabaseCursorWrapper(self.conn.cursor(), is_postgres=False)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        if self.pool_conn_cm is not None:
            try:
                self.pool_conn_cm.__exit__(None, None, None)
            except Exception:
                pass
            self.pool_conn_cm = None
        else:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


_POSTGRES_POOL: Optional[Any] = None
_INIT_MIGRATIONS_DONE: bool = False


class Database:
    """Gestionnaire de persistance hybride (PostgreSQL Serverless Neon & SQLite Fallback)."""

    def __init__(self, db_path: Optional[str] = None, database_url: Optional[str] = None, auto_migrate: bool = True):
        self.database_url = database_url or get_database_url()
        self.is_postgres = bool(self.database_url and HAS_PSYCOPG)
        self.db_path = db_path or get_db_path()
        if auto_migrate:
            self.run_migrations()

    def _get_pool(self) -> Optional[Any]:
        """Initialise ou réutilise le pool de connexions psycopg_pool pour Neon Serverless."""
        global _POSTGRES_POOL
        if not self.is_postgres or not HAS_PSYCOPG_POOL:
            return None
        if _POSTGRES_POOL is None or getattr(_POSTGRES_POOL, "closed", False):
            try:
                _POSTGRES_POOL = ConnectionPool(
                    self.database_url,
                    min_size=0,
                    max_size=10,
                    timeout=10.0,
                    max_idle=300.0,
                    max_lifetime=1800.0,
                    open=True,
                    kwargs={"autocommit": False}
                )
            except Exception as e:
                print(f"[VitalTrack DB Warning] Impossible d'initialiser ConnectionPool Neon: {e}")
                _POSTGRES_POOL = None
        return _POSTGRES_POOL

    def get_connection(self) -> DatabaseConnectionWrapper:
        """Fournit une connexion unifiée (PostgreSQL avec ConnectionPool ou SQLite)."""
        if self.is_postgres:
            pool = self._get_pool()
            if pool is not None:
                try:
                    pool_cm = pool.connection(timeout=10.0)
                    conn = pool_cm.__enter__()
                    return DatabaseConnectionWrapper(conn, is_postgres=True, pool_conn_cm=pool_cm)
                except Exception as e:
                    print(f"[VitalTrack DB Warning] Échec obtention connexion depuis pool Neon: {e}. Essai connexion directe.")
            try:
                conn = psycopg.connect(self.database_url, connect_timeout=10)
                return DatabaseConnectionWrapper(conn, is_postgres=True)
            except Exception as e:
                # Si nous sommes en environnement hébergé/production ou si DATABASE_URL a été expressément configuré :
                # Pas de bascule silencieuse sur SQLite (/tmp est éphémère et entraîne des pertes de données).
                if is_production_environment() or self.database_url:
                    err_msg = (
                        f"[VitalTrack DB Error] Connexion PostgreSQL Neon impossible en environnement de production: {e}. "
                        "Fallback SQLite interdit pour prévenir toute perte de données orphelines dans /tmp."
                    )
                    print(err_msg)
                    raise DatabaseServiceUnavailableError(err_msg) from e

                # Hors production (développement local ou sans DATABASE_URL), fallback sur SQLite local
                print(f"[VitalTrack DB Warning] Échec connexion PostgreSQL Neon: {e}. Bascule sur SQLite local.")
                self.is_postgres = False

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass
        return DatabaseConnectionWrapper(conn, is_postgres=False)

    def run_migrations(self):
        """Exécute les migrations de schéma Alembic de façon unique et idempotente."""
        global _INIT_MIGRATIONS_DONE
        if _INIT_MIGRATIONS_DONE and self.is_postgres:
            return

        try:
            from alembic.config import Config
            from alembic import command

            ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
            if ini_path.exists():
                cfg = Config(str(ini_path))
                if self.is_postgres:
                    sa_url = self.database_url
                    if sa_url.startswith("postgres://"):
                        sa_url = sa_url.replace("postgres://", "postgresql+psycopg://", 1)
                    elif sa_url.startswith("postgresql://") and not sa_url.startswith("postgresql+"):
                        sa_url = sa_url.replace("postgresql://", "postgresql+psycopg://", 1)
                    cfg.set_main_option("sqlalchemy.url", sa_url)
                else:
                    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{self.db_path}")

                command.upgrade(cfg, "head")
                _INIT_MIGRATIONS_DONE = True
            else:
                self._init_db_fallback()
        except Exception as e:
            print(f"[VitalTrack DB Warning] Alembic migration warning: {e}. Application du fallback.")
            self._init_db_fallback()

        # Garantir l'existence de l'utilisateur par défaut et le référentiel des bienfaits
        try:
            self._ensure_default_user()
            self._seed_nutrition_benefits()
            self.purge_demo_data()
        except Exception as e:
            print(f"[VitalTrack DB Warning] Initialisation post-migration: {e}")

    def _init_db(self):
        """Alias pour rétrocompatibilité : exécute run_migrations."""
        self.run_migrations()

    def _init_db_fallback(self):
        """Initialisation de secours si Alembic n'est pas disponible."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            if self.is_postgres:
                # Schéma PostgreSQL (Neon)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        uuid TEXT UNIQUE NOT NULL,
                        email TEXT UNIQUE NOT NULL,
                        password_hash TEXT,
                        auth_provider TEXT NOT NULL DEFAULT 'google',
                        google_sub TEXT UNIQUE,
                        name TEXT,
                        picture TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_profile (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        name TEXT NOT NULL DEFAULT 'Sébastien',
                        gender TEXT NOT NULL DEFAULT 'male',
                        age INTEGER NOT NULL DEFAULT 35,
                        height_cm REAL NOT NULL DEFAULT 178.0,
                        target_weight_kg REAL NOT NULL DEFAULT 77.0,
                        goal_profile_id TEXT NOT NULL DEFAULT 'weight_loss',
                        target_steps INTEGER NOT NULL DEFAULT 10000,
                        target_calories_intake REAL NOT NULL DEFAULT 2000.0,
                        protein_target_per_kg REAL NOT NULL DEFAULT 1.8,
                        daily_protein_target_g REAL,
                        daily_carbs_target_g REAL,
                        daily_fat_target_g REAL,
                        daily_water_target_ml REAL DEFAULT 2000.0,
                        goal_type TEXT DEFAULT 'weight_loss',
                        activity_level TEXT DEFAULT 'moderately_active',
                        birth_date TEXT,
                        current_weight_kg REAL,
                        meal_distribution TEXT,
                        preferred_ring TEXT DEFAULT 'ringconn',
                        preferred_scale TEXT DEFAULT 'withings',
                        google_email TEXT,
                        google_name TEXT,
                        google_picture TEXT,
                        google_sub TEXT,
                        is_demo_profile INTEGER DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        CONSTRAINT uq_user_profile_user UNIQUE (user_id)
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS weights (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        date TEXT NOT NULL,
                        weight_kg REAL NOT NULL,
                        body_fat_pct REAL,
                        muscle_mass_kg REAL,
                        water_pct REAL,
                        bmi REAL,
                        trend_7d_kg REAL,
                        source TEXT NOT NULL,
                        notes TEXT,
                        created_at TEXT NOT NULL,
                        CONSTRAINT uq_weights_user_date UNIQUE (user_id, date)
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS activities (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        date TEXT NOT NULL,
                        steps INTEGER NOT NULL,
                        active_calories_kcal REAL NOT NULL,
                        bmr_kcal REAL NOT NULL,
                        total_burned_kcal REAL NOT NULL,
                        workout_minutes INTEGER NOT NULL,
                        workout_type TEXT,
                        resting_hr_bpm INTEGER,
                        hrv_ms REAL,
                        sleep_score INTEGER,
                        source TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        CONSTRAINT uq_activities_user_date UNIQUE (user_id, date)
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS meals (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        date TEXT NOT NULL,
                        meal_type TEXT NOT NULL,
                        total_calories_kcal REAL NOT NULL,
                        protein_g REAL NOT NULL,
                        carbs_g REAL NOT NULL,
                        fat_g REAL NOT NULL,
                        fiber_g REAL,
                        photo_data_url TEXT,
                        items_json TEXT,
                        created_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS food_items (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        item_type TEXT NOT NULL DEFAULT 'food',
                        default_unit TEXT NOT NULL DEFAULT 'g',
                        default_quantity REAL NOT NULL DEFAULT 100.0,
                        calories_per_unit REAL NOT NULL,
                        protein_per_unit_g REAL NOT NULL DEFAULT 0.0,
                        carbs_per_unit_g REAL NOT NULL DEFAULT 0.0,
                        fat_per_unit_g REAL NOT NULL DEFAULT 0.0,
                        fiber_per_unit_g REAL DEFAULT 0.0,
                        photo_url TEXT,
                        recipe_items_json TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS meal_logs (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        date TEXT NOT NULL,
                        meal_type TEXT NOT NULL,
                        photo_url TEXT,
                        total_calories REAL NOT NULL DEFAULT 0.0,
                        total_protein_g REAL NOT NULL DEFAULT 0.0,
                        total_carbs_g REAL NOT NULL DEFAULT 0.0,
                        total_fat_g REAL NOT NULL DEFAULT 0.0,
                        total_fiber_g REAL DEFAULT 0.0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        CONSTRAINT uq_meal_logs_user_date_type UNIQUE (user_id, date, meal_type)
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS meal_log_items (
                        id SERIAL PRIMARY KEY,
                        meal_log_id INTEGER NOT NULL REFERENCES meal_logs(id) ON DELETE CASCADE,
                        food_item_id INTEGER REFERENCES food_items(id) ON DELETE SET NULL,
                        name TEXT NOT NULL,
                        quantity REAL NOT NULL,
                        unit TEXT NOT NULL DEFAULT 'g',
                        calories REAL NOT NULL DEFAULT 0.0,
                        protein_g REAL NOT NULL DEFAULT 0.0,
                        carbs_g REAL NOT NULL DEFAULT 0.0,
                        fat_g REAL NOT NULL DEFAULT 0.0,
                        fiber_g REAL DEFAULT 0.0,
                        created_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS saved_meals (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        meal_type TEXT NOT NULL DEFAULT 'lunch',
                        serving_size TEXT DEFAULT '1 portion',
                        quantity_grams REAL,
                        calories REAL NOT NULL,
                        protein_g REAL NOT NULL DEFAULT 0.0,
                        carbs_g REAL NOT NULL DEFAULT 0.0,
                        fat_g REAL NOT NULL DEFAULT 0.0,
                        fiber_g REAL DEFAULT 0.0,
                        ingredients TEXT,
                        items_json TEXT,
                        photo_url TEXT,
                        is_favorite INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_devices (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        device_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        device_type TEXT NOT NULL,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        connected INTEGER NOT NULL DEFAULT 0,
                        auth_type TEXT NOT NULL DEFAULT 'demo',
                        api_key TEXT,
                        encrypted_credentials TEXT,
                        account_email TEXT,
                        last_sync TEXT,
                        last_sync_at TEXT,
                        sync_status TEXT DEFAULT 'disconnected',
                        updated_at TEXT NOT NULL,
                        CONSTRAINT uq_user_devices_user_device UNIQUE (user_id, device_id)
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS google_auth_config (
                        id SERIAL PRIMARY KEY,
                        google_client_id TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS google_sessions (
                        id SERIAL PRIMARY KEY,
                        email TEXT NOT NULL UNIQUE,
                        name TEXT NOT NULL,
                        picture TEXT,
                        google_sub TEXT,
                        auth_method TEXT NOT NULL DEFAULT 'google',
                        is_active INTEGER NOT NULL DEFAULT 1,
                        last_login TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS nutrition_benefits (
                        id TEXT PRIMARY KEY,
                        category TEXT NOT NULL,
                        category_id INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        icon TEXT NOT NULL,
                        rule_config TEXT,
                        created_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS food_item_benefits (
                        food_item_id INTEGER NOT NULL REFERENCES food_items(id) ON DELETE CASCADE,
                        benefit_id TEXT NOT NULL REFERENCES nutrition_benefits(id) ON DELETE CASCADE,
                        source TEXT NOT NULL DEFAULT 'manual',
                        explanation TEXT,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (food_item_id, benefit_id)
                    );
                """)

                # Palier 3 : Nouvelles tables biométriques et d'ingestion enrichie (PostgreSQL)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS daily_metrics (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        date TEXT NOT NULL,
                        source TEXT NOT NULL,
                        steps INTEGER NOT NULL DEFAULT 0,
                        active_calories_kcal REAL NOT NULL DEFAULT 0.0,
                        total_calories_kcal REAL NOT NULL DEFAULT 0.0,
                        resting_hr_bpm INTEGER,
                        hrv_rmssd_ms REAL,
                        hrv_sdnn_ms REAL,
                        spo2_pct REAL,
                        skin_temperature_c REAL,
                        sleep_score INTEGER,
                        recovery_score INTEGER,
                        external_id TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        CONSTRAINT uq_daily_metrics_user_date_source UNIQUE (user_id, date, source)
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS workouts (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        source TEXT NOT NULL,
                        external_id TEXT,
                        workout_type TEXT NOT NULL,
                        start_time TEXT NOT NULL,
                        end_time TEXT NOT NULL,
                        duration_minutes INTEGER NOT NULL DEFAULT 0,
                        calories_kcal REAL NOT NULL DEFAULT 0.0,
                        avg_hr_bpm INTEGER,
                        max_hr_bpm INTEGER,
                        distance_meters REAL,
                        notes TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sleep_sessions (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        source TEXT NOT NULL,
                        external_id TEXT,
                        date TEXT NOT NULL,
                        start_time TEXT NOT NULL,
                        end_time TEXT NOT NULL,
                        duration_minutes INTEGER NOT NULL DEFAULT 0,
                        efficiency_pct REAL,
                        sleep_debt_minutes INTEGER,
                        sleep_score INTEGER,
                        deep_minutes INTEGER DEFAULT 0,
                        light_minutes INTEGER DEFAULT 0,
                        rem_minutes INTEGER DEFAULT 0,
                        awake_minutes INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sleep_stages (
                        id SERIAL PRIMARY KEY,
                        sleep_session_id INTEGER NOT NULL REFERENCES sleep_sessions(id) ON DELETE CASCADE,
                        stage TEXT NOT NULL,
                        start_time TEXT NOT NULL,
                        end_time TEXT NOT NULL,
                        duration_seconds INTEGER NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS intraday_samples (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        source TEXT NOT NULL,
                        metric_type TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        value REAL NOT NULL,
                        unit TEXT,
                        created_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS hydration_logs (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        date TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        volume_ml REAL NOT NULL,
                        source TEXT NOT NULL DEFAULT 'manual',
                        external_id TEXT,
                        created_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS raw_ingest (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        source TEXT NOT NULL,
                        endpoint TEXT,
                        idempotency_key TEXT,
                        payload_json TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'received',
                        received_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_consents (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        category TEXT NOT NULL,
                        consented INTEGER NOT NULL DEFAULT 1,
                        updated_at TEXT NOT NULL,
                        CONSTRAINT uq_user_consents_user_cat UNIQUE (user_id, category)
                    );
                """)

                # Migrations douces colonnes users pour PostgreSQL
                for col, def_val in [
                    ("uuid", "TEXT"),
                    ("password_hash", "TEXT"),
                    ("auth_provider", "TEXT NOT NULL DEFAULT 'google'"),
                    ("google_sub", "TEXT"),
                    ("name", "TEXT"),
                    ("picture", "TEXT"),
                ]:
                    try:
                        cursor.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {def_val};")
                    except Exception:
                        pass

                # Migrations douces colonnes weights et activities pour idempotence PostgreSQL
                for table, col, def_val in [
                    ("weights", "external_id", "TEXT"),
                    ("weights", "measured_at", "TEXT"),
                    ("weights", "idempotency_key", "TEXT"),
                    ("activities", "external_id", "TEXT"),
                    ("activities", "idempotency_key", "TEXT"),
                ]:
                    try:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {def_val};")
                    except Exception:
                        pass

                # Migrations douces colonnes user_profile pour PostgreSQL
                for col, def_val in [
                    ("user_id", "INTEGER"),
                    ("preferred_ring", "TEXT NOT NULL DEFAULT 'ringconn'"),
                    ("preferred_scale", "TEXT NOT NULL DEFAULT 'withings'"),
                    ("google_email", "TEXT"),
                    ("google_name", "TEXT"),
                    ("google_picture", "TEXT"),
                    ("google_sub", "TEXT"),
                    ("daily_protein_target_g", "REAL"),
                    ("daily_carbs_target_g", "REAL"),
                    ("daily_fat_target_g", "REAL"),
                    ("daily_water_target_ml", "REAL DEFAULT 2000.0"),
                    ("goal_type", "TEXT DEFAULT 'weight_loss'"),
                    ("activity_level", "TEXT DEFAULT 'moderately_active'"),
                    ("birth_date", "TEXT"),
                    ("current_weight_kg", "REAL"),
                    ("meal_distribution", "TEXT"),
                    ("is_demo_profile", "INTEGER DEFAULT 0"),
                ]:
                    try:
                        cursor.execute(f"ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS {col} {def_val};")
                    except Exception:
                        pass

                # Migrations douces colonnes user_devices pour PostgreSQL
                for col, def_val in [
                    ("is_active", "INTEGER NOT NULL DEFAULT 1"),
                    ("encrypted_credentials", "TEXT"),
                    ("last_sync_at", "TEXT"),
                    ("sync_status", "TEXT DEFAULT 'disconnected'")
                ]:
                    try:
                        cursor.execute(f"ALTER TABLE user_devices ADD COLUMN IF NOT EXISTS {col} {def_val};")
                    except Exception:
                        pass

                try:
                    cursor.execute("ALTER TABLE food_items ADD COLUMN IF NOT EXISTS recipe_items_json TEXT;")
                except Exception:
                    pass

                # Index optimisés PostgreSQL
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_weights_user_date ON weights(user_id, date DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_activities_user_date ON activities(user_id, date DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_weights_source_external ON weights(source, external_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_activities_source_external ON activities(source, external_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_meals_user_date ON meals(user_id, date DESC, id DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_saved_meals_user_type ON saved_meals(user_id, meal_type);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_items_user ON food_items(user_id, item_type);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_meal_logs_user_date ON meal_logs(user_id, date);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_meal_log_items_meal ON meal_log_items(meal_log_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_metrics_user_date ON daily_metrics(user_id, date DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_metrics_source_ext ON daily_metrics(source, external_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_workouts_user_time ON workouts(user_id, start_time DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_workouts_source_ext ON workouts(source, external_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sleep_sessions_user_date ON sleep_sessions(user_id, date DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sleep_sessions_source_ext ON sleep_sessions(source, external_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sleep_stages_session ON sleep_stages(sleep_session_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_intraday_samples_user_metric_time ON intraday_samples(user_id, metric_type, timestamp DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_hydration_logs_user_date ON hydration_logs(user_id, date DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_ingest_user_time ON raw_ingest(user_id, received_at DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_ingest_idempotency ON raw_ingest(source, idempotency_key);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_consents_user ON user_consents(user_id);")

            else:
                # Schéma SQLite avec support des contraintes et migrations
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        uuid TEXT UNIQUE NOT NULL,
                        email TEXT UNIQUE NOT NULL,
                        password_hash TEXT,
                        auth_provider TEXT NOT NULL DEFAULT 'google',
                        google_sub TEXT UNIQUE,
                        name TEXT,
                        picture TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_profile (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                        name TEXT NOT NULL DEFAULT 'Sébastien',
                        gender TEXT NOT NULL DEFAULT 'male',
                        age INTEGER NOT NULL DEFAULT 35,
                        height_cm REAL NOT NULL DEFAULT 178.0,
                        target_weight_kg REAL NOT NULL DEFAULT 77.0,
                        goal_profile_id TEXT NOT NULL DEFAULT 'weight_loss',
                        target_steps INTEGER NOT NULL DEFAULT 10000,
                        target_calories_intake REAL NOT NULL DEFAULT 2000.0,
                        protein_target_per_kg REAL NOT NULL DEFAULT 1.8,
                        daily_protein_target_g REAL,
                        daily_carbs_target_g REAL,
                        daily_fat_target_g REAL,
                        daily_water_target_ml REAL DEFAULT 2000.0,
                        goal_type TEXT DEFAULT 'weight_loss',
                        activity_level TEXT DEFAULT 'moderately_active',
                        birth_date TEXT,
                        current_weight_kg REAL,
                        meal_distribution TEXT,
                        preferred_ring TEXT DEFAULT 'ringconn',
                        preferred_scale TEXT DEFAULT 'withings',
                        google_email TEXT,
                        google_name TEXT,
                        google_picture TEXT,
                        google_sub TEXT,
                        is_demo_profile INTEGER DEFAULT 0,
                        updated_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS weights (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER DEFAULT 1 REFERENCES users(id) ON DELETE CASCADE,
                        date TEXT NOT NULL,
                        weight_kg REAL NOT NULL,
                        body_fat_pct REAL,
                        muscle_mass_kg REAL,
                        water_pct REAL,
                        bmi REAL,
                        trend_7d_kg REAL,
                        source TEXT NOT NULL,
                        notes TEXT,
                        created_at TEXT NOT NULL,
                        UNIQUE(user_id, date)
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS activities (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER DEFAULT 1 REFERENCES users(id) ON DELETE CASCADE,
                        date TEXT NOT NULL,
                        steps INTEGER NOT NULL,
                        active_calories_kcal REAL NOT NULL,
                        bmr_kcal REAL NOT NULL,
                        total_burned_kcal REAL NOT NULL,
                        workout_minutes INTEGER NOT NULL,
                        workout_type TEXT,
                        resting_hr_bpm INTEGER,
                        hrv_ms REAL,
                        sleep_score INTEGER,
                        source TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(user_id, date)
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS meals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER DEFAULT 1 REFERENCES users(id) ON DELETE CASCADE,
                        date TEXT NOT NULL,
                        meal_type TEXT NOT NULL,
                        total_calories_kcal REAL NOT NULL,
                        protein_g REAL NOT NULL,
                        carbs_g REAL NOT NULL,
                        fat_g REAL NOT NULL,
                        fiber_g REAL,
                        photo_data_url TEXT,
                        items_json TEXT,
                        created_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS food_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER DEFAULT 1 REFERENCES users(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        item_type TEXT NOT NULL DEFAULT 'food',
                        default_unit TEXT NOT NULL DEFAULT 'g',
                        default_quantity REAL NOT NULL DEFAULT 100.0,
                        calories_per_unit REAL NOT NULL,
                        protein_per_unit_g REAL NOT NULL DEFAULT 0.0,
                        carbs_per_unit_g REAL NOT NULL DEFAULT 0.0,
                        fat_per_unit_g REAL NOT NULL DEFAULT 0.0,
                        fiber_per_unit_g REAL DEFAULT 0.0,
                        photo_url TEXT,
                        recipe_items_json TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS meal_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER DEFAULT 1 REFERENCES users(id) ON DELETE CASCADE,
                        date TEXT NOT NULL,
                        meal_type TEXT NOT NULL,
                        photo_url TEXT,
                        total_calories REAL NOT NULL DEFAULT 0.0,
                        total_protein_g REAL NOT NULL DEFAULT 0.0,
                        total_carbs_g REAL NOT NULL DEFAULT 0.0,
                        total_fat_g REAL NOT NULL DEFAULT 0.0,
                        total_fiber_g REAL DEFAULT 0.0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(user_id, date, meal_type)
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS meal_log_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        meal_log_id INTEGER NOT NULL REFERENCES meal_logs(id) ON DELETE CASCADE,
                        food_item_id INTEGER REFERENCES food_items(id) ON DELETE SET NULL,
                        name TEXT NOT NULL,
                        quantity REAL NOT NULL,
                        unit TEXT NOT NULL DEFAULT 'g',
                        calories REAL NOT NULL DEFAULT 0.0,
                        protein_g REAL NOT NULL DEFAULT 0.0,
                        carbs_g REAL NOT NULL DEFAULT 0.0,
                        fat_g REAL NOT NULL DEFAULT 0.0,
                        fiber_g REAL DEFAULT 0.0,
                        created_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS saved_meals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER DEFAULT 1 REFERENCES users(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        meal_type TEXT NOT NULL DEFAULT 'lunch',
                        serving_size TEXT DEFAULT '1 portion',
                        quantity_grams REAL,
                        calories REAL NOT NULL,
                        protein_g REAL NOT NULL DEFAULT 0.0,
                        carbs_g REAL NOT NULL DEFAULT 0.0,
                        fat_g REAL NOT NULL DEFAULT 0.0,
                        fiber_g REAL DEFAULT 0.0,
                        ingredients TEXT,
                        items_json TEXT,
                        photo_url TEXT,
                        is_favorite INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_devices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER DEFAULT 1 REFERENCES users(id) ON DELETE CASCADE,
                        device_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        device_type TEXT NOT NULL,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        connected INTEGER NOT NULL DEFAULT 0,
                        auth_type TEXT NOT NULL DEFAULT 'demo',
                        api_key TEXT,
                        encrypted_credentials TEXT,
                        account_email TEXT,
                        last_sync TEXT,
                        last_sync_at TEXT,
                        sync_status TEXT DEFAULT 'disconnected',
                        updated_at TEXT NOT NULL,
                        UNIQUE(user_id, device_id)
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS google_auth_config (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        google_client_id TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS google_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email TEXT NOT NULL UNIQUE,
                        name TEXT NOT NULL,
                        picture TEXT,
                        google_sub TEXT,
                        auth_method TEXT NOT NULL DEFAULT 'google',
                        is_active INTEGER NOT NULL DEFAULT 1,
                        last_login TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS nutrition_benefits (
                        id TEXT PRIMARY KEY,
                        category TEXT NOT NULL,
                        category_id INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        icon TEXT NOT NULL,
                        rule_config TEXT,
                        created_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS food_item_benefits (
                        food_item_id INTEGER NOT NULL REFERENCES food_items(id) ON DELETE CASCADE,
                        benefit_id TEXT NOT NULL REFERENCES nutrition_benefits(id) ON DELETE CASCADE,
                        source TEXT NOT NULL DEFAULT 'manual',
                        explanation TEXT,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (food_item_id, benefit_id)
                    );
                """)

                # Palier 3 : Nouvelles tables biométriques et d'ingestion enrichie (SQLite)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS daily_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        date TEXT NOT NULL,
                        source TEXT NOT NULL,
                        steps INTEGER NOT NULL DEFAULT 0,
                        active_calories_kcal REAL NOT NULL DEFAULT 0.0,
                        total_calories_kcal REAL NOT NULL DEFAULT 0.0,
                        resting_hr_bpm INTEGER,
                        hrv_rmssd_ms REAL,
                        hrv_sdnn_ms REAL,
                        spo2_pct REAL,
                        skin_temperature_c REAL,
                        sleep_score INTEGER,
                        recovery_score INTEGER,
                        external_id TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE (user_id, date, source)
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS workouts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        source TEXT NOT NULL,
                        external_id TEXT,
                        workout_type TEXT NOT NULL,
                        start_time TEXT NOT NULL,
                        end_time TEXT NOT NULL,
                        duration_minutes INTEGER NOT NULL DEFAULT 0,
                        calories_kcal REAL NOT NULL DEFAULT 0.0,
                        avg_hr_bpm INTEGER,
                        max_hr_bpm INTEGER,
                        distance_meters REAL,
                        notes TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sleep_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        source TEXT NOT NULL,
                        external_id TEXT,
                        date TEXT NOT NULL,
                        start_time TEXT NOT NULL,
                        end_time TEXT NOT NULL,
                        duration_minutes INTEGER NOT NULL DEFAULT 0,
                        efficiency_pct REAL,
                        sleep_debt_minutes INTEGER,
                        sleep_score INTEGER,
                        deep_minutes INTEGER DEFAULT 0,
                        light_minutes INTEGER DEFAULT 0,
                        rem_minutes INTEGER DEFAULT 0,
                        awake_minutes INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sleep_stages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sleep_session_id INTEGER NOT NULL REFERENCES sleep_sessions(id) ON DELETE CASCADE,
                        stage TEXT NOT NULL,
                        start_time TEXT NOT NULL,
                        end_time TEXT NOT NULL,
                        duration_seconds INTEGER NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS intraday_samples (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        source TEXT NOT NULL,
                        metric_type TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        value REAL NOT NULL,
                        unit TEXT,
                        created_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS hydration_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        date TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        volume_ml REAL NOT NULL,
                        source TEXT NOT NULL DEFAULT 'manual',
                        external_id TEXT,
                        created_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS raw_ingest (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        source TEXT NOT NULL,
                        endpoint TEXT,
                        idempotency_key TEXT,
                        payload_json TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'received',
                        received_at TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_consents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        category TEXT NOT NULL,
                        consented INTEGER NOT NULL DEFAULT 1,
                        updated_at TEXT NOT NULL,
                        UNIQUE (user_id, category)
                    );
                """)

                # Migrations douces colonnes weights et activities pour idempotence SQLite
                for table, col, def_val in [
                    ("weights", "external_id", "TEXT"),
                    ("weights", "measured_at", "TEXT"),
                    ("weights", "idempotency_key", "TEXT"),
                    ("activities", "external_id", "TEXT"),
                    ("activities", "idempotency_key", "TEXT"),
                ]:
                    try:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {def_val}")
                    except Exception:
                        pass

                # Migrations douces pour ajouter user_id si les tables SQLite existaient déjà sans user_id
                for table in ["weights", "activities", "meals", "user_devices", "user_profile", "saved_meals"]:
                    try:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER DEFAULT 1")
                    except Exception:
                        pass

                # Migrations douces colonnes user_profile pour SQLite
                for col, def_val in [
                    ("daily_protein_target_g", "REAL"),
                    ("daily_carbs_target_g", "REAL"),
                    ("daily_fat_target_g", "REAL"),
                    ("daily_water_target_ml", "REAL DEFAULT 2000.0"),
                    ("goal_type", "TEXT DEFAULT 'weight_loss'"),
                    ("activity_level", "TEXT DEFAULT 'moderately_active'"),
                    ("birth_date", "TEXT"),
                    ("current_weight_kg", "REAL"),
                    ("meal_distribution", "TEXT"),
                    ("is_demo_profile", "INTEGER DEFAULT 0"),
                ]:
                    try:
                        cursor.execute(f"ALTER TABLE user_profile ADD COLUMN {col} {def_val}")
                    except Exception:
                        pass

                # Migrations douces colonnes user_devices
                for col, def_val in [
                    ("is_active", "INTEGER DEFAULT 1"),
                    ("encrypted_credentials", "TEXT"),
                    ("last_sync_at", "TEXT"),
                    ("sync_status", "TEXT DEFAULT 'disconnected'")
                ]:
                    try:
                        cursor.execute(f"ALTER TABLE user_devices ADD COLUMN {col} {def_val}")
                    except Exception:
                        pass

                try:
                    cursor.execute("ALTER TABLE food_items ADD COLUMN recipe_items_json TEXT")
                except Exception:
                    pass

                # Index uniques pour SQLite garantissant ON CONFLICT(user_id, date)
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_weights_user_date ON weights(user_id, date);")
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_activities_user_date ON activities(user_id, date);")
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_user_devices_user_dev ON user_devices(user_id, device_id);")

                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_meal_logs_user_date_type ON meal_logs(user_id, date, meal_type);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_items_user ON food_items(user_id, item_type);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_meal_logs_user_date ON meal_logs(user_id, date);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_meal_log_items_meal ON meal_log_items(meal_log_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_item_benefits_food ON food_item_benefits(food_item_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_nutrition_benefits_cat ON nutrition_benefits(category_id);")

                # Index SQLite
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_weights_user_date ON weights(user_id, date DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_activities_user_date ON activities(user_id, date DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_weights_source_external ON weights(source, external_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_activities_source_external ON activities(source, external_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_meals_user_date ON meals(user_id, date DESC, id DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_saved_meals_user_type ON saved_meals(user_id, meal_type);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_metrics_user_date ON daily_metrics(user_id, date DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_metrics_source_ext ON daily_metrics(source, external_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_workouts_user_time ON workouts(user_id, start_time DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_workouts_source_ext ON workouts(source, external_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sleep_sessions_user_date ON sleep_sessions(user_id, date DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sleep_sessions_source_ext ON sleep_sessions(source, external_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sleep_stages_session ON sleep_stages(sleep_session_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_intraday_samples_user_metric_time ON intraday_samples(user_id, metric_type, timestamp DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_hydration_logs_user_date ON hydration_logs(user_id, date DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_ingest_user_time ON raw_ingest(user_id, received_at DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_ingest_idempotency ON raw_ingest(source, idempotency_key);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_consents_user ON user_consents(user_id);")

            conn.commit()

        # Garantir l'existence de l'utilisateur par défaut
        self._ensure_default_user()
        # Seeder le référentiel expert des bienfaits nutritionnels
        self._seed_nutrition_benefits()
        # Purger toute donnée de démonstration résiduelle
        self.purge_demo_data()

    # ---------------------------------------------------------
    # Gestion des Utilisateurs (Multi-utilisateurs & Auth)
    # ---------------------------------------------------------

    def _ensure_default_user(self) -> Dict[str, Any]:
        """Crée ou retourne le compte principal par défaut (Sébastien LAMOLIATE)."""
        now_str = datetime.now(timezone.utc).isoformat()
        default_email = "sebastienlamoliate@gmail.com"
        default_name = "Sébastien LAMOLIATE"
        default_uuid = "00000000-0000-4000-8000-000000000001"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ? OR id = 1", (default_email,))
            row = cursor.fetchone()
            if not row:
                if self.is_postgres:
                    cursor.execute("""
                        INSERT INTO users (id, uuid, email, auth_provider, google_sub, name, picture, created_at, updated_at)
                        VALUES (1, ?, ?, 'google', 'default_google_sub', ?, 'https://lh3.googleusercontent.com/a/default-user=s96-c', ?, ?)
                        ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email
                        RETURNING *;
                    """, (default_uuid, default_email, default_name, now_str, now_str))
                    row = cursor.fetchone()
                else:
                    cursor.execute("""
                        INSERT INTO users (id, uuid, email, auth_provider, google_sub, name, picture, created_at, updated_at)
                        VALUES (1, ?, ?, 'google', 'default_google_sub', ?, 'https://lh3.googleusercontent.com/a/default-user=s96-c', ?, ?)
                    """, (default_uuid, default_email, default_name, now_str, now_str))
                    conn.commit()
                    cursor.execute("SELECT * FROM users WHERE id = 1")
                    row = cursor.fetchone()
            return dict(row)

    def get_or_create_user(
        self,
        email: str,
        name: Optional[str] = None,
        picture: Optional[str] = None,
        auth_provider: str = "google",
        google_sub: Optional[str] = None,
        password_hash: Optional[str] = None
    ) -> Dict[str, Any]:
        """Récupère un utilisateur par email ou le crée s'il n'existe pas."""
        now_str = datetime.now(timezone.utc).isoformat()
        email_clean = email.strip().lower()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email_clean,))
            user = cursor.fetchone()

            if user:
                # Mise à jour éventuelle des infos profil
                if (name and name != user.get("name")) or (picture and picture != user.get("picture")) or (google_sub and not user.get("google_sub")):
                    cursor.execute("""
                        UPDATE users
                        SET name = COALESCE(?, name), picture = COALESCE(?, picture),
                            google_sub = COALESCE(?, google_sub), updated_at = ?
                        WHERE id = ?
                    """, (name, picture, google_sub, now_str, user["id"]))
                    conn.commit()
                    cursor.execute("SELECT * FROM users WHERE id = ?", (user["id"],))
                    user = cursor.fetchone()
                return dict(user)

            # Création nouvel utilisateur
            new_uuid = str(uuid.uuid4())
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO users (uuid, email, password_hash, auth_provider, google_sub, name, picture, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING *;
                """, (new_uuid, email_clean, password_hash, auth_provider, google_sub, name or email_clean.split("@")[0], picture or "", now_str, now_str))
                created = cursor.fetchone()
            else:
                cursor.execute("""
                    INSERT INTO users (uuid, email, password_hash, auth_provider, google_sub, name, picture, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (new_uuid, email_clean, password_hash, auth_provider, google_sub, name or email_clean.split("@")[0], picture or "", now_str, now_str))
                conn.commit()
                cursor.execute("SELECT * FROM users WHERE email = ?", (email_clean,))
                created = cursor.fetchone()

            user_dict = dict(created)

            # Créer automatiquement son profil par défaut
            cursor.execute("""
                INSERT INTO user_profile (user_id, name, gender, age, height_cm, target_weight_kg, goal_profile_id, target_steps, target_calories_intake, protein_target_per_kg, daily_protein_target_g, daily_carbs_target_g, daily_fat_target_g, daily_water_target_ml, goal_type, activity_level, preferred_ring, preferred_scale, is_demo_profile, google_email, google_name, google_picture, google_sub, updated_at)
                VALUES (?, ?, 'male', 35, 178.0, 77.0, 'weight_loss', 10000, 2000.0, 1.8, 140.0, 220.0, 65.0, 2000.0, 'weight_loss', 'moderately_active', 'ringconn', 'withings', 0, ?, ?, ?, ?, ?)
            """, (user_dict["id"], user_dict["name"] or "Utilisateur", user_dict["email"], user_dict["name"], user_dict["picture"], google_sub, now_str))
            conn.commit()

        return user_dict

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Récupère un compte utilisateur par son identifiant numérique."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Récupère un compte utilisateur par son adresse email (insensible à la casse)."""
        clean_email = email.strip().lower()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE LOWER(email) = ?", (clean_email,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_users(self) -> List[Dict[str, Any]]:
        """Récupère la liste de tous les utilisateurs enregistrés."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users ORDER BY id ASC")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    # ---------------------------------------------------------
    # Tendance et Pesées Multi-Utilisateurs
    # ---------------------------------------------------------

    def calculate_7d_trend(self, target_date: date, new_weight_kg: float, user_id: int = 1, exclude_simulation: bool = True) -> float:
        """Calcule la moyenne mobile sur 7 jours incluant la pesée actuelle pour l'utilisateur."""
        start_date = (target_date - timedelta(days=6)).isoformat()
        end_date = target_date.isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if exclude_simulation:
                cursor.execute("""
                    SELECT weight_kg FROM weights
                    WHERE user_id = ? AND date >= ? AND date < ? AND source NOT IN ('simulation')
                    ORDER BY date ASC
                """, (user_id, start_date, end_date))
            else:
                cursor.execute("""
                    SELECT weight_kg FROM weights
                    WHERE user_id = ? AND date >= ? AND date < ?
                    ORDER BY date ASC
                """, (user_id, start_date, end_date))
            rows = cursor.fetchall()

        previous_weights = [r["weight_kg"] for r in rows]
        all_weights = previous_weights + [new_weight_kg]
        return round(sum(all_weights) / len(all_weights), 2)

    def insert_weight(self, entry: WeightEntry, user_id: int = 1) -> WeightEntry:
        """Insère ou met à jour une pesée en recalculant la tendance 7j pour user_id (avec support d'idempotence)."""
        # Vérification d'idempotence si external_id est fourni
        if entry.external_id:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM weights WHERE user_id = ? AND source = ? AND external_id = ? LIMIT 1",
                    (user_id, entry.source, entry.external_id)
                )
                existing = cursor.fetchone()
                if existing:
                    return WeightEntry(
                        id=existing["id"],
                        date=date.fromisoformat(existing["date"][:10]),
                        weight_kg=existing["weight_kg"],
                        body_fat_pct=existing["body_fat_pct"],
                        muscle_mass_kg=existing["muscle_mass_kg"],
                        water_pct=existing["water_pct"],
                        bmi=existing["bmi"],
                        trend_7d_kg=existing["trend_7d_kg"],
                        source=existing["source"],
                        is_simulated=(existing["source"] in ("simulation", "demo")),
                        notes=existing["notes"],
                        external_id=existing.get("external_id"),
                        measured_at=existing.get("measured_at"),
                        idempotency_key=existing.get("idempotency_key"),
                        created_at=datetime.fromisoformat(existing["created_at"]) if existing["created_at"] else None
                    )

        trend = entry.trend_7d_kg
        if trend is None:
            trend = self.calculate_7d_trend(entry.date, entry.weight_kg, user_id=user_id)

        now_str = datetime.now(timezone.utc).isoformat()
        date_str = entry.date.isoformat()
        measured_at_str = entry.measured_at or now_str
        idemp_key = entry.idempotency_key or (f"{entry.source}:{entry.external_id}" if entry.external_id else None)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO weights (
                        user_id, date, weight_kg, body_fat_pct, muscle_mass_kg, water_pct,
                        bmi, trend_7d_kg, source, notes, external_id, measured_at, idempotency_key, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date) DO UPDATE SET
                        weight_kg = EXCLUDED.weight_kg,
                        body_fat_pct = EXCLUDED.body_fat_pct,
                        muscle_mass_kg = EXCLUDED.muscle_mass_kg,
                        water_pct = EXCLUDED.water_pct,
                        bmi = EXCLUDED.bmi,
                        trend_7d_kg = EXCLUDED.trend_7d_kg,
                        source = EXCLUDED.source,
                        notes = EXCLUDED.notes,
                        external_id = COALESCE(EXCLUDED.external_id, weights.external_id),
                        measured_at = COALESCE(EXCLUDED.measured_at, weights.measured_at),
                        idempotency_key = COALESCE(EXCLUDED.idempotency_key, weights.idempotency_key)
                    RETURNING id;
                """, (
                    user_id, date_str, entry.weight_kg, entry.body_fat_pct,
                    entry.muscle_mass_kg, entry.water_pct, entry.bmi, trend,
                    entry.source, entry.notes, entry.external_id, measured_at_str, idemp_key, now_str
                ))
                res = cursor.fetchone()
                entry_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO weights (
                        user_id, date, weight_kg, body_fat_pct, muscle_mass_kg, water_pct,
                        bmi, trend_7d_kg, source, notes, external_id, measured_at, idempotency_key, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date) DO UPDATE SET
                        weight_kg = excluded.weight_kg,
                        body_fat_pct = excluded.body_fat_pct,
                        muscle_mass_kg = excluded.muscle_mass_kg,
                        water_pct = excluded.water_pct,
                        bmi = excluded.bmi,
                        trend_7d_kg = excluded.trend_7d_kg,
                        source = excluded.source,
                        notes = excluded.notes,
                        external_id = COALESCE(excluded.external_id, weights.external_id),
                        measured_at = COALESCE(excluded.measured_at, weights.measured_at),
                        idempotency_key = COALESCE(excluded.idempotency_key, weights.idempotency_key)
                """, (
                    user_id, date_str, entry.weight_kg, entry.body_fat_pct,
                    entry.muscle_mass_kg, entry.water_pct, entry.bmi, trend,
                    entry.source, entry.notes, entry.external_id, measured_at_str, idemp_key, now_str
                ))
                entry_id = cursor.lastrowid
            conn.commit()

        entry_dict = entry.model_dump()
        entry_dict["id"] = entry_id
        entry_dict["trend_7d_kg"] = trend
        entry_dict["measured_at"] = measured_at_str
        entry_dict["idempotency_key"] = idemp_key
        entry_dict["created_at"] = datetime.fromisoformat(now_str)
        return WeightEntry(**entry_dict)

    def get_weights(self, limit: int = 30, user_id: int = 1, exclude_simulation: bool = False) -> List[WeightEntry]:
        """Récupère l'historique des pesées ordonné par date croissante pour un utilisateur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if exclude_simulation:
                cursor.execute("""
                    SELECT * FROM (
                        SELECT * FROM weights WHERE user_id = ? AND source NOT IN ('simulation') ORDER BY date DESC LIMIT ?
                    ) sub ORDER BY date ASC
                """, (user_id, limit))
            else:
                cursor.execute("""
                    SELECT * FROM (
                        SELECT * FROM weights WHERE user_id = ? ORDER BY date DESC LIMIT ?
                    ) sub ORDER BY date ASC
                """, (user_id, limit))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            results.append(WeightEntry(
                id=r["id"],
                date=date.fromisoformat(r["date"][:10]),
                weight_kg=r["weight_kg"],
                body_fat_pct=r["body_fat_pct"],
                muscle_mass_kg=r["muscle_mass_kg"],
                water_pct=r["water_pct"],
                bmi=r["bmi"],
                trend_7d_kg=r["trend_7d_kg"],
                source=r["source"],
                is_simulated=(r["source"] in ("simulation", "demo") or "Démo" in (r.get("notes") or "")),
                notes=r["notes"],
                external_id=r.get("external_id"),
                measured_at=r.get("measured_at"),
                idempotency_key=r.get("idempotency_key"),
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
            ))
        return results

    # ---------------------------------------------------------
    
    def get_weight_by_id(self, weight_id: int, user_id: int = 1) -> Optional[WeightEntry]:
        """Récupère une pesée spécifique par son ID pour user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM weights WHERE id = ? AND user_id = ?", (weight_id, user_id))
            r = cursor.fetchone()
        if not r:
            return None
        return WeightEntry(
            id=r["id"],
            date=date.fromisoformat(r["date"][:10]),
            weight_kg=r["weight_kg"],
            body_fat_pct=r["body_fat_pct"],
            muscle_mass_kg=r["muscle_mass_kg"],
            water_pct=r["water_pct"],
            bmi=r["bmi"],
            trend_7d_kg=r["trend_7d_kg"],
            source=r["source"],
            is_simulated=(r["source"] in ("simulation", "demo") or "Démo" in (r.get("notes") or "")),
            notes=r["notes"],
            external_id=r.get("external_id"),
            measured_at=r.get("measured_at"),
            idempotency_key=r.get("idempotency_key"),
            created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
        )

    def update_weight(self, weight_id: int, entry: WeightEntry, user_id: int = 1) -> Optional[WeightEntry]:
        """Met à jour une pesée existante et recalcule la tendance 7j."""
        existing = self.get_weight_by_id(weight_id, user_id=user_id)
        if not existing:
            return None

        target_date = entry.date
        trend = entry.trend_7d_kg
        if trend is None:
            trend = self.calculate_7d_trend(target_date, entry.weight_kg, user_id=user_id)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE weights
                SET date = ?, weight_kg = ?, body_fat_pct = ?, muscle_mass_kg = ?,
                    water_pct = ?, bmi = ?, trend_7d_kg = ?, source = ?, notes = ?
                WHERE id = ? AND user_id = ?
            """, (
                target_date.isoformat(), entry.weight_kg, entry.body_fat_pct,
                entry.muscle_mass_kg, entry.water_pct, entry.bmi, trend,
                entry.source, entry.notes, weight_id, user_id
            ))
            conn.commit()

        entry_dict = entry.model_dump()
        entry_dict["id"] = weight_id
        entry_dict["trend_7d_kg"] = trend
        entry_dict["created_at"] = existing.created_at
        return WeightEntry(**entry_dict)

    def delete_weight(self, weight_id: int, user_id: int = 1) -> bool:
        """Supprime une pesée pour user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM weights WHERE id = ? AND user_id = ?", (weight_id, user_id))
            if not cursor.fetchone():
                return False
            cursor.execute("DELETE FROM weights WHERE id = ? AND user_id = ?", (weight_id, user_id))
            conn.commit()
            return True

    # Activités Multi-Utilisateurs
    # ---------------------------------------------------------

    def insert_activity(self, entry: ActivityEntry, user_id: int = 1) -> ActivityEntry:
        """Insère ou met à jour une entrée d'activité pour user_id (avec support d'idempotence)."""
        # Vérification d'idempotence si external_id est fourni
        if entry.external_id:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM activities WHERE user_id = ? AND source = ? AND external_id = ? LIMIT 1",
                    (user_id, entry.source, entry.external_id)
                )
                existing = cursor.fetchone()
                if existing:
                    return ActivityEntry(
                        id=existing["id"],
                        date=date.fromisoformat(existing["date"][:10]),
                        steps=existing["steps"],
                        active_calories_kcal=existing["active_calories_kcal"],
                        bmr_kcal=existing["bmr_kcal"],
                        total_burned_kcal=existing["total_burned_kcal"],
                        workout_minutes=existing["workout_minutes"],
                        workout_type=existing["workout_type"],
                        resting_hr_bpm=existing["resting_hr_bpm"],
                        hrv_ms=existing["hrv_ms"],
                        sleep_score=existing["sleep_score"],
                        source=existing["source"],
                        is_simulated=(existing["source"] in ("simulation", "demo")),
                        external_id=existing.get("external_id"),
                        idempotency_key=existing.get("idempotency_key"),
                        created_at=datetime.fromisoformat(existing["created_at"]) if existing["created_at"] else None
                    )

        now_str = datetime.now(timezone.utc).isoformat()
        date_str = entry.date.isoformat()
        idemp_key = entry.idempotency_key or (f"{entry.source}:{entry.external_id}" if entry.external_id else None)

        total_burned = entry.total_burned_kcal
        if total_burned <= 0 and (entry.bmr_kcal > 0 or entry.active_calories_kcal > 0):
            total_burned = round(entry.bmr_kcal + entry.active_calories_kcal, 1)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO activities (
                        user_id, date, steps, active_calories_kcal, bmr_kcal, total_burned_kcal,
                        workout_minutes, workout_type, resting_hr_bpm, hrv_ms, sleep_score,
                        source, external_id, idempotency_key, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date) DO UPDATE SET
                        steps = EXCLUDED.steps,
                        active_calories_kcal = EXCLUDED.active_calories_kcal,
                        bmr_kcal = EXCLUDED.bmr_kcal,
                        total_burned_kcal = EXCLUDED.total_burned_kcal,
                        workout_minutes = EXCLUDED.workout_minutes,
                        workout_type = EXCLUDED.workout_type,
                        resting_hr_bpm = EXCLUDED.resting_hr_bpm,
                        hrv_ms = EXCLUDED.hrv_ms,
                        sleep_score = EXCLUDED.sleep_score,
                        source = EXCLUDED.source,
                        external_id = COALESCE(EXCLUDED.external_id, activities.external_id),
                        idempotency_key = COALESCE(EXCLUDED.idempotency_key, activities.idempotency_key)
                    RETURNING id;
                """, (
                    user_id, date_str, entry.steps, entry.active_calories_kcal,
                    entry.bmr_kcal, total_burned, entry.workout_minutes,
                    entry.workout_type, entry.resting_hr_bpm, entry.hrv_ms,
                    entry.sleep_score, entry.source, entry.external_id, idemp_key, now_str
                ))
                res = cursor.fetchone()
                entry_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO activities (
                        user_id, date, steps, active_calories_kcal, bmr_kcal, total_burned_kcal,
                        workout_minutes, workout_type, resting_hr_bpm, hrv_ms, sleep_score,
                        source, external_id, idempotency_key, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date) DO UPDATE SET
                        steps = excluded.steps,
                        active_calories_kcal = excluded.active_calories_kcal,
                        bmr_kcal = excluded.bmr_kcal,
                        total_burned_kcal = excluded.total_burned_kcal,
                        workout_minutes = excluded.workout_minutes,
                        workout_type = excluded.workout_type,
                        resting_hr_bpm = excluded.resting_hr_bpm,
                        hrv_ms = excluded.hrv_ms,
                        sleep_score = excluded.sleep_score,
                        source = excluded.source,
                        external_id = COALESCE(excluded.external_id, activities.external_id),
                        idempotency_key = COALESCE(excluded.idempotency_key, activities.idempotency_key)
                """, (
                    user_id, date_str, entry.steps, entry.active_calories_kcal,
                    entry.bmr_kcal, total_burned, entry.workout_minutes,
                    entry.workout_type, entry.resting_hr_bpm, entry.hrv_ms,
                    entry.sleep_score, entry.source, entry.external_id, idemp_key, now_str
                ))
                entry_id = cursor.lastrowid
            conn.commit()

        entry_dict = entry.model_dump()
        entry_dict["id"] = entry_id
        entry_dict["total_burned_kcal"] = total_burned
        entry_dict["idempotency_key"] = idemp_key
        entry_dict["created_at"] = datetime.fromisoformat(now_str)
        return ActivityEntry(**entry_dict)

    def get_activities(self, limit: int = 30, user_id: int = 1, exclude_simulation: bool = False) -> List[ActivityEntry]:
        """Récupère l'historique d'activité ordonné par date croissante pour un utilisateur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if exclude_simulation:
                cursor.execute("""
                    SELECT * FROM (
                        SELECT * FROM activities WHERE user_id = ? AND source NOT IN ('simulation') ORDER BY date DESC LIMIT ?
                    ) sub ORDER BY date ASC
                """, (user_id, limit))
            else:
                cursor.execute("""
                    SELECT * FROM (
                        SELECT * FROM activities WHERE user_id = ? ORDER BY date DESC LIMIT ?
                    ) sub ORDER BY date ASC
                """, (user_id, limit))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            results.append(ActivityEntry(
                id=r["id"],
                date=date.fromisoformat(r["date"][:10]),
                steps=r["steps"],
                active_calories_kcal=r["active_calories_kcal"],
                bmr_kcal=r["bmr_kcal"],
                total_burned_kcal=r["total_burned_kcal"],
                workout_minutes=r["workout_minutes"],
                workout_type=r["workout_type"],
                resting_hr_bpm=r["resting_hr_bpm"],
                hrv_ms=r["hrv_ms"],
                sleep_score=r["sleep_score"],
                source=r["source"],
                is_simulated=(r["source"] in ("simulation", "demo")),
                external_id=r.get("external_id"),
                idempotency_key=r.get("idempotency_key"),
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
            ))
        return results

    # ---------------------------------------------------------
    # Repas Multi-Utilisateurs
    # ---------------------------------------------------------

    def insert_meal(self, entry: MealEntry, user_id: int = 1) -> MealEntry:
        """Insère un repas pour user_id avec ses aliments décomposés."""
        now_str = datetime.now(timezone.utc).isoformat()
        date_str = entry.date.isoformat()
        items_json = json.dumps([item.model_dump() for item in entry.items])

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO meals (user_id, date, meal_type, total_calories_kcal, protein_g, carbs_g, fat_g, fiber_g, photo_data_url, items_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id;
                """, (
                    user_id, date_str, entry.meal_type, entry.total_calories_kcal,
                    entry.protein_g, entry.carbs_g, entry.fat_g, entry.fiber_g,
                    entry.photo_data_url, items_json, now_str
                ))
                res = cursor.fetchone()
                entry_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO meals (user_id, date, meal_type, total_calories_kcal, protein_g, carbs_g, fat_g, fiber_g, photo_data_url, items_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, date_str, entry.meal_type, entry.total_calories_kcal,
                    entry.protein_g, entry.carbs_g, entry.fat_g, entry.fiber_g,
                    entry.photo_data_url, items_json, now_str
                ))
                entry_id = cursor.lastrowid
            conn.commit()

        entry_dict = entry.model_dump()
        entry_dict["id"] = entry_id
        entry_dict["created_at"] = datetime.fromisoformat(now_str)
        return MealEntry(**entry_dict)

    def get_meals_for_date(self, target_date: date, user_id: int = 1) -> List[MealEntry]:
        """Récupère tous les repas d'une date spécifique pour user_id."""
        date_str = target_date.isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM meals
                WHERE user_id = ? AND date = ?
                ORDER BY id ASC
            """, (user_id, date_str))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            raw_items = json.loads(r["items_json"]) if r.get("items_json") else []
            items = [FoodItem(**item) for item in raw_items]
            results.append(MealEntry(
                id=r["id"],
                date=date.fromisoformat(r["date"][:10]),
                meal_type=r["meal_type"],
                total_calories_kcal=r["total_calories_kcal"],
                protein_g=r["protein_g"],
                carbs_g=r["carbs_g"],
                fat_g=r["fat_g"],
                fiber_g=r["fiber_g"],
                photo_data_url=r["photo_data_url"],
                items=items,
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
            ))
        return results

    def get_meals(self, limit: int = 50, user_id: int = 1) -> List[MealEntry]:
        """Récupère l'historique récent des repas pour user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM (
                    SELECT * FROM meals WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT ?
                ) sub ORDER BY date ASC, id ASC
            """, (user_id, limit))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            raw_items = json.loads(r["items_json"]) if r.get("items_json") else []
            items = [FoodItem(**item) for item in raw_items]
            results.append(MealEntry(
                id=r["id"],
                date=date.fromisoformat(r["date"][:10]),
                meal_type=r["meal_type"],
                total_calories_kcal=r["total_calories_kcal"],
                protein_g=r["protein_g"],
                carbs_g=r["carbs_g"],
                fat_g=r["fat_g"],
                fiber_g=r["fiber_g"],
                photo_data_url=r["photo_data_url"],
                items=items,
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
            ))
        return results

    # ---------------------------------------------------------
    
    def get_meal_by_id(self, meal_id: int, user_id: int = 1) -> Optional[MealEntry]:
        """Récupère un repas spécifique par son ID pour user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM meals WHERE id = ? AND user_id = ?", (meal_id, user_id))
            r = cursor.fetchone()
        if not r:
            return None
        raw_items = json.loads(r["items_json"]) if r.get("items_json") else []
        items = [FoodItem(**item) for item in raw_items]
        return MealEntry(
            id=r["id"],
            date=date.fromisoformat(r["date"][:10]),
            meal_type=r["meal_type"],
            total_calories_kcal=r["total_calories_kcal"],
            protein_g=r["protein_g"],
            carbs_g=r["carbs_g"],
            fat_g=r["fat_g"],
            fiber_g=r["fiber_g"],
            photo_data_url=r["photo_data_url"],
            items=items,
            created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
        )

    def update_meal(self, meal_id: int, entry: MealEntry, user_id: int = 1) -> Optional[MealEntry]:
        """Met à jour un repas existant pour user_id."""
        existing = self.get_meal_by_id(meal_id, user_id=user_id)
        if not existing:
            return None

        items_json = json.dumps([item.model_dump() for item in entry.items])
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE meals
                SET date = ?, meal_type = ?, total_calories_kcal = ?, protein_g = ?,
                    carbs_g = ?, fat_g = ?, fiber_g = ?, photo_data_url = ?, items_json = ?
                WHERE id = ? AND user_id = ?
            """, (
                entry.date.isoformat(), entry.meal_type, entry.total_calories_kcal,
                entry.protein_g, entry.carbs_g, entry.fat_g, entry.fiber_g,
                entry.photo_data_url or existing.photo_data_url, items_json, meal_id, user_id
            ))
            conn.commit()

        entry_dict = entry.model_dump()
        entry_dict["id"] = meal_id
        entry_dict["created_at"] = existing.created_at
        return MealEntry(**entry_dict)

    def delete_meal(self, meal_id: int, user_id: int = 1) -> bool:
        """Supprime un repas pour user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM meals WHERE id = ? AND user_id = ?", (meal_id, user_id))
            if not cursor.fetchone():
                return False
            cursor.execute("DELETE FROM meals WHERE id = ? AND user_id = ?", (meal_id, user_id))
            conn.commit()
            return True

    # ---------------------------------------------------------
    # Plats Sauvegardés / Bibliothèque de Repas Réutilisables
    # ---------------------------------------------------------

    def insert_saved_meal(self, saved_meal: SavedMeal, user_id: int = 1) -> SavedMeal:
        """Enregistre un nouveau plat type dans la bibliothèque réutilisable."""
        now_str = datetime.now(timezone.utc).isoformat()
        items_json = json.dumps([item.model_dump() for item in saved_meal.items]) if saved_meal.items else "[]"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO saved_meals (
                        user_id, name, meal_type, serving_size, quantity_grams,
                        calories, protein_g, carbs_g, fat_g, fiber_g,
                        ingredients, items_json, photo_url, is_favorite,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id, created_at, updated_at;
                """, (
                    user_id, saved_meal.name, saved_meal.meal_type, saved_meal.serving_size or "1 portion",
                    saved_meal.quantity_grams, saved_meal.calories, saved_meal.protein_g,
                    saved_meal.carbs_g, saved_meal.fat_g, saved_meal.fiber_g or 0.0,
                    saved_meal.ingredients, items_json, saved_meal.photo_url,
                    1 if saved_meal.is_favorite else 0, now_str, now_str
                ))
                row = cursor.fetchone()
                meal_id = row["id"]
                created_at = row["created_at"]
            else:
                cursor.execute("""
                    INSERT INTO saved_meals (
                        user_id, name, meal_type, serving_size, quantity_grams,
                        calories, protein_g, carbs_g, fat_g, fiber_g,
                        ingredients, items_json, photo_url, is_favorite,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, saved_meal.name, saved_meal.meal_type, saved_meal.serving_size or "1 portion",
                    saved_meal.quantity_grams, saved_meal.calories, saved_meal.protein_g,
                    saved_meal.carbs_g, saved_meal.fat_g, saved_meal.fiber_g or 0.0,
                    saved_meal.ingredients, items_json, saved_meal.photo_url,
                    1 if saved_meal.is_favorite else 0, now_str, now_str
                ))
                meal_id = cursor.lastrowid
                created_at = now_str
            conn.commit()

        result = saved_meal.model_copy()
        result.id = meal_id
        result.user_id = user_id
        result.created_at = datetime.fromisoformat(created_at) if isinstance(created_at, str) else created_at
        result.updated_at = datetime.fromisoformat(now_str)
        return result

    def get_saved_meals(
        self,
        meal_type: Optional[str] = None,
        is_favorite: Optional[bool] = None,
        user_id: int = 1
    ) -> List[SavedMeal]:
        """Récupère les plats sauvegardés d'un utilisateur avec filtres optionnels."""
        query = "SELECT * FROM saved_meals WHERE user_id = ?"
        params: List[Any] = [user_id]

        if meal_type:
            query += " AND meal_type = ?"
            params.append(meal_type)
        if is_favorite is not None:
            query += " AND is_favorite = ?"
            params.append(1 if is_favorite else 0)

        query += " ORDER BY is_favorite DESC, updated_at DESC, id DESC"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            raw_items = json.loads(r["items_json"]) if r.get("items_json") else []
            items = [FoodItem(**item) for item in raw_items]
            results.append(SavedMeal(
                id=r["id"],
                user_id=r["user_id"],
                name=r["name"],
                meal_type=r["meal_type"],
                serving_size=r["serving_size"],
                quantity_grams=r["quantity_grams"],
                calories=r["calories"],
                protein_g=r["protein_g"],
                carbs_g=r["carbs_g"],
                fat_g=r["fat_g"],
                fiber_g=r["fiber_g"],
                ingredients=r["ingredients"],
                items=items,
                photo_url=r["photo_url"],
                is_favorite=bool(r["is_favorite"]),
                created_at=datetime.fromisoformat(r["created_at"]) if r.get("created_at") else None,
                updated_at=datetime.fromisoformat(r["updated_at"]) if r.get("updated_at") else None
            ))
        return results

    def get_saved_meal_by_id(self, meal_id: int, user_id: int = 1) -> Optional[SavedMeal]:
        """Récupère un plat réutilisable précis par son ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM saved_meals WHERE id = ? AND user_id = ?", (meal_id, user_id))
            r = cursor.fetchone()
        if not r:
            return None
        raw_items = json.loads(r["items_json"]) if r.get("items_json") else []
        items = [FoodItem(**item) for item in raw_items]
        return SavedMeal(
            id=r["id"],
            user_id=r["user_id"],
            name=r["name"],
            meal_type=r["meal_type"],
            serving_size=r["serving_size"],
            quantity_grams=r["quantity_grams"],
            calories=r["calories"],
            protein_g=r["protein_g"],
            carbs_g=r["carbs_g"],
            fat_g=r["fat_g"],
            fiber_g=r["fiber_g"],
            ingredients=r["ingredients"],
            items=items,
            photo_url=r["photo_url"],
            is_favorite=bool(r["is_favorite"]),
            created_at=datetime.fromisoformat(r["created_at"]) if r.get("created_at") else None,
            updated_at=datetime.fromisoformat(r["updated_at"]) if r.get("updated_at") else None
        )

    def update_saved_meal(self, meal_id: int, saved_meal: SavedMeal, user_id: int = 1) -> Optional[SavedMeal]:
        """Met à jour un plat type réutilisable."""
        existing = self.get_saved_meal_by_id(meal_id, user_id=user_id)
        if not existing:
            return None

        now_str = datetime.now(timezone.utc).isoformat()
        items_json = json.dumps([item.model_dump() for item in saved_meal.items]) if saved_meal.items else "[]"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE saved_meals
                SET name = ?, meal_type = ?, serving_size = ?, quantity_grams = ?,
                    calories = ?, protein_g = ?, carbs_g = ?, fat_g = ?, fiber_g = ?,
                    ingredients = ?, items_json = ?, photo_url = ?, is_favorite = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
            """, (
                saved_meal.name, saved_meal.meal_type, saved_meal.serving_size,
                saved_meal.quantity_grams, saved_meal.calories, saved_meal.protein_g,
                saved_meal.carbs_g, saved_meal.fat_g, saved_meal.fiber_g or 0.0,
                saved_meal.ingredients, items_json,
                saved_meal.photo_url if saved_meal.photo_url is not None else existing.photo_url,
                1 if saved_meal.is_favorite else 0, now_str, meal_id, user_id
            ))
            conn.commit()

        updated = saved_meal.model_copy()
        updated.id = meal_id
        updated.user_id = user_id
        updated.created_at = existing.created_at
        updated.updated_at = datetime.fromisoformat(now_str)
        return updated

    def delete_saved_meal(self, meal_id: int, user_id: int = 1) -> bool:
        """Supprime un plat réutilisable de la bibliothèque."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM saved_meals WHERE id = ? AND user_id = ?", (meal_id, user_id))
            if not cursor.fetchone():
                return False
            cursor.execute("DELETE FROM saved_meals WHERE id = ? AND user_id = ?", (meal_id, user_id))
            conn.commit()
            return True


    # ---------------------------------------------------------
    # Catalogue Aliments & Plats (Stage 12 - food_items)
    # ---------------------------------------------------------

    def insert_food_item(self, item: CatalogItem, user_id: int = 1) -> CatalogItem:
        """Crée un aliment ou un plat dans le catalogue de l'utilisateur."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO food_items (
                        user_id, name, item_type, default_unit, default_quantity,
                        calories_per_unit, protein_per_unit_g, carbs_per_unit_g,
                        fat_per_unit_g, fiber_per_unit_g, photo_url, recipe_items_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id, created_at, updated_at;
                """, (
                    user_id, item.name, item.item_type, item.default_unit or "g",
                    item.default_quantity or 100.0, item.calories_per_unit,
                    item.protein_per_unit_g or 0.0, item.carbs_per_unit_g or 0.0,
                    item.fat_per_unit_g or 0.0, item.fiber_per_unit_g or 0.0,
                    item.photo_url, json.dumps(item.recipe_items) if item.recipe_items else None,
                    now_str, now_str
                ))
                row = cursor.fetchone()
                item_id = row["id"]
                created_at = row["created_at"]
                updated_at = row["updated_at"]
            else:
                cursor.execute("""
                    INSERT INTO food_items (
                        user_id, name, item_type, default_unit, default_quantity,
                        calories_per_unit, protein_per_unit_g, carbs_per_unit_g,
                        fat_per_unit_g, fiber_per_unit_g, photo_url, recipe_items_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, item.name, item.item_type, item.default_unit or "g",
                    item.default_quantity or 100.0, item.calories_per_unit,
                    item.protein_per_unit_g or 0.0, item.carbs_per_unit_g or 0.0,
                    item.fat_per_unit_g or 0.0, item.fiber_per_unit_g or 0.0,
                    item.photo_url, json.dumps(item.recipe_items) if item.recipe_items else None,
                    now_str, now_str
                ))
                item_id = cursor.lastrowid
                created_at = now_str
                updated_at = now_str
            conn.commit()

        res = item.model_copy()
        res.id = item_id
        res.user_id = user_id
        res.created_at = datetime.fromisoformat(created_at) if isinstance(created_at, str) else created_at
        res.updated_at = datetime.fromisoformat(updated_at) if isinstance(updated_at, str) else updated_at
        if item.benefits:
            self.set_food_item_benefits(item_id, [b.model_dump() for b in item.benefits])
            res.benefits = self.get_food_item_benefits(item_id)
        else:
            res.benefits = []
        return res

    def get_food_items(
        self,
        item_type: Optional[str] = None,
        query: Optional[str] = None,
        user_id: int = 1
    ) -> List[CatalogItem]:
        """Récupère les éléments du catalogue de l'utilisateur avec filtres optionnels."""
        sql = "SELECT * FROM food_items WHERE user_id = ?"
        params: List[Any] = [user_id]

        if item_type:
            sql += " AND item_type = ?"
            params.append(item_type)

        if query:
            sql += " AND LOWER(name) LIKE ?"
            params.append(f"%{query.strip().lower()}%")

        sql += " ORDER BY name ASC"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()

        items = []
        for r in rows:
            it = CatalogItem(
                id=r["id"],
                user_id=r["user_id"],
                name=r["name"],
                item_type=r["item_type"],
                default_unit=r["default_unit"],
                default_quantity=float(r["default_quantity"]),
                calories_per_unit=float(r["calories_per_unit"]),
                protein_per_unit_g=float(r.get("protein_per_unit_g") or 0.0),
                carbs_per_unit_g=float(r.get("carbs_per_unit_g") or 0.0),
                fat_per_unit_g=float(r.get("fat_per_unit_g") or 0.0),
                fiber_per_unit_g=float(r["fiber_per_unit_g"]) if r.get("fiber_per_unit_g") is not None else 0.0,
                photo_url=r.get("photo_url"),
                recipe_items=json.loads(r["recipe_items_json"]) if r.get("recipe_items_json") else [],
                benefits=self.get_food_item_benefits(r["id"]),
                created_at=datetime.fromisoformat(r["created_at"]) if r.get("created_at") else None,
                updated_at=datetime.fromisoformat(r["updated_at"]) if r.get("updated_at") else None,
            )
            items.append(it)
        return items

    def get_food_item_by_id(self, item_id: int, user_id: int = 1) -> Optional[CatalogItem]:
        """Récupère un élément du catalogue par son ID pour user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM food_items WHERE id = ? AND user_id = ?", (item_id, user_id))
            r = cursor.fetchone()
            if not r:
                return None
            return CatalogItem(
                id=r["id"],
                user_id=r["user_id"],
                name=r["name"],
                item_type=r["item_type"],
                default_unit=r["default_unit"],
                default_quantity=float(r["default_quantity"]),
                calories_per_unit=float(r["calories_per_unit"]),
                protein_per_unit_g=float(r.get("protein_per_unit_g") or 0.0),
                carbs_per_unit_g=float(r.get("carbs_per_unit_g") or 0.0),
                fat_per_unit_g=float(r.get("fat_per_unit_g") or 0.0),
                fiber_per_unit_g=float(r["fiber_per_unit_g"]) if r.get("fiber_per_unit_g") is not None else 0.0,
                photo_url=r.get("photo_url"),
                recipe_items=json.loads(r["recipe_items_json"]) if r.get("recipe_items_json") else [],
                benefits=self.get_food_item_benefits(r["id"]),
                created_at=datetime.fromisoformat(r["created_at"]) if r.get("created_at") else None,
                updated_at=datetime.fromisoformat(r["updated_at"]) if r.get("updated_at") else None,
            )

    def update_food_item(self, item_id: int, data: Dict[str, Any], user_id: int = 1) -> Optional[CatalogItem]:
        """Met à jour un aliment ou plat du catalogue."""
        existing = self.get_food_item_by_id(item_id, user_id=user_id)
        if not existing:
            return None

        now_str = datetime.now(timezone.utc).isoformat()
        name = data.get("name", existing.name)
        item_type = data.get("item_type", existing.item_type)
        default_unit = data.get("default_unit", existing.default_unit)
        default_quantity = data.get("default_quantity", existing.default_quantity)
        calories_per_unit = data.get("calories_per_unit", existing.calories_per_unit)
        protein_per_unit_g = data.get("protein_per_unit_g", existing.protein_per_unit_g)
        carbs_per_unit_g = data.get("carbs_per_unit_g", existing.carbs_per_unit_g)
        fat_per_unit_g = data.get("fat_per_unit_g", existing.fat_per_unit_g)
        fiber_per_unit_g = data.get("fiber_per_unit_g", existing.fiber_per_unit_g)
        photo_url = data.get("photo_url", existing.photo_url)
        recipe_items = data.get("recipe_items", existing.recipe_items)
        recipe_items_json = json.dumps(recipe_items) if recipe_items is not None else None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE food_items
                SET name = ?, item_type = ?, default_unit = ?, default_quantity = ?,
                    calories_per_unit = ?, protein_per_unit_g = ?, carbs_per_unit_g = ?,
                    fat_per_unit_g = ?, fiber_per_unit_g = ?, photo_url = ?, recipe_items_json = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
            """, (
                name, item_type, default_unit, default_quantity,
                calories_per_unit, protein_per_unit_g, carbs_per_unit_g,
                fat_per_unit_g, fiber_per_unit_g, photo_url, recipe_items_json, now_str,
                item_id, user_id
            ))
            conn.commit()

        updated = existing.model_copy()
        updated.name = name
        updated.item_type = item_type
        updated.recipe_items = recipe_items or []
        updated.default_unit = default_unit
        updated.default_quantity = default_quantity
        updated.calories_per_unit = calories_per_unit
        updated.protein_per_unit_g = protein_per_unit_g
        updated.carbs_per_unit_g = carbs_per_unit_g
        updated.fat_per_unit_g = fat_per_unit_g
        updated.fiber_per_unit_g = fiber_per_unit_g
        updated.photo_url = photo_url
        updated.updated_at = datetime.fromisoformat(now_str)
        return updated

    def delete_food_item(self, item_id: int, user_id: int = 1) -> bool:
        """Supprime un aliment ou plat du catalogue de l'utilisateur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM food_items WHERE id = ? AND user_id = ?", (item_id, user_id))
            if not cursor.fetchone():
                return False
            cursor.execute("DELETE FROM food_items WHERE id = ? AND user_id = ?", (item_id, user_id))
            conn.commit()
            return True

    # ---------------------------------------------------------
    # Référentiel des Bienfaits Nutritionnels (Stage 13)
    # ---------------------------------------------------------

    def _seed_nutrition_benefits(self):
        """Seede le référentiel des bienfaits nutritionnels depuis le fichier source ou le fallback."""
        from src.nutrition_rules import EXPERT_BENEFITS_CATALOG

        # On essaie d'abord de charger les données complètes
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for b in EXPERT_BENEFITS_CATALOG:
                rule_cfg = json.dumps(b.get("rule_config") or {})
                if self.is_postgres:
                    cursor.execute("""
                        INSERT INTO nutrition_benefits (id, category, category_id, title, description, icon, rule_config, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (id) DO UPDATE SET
                            category = EXCLUDED.category,
                            category_id = EXCLUDED.category_id,
                            title = EXCLUDED.title,
                            description = EXCLUDED.description,
                            icon = EXCLUDED.icon,
                            rule_config = EXCLUDED.rule_config;
                    """, (
                        b["id"], b["category"], b["category_id"], b["title"],
                        b["description"], b["icon"], rule_cfg, now_str
                    ))
                else:
                    cursor.execute("""
                        INSERT INTO nutrition_benefits (id, category, category_id, title, description, icon, rule_config, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (id) DO UPDATE SET
                            category = excluded.category,
                            category_id = excluded.category_id,
                            title = excluded.title,
                            description = excluded.description,
                            icon = excluded.icon,
                            rule_config = excluded.rule_config;
                    """, (
                        b["id"], b["category"], b["category_id"], b["title"],
                        b["description"], b["icon"], rule_cfg, now_str
                    ))
            conn.commit()

    def get_all_nutrition_benefits(self) -> List[NutritionBenefitItem]:
        """Retourne la liste de tous les bienfaits disponibles ordonnés par catégorie."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM nutrition_benefits ORDER BY category_id ASC, title ASC")
            rows = cursor.fetchall()

        benefits = []
        for r in rows:
            cfg = None
            if r.get("rule_config"):
                try:
                    cfg = json.loads(r["rule_config"])
                except Exception:
                    cfg = None
            benefits.append(NutritionBenefitItem(
                id=r["id"],
                category=r["category"],
                category_id=int(r["category_id"]),
                title=r["title"],
                description=r["description"],
                icon=r["icon"],
                rule_config=cfg
            ))
        return benefits

    def get_food_item_benefits(self, food_item_id: int) -> List[AssociatedBenefit]:
        """Récupère les bienfaits associés à un aliment/plat du catalogue."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT nb.id, nb.category, nb.category_id, nb.title, nb.description, nb.icon,
                       fib.source, fib.explanation
                FROM food_item_benefits fib
                JOIN nutrition_benefits nb ON fib.benefit_id = nb.id
                WHERE fib.food_item_id = ?
                ORDER BY nb.category_id ASC, nb.title ASC
            """, (food_item_id,))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            results.append(AssociatedBenefit(
                benefit_id=r["id"],
                category=r["category"],
                category_id=int(r["category_id"]),
                title=r["title"],
                description=r["description"],
                icon=r["icon"],
                source=r["source"],
                explanation=r.get("explanation")
            ))
        return results

    def set_food_item_benefits(
        self,
        food_item_id: int,
        benefits_data: List[Dict[str, Any]]
    ) -> List[AssociatedBenefit]:
        """Associe ou remplace l'ensemble des bienfaits d'un aliment/plat."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Supprimer les anciens bienfaits
            cursor.execute("DELETE FROM food_item_benefits WHERE food_item_id = ?", (food_item_id,))

            for b in benefits_data:
                benefit_id = b.get("benefit_id") or b.get("id")
                if not benefit_id:
                    continue
                source = b.get("source", "manual")
                explanation = b.get("explanation", "")
                cursor.execute("""
                    INSERT INTO food_item_benefits (food_item_id, benefit_id, source, explanation, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (food_item_id, benefit_id, source, explanation, now_str))
            conn.commit()

        return self.get_food_item_benefits(food_item_id)

    # ---------------------------------------------------------

    def get_or_create_meal_log(self, date_val: date, meal_type: str, user_id: int = 1) -> MealLog:
        """Récupère l'instance de repas pour une date et un type, ou la crée si inexistante."""
        date_str = date_val.isoformat()
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM meal_logs
                WHERE user_id = ? AND date = ? AND meal_type = ?
            """, (user_id, date_str, meal_type))
            row = cursor.fetchone()

            if not row:
                if self.is_postgres:
                    cursor.execute("""
                        INSERT INTO meal_logs (user_id, date, meal_type, total_calories, total_protein_g, total_carbs_g, total_fat_g, total_fiber_g, created_at, updated_at)
                        VALUES (?, ?, ?, 0.0, 0.0, 0.0, 0.0, 0.0, ?, ?)
                        ON CONFLICT (user_id, date, meal_type) DO NOTHING
                        RETURNING id, date, meal_type, photo_url, total_calories, total_protein_g, total_carbs_g, total_fat_g, total_fiber_g, created_at, updated_at;
                    """, (user_id, date_str, meal_type, now_str, now_str))
                    row = cursor.fetchone()
                else:
                    cursor.execute("""
                        INSERT OR IGNORE INTO meal_logs (user_id, date, meal_type, total_calories, total_protein_g, total_carbs_g, total_fat_g, total_fiber_g, created_at, updated_at)
                        VALUES (?, ?, ?, 0.0, 0.0, 0.0, 0.0, 0.0, ?, ?)
                    """, (user_id, date_str, meal_type, now_str, now_str))
                conn.commit()

                if not row:
                    cursor.execute("""
                        SELECT * FROM meal_logs
                        WHERE user_id = ? AND date = ? AND meal_type = ?
                    """, (user_id, date_str, meal_type))
                    row = cursor.fetchone()

        return self._build_meal_log(dict(row), user_id=user_id)

    def _build_meal_log(self, row: Dict[str, Any], user_id: int = 1) -> MealLog:
        """Construit un objet MealLog avec tous ses MealLogItem associés."""
        meal_log_id = row["id"]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM meal_log_items
                WHERE meal_log_id = ?
                ORDER BY id ASC
            """, (meal_log_id,))
            item_rows = cursor.fetchall()

        items = [
            MealLogItem(
                id=it["id"],
                meal_log_id=it["meal_log_id"],
                food_item_id=it.get("food_item_id"),
                name=it["name"],
                quantity=float(it["quantity"]),
                unit=it["unit"],
                calories=float(it["calories"]),
                protein_g=float(it.get("protein_g") or 0.0),
                carbs_g=float(it.get("carbs_g") or 0.0),
                fat_g=float(it.get("fat_g") or 0.0),
                fiber_g=float(it["fiber_g"]) if it.get("fiber_g") is not None else 0.0,
                created_at=datetime.fromisoformat(it["created_at"]) if it.get("created_at") else None,
            )
            for it in item_rows
        ]

        return MealLog(
            id=row["id"],
            user_id=row["user_id"],
            date=date.fromisoformat(row["date"][:10]),
            meal_type=row["meal_type"],
            photo_url=row.get("photo_url"),
            total_calories=float(row.get("total_calories") or 0.0),
            total_protein_g=float(row.get("total_protein_g") or 0.0),
            total_carbs_g=float(row.get("total_carbs_g") or 0.0),
            total_fat_g=float(row.get("total_fat_g") or 0.0),
            total_fiber_g=float(row["total_fiber_g"]) if row.get("total_fiber_g") is not None else 0.0,
            items=items,
            created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row.get("updated_at") else None,
        )

    def get_meal_logs_for_date(self, target_date: date, user_id: int = 1) -> List[MealLog]:
        """Récupère les 4 repas d'une date (avec les instances existantes)."""
        date_str = target_date.isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM meal_logs
                WHERE user_id = ? AND date = ?
                ORDER BY id ASC
            """, (user_id, date_str))
            rows = cursor.fetchall()

        return [self._build_meal_log(dict(r), user_id=user_id) for r in rows]

    def add_item_to_meal_log(
        self,
        date_val: date,
        meal_type: str,
        name: str,
        quantity: float,
        unit: str,
        calories: float,
        protein_g: float = 0.0,
        carbs_g: float = 0.0,
        fat_g: float = 0.0,
        fiber_g: float = 0.0,
        food_item_id: Optional[int] = None,
        user_id: int = 1
    ) -> MealLog:
        """Ajoute un aliment/plat à un repas pour une date et recalcule les totaux."""
        meal_log = self.get_or_create_meal_log(date_val, meal_type, user_id=user_id)
        now_str = datetime.now(timezone.utc).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO meal_log_items (
                    meal_log_id, food_item_id, name, quantity, unit,
                    calories, protein_g, carbs_g, fat_g, fiber_g, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                meal_log.id, food_item_id, name, quantity, unit,
                calories, protein_g, carbs_g, fat_g, fiber_g, now_str
            ))
            conn.commit()

        self._recalculate_meal_log_totals(meal_log.id, user_id=user_id)
        self._sync_meal_log_to_meals(meal_log.id, user_id=user_id)
        return self._get_meal_log_by_id(meal_log.id, user_id=user_id)

    def delete_meal_log_item(self, item_id: int, user_id: int = 1) -> Optional[MealLog]:
        """Supprime une ligne d'aliment consommée et recalcule le repas parent."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT m.id AS meal_log_id
                FROM meal_log_items it
                JOIN meal_logs m ON it.meal_log_id = m.id
                WHERE it.id = ? AND m.user_id = ?
            """, (item_id, user_id))
            row = cursor.fetchone()
            if not row:
                return None

            meal_log_id = row["meal_log_id"]
            cursor.execute("DELETE FROM meal_log_items WHERE id = ?", (item_id,))
            conn.commit()

        self._recalculate_meal_log_totals(meal_log_id, user_id=user_id)
        self._sync_meal_log_to_meals(meal_log_id, user_id=user_id)
        return self._get_meal_log_by_id(meal_log_id, user_id=user_id)

    def _recalculate_meal_log_totals(self, meal_log_id: int, user_id: int = 1):
        """Recalcule et met à jour les totaux d'un MealLog."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COALESCE(SUM(calories), 0.0) AS total_cal,
                    COALESCE(SUM(protein_g), 0.0) AS total_prot,
                    COALESCE(SUM(carbs_g), 0.0) AS total_carbs,
                    COALESCE(SUM(fat_g), 0.0) AS total_fat,
                    COALESCE(SUM(fiber_g), 0.0) AS total_fiber
                FROM meal_log_items
                WHERE meal_log_id = ?
            """, (meal_log_id,))
            totals = cursor.fetchone()

            cursor.execute("""
                UPDATE meal_logs
                SET total_calories = ?, total_protein_g = ?, total_carbs_g = ?,
                    total_fat_g = ?, total_fiber_g = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
            """, (
                round(float(totals["total_cal"]), 1),
                round(float(totals["total_prot"]), 1),
                round(float(totals["total_carbs"]), 1),
                round(float(totals["total_fat"]), 1),
                round(float(totals["total_fiber"]), 1),
                now_str, meal_log_id, user_id
            ))
            conn.commit()


    def _sync_meal_log_to_meals(self, meal_log_id: int, user_id: int = 1):
        """Synchronise un meal_log avec la table meals pour alimenter l'historique et les calories journalières."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT date, meal_type, total_calories, total_protein_g, total_carbs_g, total_fat_g, total_fiber_g FROM meal_logs WHERE id = ? AND user_id = ?", (meal_log_id, user_id))
            ml = cursor.fetchone()
            if not ml:
                return

            date_str = ml["date"][:10]
            meal_type = ml["meal_type"]
            total_cals = round(float(ml["total_calories"] or 0.0), 1)
            total_prot = round(float(ml["total_protein_g"] or 0.0), 1)
            total_carbs = round(float(ml["total_carbs_g"] or 0.0), 1)
            total_fat = round(float(ml["total_fat_g"] or 0.0), 1)
            total_fiber = round(float(ml["total_fiber_g"] or 0.0), 1)

            # Charger les items
            cursor.execute("""
                SELECT name, quantity, unit, calories, protein_g, carbs_g, fat_g, fiber_g
                FROM meal_log_items
                WHERE meal_log_id = ?
            """, (meal_log_id,))
            items_rows = cursor.fetchall()
            items_list = [
                {
                    "name": r["name"],
                    "portion_g": float(r["quantity"]) if r["unit"] == "g" else 100.0,
                    "calories_kcal": float(r["calories"] or 0.0),
                    "protein_g": float(r["protein_g"] or 0.0),
                    "carbs_g": float(r["carbs_g"] or 0.0),
                    "fat_g": float(r["fat_g"] or 0.0),
                    "fiber_g": float(r["fiber_g"] or 0.0),
                    "confidence_score": 1.0
                }
                for r in items_rows
            ]
            items_json = json.dumps(items_list)

            # Chercher dans meals si une entrée existe déjà
            cursor.execute("""
                SELECT id FROM meals
                WHERE user_id = ? AND date = ? AND meal_type = ?
                ORDER BY id DESC LIMIT 1
            """, (user_id, date_str, meal_type))
            existing = cursor.fetchone()

            if total_cals > 0:
                if existing:
                    cursor.execute("""
                        UPDATE meals
                        SET total_calories_kcal = ?, protein_g = ?, carbs_g = ?,
                            fat_g = ?, fiber_g = ?, items_json = ?
                        WHERE id = ?
                    """, (total_cals, total_prot, total_carbs, total_fat, total_fiber, items_json, existing["id"]))
                else:
                    cursor.execute("""
                        INSERT INTO meals (
                            user_id, date, meal_type, total_calories_kcal,
                            protein_g, carbs_g, fat_g, fiber_g, photo_data_url, items_json, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_id, date_str, meal_type, total_cals,
                        total_prot, total_carbs, total_fat, total_fiber,
                        None, items_json, now_str
                    ))
            else:
                if existing:
                    cursor.execute("DELETE FROM meals WHERE id = ?", (existing["id"],))
            conn.commit()

    def sync_all_meal_logs_to_meals(self, user_id: Optional[int] = None):
        """Synchronise l'ensemble des meal_logs existants vers la table meals."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if user_id:
                cursor.execute("SELECT id, user_id FROM meal_logs WHERE user_id = ?", (user_id,))
            else:
                cursor.execute("SELECT id, user_id FROM meal_logs")
            rows = cursor.fetchall()
        for r in rows:
            self._sync_meal_log_to_meals(r["id"], user_id=r["user_id"])

    def _get_meal_log_by_id(self, meal_log_id: int, user_id: int = 1) -> MealLog:
        """Récupère un MealLog complet par son ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM meal_logs WHERE id = ? AND user_id = ?", (meal_log_id, user_id))
            row = cursor.fetchone()
        return self._build_meal_log(dict(row), user_id=user_id)

    # Profil Utilisateur & Appareils
    # ---------------------------------------------------------

    def get_user_profile(self, user_id: int = 1) -> Dict[str, Any]:
        """Récupère le profil personnalisé de user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_profile WHERE user_id = ? ORDER BY id ASC LIMIT 1", (user_id,))
            row = cursor.fetchone()

            if not row:
                now_str = datetime.now(timezone.utc).isoformat()
                cursor.execute("""
                    INSERT INTO user_profile (user_id, name, gender, age, height_cm, target_weight_kg, goal_profile_id, target_steps, target_calories_intake, protein_target_per_kg, daily_protein_target_g, daily_carbs_target_g, daily_fat_target_g, daily_water_target_ml, goal_type, activity_level, birth_date, current_weight_kg, meal_distribution, preferred_ring, preferred_scale, is_demo_profile, updated_at)
                    VALUES (?, 'Sébastien', 'male', 35, 178.0, 77.0, 'weight_loss', 10000, 2000.0, 1.8, 140.0, 220.0, 65.0, 2000.0, 'weight_loss', 'moderately_active', NULL, 79.5, NULL, 'ringconn', 'withings', 0, ?)
                """, (user_id, now_str))
                conn.commit()
                cursor.execute("SELECT * FROM user_profile WHERE user_id = ? ORDER BY id ASC LIMIT 1", (user_id,))
                row = cursor.fetchone()

        return dict(row)

    def update_user_profile(self, data: Dict[str, Any], user_id: int = 1) -> Dict[str, Any]:
        """Met à jour le profil de l'utilisateur."""
        current = self.get_user_profile(user_id=user_id)
        now_str = datetime.now(timezone.utc).isoformat()

        def _val(key, default):
            v = data.get(key)
            if v is not None:
                return v
            return current.get(key, default)

        name = _val("name", "Sébastien")
        gender = _val("gender", "male")
        age = int(_val("age", 35))
        height_cm = float(_val("height_cm", 178.0))
        target_weight = float(_val("target_weight_kg", 77.0))
        goal_id = _val("goal_profile_id", "weight_loss")
        steps = int(_val("target_steps", 10000))
        cal_intake = float(_val("target_calories_intake", 2000.0))
        prot = float(_val("protein_target_per_kg", 1.8))
        ring = _val("preferred_ring", "ringconn")
        scale = _val("preferred_scale", "withings")
        google_email = _val("google_email", None)
        google_name = _val("google_name", None)
        google_picture = _val("google_picture", None)
        google_sub = _val("google_sub", None)

        # Nouveaux champs profil nutritionnel & métabolique
        daily_protein = _val("daily_protein_target_g", None)
        if daily_protein is not None:
            daily_protein = float(daily_protein)
        daily_carbs = _val("daily_carbs_target_g", None)
        if daily_carbs is not None:
            daily_carbs = float(daily_carbs)
        daily_fat = _val("daily_fat_target_g", None)
        if daily_fat is not None:
            daily_fat = float(daily_fat)
        daily_water = _val("daily_water_target_ml", 2000.0)
        if daily_water is not None:
            daily_water = float(daily_water)
        goal_type = _val("goal_type", "weight_loss")
        activity_level = _val("activity_level", "moderately_active")
        birth_date = _val("birth_date", None)
        current_weight = _val("current_weight_kg", None)
        if current_weight is not None:
            current_weight = float(current_weight)
        meal_distribution = _val("meal_distribution", None)
        if isinstance(meal_distribution, (dict, list)):
            meal_distribution = json.dumps(meal_distribution)
        is_demo_profile = 1 if _val("is_demo_profile", 0) else 0

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_profile
                SET name = ?, gender = ?, age = ?, height_cm = ?, target_weight_kg = ?,
                    goal_profile_id = ?, target_steps = ?, target_calories_intake = ?,
                    protein_target_per_kg = ?, preferred_ring = ?, preferred_scale = ?,
                    google_email = ?, google_name = ?, google_picture = ?, google_sub = ?,
                    daily_protein_target_g = ?, daily_carbs_target_g = ?, daily_fat_target_g = ?,
                    daily_water_target_ml = ?, goal_type = ?, activity_level = ?,
                    birth_date = ?, current_weight_kg = ?, meal_distribution = ?,
                    is_demo_profile = ?,
                    updated_at = ?
                WHERE user_id = ?
            """, (
                name, gender, age, height_cm, target_weight, goal_id, steps, cal_intake,
                prot, ring, scale, google_email, google_name, google_picture, google_sub,
                daily_protein, daily_carbs, daily_fat, daily_water, goal_type, activity_level,
                birth_date, current_weight, meal_distribution, is_demo_profile, now_str, user_id
            ))
            conn.commit()

        return self.get_user_profile(user_id=user_id)

    def _format_device_row(self, row: Optional[Dict[str, Any]], reveal_secrets: bool = False) -> Optional[Dict[str, Any]]:
        """Formate et protège une ligne d'appareil en chiffrant/déchiffrant les identifiants au besoin."""
        if not row:
            return None
        d = dict(row)
        # S'assurer des champs standards
        d["connected"] = bool(d.get("connected"))
        d["is_active"] = bool(d.get("is_active", 1))
        d["sync_status"] = d.get("sync_status") or ("connected" if d["connected"] else "disconnected")
        d["last_sync_at"] = d.get("last_sync_at") or d.get("last_sync")

        # Déchiffrement des credentials
        enc_cred = d.get("encrypted_credentials")
        if enc_cred:
            creds = decrypt_credentials(enc_cred)
        elif d.get("api_key"):
            creds = {"api_key": d["api_key"]}
        else:
            creds = {}

        if reveal_secrets:
            d["credentials"] = creds
        else:
            # Masquer les clés pour éviter toute fuite dans les logs ou API publiques
            d.pop("encrypted_credentials", None)
            d.pop("api_key", None)
            d["has_credentials"] = bool(creds)
            if creds.get("api_key"):
                raw_k = str(creds["api_key"])
                d["api_key_masked"] = f"{raw_k[:4]}...{raw_k[-4:]}" if len(raw_k) > 8 else "***"
        return d

    def get_user_devices(self, user_id: int = 1, reveal_secrets: bool = False) -> List[Dict[str, Any]]:
        """Récupère les objets connectés associés à user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_devices WHERE user_id = ? ORDER BY id ASC", (user_id,))
            rows = cursor.fetchall()
        return [self._format_device_row(r, reveal_secrets=reveal_secrets) for r in rows]

    def get_user_device(self, device_id: str, user_id: int = 1, reveal_secrets: bool = False) -> Optional[Dict[str, Any]]:
        """Récupère un objet connecté spécifique pour un user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_devices WHERE user_id = ? AND device_id = ? LIMIT 1", (user_id, device_id))
            row = cursor.fetchone()
        return self._format_device_row(row, reveal_secrets=reveal_secrets)

    def find_user_by_device_token(self, token: str, device_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Identifie l'utilisateur et l'appareil associés à un token ou webhook secret dans user_devices."""
        if not token or not str(token).strip():
            return None
        token_clean = str(token).strip()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # 1. Vérification directe sur api_key en clair (si renseignée)
            if device_id:
                cursor.execute("SELECT * FROM user_devices WHERE is_active = 1 AND device_id = ? AND api_key = ? LIMIT 1", (device_id, token_clean))
            else:
                cursor.execute("SELECT * FROM user_devices WHERE is_active = 1 AND api_key = ? LIMIT 1", (token_clean,))
            row = cursor.fetchone()
            if row:
                formatted = self._format_device_row(row, reveal_secrets=True)
                user_id = row["user_id"] if isinstance(row, dict) else row[1]
                user = self.get_user_by_id(int(user_id))
                return {
                    "user_id": int(user_id),
                    "user": user,
                    "device": formatted
                }

            # 2. Vérification dans les credentials chiffrés de chaque device
            if device_id:
                cursor.execute("SELECT * FROM user_devices WHERE is_active = 1 AND device_id = ? AND encrypted_credentials IS NOT NULL", (device_id,))
            else:
                cursor.execute("SELECT * FROM user_devices WHERE is_active = 1 AND encrypted_credentials IS NOT NULL")
            rows = cursor.fetchall()

        for r in rows:
            formatted = self._format_device_row(r, reveal_secrets=True)
            if not formatted:
                continue
            creds = formatted.get("credentials") or {}
            # Vérifier api_key, webhook_secret, token, bearer_token ou webhook_token
            matched = False
            for key in ["api_key", "webhook_secret", "token", "bearer_token", "webhook_token"]:
                val = creds.get(key)
                if val and str(val).strip() == token_clean:
                    matched = True
                    break

            if matched:
                user_id = r["user_id"] if isinstance(r, dict) else r[1]
                user = self.get_user_by_id(int(user_id))
                return {
                    "user_id": int(user_id),
                    "user": user,
                    "device": formatted
                }

        return None

    def find_user_device_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Compatibilité Lot 1.1 : renvoie le dict de l'appareil (avec user_id inclus)."""
        res = self.find_user_by_device_token(token)
        if res and res.get("device"):
            dev = dict(res["device"])
            dev["user_id"] = res["user_id"]
            return dev
        return None

        return None

    def delete_user_device(self, device_id: str, user_id: int = 1) -> bool:
        """Déconnecte et révoque un objet connecté pour un user_id en supprimant la ligne et les identifiants chiffrés."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_devices WHERE user_id = ? AND device_id = ?", (user_id, device_id))
            deleted = cursor.rowcount > 0
            conn.commit()
        return deleted

    def update_device_sync_status(self, device_id: str, sync_status: str, user_id: int = 1) -> Optional[Dict[str, Any]]:
        """Met à jour le statut temps réel et l'horodatage de dernière synchronisation."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_devices
                SET sync_status = ?, last_sync = ?, last_sync_at = ?, updated_at = ?
                WHERE user_id = ? AND device_id = ?
            """, (sync_status, now_str, now_str, now_str, user_id, device_id))
            conn.commit()
            cursor.execute("SELECT * FROM user_devices WHERE user_id = ? AND device_id = ?", (user_id, device_id))
            row = cursor.fetchone()
        return self._format_device_row(row, reveal_secrets=False)

    def update_user_device(
        self,
        device_id: str,
        name: str,
        device_type: str,
        connected: bool,
        auth_type: str = "connected",
        api_key: Optional[str] = None,
        credentials: Optional[Dict[str, Any]] = None,
        account_email: Optional[str] = None,
        is_active: bool = True,
        sync_status: Optional[str] = None,
        user_id: int = 1
    ) -> Dict[str, Any]:
        """Enregistre ou met à jour un objet connecté pour user_id avec chiffrement au repos."""
        now_str = datetime.now(timezone.utc).isoformat()
        if sync_status is None:
            sync_status = "connected" if connected else "disconnected"

        # Préparation des credentials à chiffrer
        creds_to_encrypt = dict(credentials) if credentials else {}
        if api_key and "api_key" not in creds_to_encrypt:
            creds_to_encrypt["api_key"] = api_key

        encrypted_credentials = encrypt_credentials(creds_to_encrypt) if creds_to_encrypt else None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO user_devices (
                        user_id, device_id, name, device_type, connected, auth_type,
                        api_key, encrypted_credentials, account_email, is_active,
                        last_sync, last_sync_at, sync_status, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, device_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        device_type = EXCLUDED.device_type,
                        connected = EXCLUDED.connected,
                        auth_type = EXCLUDED.auth_type,
                        api_key = COALESCE(EXCLUDED.api_key, user_devices.api_key),
                        encrypted_credentials = COALESCE(EXCLUDED.encrypted_credentials, user_devices.encrypted_credentials),
                        account_email = COALESCE(EXCLUDED.account_email, user_devices.account_email),
                        is_active = EXCLUDED.is_active,
                        last_sync = EXCLUDED.last_sync,
                        last_sync_at = EXCLUDED.last_sync_at,
                        sync_status = EXCLUDED.sync_status,
                        updated_at = EXCLUDED.updated_at
                    RETURNING *;
                """, (
                    user_id, device_id, name, device_type, 1 if connected else 0, auth_type,
                    api_key, encrypted_credentials, account_email, 1 if is_active else 0,
                    now_str, now_str, sync_status, now_str
                ))
                row = cursor.fetchone()
            else:
                cursor.execute("""
                    INSERT INTO user_devices (
                        user_id, device_id, name, device_type, connected, auth_type,
                        api_key, encrypted_credentials, account_email, is_active,
                        last_sync, last_sync_at, sync_status, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, device_id) DO UPDATE SET
                        name = excluded.name,
                        device_type = excluded.device_type,
                        connected = excluded.connected,
                        auth_type = excluded.auth_type,
                        api_key = COALESCE(excluded.api_key, user_devices.api_key),
                        encrypted_credentials = COALESCE(excluded.encrypted_credentials, user_devices.encrypted_credentials),
                        account_email = COALESCE(excluded.account_email, user_devices.account_email),
                        is_active = excluded.is_active,
                        last_sync = excluded.last_sync,
                        last_sync_at = excluded.last_sync_at,
                        sync_status = excluded.sync_status,
                        updated_at = excluded.updated_at
                """, (
                    user_id, device_id, name, device_type, 1 if connected else 0, auth_type,
                    api_key, encrypted_credentials, account_email, 1 if is_active else 0,
                    now_str, now_str, sync_status, now_str
                ))
                conn.commit()
                cursor.execute("SELECT * FROM user_devices WHERE user_id = ? AND device_id = ?", (user_id, device_id))
                row = cursor.fetchone()
            conn.commit()
        return self._format_device_row(row, reveal_secrets=False)

    # ---------------------------------------------------------
    # Google OAuth / GIS Sessions
    # ---------------------------------------------------------

    def get_google_config(self) -> Dict[str, Any]:
        """Récupère la configuration Google Client ID."""
        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT google_client_id FROM google_auth_config ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row and row.get("google_client_id"):
                client_id = row["google_client_id"]

        return {
            "google_client_id": client_id,
            "is_configured": bool(client_id),
            "scopes": [
                "openid",
                "email",
                "profile",
                "https://www.googleapis.com/auth/fitness.activity.read",
                "https://www.googleapis.com/auth/fitness.body.read"
            ],
            "demo_fallback_account": "sebastienlamoliate@gmail.com"
        }

    def set_google_client_id(self, client_id: str) -> Dict[str, Any]:
        """Enregistre ou met à jour le Google Client ID."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM google_auth_config")
            cursor.execute("""
                INSERT INTO google_auth_config (google_client_id, updated_at)
                VALUES (?, ?)
            """, (client_id.strip(), now_str))
            conn.commit()
        return self.get_google_config()

    def login_google_user(self, email: str, name: str, picture: str = "", google_sub: str = "", auth_method: str = "google") -> Dict[str, Any]:
        """Enregistre la session Google, synchronise le compte et lie le profil utilisateur."""
        now_str = datetime.now(timezone.utc).isoformat()
        user = self.get_or_create_user(
            email=email,
            name=name,
            picture=picture,
            auth_provider="google",
            google_sub=google_sub
        )

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE google_sessions SET is_active = 0")
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO google_sessions (email, name, picture, google_sub, auth_method, is_active, last_login)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(email) DO UPDATE SET
                        name = EXCLUDED.name,
                        picture = EXCLUDED.picture,
                        google_sub = EXCLUDED.google_sub,
                        auth_method = EXCLUDED.auth_method,
                        is_active = 1,
                        last_login = EXCLUDED.last_login
                """, (email, name, picture, google_sub, auth_method, now_str))
            else:
                cursor.execute("""
                    INSERT INTO google_sessions (email, name, picture, google_sub, auth_method, is_active, last_login)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(email) DO UPDATE SET
                        name = excluded.name,
                        picture = excluded.picture,
                        google_sub = excluded.google_sub,
                        auth_method = excluded.auth_method,
                        is_active = 1,
                        last_login = excluded.last_login
                """, (email, name, picture, google_sub, auth_method, now_str))
            conn.commit()

        self.update_user_profile({
            "google_email": email,
            "google_name": name,
            "google_picture": picture,
            "google_sub": google_sub
        }, user_id=user["id"])

        sess = self.get_google_session()
        sess["user_id"] = user["id"]
        sess["uuid"] = user["uuid"]
        return sess

    def get_google_session(self) -> Dict[str, Any]:
        """Récupère la session active Google."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM google_sessions WHERE is_active = 1 ORDER BY last_login DESC LIMIT 1")
            row = cursor.fetchone()

        if row:
            session_data = dict(row)
            # Récupérer l'ID utilisateur correspondant
            user_row = None
            with self.get_connection() as conn2:
                cur2 = conn2.cursor()
                cur2.execute("SELECT id, uuid FROM users WHERE email = ?", (session_data["email"],))
                user_row = cur2.fetchone()

            return {
                "is_authenticated": True,
                "user_id": user_row["id"] if user_row else 1,
                "uuid": user_row["uuid"] if user_row else "00000000-0000-4000-8000-000000000001",
                "email": session_data["email"],
                "name": session_data["name"],
                "picture": session_data["picture"],
                "google_sub": session_data["google_sub"],
                "auth_method": session_data["auth_method"],
                "last_login": session_data["last_login"]
            }

        return {
            "is_authenticated": False,
            "user_id": None,
            "uuid": None,
            "email": None,
            "name": None,
            "picture": None,
            "google_sub": None
        }

    def logout_google_user(self) -> Dict[str, Any]:
        """Déconnecte la session active Google."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE google_sessions SET is_active = 0")
            conn.commit()
        return {"status": "success", "message": "Session Google fermée avec succès"}

    # ---------------------------------------------------------
    # Données Démo & Initialisation
    # ---------------------------------------------------------

    def purge_demo_data(self):
        """Supprime toutes les données de démonstration résiduelles de la base (SQLite et Neon PostgreSQL)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM weights WHERE source IN ('demo', 'simulation') OR notes LIKE '%Démo%' OR notes LIKE '%Balance Démo%'")
                cursor.execute("DELETE FROM activities WHERE source IN ('demo', 'simulation')")
                cursor.execute(
                    "DELETE FROM meals WHERE total_calories_kcal IN (430.0, 685.0, 195.0, 560.0) "
                    "AND (items_json LIKE '%Flocons d%' OR items_json LIKE '%Blanc de poulet rôti%' "
                    "OR items_json LIKE '%Pavé de saumon%' OR items_json LIKE '%Myrtilles fraîches%')"
                )
                cursor.execute("DELETE FROM users WHERE email IN ('sebastien.test@vitaltrack.io', 'test_err_diag@vitaltrack.io')")
                cursor.execute("DELETE FROM user_devices WHERE name = 'RingConn Gen 3 Sébastien'")
                conn.commit()
            except Exception:
                pass

    def _seed_demo_data_if_empty(self, user_id: int = 1):
        """Pré-charge 30 jours d'historique réaliste si la table weights est vide pour cet utilisateur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM weights WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            count = row["count"] if row else 0

        if count > 0:
            return

        today = date.today()
        base_weight = 82.5
        target_loss = 2.7
        bmr = 1780.0

        for i in range(29, -1, -1):
            day = today - timedelta(days=i)
            day_progress = (29 - i) / 29.0
            fluctuation = math.sin(i * 0.7) * 0.35 + (0.1 if i % 4 == 0 else -0.1)
            weight = round(base_weight - (target_loss * day_progress) + fluctuation, 2)
            fat_pct = round(21.5 - (1.2 * day_progress) + (fluctuation * 0.2), 1)
            muscle_kg = round(38.2 - (0.3 * day_progress), 1)
            water_pct = round(56.0 + (0.5 * day_progress), 1)
            bmi = round(weight / (1.78 ** 2), 1)

            weight_entry = WeightEntry(
                date=day,
                weight_kg=weight,
                body_fat_pct=fat_pct,
                muscle_mass_kg=muscle_kg,
                water_pct=water_pct,
                bmi=bmi,
                source="simulation",
                is_simulated=True,
                notes="Pesée automatique matinale (Balance Démo)"
            )
            self.insert_weight(weight_entry, user_id=user_id)

            is_weekend = day.weekday() >= 5
            steps = 11200 if not is_weekend else 7800
            workout_min = 45 if not is_weekend and i % 2 == 0 else (60 if is_weekend and i % 3 == 0 else 0)
            workout_type = "Course à pied" if workout_min == 45 else ("Randonnée" if workout_min == 60 else None)
            active_cal = round(steps * 0.045 + (workout_min * 7.5), 1)
            resting_hr = 58 if workout_min > 0 else 61
            hrv = round(52.0 + math.cos(i) * 6, 1)
            sleep_score = int(82 + math.sin(i * 0.5) * 8)

            activity_entry = ActivityEntry(
                date=day,
                steps=steps,
                active_calories_kcal=active_cal,
                bmr_kcal=bmr,
                total_burned_kcal=round(bmr + active_cal, 1),
                workout_minutes=workout_min,
                workout_type=workout_type,
                resting_hr_bpm=resting_hr,
                hrv_ms=hrv,
                sleep_score=sleep_score,
                source="simulation",
                is_simulated=True
            )
            self.insert_activity(activity_entry, user_id=user_id)

            if i <= 6:
                self.insert_meal(MealEntry(
                    date=day,
                    meal_type="breakfast",
                    total_calories_kcal=430.0,
                    protein_g=24.0,
                    carbs_g=52.0,
                    fat_g=14.0,
                    fiber_g=7.5,
                    items=[
                        FoodItem(name="Flocons d'avoine", portion_g=60.0, calories_kcal=219.0, protein_g=8.1, carbs_g=34.8, fat_g=4.2, fiber_g=6.0, confidence_score=0.9),
                        FoodItem(name="Oeufs brouillés (x2)", portion_g=110.0, calories_kcal=157.0, protein_g=13.8, carbs_g=0.8, fat_g=10.4, fiber_g=0.0, confidence_score=0.95),
                        FoodItem(name="Myrtilles fraîches", portion_g=80.0, calories_kcal=45.0, protein_g=0.6, carbs_g=11.2, fat_g=0.3, fiber_g=2.0, confidence_score=0.85),
                    ]
                ), user_id=user_id)

                self.insert_meal(MealEntry(
                    date=day,
                    meal_type="lunch",
                    total_calories_kcal=685.0,
                    protein_g=46.0,
                    carbs_g=68.0,
                    fat_g=22.0,
                    fiber_g=8.0,
                    items=[
                        FoodItem(name="Blanc de poulet rôti", portion_g=160.0, calories_kcal=224.0, protein_g=41.6, carbs_g=0.0, fat_g=4.5, fiber_g=0.0, confidence_score=0.92),
                        FoodItem(name="Riz basmati", portion_g=200.0, calories_kcal=260.0, protein_g=5.4, carbs_g=56.0, fat_g=0.6, fiber_g=0.8, confidence_score=0.90),
                        FoodItem(name="Brocolis vapeur", portion_g=180.0, calories_kcal=63.0, protein_g=5.0, carbs_g=12.6, fat_g=0.7, fiber_g=4.7, confidence_score=0.88),
                        FoodItem(name="Filet d'huile d'olive", portion_g=15.0, calories_kcal=132.0, protein_g=0.0, carbs_g=0.0, fat_g=15.0, fiber_g=0.0, confidence_score=0.85),
                    ]
                ), user_id=user_id)

                self.insert_meal(MealEntry(
                    date=day,
                    meal_type="snack",
                    total_calories_kcal=195.0,
                    protein_g=4.0,
                    carbs_g=34.0,
                    fat_g=4.5,
                    fiber_g=4.2,
                    items=[
                        FoodItem(name="Pomme", portion_g=160.0, calories_kcal=83.0, protein_g=0.5, carbs_g=22.4, fat_g=0.3, fiber_g=3.8, confidence_score=0.95),
                        FoodItem(name="Amandes", portion_g=20.0, calories_kcal=116.0, protein_g=4.2, carbs_g=4.3, fat_g=10.0, fiber_g=2.5, confidence_score=0.90),
                    ]
                ), user_id=user_id)

                self.insert_meal(MealEntry(
                    date=day,
                    meal_type="dinner",
                    total_calories_kcal=560.0,
                    protein_g=38.0,
                    carbs_g=38.0,
                    fat_g=26.0,
                    fiber_g=9.5,
                    items=[
                        FoodItem(name="Pavé de saumon", portion_g=150.0, calories_kcal=312.0, protein_g=30.0, carbs_g=0.0, fat_g=19.5, fiber_g=0.0, confidence_score=0.94),
                        FoodItem(name="Haricots verts", portion_g=200.0, calories_kcal=62.0, protein_g=3.6, carbs_g=14.0, fat_g=0.4, fiber_g=5.4, confidence_score=0.89),
                        FoodItem(name="Demi-avocat", portion_g=70.0, calories_kcal=112.0, protein_g=1.4, carbs_g=6.0, fat_g=10.3, fiber_g=4.7, confidence_score=0.91),
                        FoodItem(name="Pain complet", portion_g=30.0, calories_kcal=75.0, protein_g=2.7, carbs_g=15.0, fat_g=0.5, fiber_g=1.8, confidence_score=0.88),
                    ]
                ), user_id=user_id)

    # ---------------------------------------------------------
    # Sauvegarde / Export / Nettoyage
    # ---------------------------------------------------------

    def export_full_backup(self, user_id: int = 1) -> Dict[str, Any]:
        """Exporte l'intégralité du profil et de l'historique de l'utilisateur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_profile WHERE user_id = ? ORDER BY id ASC LIMIT 1", (user_id,))
            prof_row = cursor.fetchone()
            profile_dict = dict(prof_row) if prof_row else self.get_user_profile(user_id=user_id)

            cursor.execute("SELECT * FROM user_devices WHERE user_id = ? ORDER BY id ASC", (user_id,))
            devices_list = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT * FROM weights WHERE user_id = ? ORDER BY date ASC", (user_id,))
            weights_list = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT * FROM activities WHERE user_id = ? ORDER BY date ASC", (user_id,))
            activities_list = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT * FROM meals WHERE user_id = ? ORDER BY date ASC, id ASC", (user_id,))
            meals_rows = cursor.fetchall()
            meals_list = []
            for r in meals_rows:
                m = dict(r)
                if m.get("items_json"):
                    try:
                        m["items"] = json.loads(m["items_json"])
                    except Exception:
                        m["items"] = []
                else:
                    m["items"] = []
                meals_list.append(m)

            cursor.execute("SELECT * FROM saved_meals WHERE user_id = ? ORDER BY id ASC", (user_id,))
            saved_meals_rows = cursor.fetchall()
            saved_meals_list = []
            for r in saved_meals_rows:
                sm = dict(r)
                if sm.get("items_json"):
                    try:
                        sm["items"] = json.loads(sm["items_json"])
                    except Exception:
                        sm["items"] = []
                else:
                    sm["items"] = []
                saved_meals_list.append(sm)

            # Palier 3 : Nouvelles tables biométriques et RGPD
            cursor.execute("SELECT * FROM daily_metrics WHERE user_id = ? ORDER BY date ASC", (user_id,))
            daily_metrics_list = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT * FROM workouts WHERE user_id = ? ORDER BY start_time ASC", (user_id,))
            workouts_list = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT * FROM sleep_sessions WHERE user_id = ? ORDER BY date ASC", (user_id,))
            sleep_sessions_list = []
            for s_row in cursor.fetchall():
                sess_dict = dict(s_row)
                cursor.execute("SELECT * FROM sleep_stages WHERE sleep_session_id = ? ORDER BY start_time ASC", (sess_dict["id"],))
                sess_dict["stages"] = [dict(st) for st in cursor.fetchall()]
                sleep_sessions_list.append(sess_dict)

            cursor.execute("SELECT * FROM hydration_logs WHERE user_id = ? ORDER BY timestamp ASC", (user_id,))
            hydration_logs_list = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT * FROM user_consents WHERE user_id = ?", (user_id,))
            consents_list = [dict(r) for r in cursor.fetchall()]

        return {
            "version": "3.0",
            "user_id": user_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "profile": profile_dict,
            "devices": devices_list,
            "weights": weights_list,
            "activities": activities_list,
            "meals": meals_list,
            "saved_meals": saved_meals_list,
            "daily_metrics": daily_metrics_list,
            "workouts": workouts_list,
            "sleep_sessions": sleep_sessions_list,
            "hydration_logs": hydration_logs_list,
            "consents": consents_list
        }

    def import_full_backup(self, data: Dict[str, Any], overwrite: bool = False, user_id: int = 1) -> Dict[str, Any]:
        """Restaure ou synchronise des données de sauvegarde JSON pour user_id."""
        imported_counts = {"weights": 0, "activities": 0, "meals": 0, "devices": 0}

        if overwrite:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM weights WHERE user_id = ?", (user_id,))
                cursor.execute("DELETE FROM activities WHERE user_id = ?", (user_id,))
                cursor.execute("DELETE FROM meals WHERE user_id = ?", (user_id,))
                cursor.execute("DELETE FROM meal_log_items WHERE meal_log_id IN (SELECT id FROM meal_logs WHERE user_id = ?)", (user_id,))
                cursor.execute("DELETE FROM meal_logs WHERE user_id = ?", (user_id,))
                conn.commit()

        # 1. Profil
        if "profile" in data and isinstance(data["profile"], dict):
            p = data["profile"]
            self.update_user_profile(p, user_id=user_id)

        # 2. Appareils
        for dev in data.get("devices", []):
            dev_id = dev.get("device_id")
            if not dev_id:
                continue
            self.update_user_device(
                device_id=dev_id,
                name=dev.get("name", dev_id),
                device_type=dev.get("device_type", "unknown"),
                connected=bool(dev.get("connected")),
                auth_type=dev.get("auth_type", "demo"),
                api_key=dev.get("api_key"),
                account_email=dev.get("account_email"),
                user_id=user_id
            )
            imported_counts["devices"] += 1

        # 3. Pesées
        for w in data.get("weights", []):
            d_str = w.get("date")
            if not d_str:
                continue
            entry = WeightEntry(
                date=date.fromisoformat(d_str[:10]),
                weight_kg=float(w["weight_kg"]),
                body_fat_pct=float(w["body_fat_pct"]) if w.get("body_fat_pct") is not None else None,
                muscle_mass_kg=float(w["muscle_mass_kg"]) if w.get("muscle_mass_kg") is not None else None,
                water_pct=float(w["water_pct"]) if w.get("water_pct") is not None else None,
                bmi=float(w["bmi"]) if w.get("bmi") is not None else None,
                trend_7d_kg=float(w["trend_7d_kg"]) if w.get("trend_7d_kg") is not None else None,
                source=w.get("source", "manual"),
                notes=w.get("notes")
            )
            self.insert_weight(entry, user_id=user_id)
            imported_counts["weights"] += 1

        # 4. Activités
        for a in data.get("activities", []):
            d_str = a.get("date")
            if not d_str:
                continue
            act = ActivityEntry(
                date=date.fromisoformat(d_str[:10]),
                steps=int(a.get("steps", 0)),
                active_calories_kcal=float(a.get("active_calories_kcal", 0.0)),
                bmr_kcal=float(a.get("bmr_kcal", 0.0)),
                total_burned_kcal=float(a.get("total_burned_kcal", 0.0)),
                workout_minutes=int(a.get("workout_minutes", 0)),
                workout_type=a.get("workout_type"),
                resting_hr_bpm=int(a["resting_hr_bpm"]) if a.get("resting_hr_bpm") is not None else None,
                hrv_ms=float(a["hrv_ms"]) if a.get("hrv_ms") is not None else None,
                sleep_score=int(a["sleep_score"]) if a.get("sleep_score") is not None else None,
                source=a.get("source", "health_connect")
            )
            self.insert_activity(act, user_id=user_id)
            imported_counts["activities"] += 1

        # 5. Repas
        for m in data.get("meals", []):
            d_str = m.get("date")
            if not d_str:
                continue
            raw_items = m.get("items", [])
            items = [FoodItem(**it) for it in raw_items]
            meal = MealEntry(
                date=date.fromisoformat(d_str[:10]),
                meal_type=m.get("meal_type", "lunch"),
                total_calories_kcal=float(m.get("total_calories_kcal", 0.0)),
                protein_g=float(m.get("protein_g", 0.0)),
                carbs_g=float(m.get("carbs_g", 0.0)),
                fat_g=float(m.get("fat_g", 0.0)),
                fiber_g=float(m["fiber_g"]) if m.get("fiber_g") is not None else None,
                photo_data_url=m.get("photo_data_url"),
                items=items
            )
            self.insert_meal(meal, user_id=user_id)
            imported_counts["meals"] += 1

        return {
            "status": "success",
            "imported": imported_counts,
            "message": f"Restauration terminée : {imported_counts['weights']} pesées, {imported_counts['activities']} activités, {imported_counts['meals']} repas."
        }

    def clear_all_history(self, keep_profile: bool = True, user_id: int = 1):
        """Efface l'historique pour un utilisateur spécifique."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM weights WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM activities WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM meals WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM meal_log_items WHERE meal_log_id IN (SELECT id FROM meal_logs WHERE user_id = ?)", (user_id,))
            cursor.execute("DELETE FROM meal_logs WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM daily_metrics WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM workouts WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM sleep_stages WHERE sleep_session_id IN (SELECT id FROM sleep_sessions WHERE user_id = ?)", (user_id,))
            cursor.execute("DELETE FROM sleep_sessions WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM intraday_samples WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM hydration_logs WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM raw_ingest WHERE user_id = ?", (user_id,))
            if not keep_profile:
                cursor.execute("DELETE FROM user_consents WHERE user_id = ?", (user_id,))
                cursor.execute("DELETE FROM food_items WHERE user_id = ?", (user_id,))
                cursor.execute("DELETE FROM saved_meals WHERE user_id = ?", (user_id,))
                cursor.execute("DELETE FROM user_profile WHERE user_id = ?", (user_id,))
                cursor.execute("DELETE FROM user_devices WHERE user_id = ?", (user_id,))
            conn.commit()

    def reset_demo_data(self, user_id: int = 1):
        """Réinitialise et recharge le jeu complet de démonstration sur 30 jours pour user_id."""
        self.clear_all_history(keep_profile=True, user_id=user_id)
        self._seed_demo_data_if_empty(user_id=user_id)

    # ---------------------------------------------------------
    # Palier 3 : Moteur d'Ingestion Enrichi & Biométrie Haute Fréquence
    # ---------------------------------------------------------

    def insert_daily_metric(self, metric: DailyMetricsEntry, user_id: int = 1) -> DailyMetricsEntry:
        """Insère ou met à jour une métrique quotidienne multi-sources de façon idempotente."""
        now_str = datetime.now(timezone.utc).isoformat()
        date_str = metric.date.isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO daily_metrics (
                        user_id, date, source, steps, active_calories_kcal, total_calories_kcal,
                        resting_hr_bpm, hrv_rmssd_ms, hrv_sdnn_ms, spo2_pct, skin_temperature_c,
                        sleep_score, recovery_score, external_id, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date, source) DO UPDATE SET
                        steps = EXCLUDED.steps,
                        active_calories_kcal = EXCLUDED.active_calories_kcal,
                        total_calories_kcal = EXCLUDED.total_calories_kcal,
                        resting_hr_bpm = COALESCE(EXCLUDED.resting_hr_bpm, daily_metrics.resting_hr_bpm),
                        hrv_rmssd_ms = COALESCE(EXCLUDED.hrv_rmssd_ms, daily_metrics.hrv_rmssd_ms),
                        hrv_sdnn_ms = COALESCE(EXCLUDED.hrv_sdnn_ms, daily_metrics.hrv_sdnn_ms),
                        spo2_pct = COALESCE(EXCLUDED.spo2_pct, daily_metrics.spo2_pct),
                        skin_temperature_c = COALESCE(EXCLUDED.skin_temperature_c, daily_metrics.skin_temperature_c),
                        sleep_score = COALESCE(EXCLUDED.sleep_score, daily_metrics.sleep_score),
                        recovery_score = COALESCE(EXCLUDED.recovery_score, daily_metrics.recovery_score),
                        external_id = COALESCE(EXCLUDED.external_id, daily_metrics.external_id),
                        updated_at = EXCLUDED.updated_at
                    RETURNING id;
                """, (
                    user_id, date_str, metric.source, metric.steps, metric.active_calories_kcal,
                    metric.total_calories_kcal, metric.resting_hr_bpm, metric.hrv_rmssd_ms,
                    metric.hrv_sdnn_ms, metric.spo2_pct, metric.skin_temperature_c,
                    metric.sleep_score, metric.recovery_score, metric.external_id, now_str, now_str
                ))
                res = cursor.fetchone()
                m_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO daily_metrics (
                        user_id, date, source, steps, active_calories_kcal, total_calories_kcal,
                        resting_hr_bpm, hrv_rmssd_ms, hrv_sdnn_ms, spo2_pct, skin_temperature_c,
                        sleep_score, recovery_score, external_id, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date, source) DO UPDATE SET
                        steps = excluded.steps,
                        active_calories_kcal = excluded.active_calories_kcal,
                        total_calories_kcal = excluded.total_calories_kcal,
                        resting_hr_bpm = COALESCE(excluded.resting_hr_bpm, daily_metrics.resting_hr_bpm),
                        hrv_rmssd_ms = COALESCE(excluded.hrv_rmssd_ms, daily_metrics.hrv_rmssd_ms),
                        hrv_sdnn_ms = COALESCE(excluded.hrv_sdnn_ms, daily_metrics.hrv_sdnn_ms),
                        spo2_pct = COALESCE(excluded.spo2_pct, daily_metrics.spo2_pct),
                        skin_temperature_c = COALESCE(excluded.skin_temperature_c, daily_metrics.skin_temperature_c),
                        sleep_score = COALESCE(excluded.sleep_score, daily_metrics.sleep_score),
                        recovery_score = COALESCE(excluded.recovery_score, daily_metrics.recovery_score),
                        external_id = COALESCE(excluded.external_id, daily_metrics.external_id),
                        updated_at = excluded.updated_at
                """, (
                    user_id, date_str, metric.source, metric.steps, metric.active_calories_kcal,
                    metric.total_calories_kcal, metric.resting_hr_bpm, metric.hrv_rmssd_ms,
                    metric.hrv_sdnn_ms, metric.spo2_pct, metric.skin_temperature_c,
                    metric.sleep_score, metric.recovery_score, metric.external_id, now_str, now_str
                ))
                m_id = cursor.lastrowid
            conn.commit()

        d = metric.model_dump()
        d["id"] = m_id
        d["user_id"] = user_id
        d["created_at"] = datetime.fromisoformat(now_str)
        d["updated_at"] = datetime.fromisoformat(now_str)
        return DailyMetricsEntry(**d)

    def get_daily_metrics(self, limit: int = 30, source: Optional[str] = None, user_id: int = 1) -> List[DailyMetricsEntry]:
        """Récupère l'historique des métriques journalières pour user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if source:
                cursor.execute("""
                    SELECT * FROM (
                        SELECT * FROM daily_metrics WHERE user_id = ? AND source = ? ORDER BY date DESC LIMIT ?
                    ) sub ORDER BY date ASC
                """, (user_id, source, limit))
            else:
                cursor.execute("""
                    SELECT * FROM (
                        SELECT * FROM daily_metrics WHERE user_id = ? ORDER BY date DESC LIMIT ?
                    ) sub ORDER BY date ASC
                """, (user_id, limit))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            d = dict(r)
            d["date"] = date.fromisoformat(d["date"][:10])
            if d.get("created_at"):
                d["created_at"] = datetime.fromisoformat(d["created_at"])
            if d.get("updated_at"):
                d["updated_at"] = datetime.fromisoformat(d["updated_at"])
            results.append(DailyMetricsEntry(**d))
        return results

    def insert_workout(self, workout: WorkoutEntry, user_id: int = 1) -> WorkoutEntry:
        """Insère ou déduplique une séance d'entraînement de façon idempotente."""
        if workout.external_id:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM workouts WHERE user_id = ? AND source = ? AND external_id = ? LIMIT 1",
                    (user_id, workout.source, workout.external_id)
                )
                existing = cursor.fetchone()
                if existing:
                    d = dict(existing)
                    if d.get("created_at"):
                        d["created_at"] = datetime.fromisoformat(d["created_at"])
                    if d.get("updated_at"):
                        d["updated_at"] = datetime.fromisoformat(d["updated_at"])
                    return WorkoutEntry(**d)

        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO workouts (
                        user_id, source, external_id, workout_type, start_time, end_time,
                        duration_minutes, calories_kcal, avg_hr_bpm, max_hr_bpm, distance_meters,
                        notes, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id;
                """, (
                    user_id, workout.source, workout.external_id, workout.workout_type,
                    workout.start_time, workout.end_time, workout.duration_minutes,
                    workout.calories_kcal, workout.avg_hr_bpm, workout.max_hr_bpm,
                    workout.distance_meters, workout.notes, now_str, now_str
                ))
                res = cursor.fetchone()
                w_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO workouts (
                        user_id, source, external_id, workout_type, start_time, end_time,
                        duration_minutes, calories_kcal, avg_hr_bpm, max_hr_bpm, distance_meters,
                        notes, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, workout.source, workout.external_id, workout.workout_type,
                    workout.start_time, workout.end_time, workout.duration_minutes,
                    workout.calories_kcal, workout.avg_hr_bpm, workout.max_hr_bpm,
                    workout.distance_meters, workout.notes, now_str, now_str
                ))
                w_id = cursor.lastrowid
            conn.commit()

        d = workout.model_dump()
        d["id"] = w_id
        d["user_id"] = user_id
        d["created_at"] = datetime.fromisoformat(now_str)
        d["updated_at"] = datetime.fromisoformat(now_str)
        return WorkoutEntry(**d)

    def get_workouts(self, limit: int = 30, user_id: int = 1) -> List[WorkoutEntry]:
        """Récupère la liste des séances d'entraînement."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM (
                    SELECT * FROM workouts WHERE user_id = ? ORDER BY start_time DESC LIMIT ?
                ) sub ORDER BY start_time ASC
            """, (user_id, limit))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            d = dict(r)
            if d.get("created_at"):
                d["created_at"] = datetime.fromisoformat(d["created_at"])
            if d.get("updated_at"):
                d["updated_at"] = datetime.fromisoformat(d["updated_at"])
            results.append(WorkoutEntry(**d))
        return results

    def insert_sleep_session(self, session: SleepSessionEntry, user_id: int = 1) -> SleepSessionEntry:
        """Enregistre une session de sommeil complète et ses phases associées de façon idempotente."""
        if session.external_id:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM sleep_sessions WHERE user_id = ? AND source = ? AND external_id = ? LIMIT 1",
                    (user_id, session.source, session.external_id)
                )
                existing = cursor.fetchone()
                if existing:
                    return self.get_sleep_session_by_id(existing["id"], user_id=user_id) or session

        now_str = datetime.now(timezone.utc).isoformat()
        date_str = session.date.isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO sleep_sessions (
                        user_id, source, external_id, date, start_time, end_time,
                        duration_minutes, efficiency_pct, sleep_debt_minutes, sleep_score,
                        deep_minutes, light_minutes, rem_minutes, awake_minutes,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id;
                """, (
                    user_id, session.source, session.external_id, date_str,
                    session.start_time, session.end_time, session.duration_minutes,
                    session.efficiency_pct, session.sleep_debt_minutes, session.sleep_score,
                    session.deep_minutes or 0, session.light_minutes or 0,
                    session.rem_minutes or 0, session.awake_minutes or 0,
                    now_str, now_str
                ))
                res = cursor.fetchone()
                s_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO sleep_sessions (
                        user_id, source, external_id, date, start_time, end_time,
                        duration_minutes, efficiency_pct, sleep_debt_minutes, sleep_score,
                        deep_minutes, light_minutes, rem_minutes, awake_minutes,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, session.source, session.external_id, date_str,
                    session.start_time, session.end_time, session.duration_minutes,
                    session.efficiency_pct, session.sleep_debt_minutes, session.sleep_score,
                    session.deep_minutes or 0, session.light_minutes or 0,
                    session.rem_minutes or 0, session.awake_minutes or 0,
                    now_str, now_str
                ))
                s_id = cursor.lastrowid

            # Insérer les phases de sommeil
            saved_stages = []
            for st in session.stages:
                cursor.execute("""
                    INSERT INTO sleep_stages (sleep_session_id, stage, start_time, end_time, duration_seconds)
                    VALUES (?, ?, ?, ?, ?)
                """, (s_id, st.stage, st.start_time, st.end_time, st.duration_seconds))
                saved_stages.append(st)

            conn.commit()

        d = session.model_dump()
        d["id"] = s_id
        d["user_id"] = user_id
        d["stages"] = saved_stages
        d["created_at"] = datetime.fromisoformat(now_str)
        d["updated_at"] = datetime.fromisoformat(now_str)
        return SleepSessionEntry(**d)

    def get_sleep_session_by_id(self, session_id: int, user_id: int = 1) -> Optional[SleepSessionEntry]:
        """Récupère une session de sommeil avec toutes ses phases."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sleep_sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
            row = cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            d["date"] = date.fromisoformat(d["date"][:10])
            cursor.execute("SELECT * FROM sleep_stages WHERE sleep_session_id = ? ORDER BY start_time ASC", (session_id,))
            stages_rows = cursor.fetchall()
            d["stages"] = [SleepStageEntry(**dict(st)) for st in stages_rows]
            if d.get("created_at"):
                d["created_at"] = datetime.fromisoformat(d["created_at"])
            if d.get("updated_at"):
                d["updated_at"] = datetime.fromisoformat(d["updated_at"])
            return SleepSessionEntry(**d)

    def insert_intraday_samples(self, samples: List[IntradaySampleEntry], user_id: int = 1) -> int:
        """Insère un lot d'échantillons haute fréquence (FC, pas horaires, SpO2)."""
        if not samples:
            return 0
        now_str = datetime.now(timezone.utc).isoformat()
        count = 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for s in samples:
                cursor.execute("""
                    INSERT INTO intraday_samples (user_id, source, metric_type, timestamp, value, unit, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, s.source, s.metric_type, s.timestamp, s.value, s.unit, now_str))
                count += 1
            conn.commit()
        return count

    def get_intraday_samples(
        self,
        metric_type: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 500,
        user_id: int = 1
    ) -> List[IntradaySampleEntry]:
        """Récupère les échantillons haute fréquence pour une métrique donnée."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM intraday_samples WHERE user_id = ? AND metric_type = ?"
            params: List[Any] = [user_id, metric_type]
            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time)
            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time)
            query += " ORDER BY timestamp ASC LIMIT ?"
            params.append(limit)
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            d = dict(r)
            if d.get("created_at"):
                d["created_at"] = datetime.fromisoformat(d["created_at"])
            results.append(IntradaySampleEntry(**d))
        return results

    def purge_and_aggregate_intraday(self, retention_days: int = 60, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Politique de rétention configurable (30 à 90 jours) : agrège puis purge les anciens échantillons intraday."""
        days = max(30, min(90, int(retention_days)))
        cutoff_date = (date.today() - timedelta(days=days)).isoformat()
        cutoff_iso = f"{cutoff_date}T00:00:00"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Supprimer les anciens échantillons au-delà du seuil de rétention
            if user_id:
                cursor.execute(
                    "DELETE FROM intraday_samples WHERE user_id = ? AND timestamp < ?",
                    (user_id, cutoff_iso)
                )
            else:
                cursor.execute("DELETE FROM intraday_samples WHERE timestamp < ?", (cutoff_iso,))
            deleted = cursor.rowcount if hasattr(cursor, "rowcount") else 0
            conn.commit()

        return {
            "status": "success",
            "retention_days": days,
            "cutoff_timestamp": cutoff_iso,
            "purged_samples": deleted
        }

    def insert_hydration_log(self, entry: HydrationLogEntry, user_id: int = 1) -> HydrationLogEntry:
        """Enregistre un apport hydrique."""
        if entry.external_id:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM hydration_logs WHERE user_id = ? AND source = ? AND external_id = ? LIMIT 1",
                    (user_id, entry.source, entry.external_id)
                )
                existing = cursor.fetchone()
                if existing:
                    d = dict(existing)
                    d["date"] = date.fromisoformat(d["date"][:10])
                    if d.get("created_at"):
                        d["created_at"] = datetime.fromisoformat(d["created_at"])
                    return HydrationLogEntry(**d)

        now_str = datetime.now(timezone.utc).isoformat()
        date_str = entry.date.isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO hydration_logs (user_id, date, timestamp, volume_ml, source, external_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    RETURNING id;
                """, (user_id, date_str, entry.timestamp, entry.volume_ml, entry.source, entry.external_id, now_str))
                res = cursor.fetchone()
                h_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO hydration_logs (user_id, date, timestamp, volume_ml, source, external_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, date_str, entry.timestamp, entry.volume_ml, entry.source, entry.external_id, now_str))
                h_id = cursor.lastrowid
            conn.commit()

        d = entry.model_dump()
        d["id"] = h_id
        d["user_id"] = user_id
        d["created_at"] = datetime.fromisoformat(now_str)
        return HydrationLogEntry(**d)

    def insert_raw_ingest(
        self,
        source: str,
        payload: Union[Dict[str, Any], str],
        user_id: int = 1,
        endpoint: Optional[str] = None,
        idempotency_key: Optional[str] = None
    ) -> RawIngestEntry:
        """Stocke le payload JSON brut horodaté pour audit et rejeu."""
        payload_str = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)
        now_str = datetime.now(timezone.utc).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO raw_ingest (user_id, source, endpoint, idempotency_key, payload_json, status, received_at)
                    VALUES (?, ?, ?, ?, ?, 'received', ?)
                    RETURNING id;
                """, (user_id, source, endpoint, idempotency_key, payload_str, now_str))
                res = cursor.fetchone()
                r_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO raw_ingest (user_id, source, endpoint, idempotency_key, payload_json, status, received_at)
                    VALUES (?, ?, ?, ?, ?, 'received', ?)
                """, (user_id, source, endpoint, idempotency_key, payload_str, now_str))
                r_id = cursor.lastrowid
            conn.commit()

        return RawIngestEntry(
            id=r_id,
            user_id=user_id,
            source=source,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
            payload_json=payload_str,
            status="received",
            received_at=now_str
        )

    def set_user_consent(self, category: str, consented: bool, user_id: int = 1) -> UserConsentItem:
        """Enregistre le consentement de l'utilisateur pour une catégorie RGPD (biometrics, nutrition, analytics, devices)."""
        now_str = datetime.now(timezone.utc).isoformat()
        val = 1 if consented else 0

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO user_consents (user_id, category, consented, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, category) DO UPDATE SET
                        consented = EXCLUDED.consented,
                        updated_at = EXCLUDED.updated_at;
                """, (user_id, category, val, now_str))
            else:
                cursor.execute("""
                    INSERT INTO user_consents (user_id, category, consented, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, category) DO UPDATE SET
                        consented = excluded.consented,
                        updated_at = excluded.updated_at;
                """, (user_id, category, val, now_str))
            conn.commit()

        return UserConsentItem(category=category, consented=consented, updated_at=now_str)

    def get_user_consents(self, user_id: int = 1) -> Dict[str, bool]:
        """Récupère l'ensemble des consentements RGPD pour l'utilisateur."""
        categories = ["biometrics", "nutrition", "analytics", "devices"]
        consents = {cat: True for cat in categories}  # Consentement activé par défaut à l'inscription

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT category, consented FROM user_consents WHERE user_id = ?", (user_id,))
            for r in cursor.fetchall():
                consents[r["category"]] = bool(r["consented"])
        return consents

    def delete_user_account_and_data(self, user_id: int) -> bool:
        """Supprime définitivement un compte utilisateur et l'intégralité de ses données (Droit à l'oubli RGPD)."""
        # Ne pas permettre la suppression orpheline si le compte n'existe pas
        user = self.get_user_by_id(user_id)
        if not user:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Nettoyage en cascade des tables dépendantes
            cursor.execute("DELETE FROM weights WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM activities WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM meals WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM meal_log_items WHERE meal_log_id IN (SELECT id FROM meal_logs WHERE user_id = ?)", (user_id,))
            cursor.execute("DELETE FROM meal_logs WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM daily_metrics WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM workouts WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM sleep_stages WHERE sleep_session_id IN (SELECT id FROM sleep_sessions WHERE user_id = ?)", (user_id,))
            cursor.execute("DELETE FROM sleep_sessions WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM intraday_samples WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM hydration_logs WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM raw_ingest WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM user_consents WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM user_devices WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM user_profile WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM food_items WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM saved_meals WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        return True
