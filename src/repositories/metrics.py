"""Repository pour la gestion des métriques enrichies (biométrie, workouts, sommeil, intraday, hydratation, raw ingest)."""

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from src.models import (
    DailyMetricsEntry, HydrationLogEntry, IntradaySampleEntry,
    RawIngestEntry, SleepSessionEntry, SleepStageEntry, WorkoutEntry
)
from src.repositories.base import BaseRepository


class MetricsRepository(BaseRepository):
    """Gestion des métriques quotidiennes, séances de sport, sommeil, haute fréquence et ingestion brute."""

    def insert_daily_metric(self, metric: DailyMetricsEntry, user_id: int = 1) -> DailyMetricsEntry:
        """Insère ou met à jour une métrique quotidienne multi-sources de façon idempotente."""
        now_str = datetime.now(timezone.utc).isoformat()
        date_str = metric.date.isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO daily_metrics (
                        user_id, date, source, steps, active_calories_kcal, total_calories_kcal,
                        resting_hr_bpm, hrv_rmssd_ms, hrv_sdnn_ms, spo2_pct, skin_temperature_c,
                        sleep_score, recovery_score, external_id, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date, source) DO UPDATE SET
                        steps = EXCLUDED.steps,
                        active_calories_kcal = EXCLUDED.active_calories_kcal,
                        total_calories_kcal = EXCLUDED.total_calories_kcal,
                        resting_hr_bpm = COALESCE(EXCLUDED.resting_hr_bpm, daily_metrics.resting_hr_bpm),
                        hrv_rmssd_ms = COALESCE(EXCLUDED.hrv_rmssd_ms, daily_metrics.hrv_rmssd_ms),
                        hrv_sdnn_ms = COALESCE(EXCLUDED.hrv_sdnn_ms, daily_metrics.hrv_sdnn_ms),
                        spo2_pct = COALESCE(EXCLUDED.spo2_pct, daily_metrics.spo2_pct),
                        skin_temperature_c = COALESCE(EXCLUDED.skin_temperature_c, daily_metrics.skin_temperature_c),
                        sleep_score = COALESCE(EXCLUDED.sleep_score, daily_metrics.sleep_score),
                        recovery_score = COALESCE(EXCLUDED.recovery_score, daily_metrics.recovery_score),
                        external_id = COALESCE(EXCLUDED.external_id, daily_metrics.external_id),
                        updated_at = EXCLUDED.updated_at
                    RETURNING id;
                """, (
                    user_id, date_str, metric.source, metric.steps, metric.active_calories_kcal,
                    metric.total_calories_kcal, metric.resting_hr_bpm, metric.hrv_rmssd_ms,
                    metric.hrv_sdnn_ms, metric.spo2_pct, metric.skin_temperature_c,
                    metric.sleep_score, metric.recovery_score, metric.external_id, now_str, now_str
                ))
                res = cursor.fetchone()
                m_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO daily_metrics (
                        user_id, date, source, steps, active_calories_kcal, total_calories_kcal,
                        resting_hr_bpm, hrv_rmssd_ms, hrv_sdnn_ms, spo2_pct, skin_temperature_c,
                        sleep_score, recovery_score, external_id, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date, source) DO UPDATE SET
                        steps = excluded.steps,
                        active_calories_kcal = excluded.active_calories_kcal,
                        total_calories_kcal = excluded.total_calories_kcal,
                        resting_hr_bpm = COALESCE(excluded.resting_hr_bpm, daily_metrics.resting_hr_bpm),
                        hrv_rmssd_ms = COALESCE(excluded.hrv_rmssd_ms, daily_metrics.hrv_rmssd_ms),
                        hrv_sdnn_ms = COALESCE(excluded.hrv_sdnn_ms, daily_metrics.hrv_sdnn_ms),
                        spo2_pct = COALESCE(excluded.spo2_pct, daily_metrics.spo2_pct),
                        skin_temperature_c = COALESCE(excluded.skin_temperature_c, daily_metrics.skin_temperature_c),
                        sleep_score = COALESCE(excluded.sleep_score, daily_metrics.sleep_score),
                        recovery_score = COALESCE(excluded.recovery_score, daily_metrics.recovery_score),
                        external_id = COALESCE(excluded.external_id, daily_metrics.external_id),
                        updated_at = excluded.updated_at
                """, (
                    user_id, date_str, metric.source, metric.steps, metric.active_calories_kcal,
                    metric.total_calories_kcal, metric.resting_hr_bpm, metric.hrv_rmssd_ms,
                    metric.hrv_sdnn_ms, metric.spo2_pct, metric.skin_temperature_c,
                    metric.sleep_score, metric.recovery_score, metric.external_id, now_str, now_str
                ))
                m_id = cursor.lastrowid
            conn.commit()

        d = metric.model_dump()
        d["id"] = m_id
        d["user_id"] = user_id
        d["created_at"] = datetime.fromisoformat(now_str)
        d["updated_at"] = datetime.fromisoformat(now_str)
        return DailyMetricsEntry(**d)

    def get_daily_metrics(
        self,
        limit: int = 30,
        source: Optional[str] = None,
        user_id: int = 1
    ) -> List[DailyMetricsEntry]:
        """Récupère l'historique des métriques journalières pour user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if source:
                cursor.execute("""
                    SELECT * FROM (
                        SELECT * FROM daily_metrics WHERE user_id = ? AND source = ? ORDER BY date DESC LIMIT ?
                    ) sub ORDER BY date ASC
                """, (user_id, source, limit))
            else:
                cursor.execute("""
                    SELECT * FROM (
                        SELECT * FROM daily_metrics WHERE user_id = ? ORDER BY date DESC LIMIT ?
                    ) sub ORDER BY date ASC
                """, (user_id, limit))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            d = dict(r)
            d["date"] = date.fromisoformat(d["date"][:10])
            if d.get("created_at"):
                d["created_at"] = datetime.fromisoformat(d["created_at"])
            if d.get("updated_at"):
                d["updated_at"] = datetime.fromisoformat(d["updated_at"])
            results.append(DailyMetricsEntry(**d))
        return results

    def insert_workout(self, workout: WorkoutEntry, user_id: int = 1) -> WorkoutEntry:
        """Insère ou déduplique une séance d'entraînement de façon idempotente."""
        if workout.external_id:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM workouts WHERE user_id = ? AND source = ? AND external_id = ? LIMIT 1",
                    (user_id, workout.source, workout.external_id)
                )
                existing = cursor.fetchone()
                if existing:
                    d = dict(existing)
                    if d.get("created_at"):
                        d["created_at"] = datetime.fromisoformat(d["created_at"])
                    if d.get("updated_at"):
                        d["updated_at"] = datetime.fromisoformat(d["updated_at"])
                    return WorkoutEntry(**d)

        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO workouts (
                        user_id, source, external_id, workout_type, start_time, end_time,
                        duration_minutes, calories_kcal, avg_hr_bpm, max_hr_bpm, distance_meters,
                        notes, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id;
                """, (
                    user_id, workout.source, workout.external_id, workout.workout_type,
                    workout.start_time, workout.end_time, workout.duration_minutes,
                    workout.calories_kcal, workout.avg_hr_bpm, workout.max_hr_bpm,
                    workout.distance_meters, workout.notes, now_str, now_str
                ))
                res = cursor.fetchone()
                w_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO workouts (
                        user_id, source, external_id, workout_type, start_time, end_time,
                        duration_minutes, calories_kcal, avg_hr_bpm, max_hr_bpm, distance_meters,
                        notes, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, workout.source, workout.external_id, workout.workout_type,
                    workout.start_time, workout.end_time, workout.duration_minutes,
                    workout.calories_kcal, workout.avg_hr_bpm, workout.max_hr_bpm,
                    workout.distance_meters, workout.notes, now_str, now_str
                ))
                w_id = cursor.lastrowid
            conn.commit()

        d = workout.model_dump()
        d["id"] = w_id
        d["user_id"] = user_id
        d["created_at"] = datetime.fromisoformat(now_str)
        d["updated_at"] = datetime.fromisoformat(now_str)
        return WorkoutEntry(**d)

    def get_workouts(self, limit: int = 30, user_id: int = 1) -> List[WorkoutEntry]:
        """Récupère la liste des séances d'entraînement."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM (
                    SELECT * FROM workouts WHERE user_id = ? ORDER BY start_time DESC LIMIT ?
                ) sub ORDER BY start_time ASC
            """, (user_id, limit))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            d = dict(r)
            if d.get("created_at"):
                d["created_at"] = datetime.fromisoformat(d["created_at"])
            if d.get("updated_at"):
                d["updated_at"] = datetime.fromisoformat(d["updated_at"])
            results.append(WorkoutEntry(**d))
        return results

    def insert_sleep_session(self, session: SleepSessionEntry, user_id: int = 1) -> SleepSessionEntry:
        """Enregistre une session de sommeil complète et ses phases associées de façon idempotente."""
        if session.external_id:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM sleep_sessions WHERE user_id = ? AND source = ? AND external_id = ? LIMIT 1",
                    (user_id, session.source, session.external_id)
                )
                existing = cursor.fetchone()
                if existing:
                    return self.get_sleep_session_by_id(existing["id"], user_id=user_id) or session

        now_str = datetime.now(timezone.utc).isoformat()
        date_str = session.date.isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO sleep_sessions (
                        user_id, source, external_id, date, start_time, end_time,
                        duration_minutes, efficiency_pct, sleep_debt_minutes, sleep_score,
                        deep_minutes, light_minutes, rem_minutes, awake_minutes,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id;
                """, (
                    user_id, session.source, session.external_id, date_str,
                    session.start_time, session.end_time, session.duration_minutes,
                    session.efficiency_pct, session.sleep_debt_minutes, session.sleep_score,
                    session.deep_minutes or 0, session.light_minutes or 0,
                    session.rem_minutes or 0, session.awake_minutes or 0,
                    now_str, now_str
                ))
                res = cursor.fetchone()
                s_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO sleep_sessions (
                        user_id, source, external_id, date, start_time, end_time,
                        duration_minutes, efficiency_pct, sleep_debt_minutes, sleep_score,
                        deep_minutes, light_minutes, rem_minutes, awake_minutes,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, session.source, session.external_id, date_str,
                    session.start_time, session.end_time, session.duration_minutes,
                    session.efficiency_pct, session.sleep_debt_minutes, session.sleep_score,
                    session.deep_minutes or 0, session.light_minutes or 0,
                    session.rem_minutes or 0, session.awake_minutes or 0,
                    now_str, now_str
                ))
                s_id = cursor.lastrowid

            saved_stages = []
            for st in session.stages:
                cursor.execute("""
                    INSERT INTO sleep_stages (sleep_session_id, stage, start_time, end_time, duration_seconds)
                    VALUES (?, ?, ?, ?, ?)
                """, (s_id, st.stage, st.start_time, st.end_time, st.duration_seconds))
                saved_stages.append(st)

            conn.commit()

        d = session.model_dump()
        d["id"] = s_id
        d["user_id"] = user_id
        d["stages"] = saved_stages
        d["created_at"] = datetime.fromisoformat(now_str)
        d["updated_at"] = datetime.fromisoformat(now_str)
        return SleepSessionEntry(**d)

    def get_sleep_session_by_id(self, session_id: int, user_id: int = 1) -> Optional[SleepSessionEntry]:
        """Récupère une session de sommeil avec toutes ses phases."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sleep_sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
            row = cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            d["date"] = date.fromisoformat(d["date"][:10])
            cursor.execute("SELECT * FROM sleep_stages WHERE sleep_session_id = ? ORDER BY start_time ASC", (session_id,))
            stages_rows = cursor.fetchall()
            d["stages"] = [SleepStageEntry(**dict(st)) for st in stages_rows]
            if d.get("created_at"):
                d["created_at"] = datetime.fromisoformat(d["created_at"])
            if d.get("updated_at"):
                d["updated_at"] = datetime.fromisoformat(d["updated_at"])
            return SleepSessionEntry(**d)

    def get_sleep_sessions(self, limit: int = 30, user_id: int = 1) -> List[SleepSessionEntry]:
        """Récupère l'historique des sessions de sommeil avec leurs phases détaillées."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM (
                    SELECT * FROM sleep_sessions WHERE user_id = ? ORDER BY date DESC LIMIT ?
                ) sub ORDER BY date ASC
            """, (user_id, limit))
            rows = cursor.fetchall()

            results = []
            for r in rows:
                d = dict(r)
                d["date"] = date.fromisoformat(d["date"][:10])
                cursor.execute(
                    "SELECT * FROM sleep_stages WHERE sleep_session_id = ? ORDER BY start_time ASC",
                    (d["id"],)
                )
                stages_rows = cursor.fetchall()
                d["stages"] = [SleepStageEntry(**dict(st)) for st in stages_rows]
                if d.get("created_at"):
                    d["created_at"] = datetime.fromisoformat(d["created_at"])
                if d.get("updated_at"):
                    d["updated_at"] = datetime.fromisoformat(d["updated_at"])
                results.append(SleepSessionEntry(**d))
        return results

    def insert_intraday_samples(self, samples: List[IntradaySampleEntry], user_id: int = 1) -> int:
        """Insère un lot d'échantillons haute fréquence (FC, pas horaires, SpO2)."""
        if not samples:
            return 0
        now_str = datetime.now(timezone.utc).isoformat()
        count = 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for s in samples:
                cursor.execute("""
                    INSERT INTO intraday_samples (user_id, source, metric_type, timestamp, value, unit, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, s.source, s.metric_type, s.timestamp, s.value, s.unit, now_str))
                count += 1
            conn.commit()
        return count

    def get_intraday_samples(
        self,
        metric_type: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 500,
        user_id: int = 1
    ) -> List[IntradaySampleEntry]:
        """Récupère les échantillons haute fréquence pour une métrique donnée."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM intraday_samples WHERE user_id = ? AND metric_type = ?"
            params: List[Any] = [user_id, metric_type]
            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time)
            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time)
            query += " ORDER BY timestamp ASC LIMIT ?"
            params.append(limit)
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            d = dict(r)
            if d.get("created_at"):
                d["created_at"] = datetime.fromisoformat(d["created_at"])
            results.append(IntradaySampleEntry(**d))
        return results

    def purge_and_aggregate_intraday(self, retention_days: int = 60, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Politique de rétention configurable (30 à 90 jours) : agrège d'abord vers daily_metrics puis purge dans la même transaction."""
        days = max(30, min(90, int(retention_days)))
        cutoff_date = (date.today() - timedelta(days=days)).isoformat()
        cutoff_iso = f"{cutoff_date}T00:00:00"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            query_agg = """
                SELECT 
                    user_id,
                    SUBSTR(timestamp, 1, 10) AS sample_date,
                    source,
                    metric_type,
                    AVG(value) AS avg_val,
                    MIN(value) AS min_val,
                    MAX(value) AS max_val,
                    SUM(value) AS sum_val,
                    COUNT(*) AS count_val
                FROM intraday_samples
                WHERE timestamp < ?
            """
            params: List[Any] = [cutoff_iso]
            if user_id:
                query_agg += " AND user_id = ?"
                params.append(user_id)
            query_agg += " GROUP BY user_id, SUBSTR(timestamp, 1, 10), source, metric_type"
            
            cursor.execute(query_agg, tuple(params))
            agg_rows = cursor.fetchall()
            
            summaries: Dict[Tuple[int, str, str], Dict[str, Any]] = {}
            for r in agg_rows:
                key = (r["user_id"], r["sample_date"], r["source"])
                if key not in summaries:
                    summaries[key] = {
                        "steps": 0,
                        "resting_hr": None,
                        "spo2": None
                    }
                m_type = r["metric_type"]
                if m_type in ("steps", "steps_hourly"):
                    summaries[key]["steps"] = int(r["sum_val"] or 0)
                elif m_type in ("hr", "heart_rate"):
                    summaries[key]["resting_hr"] = round(float(r["avg_val"] or 0))
                elif m_type in ("spo2", "spo2_pct"):
                    summaries[key]["spo2"] = round(float(r["avg_val"] or 0), 1)

            now_str = datetime.now(timezone.utc).isoformat()
            aggregated_count = 0
            for (u_id, s_date, src), data in summaries.items():
                if self.is_postgres:
                    cursor.execute("""
                        INSERT INTO daily_metrics (
                            user_id, date, source, steps, active_calories_kcal, total_calories_kcal,
                            resting_hr_bpm, spo2_pct, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, 0.0, 0.0, ?, ?, ?, ?)
                        ON CONFLICT(user_id, date, source) DO UPDATE SET
                            steps = CASE WHEN daily_metrics.steps = 0 THEN EXCLUDED.steps ELSE daily_metrics.steps END,
                            resting_hr_bpm = COALESCE(daily_metrics.resting_hr_bpm, EXCLUDED.resting_hr_bpm),
                            spo2_pct = COALESCE(daily_metrics.spo2_pct, EXCLUDED.spo2_pct),
                            updated_at = EXCLUDED.updated_at;
                    """, (u_id, s_date, src, data["steps"], data["resting_hr"], data["spo2"], now_str, now_str))
                else:
                    cursor.execute("""
                        INSERT INTO daily_metrics (
                            user_id, date, source, steps, active_calories_kcal, total_calories_kcal,
                            resting_hr_bpm, spo2_pct, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, 0.0, 0.0, ?, ?, ?, ?)
                        ON CONFLICT(user_id, date, source) DO UPDATE SET
                            steps = CASE WHEN daily_metrics.steps = 0 THEN excluded.steps ELSE daily_metrics.steps END,
                            resting_hr_bpm = COALESCE(daily_metrics.resting_hr_bpm, excluded.resting_hr_bpm),
                            spo2_pct = COALESCE(daily_metrics.spo2_pct, excluded.spo2_pct),
                            updated_at = excluded.updated_at;
                    """, (u_id, s_date, src, data["steps"], data["resting_hr"], data["spo2"], now_str, now_str))
                aggregated_count += 1

            if user_id:
                cursor.execute(
                    "DELETE FROM intraday_samples WHERE user_id = ? AND timestamp < ?",
                    (user_id, cutoff_iso)
                )
            else:
                cursor.execute("DELETE FROM intraday_samples WHERE timestamp < ?", (cutoff_iso,))
            deleted = cursor.rowcount if hasattr(cursor, "rowcount") else 0
            conn.commit()

        return {
            "status": "success",
            "retention_days": days,
            "cutoff_timestamp": cutoff_iso,
            "aggregated_days": aggregated_count,
            "purged_samples": deleted
        }

    def insert_hydration_log(self, entry: HydrationLogEntry, user_id: int = 1) -> HydrationLogEntry:
        """Enregistre un apport hydrique."""
        if entry.external_id:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM hydration_logs WHERE user_id = ? AND source = ? AND external_id = ? LIMIT 1",
                    (user_id, entry.source, entry.external_id)
                )
                existing = cursor.fetchone()
                if existing:
                    d = dict(existing)
                    d["date"] = date.fromisoformat(d["date"][:10])
                    if d.get("created_at"):
                        d["created_at"] = datetime.fromisoformat(d["created_at"])
                    return HydrationLogEntry(**d)

        now_str = datetime.now(timezone.utc).isoformat()
        date_str = entry.date.isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO hydration_logs (user_id, date, timestamp, volume_ml, source, external_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    RETURNING id;
                """, (user_id, date_str, entry.timestamp, entry.volume_ml, entry.source, entry.external_id, now_str))
                res = cursor.fetchone()
                h_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO hydration_logs (user_id, date, timestamp, volume_ml, source, external_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, date_str, entry.timestamp, entry.volume_ml, entry.source, entry.external_id, now_str))
                h_id = cursor.lastrowid
            conn.commit()

        d = entry.model_dump()
        d["id"] = h_id
        d["user_id"] = user_id
        d["created_at"] = datetime.fromisoformat(now_str)
        return HydrationLogEntry(**d)

    def insert_raw_ingest(
        self,
        source: str,
        payload: Union[Dict[str, Any], str],
        user_id: int = 1,
        endpoint: Optional[str] = None,
        idempotency_key: Optional[str] = None
    ) -> RawIngestEntry:
        """Stocke le payload JSON brut horodaté pour audit et rejeu de façon strictement idempotente."""
        payload_str = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)
        now_str = datetime.now(timezone.utc).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                if idempotency_key:
                    cursor.execute("""
                        INSERT INTO raw_ingest (user_id, source, endpoint, idempotency_key, payload_json, status, received_at)
                        VALUES (?, ?, ?, ?, ?, 'received', ?)
                        ON CONFLICT (idempotency_key) DO NOTHING
                        RETURNING id, user_id, source, endpoint, idempotency_key, payload_json, status, received_at;
                    """, (user_id, source, endpoint, idempotency_key, payload_str, now_str))
                    res = cursor.fetchone()
                    if res:
                        conn.commit()
                        return RawIngestEntry(**res)
                    cursor.execute("SELECT * FROM raw_ingest WHERE idempotency_key = ? LIMIT 1", (idempotency_key,))
                    existing = cursor.fetchone()
                    return RawIngestEntry(**existing) if existing else RawIngestEntry(
                        id=None, user_id=user_id, source=source, endpoint=endpoint,
                        idempotency_key=idempotency_key, payload_json=payload_str,
                        status="received", received_at=now_str
                    )
                else:
                    cursor.execute("""
                        INSERT INTO raw_ingest (user_id, source, endpoint, idempotency_key, payload_json, status, received_at)
                        VALUES (?, ?, ?, ?, ?, 'received', ?)
                        RETURNING id;
                    """, (user_id, source, endpoint, idempotency_key, payload_str, now_str))
                    res = cursor.fetchone()
                    r_id = res["id"] if res else None
            else:
                if idempotency_key:
                    cursor.execute("""
                        INSERT INTO raw_ingest (user_id, source, endpoint, idempotency_key, payload_json, status, received_at)
                        VALUES (?, ?, ?, ?, ?, 'received', ?)
                        ON CONFLICT (idempotency_key) DO NOTHING;
                    """, (user_id, source, endpoint, idempotency_key, payload_str, now_str))
                    conn.commit()
                    if cursor.rowcount == 0:
                        cursor.execute("SELECT * FROM raw_ingest WHERE idempotency_key = ? LIMIT 1", (idempotency_key,))
                        existing = cursor.fetchone()
                        if existing:
                            return RawIngestEntry(**existing)
                    r_id = cursor.lastrowid
                else:
                    cursor.execute("""
                        INSERT INTO raw_ingest (user_id, source, endpoint, idempotency_key, payload_json, status, received_at)
                        VALUES (?, ?, ?, ?, ?, 'received', ?)
                    """, (user_id, source, endpoint, idempotency_key, payload_str, now_str))
                    r_id = cursor.lastrowid
            conn.commit()

        return RawIngestEntry(
            id=r_id,
            user_id=user_id,
            source=source,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
            payload_json=payload_str,
            status="received",
            received_at=now_str
        )
