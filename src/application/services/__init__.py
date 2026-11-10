"""Application Services (Orchestration & Coordination)."""
from typing import List, Optional
from datetime import date as DateType

from src.domain.ports import WeightRepositoryPort
from src.application.dtos import WeightCreateDTO, WeightResponseDTO
from src.application.mappers import WeightMapper


class WeightApplicationService:
    """Service d'application orchestrant les use cases de pesée."""

    def __init__(self, weight_repo: WeightRepositoryPort):
        self.weight_repo = weight_repo

    async def record_new_weight(self, dto: WeightCreateDTO, user_id: int = 1) -> WeightResponseDTO:
        entity = WeightMapper.to_entity(dto)
        saved = await self.weight_repo.add(entity, user_id=user_id)
        return WeightMapper.to_dto(saved)

    async def get_history(self, limit: int = 100, user_id: int = 1) -> List[WeightResponseDTO]:
        entries = await self.weight_repo.get_all(limit=limit, user_id=user_id)
        return [WeightMapper.to_dto(e) for e in entries]
