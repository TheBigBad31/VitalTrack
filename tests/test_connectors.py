"""Tests unitaires pour l'architecture IoT Santé et les connecteurs."""

import os
import tempfile
from datetime import date, timedelta
import pytest

from src.models import ActivityEntry, MealEntry, FoodItem, WeightEntry
from src.db import Database
from src.connectors.withings import WithingsScaleConnector
from src.connectors.oura import OuraRingConnector
from src.connectors.ringconn import RingConnConnector
from src.connectors.webhook import MobileHealthWebhookConnector
from src.connectors.template import TemplateHealthConnector
from src.connectors.registry import get_connector, load_devices_config


@pytest.fixture
def temp_db():
    """Crée une base de données temporaire pour chaque test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name
    # Supprimer le fichier pour tester l'initialisation et le seed
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass
    
    db = Database(db_path=temp_path)
    yield db

    # Nettoyage
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


def test_models_validation():
    """Vérifie la création et validation des modèles de données."""
    today = date.today()
    weight = WeightEntry(
        date=today,
        weight_kg=80.5,
        body_fat_pct=19.2,
        muscle_mass_kg=39.0,
        water_pct=58.0,
        bmi=24.1,
        source="withings"
    )
    assert weight.weight_kg == 80.5
    assert weight.source == "withings"

    activity = ActivityEntry(
        date=today,
        steps=10500,
        active_calories_kcal=450.0,
        bmr_kcal=1750.0,
        total_burned_kcal=2200.0,
        workout_minutes=45,
        resting_hr_bpm=58,
        hrv_ms=62.5,
        sleep_score=85,
        source="oura"
    )
    assert activity.steps == 10500
    assert activity.sleep_score == 85

    meal = MealEntry(
        date=today,
        meal_type="lunch",
        total_calories_kcal=650.0,
        protein_g=45.0,
        carbs_g=60.0,
        fat_g=22.0,
        items=[
            FoodItem(name="Blanc de poulet", portion_g=150, calories_kcal=240, protein_g=35, carbs_g=0, fat_g=4),
            FoodItem(name="Riz basmati", portion_g=200, calories_kcal=260, protein_g=6, carbs_g=55, fat_g=1)
        ]
    )
    assert meal.meal_type == "lunch"
    assert len(meal.items) == 2


def test_db_auto_seed_and_trend(temp_db):
    """Vérifie le seed automatique de 30 jours et le calcul de la moyenne mobile sur 7 jours."""
    weights = temp_db.get_weights(limit=50)
    assert len(weights) == 30
    # Vérifie que la tendance est bien calculée pour chaque entrée
    for w in weights:
        assert w.trend_7d_kg is not None
        assert 70.0 < w.trend_7d_kg < 90.0

    activities = temp_db.get_activities(limit=50)
    assert len(activities) == 30
    assert activities[0].steps > 0
    assert activities[0].total_burned_kcal > 0


def test_db_insert_and_custom_trend(temp_db):
    """Vérifie l'insertion et la mise à jour de pesée avec calcul de tendance glissante 7j."""
    tomorrow = date.today() + timedelta(days=1)
    new_entry = WeightEntry(
        date=tomorrow,
        weight_kg=79.5,
        source="manual"
    )
    saved = temp_db.insert_weight(new_entry)
    assert saved.id is not None
    assert saved.trend_7d_kg is not None
    # La tendance doit être une moyenne cohérente
    assert round(saved.trend_7d_kg, 1) > 75.0


def test_withings_connector_demo_mode():
    """Teste le WithingsScaleConnector en mode démo (sans identifiants)."""
    connector = WithingsScaleConnector()
    assert not connector.is_configured
    
    start = date.today() - timedelta(days=7)
    end = date.today()
    weights = connector.sync_weights(start, end)
    assert len(weights) == 8
    assert all(w.source == "withings" for w in weights)
    assert all(w.weight_kg > 70 for w in weights)


def test_withings_connector_parsing():
    """Teste le parsing d'une trame réelle Withings API getmeas."""
    connector = WithingsScaleConnector(config={"client_id": "test_id", "access_token": "test_tok", "user_height_m": 1.80})
    assert connector.is_configured

    mock_grp = {
        "date": 1700000000,
        "measures": [
            {"value": 81200, "unit": -3, "type": 1},   # Poids 81.2 kg
            {"value": 1850, "unit": -2, "type": 6},    # Masse grasse 18.5%
            {"value": 39500, "unit": -3, "type": 76},  # Muscle 39.5 kg
            {"value": 5720, "unit": -2, "type": 77}    # Eau 57.2%
        ]
    }
    parsed = connector.parse_withings_measure_group(mock_grp)
    assert parsed.weight_kg == 81.2
    assert parsed.body_fat_pct == 18.5
    assert parsed.muscle_mass_kg == 39.5
    assert parsed.water_pct == 57.2
    assert parsed.bmi == round(81.2 / (1.80 ** 2), 1)


def test_oura_connector_demo_mode():
    """Teste le connecteur Oura en mode démo."""
    connector = OuraRingConnector()
    assert not connector.is_configured

    start = date.today() - timedelta(days=5)
    end = date.today()
    acts = connector.sync_activities(start, end)
    assert len(acts) == 6
    assert all(a.source == "oura" for a in acts)
    assert all(a.sleep_score is not None for a in acts)
    assert all(a.hrv_ms is not None for a in acts)


