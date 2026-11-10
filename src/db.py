"""Gestion de la base de données universelle pour VitalTrack.

Supporte une architecture hybride :
1. PostgreSQL Serverless (Neon) :
   - Détection automatique via DATABASE_URL ou POSTGRES_URL
   - Connexions résilientes avec SSL (sslmode=require)
   - Support PGBouncer et ConnectionPool psycopg_pool
2. Fallback SQLite local :
   - Détection si aucune variable PostgreSQL n'est fournie
   - Persistance dans data/vitaltrack.db ou /tmp/vitaltrack.db (Vercel)
   - 100% compatible avec l'environnement de développement et pytest

Schéma DDL unifié via migrations Alembic (seule source de vérité).
Architecture par domaines via repositories (weights, meals, devices, users, metrics).
La classe Database sert de façade transitoire unifiée pour préserver la rétrocompatibilité.
"""

import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from src.models import (
    ActivityEntry, AssociatedBenefit, CatalogItem, DailyMetricsEntry,
    FoodItem, HydrationLogEntry, IntradaySampleEntry, MealEntry, MealLog,
    MealLogItem, NutritionBenefitItem, RawIngestEntry, SavedMeal,
    SleepSessionEntry, UserConsentItem, WeightEntry, WorkoutEntry
)
from src.repositories import (
    DevicesRepository, MealsRepository, MetricsRepository,
    UsersRepository, WeightsRepository
)

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
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
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
        return dict(row)

    def fetchall(self) -> List[Dict[str, Any]]:
        rows = self.cursor.fetchall()
        return [dict(r) for r in rows]

    @property
    def rowcount(self) -> int:
        return getattr(self.cursor, "rowcount", -1)

    @property
    def lastrowid(self) -> Optional[int]:
        if not self.is_postgres:
            return self.cursor.lastrowid
        return getattr(self.cursor, "lastrowid", None)

    def executemany(self, sql: str, params_list: List[tuple]):
        if self.is_postgres:
            pg_sql = sql.replace("?", "%s")
            return self.cursor.executemany(pg_sql, params_list)
        else:
            return self.cursor.executemany(sql, params_list)


