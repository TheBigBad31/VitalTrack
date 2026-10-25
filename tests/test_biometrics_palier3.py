"""Tests d'intégration et unitaires pour les spécifications Palier 3 - Ticket 2.

Vérifie :
1. Migrations Alembic & nouvelles tables (daily_metrics, workouts, sleep_sessions, sleep_stages, intraday_samples, hydration_logs, raw_ingest, user_consents)
2. Ingestion idempotente (external_id / source) sur weights, activities et webhooks
3. Support multi-mesures avec measured_at
4. Sécurité des tokens au repos (chiffrement/déchiffrement Fernet)
5. Endpoints RGPD : export JSON, export CSV, gestion des consentements, droit à l'oubli / suppression de compte
"""

import io
import os
import tempfile
from datetime import date, datetime, timezone
import pytest
from fastapi.testclient import TestClient

from alembic.config import Config
from alembic import command
from src.app import app
from src.crypto import encrypt_data, decrypt_data, encrypt_credentials, decrypt_credentials
from src.db import Database
from src.models import (
    DailyMetricsEntry, WorkoutEntry, SleepSessionEntry, SleepStageEntry,
    IntradaySampleEntry, HydrationLogEntry, WeightEntry, ActivityEntry
)


def test_alembic_v2_migration_and_tables():
    """Vérifie que la migration Alembic 0002 crée toutes les tables du Palier 3 sur SQLite."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name

    try:
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{temp_path}")

        # Upgrade head (0001 -> 0002)
        command.upgrade(cfg, "head")

        import sqlite3
        conn = sqlite3.connect(temp_path)
        tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if r[0] != "sqlite_sequence"
        }
        conn.close()

        palier3_tables = {
            "daily_metrics",
            "workouts",
            "sleep_sessions",
            "sleep_stages",
            "intraday_samples",
            "hydration_logs",
            "raw_ingest",
            "user_consents"
        }
        assert palier3_tables.issubset(tables), f"Tables Palier 3 manquantes: {palier3_tables - tables}"

        # Downgrade 0001
        command.downgrade(cfg, "0001_initial_schema")
        conn = sqlite3.connect(temp_path)
        tables_down = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        for t in palier3_tables:
            assert t not in tables_down
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_idempotent_weight_and_activity_ingestion():
    """Vérifie que les doublons webhook/cron avec (source, external_id) sont dédupliqués de manière transparente."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name

    try:
        db = Database(db_path=temp_path, auto_migrate=True)
        user_id = 1

        w1 = WeightEntry(
            date=date(2026, 10, 25),
            weight_kg=78.2,
            source="withings",
            external_id="withings_measure_999",
            measured_at="2026-10-25T07:15:00Z"
        )
        res1 = db.insert_weight(w1, user_id=user_id)
        assert res1.id is not None

        # Ré-envoi identique
        w2 = WeightEntry(
            date=date(2026, 10, 25),
            weight_kg=78.2,
            source="withings",
            external_id="withings_measure_999",
            measured_at="2026-10-25T07:15:00Z"
        )
        res2 = db.insert_weight(w2, user_id=user_id)
        assert res2.id == res1.id

        # Activité identique
        a1 = ActivityEntry(
            date=date(2026, 10, 25),
            steps=10500,
            active_calories_kcal=450.0,
            source="ringconn",
            external_id="ringconn_act_888"
        )
        act_res1 = db.insert_activity(a1, user_id=user_id)

        a2 = ActivityEntry(
            date=date(2026, 10, 25),
            steps=10500,
            active_calories_kcal=450.0,
            source="ringconn",
            external_id="ringconn_act_888"
        )
        act_res2 = db.insert_activity(a2, user_id=user_id)
        assert act_res2.id == act_res1.id
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_daily_metrics_and_workouts_persistence():
    """Vérifie l'enregistrement des métriques multi-sources et des séances d'entraînement."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name

    try:
        db = Database(db_path=temp_path, auto_migrate=True)
        user_id = 1

        metric = DailyMetricsEntry(
            user_id=user_id,
            date=date(2026, 10, 25),
            source="ringconn",
            steps=12400,
            active_calories_kcal=520.0,
            total_calories_kcal=2300.0,
            resting_hr_bpm=52,
            hrv_rmssd_ms=64.5,
            hrv_sdnn_ms=78.0,
            spo2_pct=98.5,
            skin_temperature_c=36.4,
            sleep_score=88,
            recovery_score=92,
            external_id="ringconn_metric_1"
        )
        saved_m = db.insert_daily_metric(metric, user_id=user_id)
        assert saved_m.id is not None
        assert saved_m.hrv_rmssd_ms == 64.5

        # Workouts
        workout = WorkoutEntry(
            user_id=user_id,
            source="strava",
            external_id="strava_run_12345",
            workout_type="running",
            start_time="2026-10-25T08:00:00Z",
            end_time="2026-10-25T08:45:00Z",
            duration_minutes=45,
            calories_kcal=480.0,
            avg_hr_bpm=155,
            max_hr_bpm=172,
            distance_meters=8500.0
        )
        saved_w = db.insert_workout(workout, user_id=user_id)
        assert saved_w.id is not None

        # Re-insert workout (idempotence)
        w_dup = db.insert_workout(workout, user_id=user_id)
        assert w_dup.id == saved_w.id
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_sleep_sessions_and_intraday_retention():
    """Vérifie le stockage des phases de sommeil et la rétention intraday."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name

    try:
        db = Database(db_path=temp_path, auto_migrate=True)
        user_id = 1

        session = SleepSessionEntry(
            user_id=user_id,
            source="ringconn",
            external_id="sleep_session_777",
            date=date(2026, 10, 25),
            start_time="2026-10-24T23:00:00Z",
            end_time="2026-10-25T07:00:00Z",
            duration_minutes=480,
            efficiency_pct=92.0,
            sleep_score=85,
            stages=[
                SleepStageEntry(stage="deep", start_time="2026-10-24T23:30:00Z", end_time="2026-10-25T01:30:00Z", duration_seconds=7200),
                SleepStageEntry(stage="rem", start_time="2026-10-25T01:30:00Z", end_time="2026-10-25T03:00:00Z", duration_seconds=5400)
            ]
        )
        saved_s = db.insert_sleep_session(session, user_id=user_id)
        assert saved_s.id is not None
        assert len(saved_s.stages) == 2

        # Intraday samples
        samples = [
            IntradaySampleEntry(source="ringconn", metric_type="hr", timestamp="2026-08-01T12:00:00Z", value=62.0, unit="bpm"),
            IntradaySampleEntry(source="ringconn", metric_type="hr", timestamp="2026-10-25T12:00:00Z", value=68.0, unit="bpm")
        ]
        inserted = db.insert_intraday_samples(samples, user_id=user_id)
        assert inserted == 2

        # Purge et agrégation de rétention 60 jours
        purge_res = db.purge_and_aggregate_intraday(retention_days=60, user_id=user_id)
        assert purge_res["status"] == "success"
        assert purge_res["purged_samples"] >= 1
        assert purge_res["aggregated_days"] >= 1

        # Vérifier que l'agrégat a bien été sauvegardé dans daily_metrics
        daily_metrics = db.get_daily_metrics(limit=10, user_id=user_id)
        agg_date_str = "2026-08-01"
        matched_agg = [m for m in daily_metrics if m.date.isoformat() == agg_date_str]
        assert len(matched_agg) > 0
        assert matched_agg[0].resting_hr_bpm == 62
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_encryption_at_rest_and_rgpd_endpoints():
    """Vérifie le chiffrement réversible des jetons d'API et les endpoints d'export / droit à l'oubli."""
    # Test chiffrement Fernet
    secret = "vitaltrack_oauth_token_secret_xyz"
    encrypted = encrypt_data(secret)
    assert encrypted.startswith("enc::")
    assert decrypt_data(encrypted) == secret

    client = TestClient(app)

    # 1. Export JSON
    resp_json = client.get("/api/export/json")
    assert resp_json.status_code == 200
    export_data = resp_json.json()
    assert "weights" in export_data
    assert "daily_metrics" in export_data
    assert export_data["version"] == "3.0"

    # 2. Export CSV (sans limite)
    resp_csv = client.get("/api/export/csv")
    assert resp_csv.status_code == 200
    assert "text/csv" in resp_csv.headers["content-type"]
    assert "### SECTION: WEIGHTS ###" in resp_csv.text

    # 3. Consentements RGPD
    resp_c_get = client.get("/api/user/consents")
    assert resp_c_get.status_code == 200
    assert resp_c_get.json()["consents"]["biometrics"] is True

    resp_c_post = client.post("/api/user/consents", json={"category": "analytics", "consented": False})
    assert resp_c_post.status_code == 200
    assert resp_c_post.json()["consent"]["consented"] is False

    # 4. Suppression de données biométriques uniquement (sans supprimer le compte)
    resp_del_data = client.delete("/api/user/data?confirm=true")
    assert resp_del_data.status_code == 200
    assert "purgées avec succès" in resp_del_data.json()["message"]

    # 5. Droit à l'oubli complet avec confirmation
    resp_del_unconfirmed = client.delete("/api/user/account?confirm=false")
    assert resp_del_unconfirmed.status_code == 400

    resp_del_account = client.delete("/api/user/account?confirm=true")
    assert resp_del_account.status_code == 200
    assert "définitivement supprimés" in resp_del_account.json()["message"]
