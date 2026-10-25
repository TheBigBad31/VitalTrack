"""Repository WeightsRepository : extrait de `src/db.py` (BALI-47).

Les méthodes sont déplacées à l'identique. La connexion et l'état partagé
(`get_connection`, `is_postgres`, `db_path`...) ainsi que les appels inter-repositories
sont résolus via la façade `Database` passée à la construction.
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

from src.models import (
    ActivityEntry, AssociatedBenefit, CatalogItem, FoodItem, MealEntry,
    MealLog, MealLogItem, NutritionBenefitItem, SavedMeal, WeightEntry
)
from src.crypto import encrypt_data, decrypt_data, encrypt_credentials, decrypt_credentials

# Essai d'import de psycopg pour le support Neon PostgreSQL
try:
    import psycopg
    from psycopg.rows import dict_row
    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False



class WeightsRepository:
    """Accès aux données (weights)."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        # Délégation vers la façade Database (connexion, état, autres repositories)
        return getattr(self._db, name)


    # ---------------------------------------------------------
    # Tendance et Pesées Multi-Utilisateurs
    # ---------------------------------------------------------

    def calculate_7d_trend(self, target_date: date, new_weight_kg: float, user_id: int) -> float:
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


    def insert_weight(self, entry: WeightEntry, user_id: int) -> WeightEntry:
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


    def get_weights(self, limit: int = 30, *, user_id: int) -> List[WeightEntry]:
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
    
    def get_weight_by_id(self, weight_id: int, user_id: int) -> Optional[WeightEntry]:
        """Récupère une pesée spécifique par son ID pour user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM weights WHERE id = ? AND user_id = ?", (weight_id, user_id))
            r = cursor.fetchone()
        if not r:
            return None
        return WeightEntry(
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
        )


    def update_weight(self, weight_id: int, entry: WeightEntry, user_id: int) -> Optional[WeightEntry]:
        """Met à jour une pesée existante et recalcule la tendance 7j."""
        existing = self.get_weight_by_id(weight_id, user_id=user_id)
        if not existing:
            return None

        target_date = entry.date
        trend = entry.trend_7d_kg
        if trend is None:
            trend = self.calculate_7d_trend(target_date, entry.weight_kg, user_id=user_id)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE weights
                SET date = ?, weight_kg = ?, body_fat_pct = ?, muscle_mass_kg = ?,
                    water_pct = ?, bmi = ?, trend_7d_kg = ?, source = ?, notes = ?
                WHERE id = ? AND user_id = ?
            """, (
                target_date.isoformat(), entry.weight_kg, entry.body_fat_pct,
                entry.muscle_mass_kg, entry.water_pct, entry.bmi, trend,
                entry.source, entry.notes, weight_id, user_id
            ))
            conn.commit()

        entry_dict = entry.model_dump()
        entry_dict["id"] = weight_id
        entry_dict["trend_7d_kg"] = trend
        entry_dict["created_at"] = existing.created_at
        return WeightEntry(**entry_dict)


    def delete_weight(self, weight_id: int, user_id: int) -> bool:
        """Supprime une pesée pour user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM weights WHERE id = ? AND user_id = ?", (weight_id, user_id))
            if not cursor.fetchone():
                return False
            cursor.execute("DELETE FROM weights WHERE id = ? AND user_id = ?", (weight_id, user_id))
            conn.commit()
            return True


    # Activités Multi-Utilisateurs
    # ---------------------------------------------------------

    def insert_activity(self, entry: ActivityEntry, user_id: int) -> ActivityEntry:
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


    def get_activities(self, limit: int = 30, *, user_id: int) -> List[ActivityEntry]:
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
