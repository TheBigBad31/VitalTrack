"""Dépendances partagées FastAPI pour VitalTrack.

Ce module constitue la source de vérité unique pour l'injection de dépendances (DI)
du backend FastAPI :
- `get_db` / `set_db`
- `get_current_user` / `get_strict_user`
- `get_device_registry` / `set_device_registry`
- `get_calorie_estimator` / `set_calorie_estimator`
- `get_nutrition_engine` / `set_nutrition_engine`
- `invalidate_dashboard_cache`
- `get_static_dir`
- Factories de repositories (`get_weights_repo`, `get_meals_repo`, `get_devices_repo`,
  `get_users_repo`, `get_metrics_repo`) pour préparer le décommissionnement progressif
  des méthodes façade de `src.db.Database`.

Tous les routeurs (`src/routers/*`) dépendent exclusivement de ce module (aucun import
de `src.app`), ce qui supprime les cycles d'imports et permet l'utilisation native de
`app.dependency_overrides[...]` dans les tests.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from fastapi import Depends, Header, HTTPException
from fastapi.params import Depends as DependsParam, Header as HeaderParam

from src.auth import AuthUser, decode_access_token, is_strict_auth_enabled
from src.cache import dashboard_cache
from src.connectors.registry import DeviceConnectorRegistry, create_device_registry
from src.db import Database
from src.nutrition_engine import NutritionEngine
from src.repositories import (
    DevicesRepository,
    MealsRepository,
    MetricsRepository,
    UsersRepository,
    WeightsRepository,
)
from src.vision_nutrition import PhotoCalorieEstimator

# Instances globales partagées (initialisées par src.app ou à la demande)
_db_instance: Optional[Database] = None
_device_registry: Optional[DeviceConnectorRegistry] = None
_calorie_estimator: Optional[PhotoCalorieEstimator] = None
_nutrition_engine: Optional[NutritionEngine] = None

DEFAULT_STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))


# =====================================================================
# Base de données
# =====================================================================

def set_db(db: Database) -> None:
    """Enregistre l'instance Database courante et synchronise src.app si chargé."""
    global _db_instance
    _db_instance = db
    app_module = sys.modules.get("src.app")
    if app_module is not None and getattr(app_module, "db", None) is not db:
        app_module.db = db


def get_db_if_initialized() -> Optional[Database]:
    """Retourne l'instance Database active sans déclencher d'instanciation paresseuse."""
    app_module = sys.modules.get("src.app")
    if app_module is not None:
        app_db = getattr(app_module, "db", None)
        if app_db is not None:
            return app_db
    return _db_instance


def get_db() -> Database:
    """Factory de dépendance retournant l'instance Database active.

    Supporte :
    - `app.dependency_overrides[get_db]` (FastAPI DI natif)
    - `set_db(db)`
    - Rétrocompatibilité avec les monkeypatches de tests sur `src.app.db`.
    """
    app_module = sys.modules.get("src.app")
    if app_module is not None:
        app_db = getattr(app_module, "db", None)
        if app_db is not None:
            return app_db

    global _db_instance
    if _db_instance is not None:
        return _db_instance

    _db_instance = Database()
    return _db_instance


# =====================================================================
# Authentification utilisateur
# =====================================================================

def _resolve_db_param(db: Database) -> Database:
    """Résout le paramètre `db` même si la dépendance est appelée hors contexte FastAPI."""
    if isinstance(db, DependsParam) or db is None:
        return get_db()
    return db


def get_current_user(
    authorization: Optional[str] = Header(None),
    x_webhook_token: Optional[str] = Header(None, alias="X-Webhook-Token"),
    db: Database = Depends(get_db),
) -> AuthUser:
    """Extrait et valide l'utilisateur authentifié depuis le jeton JWT Bearer ou X-Webhook-Token."""
    if isinstance(authorization, HeaderParam):
        authorization = None
    if isinstance(x_webhook_token, HeaderParam):
        x_webhook_token = None
    active_db = _resolve_db_param(db)

    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
        payload = decode_access_token(token)
        if payload and "user_id" in payload:
            user_data = active_db.get_user_by_id(int(payload["user_id"]))
            if user_data:
                return AuthUser(
                    id=user_data["id"],
                    uuid=user_data["uuid"],
                    email=user_data["email"],
                    name=user_data.get("name"),
                    picture=user_data.get("picture"),
                    auth_provider=user_data.get("auth_provider", "google"),
                    google_sub=user_data.get("google_sub"),
                )

    if x_webhook_token and str(x_webhook_token).strip():
        user_match = active_db.find_user_by_device_token(str(x_webhook_token).strip())
        if user_match and user_match.get("user"):
            u = user_match["user"]
            return AuthUser(
                id=u["id"],
                uuid=u["uuid"],
                email=u["email"],
                name=u.get("name"),
                picture=u.get("picture"),
                auth_provider=u.get("auth_provider", "device_token"),
                google_sub=u.get("google_sub"),
            )

    if is_strict_auth_enabled():
        raise HTTPException(
            status_code=401,
            detail="Authentification requise : aucun jeton Bearer ou token d'appareil valide",
            headers={"WWW-Authenticate": "Bearer"},
        )

    demo_user = active_db.get_user_by_id(1) or active_db._ensure_default_user()
    return AuthUser(
        id=demo_user["id"],
        uuid=demo_user["uuid"],
        email=demo_user["email"],
        name=demo_user.get("name"),
        picture=demo_user.get("picture"),
        auth_provider=demo_user.get("auth_provider", "demo"),
        google_sub=demo_user.get("google_sub"),
    )


