"""Tests de validation des packages Clean Architecture (BALI-217 / VTR-201).
Vérifie la séparation stricte :
- Domain (entities, value objects, use cases, ports)
- Application (services, DTOs, mappers)
- Infrastructure (repositories, api, db, connectors, config)
- Règle de dépendance : domain <- application <- infrastructure
"""
import pytest
from datetime import date
from src.domain.entities.models import WeightEntry, MealEntry
from src.domain.value_objects import WeightSource, MealType
from src.domain.ports import WeightRepositoryPort, MealRepositoryPort
from src.domain.use_cases import RecordWeightUseCase, GetWeightHistoryUseCase
from src.application.dtos import WeightCreateDTO, WeightResponseDTO
from src.application.mappers import WeightMapper
from src.application.services import WeightApplicationService
from src.infrastructure.config import config
from src.infrastructure.repositories import WeightsRepository
from src.infrastructure.db import Database


class FakeWeightRepository:
    def __init__(self):
        self._entries = []

    async def get_all(self, limit: int = 100, user_id: int = 1):
        return self._entries[:limit]

    async def add(self, entry: WeightEntry, user_id: int = 1):
        entry.id = len(self._entries) + 1
        self._entries.append(entry)
        return entry

    async def get_by_date(self, entry_date, user_id: int = 1):
        for e in self._entries:
            if e.date == entry_date:
                return e
        return None


def test_domain_entity_creation():
    entry = WeightEntry(date=date(2026, 11, 7), weight_kg=75.5, source="manual")
    assert entry.weight_kg == 75.5
    assert entry.source == "manual"


def test_domain_ports_compliance():
    fake_repo = FakeWeightRepository()
    assert isinstance(fake_repo, WeightRepositoryPort)


@pytest.mark.asyncio
async def test_domain_use_cases():
    fake_repo = FakeWeightRepository()
    use_case = RecordWeightUseCase(fake_repo)
    entry = WeightEntry(date=date(2026, 11, 7), weight_kg=76.0)
    saved = await use_case.execute(entry)
    assert saved.id == 1

    history_use_case = GetWeightHistoryUseCase(fake_repo)
    history = await history_use_case.execute()
    assert len(history) == 1
    assert history[0].weight_kg == 76.0


def test_application_mapper_and_dtos():
    dto = WeightCreateDTO(date=date(2026, 11, 7), weight_kg=78.2, notes="Test DTO")
    entity = WeightMapper.to_entity(dto)
    assert entity.weight_kg == 78.2
    assert entity.notes == "Test DTO"

    response_dto = WeightMapper.to_dto(entity)
    assert response_dto.weight_kg == 78.2
    assert response_dto.source == "manual"


@pytest.mark.asyncio
async def test_application_service_orchestration():
    fake_repo = FakeWeightRepository()
    service = WeightApplicationService(fake_repo)
    dto = WeightCreateDTO(date=date(2026, 11, 7), weight_kg=74.3)
    res = await service.record_new_weight(dto)
    assert res.id == 1
    assert res.weight_kg == 74.3

    history = await service.get_history()
    assert len(history) == 1
    assert history[0].weight_kg == 74.3


def test_infrastructure_exports():
    assert config is not None
    assert WeightsRepository is not None
    assert Database is not None
