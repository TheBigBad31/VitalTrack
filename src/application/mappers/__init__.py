"""Application Mappers (Entity <-> DTO)."""
from src.domain.entities.models import WeightEntry, MealEntry
from src.application.dtos import WeightCreateDTO, WeightResponseDTO, MealCreateDTO


class WeightMapper:
    @staticmethod
    def to_entity(dto: WeightCreateDTO, source: str = "manual") -> WeightEntry:
        return WeightEntry(
            date=dto.date,
            weight_kg=dto.weight_kg,
            body_fat_pct=dto.body_fat_pct,
            muscle_mass_kg=dto.muscle_mass_kg,
            notes=dto.notes,
            measured_at=dto.measured_at,
            source=source,
        )

    @staticmethod
    def to_dto(entity: WeightEntry) -> WeightResponseDTO:
        return WeightResponseDTO(
            id=entity.id,
            date=entity.date,
            weight_kg=entity.weight_kg,
            body_fat_pct=entity.body_fat_pct,
            muscle_mass_kg=entity.muscle_mass_kg,
            bmi=entity.bmi,
            trend_7d_kg=entity.trend_7d_kg,
            source=str(entity.source),
        )


class MealMapper:
    @staticmethod
    def to_entity(dto: MealCreateDTO) -> MealEntry:
        return MealEntry(
            date=dto.date,
            meal_type=dto.meal_type,  # type: ignore
            total_calories_kcal=dto.total_calories_kcal,
            protein_g=dto.protein_g,
            carbs_g=dto.carbs_g,
            fat_g=dto.fat_g,
            photo_data_url=dto.photo_data_url,
        )