def test_oura_connector_parsing():
    """Teste le parsing des payloads Oura Ring v2."""
    connector = OuraRingConnector(config={"personal_access_token": "oura_token_secret"})
    assert connector.is_configured

    activity_payload = {
        "day": "2026-10-15",
        "steps": 12450,
        "active_calories": 520.0,
        "total_calories": 2350.0
    }
    readiness_payload = {
        "day": "2026-10-15",
        "score": 88,
        "contributors": {
            "resting_heart_rate": 54
        }
    }
    sleep_payload = {
        "day": "2026-10-15",
        "score": 91
    }

    parsed = connector.parse_oura_daily_data(
        activity=activity_payload,
        readiness=readiness_payload,
        sleep=sleep_payload
    )
    assert parsed.date == date(2026, 10, 15)
    assert parsed.steps == 12450
    assert parsed.active_calories_kcal == 520.0
    assert parsed.resting_hr_bpm == 54
    assert parsed.sleep_score == 91
    assert parsed.source == "oura"


def test_mobile_webhook_connector():
    """Teste le connecteur universel de webhook (Apple Health / Android Health Connect)."""
    connector = MobileHealthWebhookConnector(config={"webhook_secret": "my_secret_token", "user_height_m": 1.75})
    
    # Auth test
    assert connector.authenticate_request("my_secret_token")
    assert not connector.authenticate_request("bad_token")

    # Payload Apple Santé combinant Pesée et Activité
    payload = {
        "date": "2026-10-16",
        "source": "apple_health",
        "weight_kg": 79.8,
        "body_fat_pct": 18.2,
        "steps": 13200,
        "active_calories_kcal": 580.0,
        "resting_hr_bpm": 56,
        "hrv_ms": 68.0,
        "sleep_score": 87
    }

    weight, activity = connector.process_webhook_payload(payload)
    assert weight is not None
    assert weight.weight_kg == 79.8
    assert weight.body_fat_pct == 18.2
    assert weight.source == "apple_health"
    assert weight.bmi == round(79.8 / (1.75 ** 2), 1)

    assert activity is not None
    assert activity.steps == 13200
    assert activity.active_calories_kcal == 580.0
    assert activity.resting_hr_bpm == 56
    assert activity.hrv_ms == 68.0
    assert activity.source == "apple_health"


def test_template_and_registry():
    """Teste le registre déclaratif et le connecteur template."""
    config = load_devices_config()
    assert "devices" in config
    assert "withings" in config["devices"]
    assert "oura" in config["devices"]
    assert "ringconn" in config["devices"]
    assert "mobile_webhook" in config["devices"]

    connector = get_connector("withings")
    assert isinstance(connector, WithingsScaleConnector)

    ring_conn = get_connector("ringconn")
    assert isinstance(ring_conn, RingConnConnector)

    template = TemplateHealthConnector()
    assert not template.is_configured
    assert template.sync_weights(date.today(), date.today()) == []


def test_ringconn_connector_demo_mode():
    """Teste le connecteur RingConn en mode démo (30 jours réalistes Gen 3)."""
    connector = RingConnConnector()
    assert not connector.is_configured

    start = date.today() - timedelta(days=6)
    end = date.today()
    activities = connector.sync_activities(start, end)
    assert len(activities) == 7
    assert all(a.source == "ringconn" for a in activities)
    assert all(a.steps > 8000 for a in activities)
    assert all(a.resting_hr_bpm in [56, 59] for a in activities)
    assert all(a.hrv_ms is not None for a in activities)
    assert all(a.sleep_score is not None for a in activities)
    assert connector.sync_weights(start, end) == []


def test_ringconn_connector_parsing_and_mock():
    """Teste le parsing précis des payloads RingConn Cloud API (Gen 3)."""
    connector = RingConnConnector(config={"api_key": "rc_live_secret_token_123"})
    assert connector.is_configured

    activity_payload = {
        "date": "2026-10-18",
        "steps": 12850,
        "active_calories": 535.0,
        "bmr": 1780.0,
        "total_calories": 2315.0,
        "workout_minutes": 50,
        "resting_heart_rate": 55
    }
    sleep_payload = {
        "score": 89,
        "avg_heart_rate": 54,
        "hrv": 64.5
    }
    hrv_payload = {
        "rmssd": 65.2
    }

    entry = connector.parse_ringconn_daily_data(
        activity_data=activity_payload,
        sleep_data=sleep_payload,
        hrv_data=hrv_payload
    )

    assert entry.date == date(2026, 10, 18)
    assert entry.steps == 12850
    assert entry.active_calories_kcal == 535.0
    assert entry.bmr_kcal == 1780.0
    assert entry.total_burned_kcal == 2315.0
    assert entry.resting_hr_bpm == 55
    assert entry.hrv_ms == 65.2
    assert entry.sleep_score == 89
    assert entry.source == "ringconn"


def test_ringconn_webhook_auth_and_mobile_gateway():
    """Teste l'authentification et l'ingestion via webhook sécurisé pour RingConn."""
    connector = RingConnConnector(config={"webhook_token": "my_ringconn_secret"})
    assert connector.authenticate_webhook("my_ringconn_secret") is True
    assert connector.authenticate_webhook("invalid_secret") is False

    # Webhook mobile
    mobile_connector = MobileHealthWebhookConnector(config={"webhook_secret": "my_ringconn_secret"})
    payload = {
        "date": "2026-10-19",
        "source": "ringconn_gen3",
        "steps": 11450,
        "active_calories_kcal": 490.0,
        "resting_hr_bpm": 56,
        "hrv_ms": 62.0,
        "sleep_score": 88,
        "workout_minutes": 40,
        "workout_type": "Marche & Cardio (RingConn Gen 3)"
    }
    weight, act = mobile_connector.process_webhook_payload(payload)
    assert weight is None
    assert act is not None
    assert act.steps == 11450
    assert act.active_calories_kcal == 490.0
    assert act.resting_hr_bpm == 56
    assert act.hrv_ms == 62.0
    assert act.sleep_score == 88
    assert act.source == "ringconn"
