"""Domain Use Cases (Interactors métier)."""
from datetime import date as DateType
from typing import List, Optional

from src.domain.entities.models import WeightEntry, MealEntry
from src.domain.ports import WeightRepositoryPort, MealRepositoryPort


class RecordWeightUseCase:
    """Use case : Enregistrement d'une nouvelle pesée."""

    def __init__(self, weight_repo: WeightRepositoryPort):
        self.weight_repo = weight_repo

    async def execute(self, entry: WeightEntry, user_id: int = 1) -> WeightEntry:
        return await self.weight_repo.add(entry, user_id=user_id)


class GetWeightHistoryUseCase:
    """Use case : Récupération de l'historique des pesées."""

    def __init__(self, weight_repo: WeightRepositoryPort):
        self.weight_repo = weight_repo

    async def execute(self, limit: int = 100, user_id: int = 1) -> List[WeightEntry]:
        return await self.weight_repo.get_all(limit=limit, user_id=user_id)


class LogMealUseCase:
    """Use case : Enregistrement d'un repas."""

    def __init__(self, meal_repo: MealRepositoryPort):
        self.meal_repo = meal_repo

    async def execute(self, entry: MealEntry, user_id: int = 1) -> MealEntry:
        return await self.meal_repo.add(entry, user_id=user_id)
