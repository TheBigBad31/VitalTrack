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
    MealLog, MealLogItem, NutritionBenefitItem, SavedMeal, WeightEntry
)
from src.repositories.users_repo import UsersRepository
from src.repositories.weights_repo import WeightsRepository
from src.repositories.meals_repo import MealsRepository
from src.repositories.devices_repo import DevicesRepository
from src.crypto import encrypt_data, decrypt_data, encrypt_credentials, decrypt_credentials

# Essai d'import de psycopg pour le support Neon PostgreSQL
try:
    import psycopg
    from psycopg.rows import dict_row
    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False


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

    def __init__(self, raw_conn: Any, is_postgres: bool):
        self.conn = raw_conn
        self.is_postgres = is_postgres

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
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


class Database:
    """Gestionnaire de persistance hybride (PostgreSQL Serverless Neon & SQLite Fallback)."""


    def __init__(self, db_path: Optional[str] = None, database_url: Optional[str] = None):
        self.database_url = database_url or get_database_url()
        self.is_postgres = bool(self.database_url and HAS_PSYCOPG)
        self.db_path = db_path or get_db_path()
        # Repositories (la façade Database délègue à ces classes)
        self.users = UsersRepository(self)
        self.weights = WeightsRepository(self)
        self.meals = MealsRepository(self)
        self.devices = DevicesRepository(self)
        self._init_db()


    def get_connection(self) -> DatabaseConnectionWrapper:
        """Fournit une connexion unifiée (PostgreSQL ou SQLite)."""
        if self.is_postgres:
            try:
                conn = psycopg.connect(self.database_url, connect_timeout=10)
                return DatabaseConnectionWrapper(conn, is_postgres=True)
            except Exception as e:
                # Si la connexion Neon échoue, fallback d'urgence sur SQLite
                print(f"[VitalTrack DB Warning] Échec connexion PostgreSQL Neon: {e}. Bascule sur SQLite.")
                self.is_postgres = False

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass
        return DatabaseConnectionWrapper(conn, is_postgres=False)


    def _init_db(self):
        """Initialise le schéma multi-utilisateurs et effectue les migrations idempotentes."""
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
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_meals_user_date ON meals(user_id, date DESC, id DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_saved_meals_user_type ON saved_meals(user_id, meal_type);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_items_user ON food_items(user_id, item_type);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_meal_logs_user_date ON meal_logs(user_id, date);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_meal_log_items_meal ON meal_log_items(meal_log_id);")

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
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_meals_user_date ON meals(user_id, date DESC, id DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_saved_meals_user_type ON saved_meals(user_id, meal_type);")

            conn.commit()

        # Garantir l'existence de l'utilisateur par défaut
        self._ensure_default_user()
        # Seeder le référentiel expert des bienfaits nutritionnels
        self._seed_nutrition_benefits()
        # Purger toute donnée de démonstration résiduelle
        self.purge_demo_data()


    # ---------------------------------------------------------
    # Données Démo & Initialisation
    # ---------------------------------------------------------

    def purge_demo_data(self):
        """Supprime toutes les données de démonstration résiduelles de la base (SQLite et Neon PostgreSQL)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM weights WHERE source = 'demo' OR notes LIKE '%Démo%' OR notes LIKE '%Balance Démo%'")
                cursor.execute("DELETE FROM activities WHERE source = 'demo'")
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


    def _seed_demo_data_if_empty(self, user_id: int):
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
                source="demo",
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
                source="demo"
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

    def export_full_backup(self, user_id: int) -> Dict[str, Any]:
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

        return {
            "version": "2.0",
            "user_id": user_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "profile": profile_dict,
            "devices": devices_list,
            "weights": weights_list,
            "activities": activities_list,
            "meals": meals_list,
            "saved_meals": saved_meals_list
        }


    def import_full_backup(self, data: Dict[str, Any], overwrite: bool = False, *, user_id: int) -> Dict[str, Any]:
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


    def clear_all_history(self, keep_profile: bool = True, *, user_id: int):
        """Efface l'historique pour un utilisateur spécifique."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM weights WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM activities WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM meals WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM meal_log_items WHERE meal_log_id IN (SELECT id FROM meal_logs WHERE user_id = ?)", (user_id,))
            cursor.execute("DELETE FROM meal_logs WHERE user_id = ?", (user_id,))
            if not keep_profile:
                cursor.execute("DELETE FROM food_items WHERE user_id = ?", (user_id,))
                cursor.execute("DELETE FROM saved_meals WHERE user_id = ?", (user_id,))
                cursor.execute("DELETE FROM user_profile WHERE user_id = ?", (user_id,))
                cursor.execute("DELETE FROM user_devices WHERE user_id = ?", (user_id,))
            conn.commit()


    def reset_demo_data(self, user_id: int):
        """Réinitialise et recharge le jeu complet de démonstration sur 30 jours pour user_id."""
        self.clear_all_history(keep_profile=True, user_id=user_id)
        self._seed_demo_data_if_empty(user_id=user_id)

    # =====================================================================
    # Délégation vers les repositories (compatibilité de l'API historique)
    # =====================================================================

    def _ensure_default_user(self) -> Dict[str, Any]:
        return self.users._ensure_default_user()

    def get_or_create_user(self, email: str, name: Optional[str]=None, picture: Optional[str]=None, auth_provider: str='google', google_sub: Optional[str]=None, password_hash: Optional[str]=None) -> Dict[str, Any]:
        return self.users.get_or_create_user(email=email, name=name, picture=picture, auth_provider=auth_provider, google_sub=google_sub, password_hash=password_hash)

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self.users.get_user_by_id(user_id=user_id)

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return self.users.get_user_by_email(email=email)

    def calculate_7d_trend(self, target_date: date, new_weight_kg: float, user_id: int) -> float:
        return self.weights.calculate_7d_trend(target_date=target_date, new_weight_kg=new_weight_kg, user_id=user_id)

    def insert_weight(self, entry: WeightEntry, user_id: int) -> WeightEntry:
        return self.weights.insert_weight(entry=entry, user_id=user_id)

    def get_weights(self, limit: int=30, *, user_id: int) -> List[WeightEntry]:
        return self.weights.get_weights(limit=limit, user_id=user_id)

    def get_weight_by_id(self, weight_id: int, user_id: int) -> Optional[WeightEntry]:
        return self.weights.get_weight_by_id(weight_id=weight_id, user_id=user_id)

    def update_weight(self, weight_id: int, entry: WeightEntry, user_id: int) -> Optional[WeightEntry]:
        return self.weights.update_weight(weight_id=weight_id, entry=entry, user_id=user_id)

    def delete_weight(self, weight_id: int, user_id: int) -> bool:
        return self.weights.delete_weight(weight_id=weight_id, user_id=user_id)

    def insert_activity(self, entry: ActivityEntry, user_id: int) -> ActivityEntry:
        return self.weights.insert_activity(entry=entry, user_id=user_id)

    def get_activities(self, limit: int=30, *, user_id: int) -> List[ActivityEntry]:
        return self.weights.get_activities(limit=limit, user_id=user_id)

    def insert_meal(self, entry: MealEntry, user_id: int) -> MealEntry:
        return self.meals.insert_meal(entry=entry, user_id=user_id)

    def get_meals_for_date(self, target_date: date, user_id: int) -> List[MealEntry]:
        return self.meals.get_meals_for_date(target_date=target_date, user_id=user_id)

    def get_meals(self, limit: int=50, *, user_id: int) -> List[MealEntry]:
        return self.meals.get_meals(limit=limit, user_id=user_id)

    def get_meal_by_id(self, meal_id: int, user_id: int) -> Optional[MealEntry]:
        return self.meals.get_meal_by_id(meal_id=meal_id, user_id=user_id)

    def update_meal(self, meal_id: int, entry: MealEntry, user_id: int) -> Optional[MealEntry]:
        return self.meals.update_meal(meal_id=meal_id, entry=entry, user_id=user_id)

    def delete_meal(self, meal_id: int, user_id: int) -> bool:
        return self.meals.delete_meal(meal_id=meal_id, user_id=user_id)

    def insert_saved_meal(self, saved_meal: SavedMeal, user_id: int) -> SavedMeal:
        return self.meals.insert_saved_meal(saved_meal=saved_meal, user_id=user_id)

    def get_saved_meals(self, meal_type: Optional[str]=None, is_favorite: Optional[bool]=None, *, user_id: int) -> List[SavedMeal]:
        return self.meals.get_saved_meals(meal_type=meal_type, is_favorite=is_favorite, user_id=user_id)

    def get_saved_meal_by_id(self, meal_id: int, user_id: int) -> Optional[SavedMeal]:
        return self.meals.get_saved_meal_by_id(meal_id=meal_id, user_id=user_id)

    def update_saved_meal(self, meal_id: int, saved_meal: SavedMeal, user_id: int) -> Optional[SavedMeal]:
        return self.meals.update_saved_meal(meal_id=meal_id, saved_meal=saved_meal, user_id=user_id)

    def delete_saved_meal(self, meal_id: int, user_id: int) -> bool:
        return self.meals.delete_saved_meal(meal_id=meal_id, user_id=user_id)

    def insert_food_item(self, item: CatalogItem, user_id: int) -> CatalogItem:
        return self.meals.insert_food_item(item=item, user_id=user_id)

    def get_food_items(self, item_type: Optional[str]=None, query: Optional[str]=None, *, user_id: int) -> List[CatalogItem]:
        return self.meals.get_food_items(item_type=item_type, query=query, user_id=user_id)

    def get_food_item_by_id(self, item_id: int, user_id: int) -> Optional[CatalogItem]:
        return self.meals.get_food_item_by_id(item_id=item_id, user_id=user_id)

    def update_food_item(self, item_id: int, data: Dict[str, Any], user_id: int) -> Optional[CatalogItem]:
        return self.meals.update_food_item(item_id=item_id, data=data, user_id=user_id)

    def delete_food_item(self, item_id: int, user_id: int) -> bool:
        return self.meals.delete_food_item(item_id=item_id, user_id=user_id)

    def _seed_nutrition_benefits(self):
        return self.meals._seed_nutrition_benefits()

    def get_all_nutrition_benefits(self) -> List[NutritionBenefitItem]:
        return self.meals.get_all_nutrition_benefits()

    def get_food_item_benefits(self, food_item_id: int) -> List[AssociatedBenefit]:
        return self.meals.get_food_item_benefits(food_item_id=food_item_id)

    def set_food_item_benefits(self, food_item_id: int, benefits_data: List[Dict[str, Any]]) -> List[AssociatedBenefit]:
        return self.meals.set_food_item_benefits(food_item_id=food_item_id, benefits_data=benefits_data)

    def get_or_create_meal_log(self, date_val: date, meal_type: str, user_id: int) -> MealLog:
        return self.meals.get_or_create_meal_log(date_val=date_val, meal_type=meal_type, user_id=user_id)

    def _build_meal_log(self, row: Dict[str, Any], user_id: int) -> MealLog:
        return self.meals._build_meal_log(row=row, user_id=user_id)

    def get_meal_logs_for_date(self, target_date: date, user_id: int) -> List[MealLog]:
        return self.meals.get_meal_logs_for_date(target_date=target_date, user_id=user_id)

    def add_item_to_meal_log(self, date_val: date, meal_type: str, name: str, quantity: float, unit: str, calories: float, protein_g: float=0.0, carbs_g: float=0.0, fat_g: float=0.0, fiber_g: float=0.0, food_item_id: Optional[int]=None, *, user_id: int) -> MealLog:
        return self.meals.add_item_to_meal_log(date_val=date_val, meal_type=meal_type, name=name, quantity=quantity, unit=unit, calories=calories, protein_g=protein_g, carbs_g=carbs_g, fat_g=fat_g, fiber_g=fiber_g, food_item_id=food_item_id, user_id=user_id)

    def delete_meal_log_item(self, item_id: int, user_id: int) -> Optional[MealLog]:
        return self.meals.delete_meal_log_item(item_id=item_id, user_id=user_id)

    def _recalculate_meal_log_totals(self, meal_log_id: int, user_id: int):
        return self.meals._recalculate_meal_log_totals(meal_log_id=meal_log_id, user_id=user_id)

    def _sync_meal_log_to_meals(self, meal_log_id: int, user_id: int):
        return self.meals._sync_meal_log_to_meals(meal_log_id=meal_log_id, user_id=user_id)

    def sync_all_meal_logs_to_meals(self, user_id: Optional[int]=None):
        return self.meals.sync_all_meal_logs_to_meals(user_id=user_id)

    def _get_meal_log_by_id(self, meal_log_id: int, user_id: int) -> MealLog:
        return self.meals._get_meal_log_by_id(meal_log_id=meal_log_id, user_id=user_id)

    def get_user_profile(self, user_id: int) -> Dict[str, Any]:
        return self.users.get_user_profile(user_id=user_id)

    def update_user_profile(self, data: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        return self.users.update_user_profile(data=data, user_id=user_id)

    def _format_device_row(self, row: Optional[Dict[str, Any]], reveal_secrets: bool=False) -> Optional[Dict[str, Any]]:
        return self.devices._format_device_row(row=row, reveal_secrets=reveal_secrets)

    def get_user_devices(self, user_id: int, reveal_secrets: bool=False) -> List[Dict[str, Any]]:
        return self.devices.get_user_devices(user_id=user_id, reveal_secrets=reveal_secrets)

    def get_user_device(self, device_id: str, user_id: int, reveal_secrets: bool=False) -> Optional[Dict[str, Any]]:
        return self.devices.get_user_device(device_id=device_id, user_id=user_id, reveal_secrets=reveal_secrets)

    def delete_user_device(self, device_id: str, user_id: int) -> bool:
        return self.devices.delete_user_device(device_id=device_id, user_id=user_id)

    def update_device_sync_status(self, device_id: str, sync_status: str, user_id: int) -> Optional[Dict[str, Any]]:
        return self.devices.update_device_sync_status(device_id=device_id, sync_status=sync_status, user_id=user_id)

    def update_user_device(self, device_id: str, name: str, device_type: str, connected: bool, auth_type: str='connected', api_key: Optional[str]=None, credentials: Optional[Dict[str, Any]]=None, account_email: Optional[str]=None, is_active: bool=True, sync_status: Optional[str]=None, *, user_id: int) -> Dict[str, Any]:
        return self.devices.update_user_device(device_id=device_id, name=name, device_type=device_type, connected=connected, auth_type=auth_type, api_key=api_key, credentials=credentials, account_email=account_email, is_active=is_active, sync_status=sync_status, user_id=user_id)

    def get_google_config(self) -> Dict[str, Any]:
        return self.users.get_google_config()

    def set_google_client_id(self, client_id: str) -> Dict[str, Any]:
        return self.users.set_google_client_id(client_id=client_id)

    def login_google_user(self, email: str, name: str, picture: str='', google_sub: str='', auth_method: str='google') -> Dict[str, Any]:
        return self.users.login_google_user(email=email, name=name, picture=picture, google_sub=google_sub, auth_method=auth_method)

    def get_google_session(self) -> Dict[str, Any]:
        return self.users.get_google_session()

    def logout_google_user(self) -> Dict[str, Any]:
        return self.users.logout_google_user()