class DatabaseConnectionWrapper:
    """Wrapper unifié pour connexions SQLite et PostgreSQL."""

    def __init__(self, raw_conn: Any, is_postgres: bool, pool_conn_cm: Any = None):
        self.conn = raw_conn
        self.is_postgres = is_postgres
        self.pool_conn_cm = pool_conn_cm

    def set_user_context(self, user_id: Optional[int]) -> None:
        """Définit le contexte utilisateur multi-tenant pour les policies RLS PostgreSQL."""
        if not self.is_postgres:
            return
        cur = self.conn.cursor()
        try:
            if user_id is not None:
                cur.execute(f"SET LOCAL app.current_user_id = '{int(user_id)}';")
            else:
                cur.execute("RESET app.current_user_id;")
        finally:
            cur.close()

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
    """Gestionnaire de persistance universel (PostgreSQL Serverless Neon & SQLite local).

    Alembic est la source de vérité UNIQUE pour le schéma DDL de la base.
    Les opérations métiers sont factorisées dans des repositories par domaine, accessibles
    directement (`db.weights`, `db.meals`, etc.) ou via les méthodes de façade de `db.*`.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        database_url: Optional[str] = None,
        auto_migrate: bool = True,
        pool: Optional[Any] = None,
        weights_repo: Optional[WeightsRepository] = None,
        meals_repo: Optional[MealsRepository] = None,
        devices_repo: Optional[DevicesRepository] = None,
        users_repo: Optional[UsersRepository] = None,
        metrics_repo: Optional[MetricsRepository] = None,
        container: Optional[Any] = None,
    ):
        self.database_url = database_url or get_database_url()
        self.is_postgres = bool(self.database_url and HAS_PSYCOPG)
        self.db_path = db_path or get_db_path()
        self.pool = pool

        # Composition explicite & Container DI
        if container is not None:
            self._container = container
            self.weights = weights_repo or container.weights
            self.meals = meals_repo or container.meals
            self.devices = devices_repo or container.devices
            self.users = users_repo or container.users
            self.metrics = metrics_repo or container.metrics
        else:
            self.weights = weights_repo or WeightsRepository(self)
            self.meals = meals_repo or MealsRepository(self)
            self.devices = devices_repo or DevicesRepository(self)
            self.users = users_repo or UsersRepository(self)
            self.metrics = metrics_repo or MetricsRepository(self)
            self._container = None

        if auto_migrate:
            try:
                self.run_migrations()
            except DatabaseServiceUnavailableError:
                raise
            except Exception as mig_err:
                print(f"[VitalTrack DB Warning] Migrations ignorées au démarrage: {mig_err}")

        # Auto-rattrapage DDL idempotent pour Neon PostgreSQL (garantie contraintes ON CONFLICT)
        if self.is_postgres:
            try:
                self._ensure_pg_schema_constraints()
            except Exception as ddl_err:
                print(f"[VitalTrack DB Warning] Erreur vérification contraintes Neon: {ddl_err}")

    @property
    def container(self):
        """Fournit le conteneur DI associé à cette base (initialisé à la demande si non fourni)."""
        if self._container is None:
            from src.container import Container
            self._container = Container(self)
            # Aligner les repositories
            self._container.weights = self.weights
            self._container.meals = self.meals
            self._container.devices = self.devices
            self._container.users = self.users
            self._container.metrics = self.metrics
        return self._container

    def create_pool(
        self,
        min_size: int = 0,
        max_size: int = 10,
        timeout: float = 10.0,
        max_idle: float = 300.0,
        max_lifetime: float = 1800.0,
    ) -> Optional[Any]:
        """Crée et initialise un ConnectionPool psycopg_pool pour cette instance Database."""
        if not self.is_postgres or not HAS_PSYCOPG_POOL:
            return None
        try:
            self.pool = ConnectionPool(
                self.database_url,
                min_size=min_size,
                max_size=max_size,
                timeout=timeout,
                max_idle=max_idle,
                max_lifetime=max_lifetime,
                open=True,
                kwargs={"autocommit": False},
            )
            return self.pool
        except Exception as e:
            print(f"[VitalTrack DB Warning] Impossible d'initialiser ConnectionPool Neon: {e}")
            self.pool = None
            return None

    def close_pool(self):
        """Ferme proprement le pool de connexions associé à cette instance."""
        if self.pool is not None and not getattr(self.pool, "closed", False):
            try:
                self.pool.close()
            except Exception as e:
                print(f"[VitalTrack DB Warning] Erreur lors de la fermeture du pool Neon: {e}")
        self.pool = None

    def _get_pool(self) -> Optional[Any]:
        """Retourne le pool d'instance s'il existe, sinon l'initialise si configuré."""
        if not self.is_postgres or not HAS_PSYCOPG_POOL:
            return None
        if self.pool is not None and not getattr(self.pool, "closed", False):
            return self.pool

        global _POSTGRES_POOL
        if self.pool is None:
            if _POSTGRES_POOL is not None and not getattr(_POSTGRES_POOL, "closed", False):
                self.pool = _POSTGRES_POOL
                return self.pool
            pool = self.create_pool()
            _POSTGRES_POOL = pool
            return pool
        return self.pool

    def get_connection(self, user_id: Optional[int] = None) -> DatabaseConnectionWrapper:
        """Fournit une connexion unifiée (PostgreSQL avec ConnectionPool ou SQLite).
        Si user_id est fourni, configure le contexte local pour RLS PostgreSQL.
        """
        if self.is_postgres:
            pool = self._get_pool()
            if pool is not None:
                try:
                    pool_cm = pool.connection(timeout=10.0)
                    conn = pool_cm.__enter__()
                    wrapper = DatabaseConnectionWrapper(conn, is_postgres=True, pool_conn_cm=pool_cm)
                    if user_id is not None:
                        wrapper.set_user_context(user_id)
                    return wrapper
                except Exception as e:
                    print(f"[VitalTrack DB Warning] Échec obtention connexion depuis pool Neon: {e}. Essai connexion directe.")
            try:
                conn = psycopg.connect(self.database_url, connect_timeout=10)
                wrapper = DatabaseConnectionWrapper(conn, is_postgres=True)
                if user_id is not None:
                    wrapper.set_user_context(user_id)
                return wrapper
            except Exception as e:
                if is_production_environment() or self.database_url:
                    err_msg = (
                        f"[VitalTrack DB Error] Connexion PostgreSQL Neon impossible en environnement de production: {e}. "
                        "Fallback SQLite interdit pour prévenir toute perte de données orphelines dans /tmp."
                    )
                    print(err_msg)
                    raise DatabaseServiceUnavailableError(err_msg) from e

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
        """Exécute les migrations de schéma Alembic (source unique de vérité DDL)."""
        global _INIT_MIGRATIONS_DONE
        if _INIT_MIGRATIONS_DONE and self.is_postgres:
            return

        from alembic.config import Config
        from alembic import command

        ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
        if not ini_path.exists():
            raise FileNotFoundError(f"Configuration Alembic introuvable à {ini_path}")

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

        # Initialisation des données indispensables (compte par défaut, catalogue socle et bienfaits)
        try:
            self._ensure_default_user()
            self._seed_public_food_items()
            self._seed_nutrition_benefits()
            self.purge_demo_data()
        except Exception as e:
            print(f"[VitalTrack DB Warning] Initialisation post-migration: {e}")

    def _init_db(self):
        """Alias pour rétrocompatibilité : exécute run_migrations."""
        self.run_migrations()

    def _ensure_pg_schema_constraints(self):
        """Vérifie et applique les contraintes d'unicité composites requises sur PostgreSQL Neon."""
        if not self.is_postgres:
            return
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DO $$
                BEGIN
                    -- 1. Table weights : assurer la contrainte composite (user_id, date, source)
                    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_weights_user_date') THEN
                        ALTER TABLE weights DROP CONSTRAINT uq_weights_user_date;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_weights_user_date_source') THEN
                        ALTER TABLE weights ADD CONSTRAINT uq_weights_user_date_source UNIQUE (user_id, date, source);
                    END IF;

                    -- 2. Table activities : assurer la contrainte composite (user_id, date, source)
                    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_activities_user_date') THEN
                        ALTER TABLE activities DROP CONSTRAINT uq_activities_user_date;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_activities_user_date_source') THEN
                        ALTER TABLE activities ADD CONSTRAINT uq_activities_user_date_source UNIQUE (user_id, date, source);
                    END IF;
                END $$;
            """)
            conn.commit()

    def _pg_bool_true(self):
        """Valeur littérale de `true` adaptée au moteur (BOOLEAN sous PostgreSQL, INTEGER 1 sous SQLite)."""
        return True if self.is_postgres else 1

    # -------------------------------------------------------------------------
    # Façade : Utilisateurs, Profils & Authentification (UsersRepository)
    # -------------------------------------------------------------------------

    def _ensure_default_user(self) -> Dict[str, Any]:
        return self.users._ensure_default_user()

    def get_or_create_user(self, email: str, name: Optional[str] = None, picture: Optional[str] = None,
                           auth_provider: str = "google", google_sub: Optional[str] = None,
                           password_hash: Optional[str] = None) -> Dict[str, Any]:
        return self.users.get_or_create_user(
            email=email, name=name, picture=picture,
            auth_provider=auth_provider, google_sub=google_sub, password_hash=password_hash
        )

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self.users.get_user_by_id(user_id)

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return self.users.get_user_by_email(email)

    def get_all_users(self) -> List[Dict[str, Any]]:
        return self.users.get_all_users()

    def get_user_profile(self, user_id: int = 1) -> Dict[str, Any]:
        return self.users.get_user_profile(user_id=user_id)

    def update_user_profile(self, data: Dict[str, Any], user_id: int = 1) -> Dict[str, Any]:
        return self.users.update_user_profile(data, user_id=user_id)

    def get_google_config(self) -> Dict[str, Any]:
        return self.users.get_google_config()

    def set_google_client_id(self, client_id: str) -> Dict[str, Any]:
        return self.users.set_google_client_id(client_id)

    def login_google_user(self, email: str, name: str, picture: str = "", google_sub: str = "",
                          auth_method: str = "google") -> Dict[str, Any]:
        return self.users.login_google_user(email=email, name=name, picture=picture,
                                            google_sub=google_sub, auth_method=auth_method)

    def get_google_session(self) -> Dict[str, Any]:
        return self.users.get_google_session()

    def logout_google_user(self) -> Dict[str, Any]:
        return self.users.logout_google_user()

    def set_user_consent(self, category: str, consented: bool, user_id: int = 1) -> UserConsentItem:
        return self.users.set_user_consent(category, consented, user_id=user_id)

    def get_user_consents(self, user_id: int = 1) -> Dict[str, bool]:
        return self.users.get_user_consents(user_id=user_id)

    def delete_user_data_only(self, user_id: int) -> bool:
        return self.users.delete_user_data_only(user_id)

    def delete_user_account_and_data(self, user_id: int) -> bool:
        return self.users.delete_user_account_and_data(user_id)

    def create_friend_request(self, user_id: int, target_identifier: str, permission: str = "read_only") -> Dict[str, Any]:
        return self.users.create_friend_request(user_id, target_identifier, permission)

    def get_friendships(self, user_id: int) -> Dict[str, List[Dict[str, Any]]]:
        return self.users.get_friendships(user_id)

    def accept_friend_request(self, request_id: int, user_id: int) -> Dict[str, Any]:
        return self.users.accept_friend_request(request_id, user_id)

    def reject_friend_request(self, request_id: int, user_id: int) -> Dict[str, Any]:
        return self.users.reject_friend_request(request_id, user_id)

    def delete_friendship(self, target_id: int, user_id: int) -> bool:
        return self.users.delete_friendship(target_id, user_id)

    def check_friendship_access(self, observer_id: int, target_user_id: int) -> Optional[Dict[str, Any]]:
        return self.users.check_friendship_access(observer_id, target_user_id)

    def delete_demo_users(self) -> int:
        return self.users.delete_demo_users()

    # -------------------------------------------------------------------------
    # Façade : Pesées & Activités Physiques (WeightsRepository)
    # -------------------------------------------------------------------------

    def calculate_7d_trend(self, target_date: date, new_weight_kg: float, user_id: int = 1,
                           exclude_simulation: bool = True) -> float:
        return self.weights.calculate_7d_trend(target_date, new_weight_kg, user_id=user_id,
                                               exclude_simulation=exclude_simulation)

    def insert_weight(self, entry: WeightEntry, user_id: int = 1) -> WeightEntry:
        return self.weights.insert_weight(entry, user_id=user_id)

    def get_weights(self, limit: int = 30, user_id: int = 1, exclude_simulation: bool = False) -> List[WeightEntry]:
        return self.weights.get_weights(limit=limit, user_id=user_id, exclude_simulation=exclude_simulation)

    def batch_insert_weights(self, entries: List[WeightEntry], user_id: int = 1) -> int:
        return self.weights.batch_insert_weights(entries, user_id=user_id)

    def get_weight_by_id(self, weight_id: int, user_id: int = 1) -> Optional[WeightEntry]:
        return self.weights.get_weight_by_id(weight_id, user_id=user_id)

    def update_weight(self, weight_id: int, entry: WeightEntry, user_id: int = 1) -> Optional[WeightEntry]:
        return self.weights.update_weight(weight_id, entry, user_id=user_id)

    def delete_weight(self, weight_id: int, user_id: int = 1) -> bool:
        return self.weights.delete_weight(weight_id, user_id=user_id)

    def insert_activity(self, entry: ActivityEntry, user_id: int = 1) -> ActivityEntry:
        return self.weights.insert_activity(entry, user_id=user_id)

    def get_activities(self, limit: int = 30, user_id: int = 1, exclude_simulation: bool = False) -> List[ActivityEntry]:
        return self.weights.get_activities(limit=limit, user_id=user_id, exclude_simulation=exclude_simulation)

    def batch_insert_activities(self, entries: List[ActivityEntry], user_id: int = 1) -> int:
        return self.weights.batch_insert_activities(entries, user_id=user_id)

    def delete_demo_weights(self, user_id: Optional[int] = None) -> int:
        return self.weights.delete_demo_weights(user_id=user_id)

    def delete_demo_activities(self, user_id: Optional[int] = None) -> int:
        return self.weights.delete_demo_activities(user_id=user_id)

    # -------------------------------------------------------------------------
    # Façade : Repas, Catalogue & Nutrition (MealsRepository)
    # -------------------------------------------------------------------------

    def insert_meal(self, entry: MealEntry, user_id: int = 1) -> MealEntry:
        return self.meals.insert_meal(entry, user_id=user_id)

    def get_meals_for_date(self, target_date: date, user_id: int = 1) -> List[MealEntry]:
        return self.meals.get_meals_for_date(target_date, user_id=user_id)

    def get_meals(self, limit: int = 50, user_id: int = 1) -> List[MealEntry]:
        return self.meals.get_meals(limit=limit, user_id=user_id)

    def get_meal_by_id(self, meal_id: int, user_id: int = 1) -> Optional[MealEntry]:
        return self.meals.get_meal_by_id(meal_id, user_id=user_id)

    def update_meal(self, meal_id: int, entry: MealEntry, user_id: int = 1) -> Optional[MealEntry]:
        return self.meals.update_meal(meal_id, entry, user_id=user_id)

    def delete_meal(self, meal_id: int, user_id: int = 1) -> bool:
        return self.meals.delete_meal(meal_id, user_id=user_id)

    def insert_saved_meal(self, saved_meal: SavedMeal, user_id: int = 1) -> SavedMeal:
        return self.meals.insert_saved_meal(saved_meal, user_id=user_id)

    def get_saved_meals(self, meal_type: Optional[str] = None, is_favorite: Optional[bool] = None,
                        user_id: int = 1) -> List[SavedMeal]:
        return self.meals.get_saved_meals(meal_type=meal_type, is_favorite=is_favorite, user_id=user_id)

    def get_saved_meal_by_id(self, meal_id: int, user_id: int = 1) -> Optional[SavedMeal]:
        return self.meals.get_saved_meal_by_id(meal_id, user_id=user_id)

    def update_saved_meal(self, meal_id: int, saved_meal: SavedMeal, user_id: int = 1) -> Optional[SavedMeal]:
        return self.meals.update_saved_meal(meal_id, saved_meal, user_id=user_id)

    def delete_saved_meal(self, meal_id: int, user_id: int = 1) -> bool:
        return self.meals.delete_saved_meal(meal_id, user_id=user_id)

    def insert_food_item(self, item: CatalogItem, user_id: int = 1) -> CatalogItem:
        return self.meals.insert_food_item(item, user_id=user_id)

    def get_food_items(self, item_type: Optional[str] = None, query: Optional[str] = None,
                       user_id: int = 1, source: str = "mine", friend_id: Optional[int] = None,
                       limit: Optional[int] = None, offset: int = 0) -> List[CatalogItem]:
        return self.meals.get_food_items(item_type=item_type, query=query, user_id=user_id,
                                         source=source, friend_id=friend_id, limit=limit, offset=offset)

    def get_food_item_by_id(self, item_id: int, user_id: Optional[int] = None) -> Optional[CatalogItem]:
        return self.meals.get_food_item_by_id(item_id, user_id=user_id)

    def update_food_item(self, item_id: int, data: Dict[str, Any], user_id: int = 1) -> Optional[CatalogItem]:
        return self.meals.update_food_item(item_id, data, user_id=user_id)

    def delete_food_item(self, item_id: int, user_id: int = 1) -> bool:
        return self.meals.delete_food_item(item_id, user_id=user_id)

    def add_catalog_subscription(self, subscriber_id: int, target_user_id: int) -> bool:
        return self.meals.add_catalog_subscription(subscriber_id, target_user_id)

    def remove_catalog_subscription(self, subscriber_id: int, target_user_id: int) -> bool:
        return self.meals.remove_catalog_subscription(subscriber_id, target_user_id)

    def get_catalog_subscriptions(self, subscriber_id: int) -> List[Dict[str, Any]]:
        return self.meals.get_catalog_subscriptions(subscriber_id)

    def is_subscribed_to_catalog(self, subscriber_id: int, target_user_id: int) -> bool:
        return self.meals.is_subscribed_to_catalog(subscriber_id, target_user_id)

    def _seed_public_food_items(self):
        return self.meals._seed_public_food_items()

    def _seed_nutrition_benefits(self):
        return self.meals._seed_nutrition_benefits()

    def get_all_nutrition_benefits(self) -> List[NutritionBenefitItem]:
        return self.meals.get_all_nutrition_benefits()

    def get_food_item_benefits(self, food_item_id: int) -> List[AssociatedBenefit]:
        return self.meals.get_food_item_benefits(food_item_id)

    def set_food_item_benefits(self, food_item_id: int, benefits_data: List[Dict[str, Any]]) -> List[AssociatedBenefit]:
        return self.meals.set_food_item_benefits(food_item_id, benefits_data)

    def get_or_create_meal_log(self, date_val: date, meal_type: str, user_id: int = 1) -> MealLog:
        return self.meals.get_or_create_meal_log(date_val, meal_type, user_id=user_id)

    def get_meal_log(self, date_val: date, meal_type: str, user_id: int = 1) -> MealLog:
        return self.meals.get_or_create_meal_log(date_val, meal_type, user_id=user_id)

    def get_meal_logs_for_date(self, target_date: date, user_id: int = 1) -> List[MealLog]:
        return self.meals.get_meal_logs_for_date(target_date, user_id=user_id)

    def add_item_to_meal_log(self, date_val: date, meal_type: str, name: str, quantity: float,
                             unit: str, calories: float, protein_g: float = 0.0, carbs_g: float = 0.0,
                             fat_g: float = 0.0, fiber_g: float = 0.0, food_item_id: Optional[int] = None,
                             user_id: int = 1) -> MealLog:
        return self.meals.add_item_to_meal_log(
            date_val=date_val, meal_type=meal_type, name=name, quantity=quantity,
            unit=unit, calories=calories, protein_g=protein_g, carbs_g=carbs_g,
            fat_g=fat_g, fiber_g=fiber_g, food_item_id=food_item_id, user_id=user_id
        )

    def batch_add_items_to_meal_log(self, date_val: date, meal_type: str, items: List[Dict[str, Any]],
                                    user_id: int = 1) -> MealLog:
        return self.meals.batch_add_items_to_meal_log(date_val, meal_type, items, user_id=user_id)

    def delete_meal_log_item(self, item_id: int, user_id: int = 1) -> Optional[MealLog]:
        return self.meals.delete_meal_log_item(item_id, user_id=user_id)

    def _recalculate_meal_log_totals(self, meal_log_id: int, user_id: int = 1):
        return self.meals._recalculate_meal_log_totals(meal_log_id, user_id=user_id)

    def delete_demo_meals(self, user_id: Optional[int] = None) -> int:
        return self.meals.delete_demo_meals(user_id=user_id)

    def _sync_meal_log_to_meals(self, meal_log_id: int, user_id: int = 1):
        return self.meals._sync_meal_log_to_meals(meal_log_id, user_id=user_id)

    def sync_all_meal_logs_to_meals(self, user_id: Optional[int] = None):
        return self.meals.sync_all_meal_logs_to_meals(user_id=user_id)

    def _get_meal_log_by_id(self, meal_log_id: int, user_id: int = 1) -> MealLog:
        return self.meals._get_meal_log_by_id(meal_log_id, user_id=user_id)

    # -------------------------------------------------------------------------
    # Façade : Objets Connectés & Tokens (DevicesRepository)
    # -------------------------------------------------------------------------

    def _format_device_row(self, row: Optional[Dict[str, Any]], reveal_secrets: bool = False) -> Optional[Dict[str, Any]]:
        return self.devices._format_device_row(row, reveal_secrets=reveal_secrets)

    @staticmethod
    def decrypt_device_credentials(encrypted_str: Optional[str]) -> Dict[str, Any]:
        return DevicesRepository.decrypt_device_credentials(encrypted_str)

    def get_user_devices(self, user_id: int = 1, reveal_secrets: bool = False) -> List[Dict[str, Any]]:
        return self.devices.get_user_devices(user_id=user_id, reveal_secrets=reveal_secrets)

    def get_user_device(self, device_id: str, user_id: int = 1, reveal_secrets: bool = False) -> Optional[Dict[str, Any]]:
        return self.devices.get_user_device(device_id, user_id=user_id, reveal_secrets=reveal_secrets)

    def get_devices_data_map(self, user_id: int = 1) -> Dict[str, Any]:
        return self.devices.get_devices_data_map(user_id=user_id)

    def find_user_by_device_token(self, token: str, device_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.devices.find_user_by_device_token(token, device_id=device_id)

    def find_user_device_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        return self.devices.find_user_device_by_token(token)

    def generate_device_token(self, device_id: str, name: Optional[str] = None,
                              device_type: Optional[str] = None, user_id: int = 1) -> Dict[str, Any]:
        return self.devices.generate_device_token(device_id, name=name, device_type=device_type, user_id=user_id)

    def delete_user_device(self, device_id: str, user_id: int = 1) -> bool:
        return self.devices.delete_user_device(device_id, user_id=user_id)

    def delete_demo_devices(self, user_id: Optional[int] = None) -> int:
        return self.devices.delete_demo_devices(user_id=user_id)

    def update_device_sync_status(self, device_id: str, sync_status: str, user_id: int = 1) -> Optional[Dict[str, Any]]:
        return self.devices.update_device_sync_status(device_id, sync_status, user_id=user_id)

    def update_user_device(self, device_id: str, name: str, device_type: str, connected: bool,
                           auth_type: str = "connected", api_key: Optional[str] = None,
                           credentials: Optional[Dict[str, Any]] = None, account_email: Optional[str] = None,
                           is_active: bool = True, sync_status: Optional[str] = None, user_id: int = 1) -> Dict[str, Any]:
        return self.devices.update_user_device(
            device_id=device_id, name=name, device_type=device_type, connected=connected,
            auth_type=auth_type, api_key=api_key, credentials=credentials, account_email=account_email,
            is_active=is_active, sync_status=sync_status, user_id=user_id
        )

    # -------------------------------------------------------------------------
    # Façade : Métriques, Workouts, Sommeil, Intraday & Ingest (MetricsRepository)
    # -------------------------------------------------------------------------

    def insert_daily_metric(self, metric: DailyMetricsEntry, user_id: int = 1) -> DailyMetricsEntry:
        return self.metrics.insert_daily_metric(metric, user_id=user_id)

    def get_daily_metrics(self, limit: int = 30, source: Optional[str] = None, user_id: int = 1) -> List[DailyMetricsEntry]:
        return self.metrics.get_daily_metrics(limit=limit, source=source, user_id=user_id)

    def insert_workout(self, workout: WorkoutEntry, user_id: int = 1) -> WorkoutEntry:
        return self.metrics.insert_workout(workout, user_id=user_id)

    def get_workouts(self, limit: int = 30, user_id: int = 1) -> List[WorkoutEntry]:
        return self.metrics.get_workouts(limit=limit, user_id=user_id)

    def insert_sleep_session(self, session: SleepSessionEntry, user_id: int = 1) -> SleepSessionEntry:
        return self.metrics.insert_sleep_session(session, user_id=user_id)

    def get_sleep_session_by_id(self, session_id: int, user_id: int = 1) -> Optional[SleepSessionEntry]:
        return self.metrics.get_sleep_session_by_id(session_id, user_id=user_id)

    def get_sleep_sessions(self, limit: int = 30, user_id: int = 1) -> List[SleepSessionEntry]:
        return self.metrics.get_sleep_sessions(limit=limit, user_id=user_id)

    def insert_intraday_samples(self, samples: List[IntradaySampleEntry], user_id: int = 1) -> int:
        return self.metrics.insert_intraday_samples(samples, user_id=user_id)

    def get_intraday_samples(self, metric_type: str, start_time: Optional[str] = None,
                             end_time: Optional[str] = None, limit: int = 500, user_id: int = 1) -> List[IntradaySampleEntry]:
        return self.metrics.get_intraday_samples(metric_type, start_time=start_time, end_time=end_time,
                                                limit=limit, user_id=user_id)

    def purge_and_aggregate_intraday(self, retention_days: int = 60, user_id: Optional[int] = None) -> Dict[str, Any]:
        return self.metrics.purge_and_aggregate_intraday(retention_days=retention_days, user_id=user_id)

    def insert_hydration_log(self, entry: HydrationLogEntry, user_id: int = 1) -> HydrationLogEntry:
        return self.metrics.insert_hydration_log(entry, user_id=user_id)

    def insert_raw_ingest(self, source: str, payload: Union[Dict[str, Any], str], user_id: int = 1,
                          endpoint: Optional[str] = None, idempotency_key: Optional[str] = None) -> RawIngestEntry:
        return self.metrics.insert_raw_ingest(source, payload, user_id=user_id, endpoint=endpoint,
                                              idempotency_key=idempotency_key)

    # -------------------------------------------------------------------------
    # Sauvegarde, Export & Données Démo
    # -------------------------------------------------------------------------

    def purge_demo_data(self, user_id: Optional[int] = None) -> Dict[str, int]:
        """Supprime toutes les données de démonstration résiduelles via les repositories typés."""
        try:
            return {
                "weights": self.weights.delete_demo_weights(user_id=user_id),
                "activities": self.weights.delete_demo_activities(user_id=user_id),
                "meals": self.meals.delete_demo_meals(user_id=user_id),
                "users": self.users.delete_demo_users(),
                "devices": self.devices.delete_demo_devices(user_id=user_id)
            }
        except Exception as e:
            print(f"[VitalTrack DB Warning] purge_demo_data error: {e}")
            return {
                "weights": 0,
                "activities": 0,
                "meals": 0,
                "users": 0,
                "devices": 0
            }

    def _seed_demo_data_if_empty(self, user_id: int = 1):
        """Charge le jeu de démonstration 30 jours via scripts/seed_demo.py."""
        from scripts.seed_demo import seed_demo_data
        seed_demo_data(self, user_id=user_id)

    def reset_demo_data(self, user_id: int = 1):
        """Réinitialise et recharge le jeu complet de démonstration sur 30 jours pour user_id."""
        self.clear_all_history(keep_profile=True, user_id=user_id)
        self._seed_demo_data_if_empty(user_id=user_id)

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

        if "profile" in data and isinstance(data["profile"], dict):
            self.update_user_profile(data["profile"], user_id=user_id)

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
