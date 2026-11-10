"""Conteneur d'injection de dépendances (DI) pour la persistance VitalTrack."""

from typing import Optional, Tuple, TYPE_CHECKING
from src.repositories import (
    WeightsRepository,
    MealsRepository,
    DevicesRepository,
    UsersRepository,
    MetricsRepository,
)

if TYPE_CHECKING:
    from src.db import Database


class Container:
    """Conteneur DI pour instancier et résoudre les repositories et services de persistance."""

    def __init__(self, db: "Database"):
        self.db = db
        # Instanciation explicite des repositories avec leurs dépendances déclarées
        self.users = UsersRepository(self.db)
        self.weights = WeightsRepository(self.db)
        self.meals = MealsRepository(self.db)
        self.devices = DevicesRepository(self.db)
        self.metrics = MetricsRepository(self.db)


def create_container(
    db_path: Optional[str] = None,
    database_url: Optional[str] = None,
    auto_migrate: bool = True
) -> Tuple["Database", Container]:
    """Helper factory retournant le couple (Database, Container)."""
    from src.db import Database
    database = Database(db_path=db_path, database_url=database_url, auto_migrate=auto_migrate)
    return database, database.container
