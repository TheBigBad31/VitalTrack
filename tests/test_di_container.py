"""Tests for DI Container and explicit composition (BALI-211)."""

import pytest
from unittest.mock import MagicMock

from src.container import Container, create_container
from src.db import Database
from src.repositories.users import UsersRepository
from src.repositories.weights import WeightsRepository
from src.repositories.meals import MealsRepository
from src.repositories.devices import DevicesRepository
from src.repositories.metrics import MetricsRepository


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_di.db"
    return Database(db_path=str(db_file), auto_migrate=True)


def test_container_explicit_resolution(temp_db):
    """Container should instantiate all repositories with declared db dependency."""
    container = Container(temp_db)

    assert isinstance(container.users, UsersRepository)
    assert isinstance(container.weights, WeightsRepository)
    assert isinstance(container.meals, MealsRepository)
    assert isinstance(container.devices, DevicesRepository)
    assert isinstance(container.metrics, MetricsRepository)

    # Repository dependencies are correctly passed
    assert container.users.db is temp_db
    assert container.weights.db is temp_db
    assert container.meals.db is temp_db
    assert container.devices.db is temp_db
    assert container.metrics.db is temp_db


def test_container_singleton_behavior(temp_db):
    """Container repositories should be cached as singletons within container instance."""
    container = Container(temp_db)

    assert container.users is container.users
    assert container.weights is container.weights
    assert container.meals is container.meals
    assert container.devices is container.devices
    assert container.metrics is container.metrics


def test_create_container_factory(tmp_path):
    """create_container factory creates Database and Container linked together."""
    db_file = tmp_path / "factory_test.db"
    db, container = create_container(db_path=str(db_file), auto_migrate=True)

    assert isinstance(db, Database)
    assert isinstance(container, Container)
    assert db.container is container
    assert container.db is db
    assert db.users is container.users
    assert db.weights is container.weights


def test_custom_repository_injection(tmp_path):
    """Database should accept custom or mocked repository instances."""
    mock_users_repo = MagicMock(spec=UsersRepository)
    mock_weights_repo = MagicMock(spec=WeightsRepository)

    db_file = tmp_path / "custom_injection.db"
    db = Database(
        db_path=str(db_file),
        auto_migrate=True,
        users_repo=mock_users_repo,
        weights_repo=mock_weights_repo,
    )

    assert db.users is mock_users_repo
    assert db.weights is mock_weights_repo
    assert isinstance(db.meals, MealsRepository)


def test_database_container_property(temp_db):
    """Database.container property returns linked container."""
    container = temp_db.container
    assert isinstance(container, Container)
    assert container.db is temp_db
    assert temp_db.users is container.users
