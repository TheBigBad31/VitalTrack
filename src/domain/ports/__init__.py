"""Domain Ports (Interfaces / Protocols / Abstract Base Classes).
Définit les contrats de persistance, de connecteurs et d'observabilité
dont le domaine a besoin sans dépendre de l'infrastructure.
"""
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
from datetime import date as DateType

from src.domain.entities.models import (
    WeightEntry,
    ActivityEntry,
    DailyMetricsEntry,
    MealEntry,
)


@runtime_checkable
class WeightRepositoryPort(Protocol):
    """Port pour l'accès et la persistance des pesées."""

    async def get_all(self, limit: int = 100, user_id: int = 1) -> List[WeightEntry]:
        ...

    async def add(self, entry: WeightEntry, user_id: int = 1) -> WeightEntry:
        ...

    async def get_by_date(self, entry_date: DateType, user_id: int = 1) -> Optional[WeightEntry]:
        ...


@runtime_checkable
class MealRepositoryPort(Protocol):
    """Port pour la persistance des repas et nutrition."""

    async def get_all(self, limit: int = 100, user_id: int = 1) -> List[MealEntry]:
        ...

    async def add(self, entry: MealEntry, user_id: int = 1) -> MealEntry:
        ...


@runtime_checkable
class DeviceConnectorPort(Protocol):
    """Port pour les connecteurs d'objets connectés et balances."""

    device_id: str
    name: str

    async def get_status(self, user_id: int = 1) -> Dict[str, Any]:
        ...

    async def fetch_data(self, user_id: int = 1, start_date: Optional[DateType] = None) -> Dict[str, Any]:
        ...


@runtime_checkable
class UserRepositoryPort(Protocol):
    """Port pour la gestion des utilisateurs et profils."""

    async def get_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        ...

    async def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        ...

    async def get_profile(self, user_id: int) -> Optional[Dict[str, Any]]:
        ...