def get_strict_user(
    authorization: Optional[str] = Header(None),
    db: Database = Depends(get_db),
) -> AuthUser:
    """Dépendance stricte exigeant un jeton Bearer JWT valide (sans fallback dev ni session globale)."""
    if isinstance(authorization, HeaderParam):
        authorization = None
    active_db = _resolve_db_param(db)

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Jeton d'authentification Bearer manquant ou invalide")
    token = authorization.split("Bearer ", 1)[1].strip()
    payload = decode_access_token(token)
    if not payload or "user_id" not in payload:
        raise HTTPException(status_code=401, detail="Jeton JWT expiré ou signature invalide")
    user_data = active_db.get_user_by_id(int(payload["user_id"]))
    if not user_data:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return AuthUser(
        id=user_data["id"],
        uuid=user_data["uuid"],
        email=user_data["email"],
        name=user_data.get("name"),
        picture=user_data.get("picture"),
        auth_provider=user_data.get("auth_provider", "google"),
        google_sub=user_data.get("google_sub"),
    )


# =====================================================================
# Services applicatifs (Registry, Vision, Nutrition, Cache, Static)
# =====================================================================

def set_device_registry(registry: DeviceConnectorRegistry) -> None:
    """Enregistre l'instance DeviceConnectorRegistry active."""
    global _device_registry
    _device_registry = registry


def get_device_registry() -> DeviceConnectorRegistry:
    """Retourne le registre des connecteurs IoT (supporte `app.dependency_overrides`)."""
    app_module = sys.modules.get("src.app")
    if app_module is not None:
        app_reg = getattr(app_module, "device_registry", None)
        if app_reg is not None:
            return app_reg

    global _device_registry
    if _device_registry is None:
        _device_registry = create_device_registry()
    return _device_registry


def set_calorie_estimator(estimator: PhotoCalorieEstimator) -> None:
    """Enregistre l'instance PhotoCalorieEstimator active."""
    global _calorie_estimator
    _calorie_estimator = estimator


def get_calorie_estimator() -> PhotoCalorieEstimator:
    """Retourne l'estimateur calorique photo/OpenFoodFacts (supporte `app.dependency_overrides`)."""
    app_module = sys.modules.get("src.app")
    if app_module is not None:
        app_est = getattr(app_module, "calorie_estimator", None)
        if app_est is not None:
            return app_est

    global _calorie_estimator
    if _calorie_estimator is None:
        _calorie_estimator = PhotoCalorieEstimator()
    return _calorie_estimator


def set_nutrition_engine(engine: NutritionEngine) -> None:
    """Enregistre l'instance NutritionEngine active."""
    global _nutrition_engine
    _nutrition_engine = engine


def get_nutrition_engine(db: Database = Depends(get_db)) -> NutritionEngine:
    """Retourne l'instance NutritionEngine liée à la base courante (supporte `app.dependency_overrides`)."""
    active_db = _resolve_db_param(db)

    app_module = sys.modules.get("src.app")
    if app_module is not None:
        app_engine = getattr(app_module, "nutrition_engine", None)
        if app_engine is not None and getattr(app_engine, "db", None) is active_db:
            return app_engine

    global _nutrition_engine
    if _nutrition_engine is not None and getattr(_nutrition_engine, "db", None) is active_db:
        return _nutrition_engine

    return NutritionEngine(db=active_db)


def invalidate_dashboard_cache(user_id: Optional[int] = None) -> None:
    """Invalide le cache du dashboard (global ou par utilisateur via DashboardCache)."""
    app_module = sys.modules.get("src.app")
    if app_module is not None:
        app_fn = getattr(app_module, "invalidate_dashboard_cache", None)
        if callable(app_fn) and app_fn is not invalidate_dashboard_cache:
            app_fn(user_id)
            return
    dashboard_cache.invalidate(user_id)


def get_static_dir() -> str:
    """Retourne le répertoire des fichiers statiques de la PWA."""
    app_module = sys.modules.get("src.app")
    if app_module is not None:
        static_dir = getattr(app_module, "STATIC_DIR", None)
        if static_dir:
            return static_dir
    return DEFAULT_STATIC_DIR


# =====================================================================
# Repositories dédiés (Préparation décommissionnement façade src/db.py)
# =====================================================================

def get_weights_repo(db: Database = Depends(get_db)) -> WeightsRepository:
    """Injecte directement WeightsRepository (remplace progressivement les méthodes façade de Database)."""
    return _resolve_db_param(db).weights


def get_meals_repo(db: Database = Depends(get_db)) -> MealsRepository:
    """Injecte directement MealsRepository (remplace progressivement les méthodes façade de Database)."""
    return _resolve_db_param(db).meals


def get_devices_repo(db: Database = Depends(get_db)) -> DevicesRepository:
    """Injecte directement DevicesRepository (remplace progressivement les méthodes façade de Database)."""
    return _resolve_db_param(db).devices


def get_users_repo(db: Database = Depends(get_db)) -> UsersRepository:
    """Injecte directement UsersRepository (remplace progressivement les méthodes façade de Database)."""
    return _resolve_db_param(db).users


def get_metrics_repo(db: Database = Depends(get_db)) -> MetricsRepository:
    """Injecte directement MetricsRepository (remplace progressivement les méthodes façade de Database)."""
    return _resolve_db_param(db).metrics
