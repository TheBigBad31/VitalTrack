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

from src.models import ActivityEntry, FoodItem, MealEntry, WeightEntry

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
                    CREATE TABLE IF NOT EXISTS user_devices (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        device_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        device_type TEXT NOT NULL,
                        connected INTEGER NOT NULL DEFAULT 0,
                        auth_type TEXT NOT NULL DEFAULT 'demo',
                        api_key TEXT,
                        account_email TEXT,
                        last_sync TEXT,
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

                # Index optimisés PostgreSQL
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_weights_user_date ON weights(user_id, date DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_activities_user_date ON activities(user_id, date DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_meals_user_date ON meals(user_id, date DESC, id DESC);")

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
                    CREATE TABLE IF NOT EXISTS user_devices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER DEFAULT 1 REFERENCES users(id) ON DELETE CASCADE,
                        device_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        device_type TEXT NOT NULL,
                        connected INTEGER NOT NULL DEFAULT 0,
                        auth_type TEXT NOT NULL DEFAULT 'demo',
                        api_key TEXT,
                        account_email TEXT,
                        last_sync TEXT,
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

                # Migrations douces pour ajouter user_id si les tables SQLite existaient déjà sans user_id
                for table in ["weights", "activities", "meals", "user_devices", "user_profile"]:
                    try:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER DEFAULT 1")
                    except Exception:
                        pass

                # Index uniques pour SQLite garantissant ON CONFLICT(user_id, date)
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_weights_user_date ON weights(user_id, date);")
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_activities_user_date ON activities(user_id, date);")
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_user_devices_user_dev ON user_devices(user_id, device_id);")

                # Index SQLite
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_weights_user_date ON weights(user_id, date DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_activities_user_date ON activities(user_id, date DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_meals_user_date ON meals(user_id, date DESC, id DESC);")

            conn.commit()

        # Garantir l'existence de l'utilisateur par défaut
        self._ensure_default_user()
        # Initialiser le jeu de données démo 30 jours si vide pour cet utilisateur
        self._seed_demo_data_if_empty(user_id=1)

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
                INSERT INTO user_profile (user_id, name, gender, age, height_cm, target_weight_kg, goal_profile_id, target_steps, target_calories_intake, protein_target_per_kg, preferred_ring, preferred_scale, google_email, google_name, google_picture, google_sub, updated_at)
                VALUES (?, ?, 'male', 35, 178.0, 77.0, 'weight_loss', 10000, 2000.0, 1.8, 'ringconn', 'withings', ?, ?, ?, ?, ?)
            """, (user_dict["id"], user_dict["name"] or "Utilisateur", user_dict["email"], user_dict["name"], user_dict["picture"], google_sub, now_str))
            conn.commit()

        # Seed 30 jours de démo pour ce nouvel utilisateur
        self._seed_demo_data_if_empty(user_id=user_dict["id"])
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

    # ---------------------------------------------------------
    # Tendance et Pesées Multi-Utilisateurs
    # ---------------------------------------------------------

    def calculate_7d_trend(self, target_date: date, new_weight_kg: float, user_id: int = 1) -> float:
        """Calcule la moyenne mobile sur 7 jours incluant la pesée actuelle pour l'utilisateur."""
        start_date = (target_date - timedelta(days=6)).isoformat()
        end_date = target_date.isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
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
        """Insère ou met à jour une pesée en recalculant la tendance 7j pour user_id."""
        trend = entry.trend_7d_kg
        if trend is None:
            trend = self.calculate_7d_trend(entry.date, entry.weight_kg, user_id=user_id)

        now_str = datetime.now(timezone.utc).isoformat()
        date_str = entry.date.isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO weights (user_id, date, weight_kg, body_fat_pct, muscle_mass_kg, water_pct, bmi, trend_7d_kg, source, notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date) DO UPDATE SET
                        weight_kg = EXCLUDED.weight_kg,
                        body_fat_pct = EXCLUDED.body_fat_pct,
                        muscle_mass_kg = EXCLUDED.muscle_mass_kg,
                        water_pct = EXCLUDED.water_pct,
                        bmi = EXCLUDED.bmi,
                        trend_7d_kg = EXCLUDED.trend_7d_kg,
                        source = EXCLUDED.source,
                        notes = EXCLUDED.notes
                    RETURNING id;
                """, (
                    user_id, date_str, entry.weight_kg, entry.body_fat_pct,
                    entry.muscle_mass_kg, entry.water_pct, entry.bmi, trend,
                    entry.source, entry.notes, now_str
                ))
                res = cursor.fetchone()
                entry_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO weights (user_id, date, weight_kg, body_fat_pct, muscle_mass_kg, water_pct, bmi, trend_7d_kg, source, notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date) DO UPDATE SET
                        weight_kg = excluded.weight_kg,
                        body_fat_pct = excluded.body_fat_pct,
                        muscle_mass_kg = excluded.muscle_mass_kg,
                        water_pct = excluded.water_pct,
                        bmi = excluded.bmi,
                        trend_7d_kg = excluded.trend_7d_kg,
                        source = excluded.source,
                        notes = excluded.notes
                """, (
                    user_id, date_str, entry.weight_kg, entry.body_fat_pct,
                    entry.muscle_mass_kg, entry.water_pct, entry.bmi, trend,
                    entry.source, entry.notes, now_str
                ))
                entry_id = cursor.lastrowid
            conn.commit()

        entry_dict = entry.model_dump()
        entry_dict["id"] = entry_id
        entry_dict["trend_7d_kg"] = trend
        entry_dict["created_at"] = datetime.fromisoformat(now_str)
        return WeightEntry(**entry_dict)

    def get_weights(self, limit: int = 30, user_id: int = 1) -> List[WeightEntry]:
        """Récupère l'historique des pesées ordonné par date croissante pour un utilisateur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
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
                notes=r["notes"],
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
            ))
        return results

    # ---------------------------------------------------------
    # Activités Multi-Utilisateurs
    # ---------------------------------------------------------

    def insert_activity(self, entry: ActivityEntry, user_id: int = 1) -> ActivityEntry:
        """Insère ou met à jour une entrée d'activité pour user_id."""
        now_str = datetime.now(timezone.utc).isoformat()
        date_str = entry.date.isoformat()

        total_burned = entry.total_burned_kcal
        if total_burned <= 0 and (entry.bmr_kcal > 0 or entry.active_calories_kcal > 0):
            total_burned = round(entry.bmr_kcal + entry.active_calories_kcal, 1)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO activities (user_id, date, steps, active_calories_kcal, bmr_kcal, total_burned_kcal, workout_minutes, workout_type, resting_hr_bpm, hrv_ms, sleep_score, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        source = EXCLUDED.source
                    RETURNING id;
                """, (
                    user_id, date_str, entry.steps, entry.active_calories_kcal,
                    entry.bmr_kcal, total_burned, entry.workout_minutes,
                    entry.workout_type, entry.resting_hr_bpm, entry.hrv_ms,
                    entry.sleep_score, entry.source, now_str
                ))
                res = cursor.fetchone()
                entry_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO activities (user_id, date, steps, active_calories_kcal, bmr_kcal, total_burned_kcal, workout_minutes, workout_type, resting_hr_bpm, hrv_ms, sleep_score, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        source = excluded.source
                """, (
                    user_id, date_str, entry.steps, entry.active_calories_kcal,
                    entry.bmr_kcal, total_burned, entry.workout_minutes,
                    entry.workout_type, entry.resting_hr_bpm, entry.hrv_ms,
                    entry.sleep_score, entry.source, now_str
                ))
                entry_id = cursor.lastrowid
            conn.commit()

        entry_dict = entry.model_dump()
        entry_dict["id"] = entry_id
        entry_dict["total_burned_kcal"] = total_burned
        entry_dict["created_at"] = datetime.fromisoformat(now_str)
        return ActivityEntry(**entry_dict)

    def get_activities(self, limit: int = 30, user_id: int = 1) -> List[ActivityEntry]:
        """Récupère l'historique d'activité ordonné par date croissante pour un utilisateur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
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
                    INSERT INTO user_profile (user_id, name, gender, age, height_cm, target_weight_kg, goal_profile_id, target_steps, target_calories_intake, protein_target_per_kg, preferred_ring, preferred_scale, updated_at)
                    VALUES (?, 'Sébastien', 'male', 35, 178.0, 77.0, 'weight_loss', 10000, 2000.0, 1.8, 'ringconn', 'withings', ?)
                """, (user_id, now_str))
                conn.commit()
                cursor.execute("SELECT * FROM user_profile WHERE user_id = ? ORDER BY id ASC LIMIT 1", (user_id,))
                row = cursor.fetchone()

        return dict(row)

    def update_user_profile(self, data: Dict[str, Any], user_id: int = 1) -> Dict[str, Any]:
        """Met à jour le profil de l'utilisateur."""
        current = self.get_user_profile(user_id=user_id)
        now_str = datetime.now(timezone.utc).isoformat()

        name = data.get("name", current.get("name", "Sébastien"))
        gender = data.get("gender", current.get("gender", "male"))
        age = int(data.get("age", current.get("age", 35)))
        height_cm = float(data.get("height_cm", current.get("height_cm", 178.0)))
        target_weight = float(data.get("target_weight_kg", current.get("target_weight_kg", 77.0)))
        goal_id = data.get("goal_profile_id", current.get("goal_profile_id", "weight_loss"))
        steps = int(data.get("target_steps", current.get("target_steps", 10000)))
        cal_intake = float(data.get("target_calories_intake", current.get("target_calories_intake", 2000.0)))
        prot = float(data.get("protein_target_per_kg", current.get("protein_target_per_kg", 1.8)))
        ring = data.get("preferred_ring", current.get("preferred_ring", "ringconn"))
        scale = data.get("preferred_scale", current.get("preferred_scale", "withings"))
        google_email = data.get("google_email", current.get("google_email"))
        google_name = data.get("google_name", current.get("google_name"))
        google_picture = data.get("google_picture", current.get("google_picture"))
        google_sub = data.get("google_sub", current.get("google_sub"))

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_profile
                SET name = ?, gender = ?, age = ?, height_cm = ?, target_weight_kg = ?,
                    goal_profile_id = ?, target_steps = ?, target_calories_intake = ?,
                    protein_target_per_kg = ?, preferred_ring = ?, preferred_scale = ?,
                    google_email = ?, google_name = ?, google_picture = ?, google_sub = ?,
                    updated_at = ?
                WHERE user_id = ?
            """, (name, gender, age, height_cm, target_weight, goal_id, steps, cal_intake, prot, ring, scale, google_email, google_name, google_picture, google_sub, now_str, user_id))
            conn.commit()

        return self.get_user_profile(user_id=user_id)

    def get_user_devices(self, user_id: int = 1) -> List[Dict[str, Any]]:
        """Récupère les objets connectés associés à user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_devices WHERE user_id = ? ORDER BY id ASC", (user_id,))
            rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def update_user_device(
        self,
        device_id: str,
        name: str,
        device_type: str,
        connected: bool,
        auth_type: str = "connected",
        api_key: Optional[str] = None,
        account_email: Optional[str] = None,
        user_id: int = 1
    ) -> Dict[str, Any]:
        """Enregistre ou met à jour un objet connecté pour user_id."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO user_devices (user_id, device_id, name, device_type, connected, auth_type, api_key, account_email, last_sync, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, device_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        device_type = EXCLUDED.device_type,
                        connected = EXCLUDED.connected,
                        auth_type = EXCLUDED.auth_type,
                        api_key = COALESCE(EXCLUDED.api_key, user_devices.api_key),
                        account_email = COALESCE(EXCLUDED.account_email, user_devices.account_email),
                        last_sync = EXCLUDED.last_sync,
                        updated_at = EXCLUDED.updated_at
                    RETURNING *;
                """, (user_id, device_id, name, device_type, 1 if connected else 0, auth_type, api_key, account_email, now_str, now_str))
                row = cursor.fetchone()
            else:
                cursor.execute("""
                    INSERT INTO user_devices (user_id, device_id, name, device_type, connected, auth_type, api_key, account_email, last_sync, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, device_id) DO UPDATE SET
                        name = excluded.name,
                        device_type = excluded.device_type,
                        connected = excluded.connected,
                        auth_type = excluded.auth_type,
                        api_key = COALESCE(excluded.api_key, user_devices.api_key),
                        account_email = COALESCE(excluded.account_email, user_devices.account_email),
                        last_sync = excluded.last_sync,
                        updated_at = excluded.updated_at
                """, (user_id, device_id, name, device_type, 1 if connected else 0, auth_type, api_key, account_email, now_str, now_str))
                conn.commit()
                cursor.execute("SELECT * FROM user_devices WHERE user_id = ? AND device_id = ?", (user_id, device_id))
                row = cursor.fetchone()
            conn.commit()
        return dict(row)

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

        return {
            "version": "2.0",
            "user_id": user_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "profile": profile_dict,
            "devices": devices_list,
            "weights": weights_list,
            "activities": activities_list,
            "meals": meals_list
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
            if not keep_profile:
                cursor.execute("DELETE FROM user_profile WHERE user_id = ?", (user_id,))
                cursor.execute("DELETE FROM user_devices WHERE user_id = ?", (user_id,))
            conn.commit()

    def reset_demo_data(self, user_id: int = 1):
        """Réinitialise et recharge le jeu complet de démonstration sur 30 jours pour user_id."""
        self.clear_all_history(keep_profile=True, user_id=user_id)
        self._seed_demo_data_if_empty(user_id=user_id)
