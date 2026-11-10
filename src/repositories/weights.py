"""Repository pour la gestion des pesées et des activités physiques."""

from datetime import date, datetime, timedelta, timezone
import json
from typing import List, Optional

from src.models import ActivityEntry, WeightEntry
from src.repositories.base import BaseRepository


class WeightsRepository(BaseRepository):
    """Gestion des pesées, tendances de poids et activités physiques."""

    def calculate_7d_trend(
        self,
        target_date: date,
        new_weight_kg: float,
        user_id: int = 1,
        exclude_simulation: bool = True
    ) -> float:
        """Calcule la moyenne mobile sur 7 jours incluant la pesée actuelle pour l'utilisateur."""
        start_date = (target_date - timedelta(days=6)).isoformat()
        end_date = target_date.isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if exclude_simulation:
                cursor.execute("""
                    SELECT weight_kg FROM weights
                    WHERE user_id = ? AND date >= ? AND date < ? AND source NOT IN ('simulation')
                    ORDER BY date ASC
                """, (user_id, start_date, end_date))
            else:
                cursor.execute("""
                    SELECT weight_kg FROM weights
                    WHERE user_id = ? AND date >= ? AND date < ?
                    ORDER BY date ASC
                """, (user_id, start_date, end_date))
            rows = cursor.fetchall()

        previous_weights = [r["weight_kg"] for r in rows]
        all_weights = previous_weights + [new_weight_kg]
        return round(sum(all_weights) / len(all_weights), 2)

    def insert_weight(self, entry: WeightEntry, user_id: int = 1) -> WeightEntry:
        """Insère ou met à jour une pesée en recalculant la tendance 7j pour user_id (avec support d'idempotence)."""
        if entry.external_id:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM weights WHERE user_id = ? AND source = ? AND external_id = ? LIMIT 1",
                    (user_id, entry.source, entry.external_id)
                )
                existing = cursor.fetchone()
                if existing:
                    return WeightEntry(
                        id=existing["id"],
                        date=date.fromisoformat(existing["date"][:10]),
                        weight_kg=existing["weight_kg"],
                        body_fat_pct=existing["body_fat_pct"],
                        muscle_mass_kg=existing["muscle_mass_kg"],
                        water_pct=existing["water_pct"],
                        bmi=existing["bmi"],
                        trend_7d_kg=existing["trend_7d_kg"],
                        source=existing["source"],
                        is_simulated=(existing["source"] in ("simulation", "demo")),
                        notes=existing["notes"],
                        external_id=existing.get("external_id"),
                        measured_at=existing.get("measured_at"),
                        idempotency_key=existing.get("idempotency_key"),
                        created_at=datetime.fromisoformat(existing["created_at"]) if existing["created_at"] else None
                    )

        trend = entry.trend_7d_kg
        if trend is None:
            trend = self.calculate_7d_trend(entry.date, entry.weight_kg, user_id=user_id)

        now_str = datetime.now(timezone.utc).isoformat()
        date_str = entry.date.isoformat()
        measured_at_str = entry.measured_at or now_str
        idemp_key = entry.idempotency_key or (f"{entry.source}:{entry.external_id}" if entry.external_id else None)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Tracer l'écrasement dans raw_ingest si une pesée préalable existe pour le même jour/source
            cursor.execute(
                "SELECT id, weight_kg, external_id, measured_at FROM weights WHERE user_id = ? AND date = ? AND source = ? LIMIT 1",
                (user_id, date_str, entry.source)
            )
            prior = cursor.fetchone()
            if prior and (prior.get("external_id") != entry.external_id or prior.get("weight_kg") != entry.weight_kg):
                try:
                    payload_json = json.dumps({
                        "event": "weight_overwritten",
                        "previous_id": prior["id"],
                        "previous_weight_kg": prior["weight_kg"],
                        "previous_external_id": prior.get("external_id"),
                        "new_weight_kg": entry.weight_kg,
                        "new_external_id": entry.external_id,
                        "measured_at": measured_at_str
                    })
                    overwrite_idemp = f"overwrite:{entry.source}:{date_str}:{entry.external_id or now_str}"
                    cursor.execute("""
                        INSERT INTO raw_ingest (user_id, source, endpoint, idempotency_key, payload_json, status, received_at)
                        VALUES (?, ?, ?, ?, ?, 'received', ?)
                    """, (user_id, f"{entry.source}:overwrite", "insert_weight", overwrite_idemp, payload_json, now_str))
                except Exception:
                    pass

            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO weights (
                        user_id, date, weight_kg, body_fat_pct, muscle_mass_kg, water_pct,
                        bmi, trend_7d_kg, source, notes, external_id, measured_at, idempotency_key, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date, source) DO UPDATE SET
                        weight_kg = EXCLUDED.weight_kg,
                        body_fat_pct = EXCLUDED.body_fat_pct,
                        muscle_mass_kg = EXCLUDED.muscle_mass_kg,
                        water_pct = EXCLUDED.water_pct,
                        bmi = EXCLUDED.bmi,
                        trend_7d_kg = EXCLUDED.trend_7d_kg,
                        notes = EXCLUDED.notes,
                        external_id = COALESCE(EXCLUDED.external_id, weights.external_id),
                        measured_at = COALESCE(EXCLUDED.measured_at, weights.measured_at),
                        idempotency_key = COALESCE(EXCLUDED.idempotency_key, weights.idempotency_key)
                    RETURNING id;
                """, (
                    user_id, date_str, entry.weight_kg, entry.body_fat_pct,
                    entry.muscle_mass_kg, entry.water_pct, entry.bmi, trend,
                    entry.source, entry.notes, entry.external_id, measured_at_str, idemp_key, now_str
                ))
                res = cursor.fetchone()
                entry_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO weights (
                        user_id, date, weight_kg, body_fat_pct, muscle_mass_kg, water_pct,
                        bmi, trend_7d_kg, source, notes, external_id, measured_at, idempotency_key, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date, source) DO UPDATE SET
                        weight_kg = excluded.weight_kg,
                        body_fat_pct = excluded.body_fat_pct,
                        muscle_mass_kg = excluded.muscle_mass_kg,
                        water_pct = excluded.water_pct,
                        bmi = excluded.bmi,
                        trend_7d_kg = excluded.trend_7d_kg,
                        notes = excluded.notes,
                        external_id = COALESCE(excluded.external_id, weights.external_id),
                        measured_at = COALESCE(excluded.measured_at, weights.measured_at),
                        idempotency_key = COALESCE(excluded.idempotency_key, weights.idempotency_key)
                """, (
                    user_id, date_str, entry.weight_kg, entry.body_fat_pct,
                    entry.muscle_mass_kg, entry.water_pct, entry.bmi, trend,
                    entry.source, entry.notes, entry.external_id, measured_at_str, idemp_key, now_str
                ))
                entry_id = cursor.lastrowid
            conn.commit()

        entry_dict = entry.model_dump()
        entry_dict["id"] = entry_id
        entry_dict["trend_7d_kg"] = trend
        entry_dict["measured_at"] = measured_at_str
        entry_dict["idempotency_key"] = idemp_key
        entry_dict["created_at"] = datetime.fromisoformat(now_str)
        return WeightEntry(**entry_dict)

    def get_weights(
        self,
        limit: int = 30,
        user_id: int = 1,
        exclude_simulation: bool = False
    ) -> List[WeightEntry]:
        """Récupère l'historique des pesées ordonné par date croissante pour un utilisateur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if exclude_simulation:
                cursor.execute("""
                    SELECT * FROM (
                        SELECT * FROM weights WHERE user_id = ? AND source NOT IN ('simulation') ORDER BY date DESC LIMIT ?
                    ) sub ORDER BY date ASC
                """, (user_id, limit))
            else:
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
                is_simulated=(r["source"] in ("simulation", "demo") or "Démo" in (r.get("notes") or "")),
                notes=r["notes"],
                external_id=r.get("external_id"),
                measured_at=r.get("measured_at"),
                idempotency_key=r.get("idempotency_key"),
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
            ))
        return results

    def batch_insert_weights(self, entries: List[WeightEntry], user_id: int = 1) -> int:
        """Insère plusieurs pesées en une seule transaction (batch)."""
        if not entries:
            return 0
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            params_list = []
            for entry in entries:
                date_str = entry.date.isoformat()
                trend = entry.trend_7d_kg or 0.0
                idemp_key = entry.idempotency_key or (f"{entry.source}:{entry.external_id}" if entry.external_id else None)
                measured_at_str = entry.measured_at or now_str
                params_list.append((
                    user_id, date_str, entry.weight_kg, entry.body_fat_pct or 0.0,
                    entry.muscle_mass_kg or 0.0, entry.water_pct or 0.0,
                    entry.bmi or 0.0, trend, entry.source, entry.notes,
                    entry.external_id, measured_at_str, idemp_key, now_str
                ))
            sql = """
                INSERT INTO weights (
                    user_id, date, weight_kg, body_fat_pct, muscle_mass_kg, water_pct,
                    bmi, trend_7d_kg, source, notes, external_id, measured_at, idempotency_key, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, date, source) DO UPDATE SET
                    weight_kg = excluded.weight_kg,
                    body_fat_pct = excluded.body_fat_pct,
                    muscle_mass_kg = excluded.muscle_mass_kg,
                    water_pct = excluded.water_pct,
                    bmi = excluded.bmi,
                    trend_7d_kg = excluded.trend_7d_kg,
                    notes = excluded.notes,
                    external_id = COALESCE(excluded.external_id, weights.external_id),
                    measured_at = COALESCE(excluded.measured_at, weights.measured_at),
                    idempotency_key = COALESCE(excluded.idempotency_key, weights.idempotency_key)
            """
            cursor.executemany(sql, params_list)
            conn.commit()
            return len(params_list)

    def get_weight_by_id(self, weight_id: int, user_id: int = 1) -> Optional[WeightEntry]:
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
            is_simulated=(r["source"] in ("simulation", "demo") or "Démo" in (r.get("notes") or "")),
            notes=r["notes"],
            external_id=r.get("external_id"),
            measured_at=r.get("measured_at"),
            idempotency_key=r.get("idempotency_key"),
            created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
        )

    def update_weight(self, weight_id: int, entry: WeightEntry, user_id: int = 1) -> Optional[WeightEntry]:
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

    def delete_weight(self, weight_id: int, user_id: int = 1) -> bool:
        """Supprime une pesée pour user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM weights WHERE id = ? AND user_id = ?", (weight_id, user_id))
            if not cursor.fetchone():
                return False
            cursor.execute("DELETE FROM weights WHERE id = ? AND user_id = ?", (weight_id, user_id))
            conn.commit()
            return True

    def insert_activity(self, entry: ActivityEntry, user_id: int = 1) -> ActivityEntry:
        """Insère ou met à jour une entrée d'activité pour user_id (avec support d'idempotence)."""
        if entry.external_id:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM activities WHERE user_id = ? AND source = ? AND external_id = ? LIMIT 1",
                    (user_id, entry.source, entry.external_id)
                )
                existing = cursor.fetchone()
                if existing:
                    return ActivityEntry(
                        id=existing["id"],
                        date=date.fromisoformat(existing["date"][:10]),
                        steps=existing["steps"],
                        active_calories_kcal=existing["active_calories_kcal"],
                        bmr_kcal=existing["bmr_kcal"],
                        total_burned_kcal=existing["total_burned_kcal"],
                        workout_minutes=existing["workout_minutes"],
                        workout_type=existing["workout_type"],
                        resting_hr_bpm=existing["resting_hr_bpm"],
                        hrv_ms=existing["hrv_ms"],
                        sleep_score=existing["sleep_score"],
                        source=existing["source"],
                        is_simulated=(existing["source"] in ("simulation", "demo")),
                        external_id=existing.get("external_id"),
                        idempotency_key=existing.get("idempotency_key"),
                        created_at=datetime.fromisoformat(existing["created_at"]) if existing["created_at"] else None
                    )

        now_str = datetime.now(timezone.utc).isoformat()
        date_str = entry.date.isoformat()
        idemp_key = entry.idempotency_key or (f"{entry.source}:{entry.external_id}" if entry.external_id else None)

        total_burned = entry.total_burned_kcal
        if total_burned <= 0 and (entry.bmr_kcal > 0 or entry.active_calories_kcal > 0):
            total_burned = round(entry.bmr_kcal + entry.active_calories_kcal, 1)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO activities (
                        user_id, date, steps, active_calories_kcal, bmr_kcal, total_burned_kcal,
                        workout_minutes, workout_type, resting_hr_bpm, hrv_ms, sleep_score,
                        source, external_id, idempotency_key, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date, source) DO UPDATE SET
                        steps = EXCLUDED.steps,
                        active_calories_kcal = EXCLUDED.active_calories_kcal,
                        bmr_kcal = EXCLUDED.bmr_kcal,
                        total_burned_kcal = EXCLUDED.total_burned_kcal,
                        workout_minutes = EXCLUDED.workout_minutes,
                        workout_type = EXCLUDED.workout_type,
                        resting_hr_bpm = EXCLUDED.resting_hr_bpm,
                        hrv_ms = EXCLUDED.hrv_ms,
                        sleep_score = EXCLUDED.sleep_score,
                        external_id = COALESCE(EXCLUDED.external_id, activities.external_id),
                        idempotency_key = COALESCE(EXCLUDED.idempotency_key, activities.idempotency_key)
                    RETURNING id;
                """, (
                    user_id, date_str, entry.steps, entry.active_calories_kcal,
                    entry.bmr_kcal, total_burned, entry.workout_minutes,
                    entry.workout_type, entry.resting_hr_bpm, entry.hrv_ms,
                    entry.sleep_score, entry.source, entry.external_id, idemp_key, now_str
                ))
                res = cursor.fetchone()
                entry_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO activities (
                        user_id, date, steps, active_calories_kcal, bmr_kcal, total_burned_kcal,
                        workout_minutes, workout_type, resting_hr_bpm, hrv_ms, sleep_score,
                        source, external_id, idempotency_key, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date, source) DO UPDATE SET
                        steps = excluded.steps,
                        active_calories_kcal = excluded.active_calories_kcal,
                        bmr_kcal = excluded.bmr_kcal,
                        total_burned_kcal = excluded.total_burned_kcal,
                        workout_minutes = excluded.workout_minutes,
                        workout_type = excluded.workout_type,
                        resting_hr_bpm = excluded.resting_hr_bpm,
                        hrv_ms = excluded.hrv_ms,
                        sleep_score = excluded.sleep_score,
                        external_id = COALESCE(excluded.external_id, activities.external_id),
                        idempotency_key = COALESCE(excluded.idempotency_key, activities.idempotency_key)
                """, (
                    user_id, date_str, entry.steps, entry.active_calories_kcal,
                    entry.bmr_kcal, total_burned, entry.workout_minutes,
                    entry.workout_type, entry.resting_hr_bpm, entry.hrv_ms,
                    entry.sleep_score, entry.source, entry.external_id, idemp_key, now_str
                ))
                entry_id = cursor.lastrowid
            conn.commit()

        entry_dict = entry.model_dump()
        entry_dict["id"] = entry_id
        entry_dict["total_burned_kcal"] = total_burned
        entry_dict["idempotency_key"] = idemp_key
        entry_dict["created_at"] = datetime.fromisoformat(now_str)
        return ActivityEntry(**entry_dict)

    def get_activities(
        self,
        limit: int = 30,
        user_id: int = 1,
        exclude_simulation: bool = False
    ) -> List[ActivityEntry]:
        """Récupère l'historique d'activité ordonné par date croissante pour un utilisateur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if exclude_simulation:
                cursor.execute("""
                    SELECT * FROM (
                        SELECT * FROM activities WHERE user_id = ? AND source NOT IN ('simulation') ORDER BY date DESC LIMIT ?
                    ) sub ORDER BY date ASC
                """, (user_id, limit))
            else:
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
                is_simulated=(r["source"] in ("simulation", "demo")),
                external_id=r.get("external_id"),
                idempotency_key=r.get("idempotency_key"),
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
            ))
        return results

    def batch_insert_activities(self, entries: List[ActivityEntry], user_id: int = 1) -> int:
        """Insère plusieurs activités en une seule transaction (batch)."""
        if not entries:
            return 0
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            params_list = []
            for entry in entries:
                date_str = entry.date.isoformat()
                total_burned = (
                    entry.total_burned_kcal
                    if entry.total_burned_kcal > 0
                    else (
                        round(entry.bmr_kcal + entry.active_calories_kcal, 1)
                        if (entry.bmr_kcal > 0 or entry.active_calories_kcal > 0)
                        else 0.0
                    )
                )
                idemp_key = entry.idempotency_key or (f"{entry.source}:{entry.external_id}" if entry.external_id else None)
                params_list.append((
                    user_id, date_str, entry.steps, entry.active_calories_kcal,
                    entry.bmr_kcal, total_burned, entry.workout_minutes,
                    entry.workout_type, entry.resting_hr_bpm, entry.hrv_ms,
                    entry.sleep_score, entry.source, entry.external_id, idemp_key, now_str
                ))
            sql = """
                INSERT INTO activities (
                    user_id, date, steps, active_calories_kcal, bmr_kcal, total_burned_kcal,
                    workout_minutes, workout_type, resting_hr_bpm, hrv_ms, sleep_score,
                    source, external_id, idempotency_key, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, date, source) DO UPDATE SET
                    steps = excluded.steps,
                    active_calories_kcal = excluded.active_calories_kcal,
                    bmr_kcal = excluded.bmr_kcal,
                    total_burned_kcal = excluded.total_burned_kcal,
                    workout_minutes = excluded.workout_minutes,
                    workout_type = excluded.workout_type,
                    resting_hr_bpm = excluded.resting_hr_bpm,
                    hrv_ms = excluded.hrv_ms,
                    sleep_score = excluded.sleep_score,
                    external_id = COALESCE(excluded.external_id, activities.external_id),
                    idempotency_key = COALESCE(excluded.idempotency_key, activities.idempotency_key)
            """
            cursor.executemany(sql, params_list)
            conn.commit()
            return len(params_list)

    def delete_activity(self, activity_id: int, user_id: int = 1) -> bool:
        """Supprime une activité physique spécifique par son identifiant pour user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM activities WHERE id = ? AND user_id = ?", (activity_id, user_id))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted

    def delete_demo_weights(self, user_id: Optional[int] = None) -> int:
        """Supprime les pesées de démonstration ou simulation."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if user_id is not None:
                cursor.execute("""
                    DELETE FROM weights
                    WHERE user_id = ?
                      AND (source IN ('demo', 'simulation') OR notes LIKE '%Démo%' OR notes LIKE '%Balance Démo%')
                """, (user_id,))
            else:
                cursor.execute("""
                    DELETE FROM weights
                    WHERE source IN ('demo', 'simulation') OR notes LIKE '%Démo%' OR notes LIKE '%Balance Démo%'
                """)
            count = cursor.rowcount if cursor.rowcount != -1 else 0
            conn.commit()
            return count

    def delete_demo_activities(self, user_id: Optional[int] = None) -> int:
        """Supprime les activités physiques de démonstration ou simulation."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if user_id is not None:
                cursor.execute("""
                    DELETE FROM activities
                    WHERE user_id = ? AND source IN ('demo', 'simulation')
                """, (user_id,))
            else:
                cursor.execute("""
                    DELETE FROM activities
                    WHERE source IN ('demo', 'simulation')
                """)
            count = cursor.rowcount if cursor.rowcount != -1 else 0
            conn.commit()
            return count

