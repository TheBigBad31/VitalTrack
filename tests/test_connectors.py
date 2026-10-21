"""Tests unitaires pour l'architecture IoT Santé et les connecteurs."""

import os
import tempfile
from datetime import date, timedelta
import pytest

from src.models import ActivityEntry, MealEntry, FoodItem, WeightEntry
from src.db import Database
from src.connectors.withings import WithingsScaleConnector
from src.connectors.oura import OuraRingConnector
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
    """Vérifie que la base démarre vierge et que reset_demo_data calcule la moyenne mobile sur 7 jours."""
    assert len(temp_db.get_weights(limit=50)) == 0
    temp_db.reset_demo_data()
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
    assert "health_connect" in config["devices"]
    assert "mobile_webhook" in config["devices"]

    connector = get_connector("withings")
    assert isinstance(connector, WithingsScaleConnector)

    gh_connector = get_connector("health_connect")
    from src.connectors.health_connect import GoogleHealthConnectConnector
    assert isinstance(gh_connector, GoogleHealthConnectConnector)

    template = TemplateHealthConnector()
    assert not template.is_configured
    assert template.sync_weights(date.today(), date.today()) == []


def test_google_health_connect_demo_and_config():
    """Teste le connecteur Google Health Connect en mode démo et configuré."""
    from src.connectors.health_connect import GoogleHealthConnectConnector

    # Mode Démo sans tokens
    demo_conn = GoogleHealthConnectConnector()
    assert not demo_conn.is_configured
    assert demo_conn.is_token_expired()

    start = date.today() - timedelta(days=6)
    end = date.today()
    activities = demo_conn.sync_activities(start, end)
    assert len(activities) == 7
    assert all(a.source == "health_connect" for a in activities)
    assert all(a.steps > 5000 for a in activities)
    assert all(a.sleep_score is not None for a in activities)

    # Scopes obligatoires
    assert len(demo_conn.REQUIRED_SCOPES) == 3
    assert any("fitness.activity.read" in s for s in demo_conn.REQUIRED_SCOPES)
    assert any("fitness.body.read" in s for s in demo_conn.REQUIRED_SCOPES)
    assert any("fitness.sleep.read" in s for s in demo_conn.REQUIRED_SCOPES)


def test_google_health_connect_token_refresh():
    """Teste la logique de rafraîchissement automatique de token OAuth2."""
    from src.connectors.health_connect import GoogleHealthConnectConnector

    # Connecteur configuré avec refresh_token
    conn = GoogleHealthConnectConnector(config={
        "client_id": "google_test_client_id.apps.googleusercontent.com",
        "client_secret": "sec_test_123",
        "refresh_token": "1//test_refresh_token_abc456",
        "access_token": "ya29.expired_token",
        "token_expiry": 1000  # Expiré
    })
    assert conn.is_configured
    assert conn.is_token_expired()

    # Rafraîchissement
    new_token = conn.refresh_access_token_if_needed()
    assert new_token is not None
    assert new_token != "ya29.expired_token"
    assert not conn.is_token_expired()
    assert conn.access_token == new_token


def test_google_health_connect_aggregate_parsing():
    """Teste le parsing d'un bucket aggregate de l'API Google Fitness / Health Connect."""
    from src.connectors.health_connect import GoogleHealthConnectConnector

    conn = GoogleHealthConnectConnector(config={"client_id": "test_id", "access_token": "valid_token"})

    bucket = {
        "startTimeMillis": "1760572800000",  # Millisecondes epoch
        "endTimeMillis": "1760659200000",
        "dataset": [
            {
                "dataSourceId": "derived:com.google.step_count.delta:com.google.android.gms:aggregated",
                "point": [
                    {"value": [{"intVal": 11850}]}
                ]
            },
            {
                "dataSourceId": "derived:com.google.calories.expended:com.google.android.gms:aggregated",
                "point": [
                    {"value": [{"fpVal": 520.5}]}
                ]
            },
            {
                "dataSourceId": "derived:com.google.calories.bmr:com.google.android.gms:aggregated",
                "point": [
                    {"value": [{"fpVal": 1765.0}]}
                ]
            },
            {
                "dataSourceId": "derived:com.google.heart_rate.bpm:com.google.android.gms:resting_heart_rate",
                "point": [
                    {"value": [{"fpVal": 56.0}]}
                ]
            },
            {
                "dataSourceId": "derived:com.google.sleep.segment:com.google.android.gms:sleep_score",
                "point": [
                    {"value": [{"intVal": 87}]}
                ]
            }
        ]
    }

    entry = conn.parse_google_fit_aggregate(bucket)
    assert entry.steps == 11850
    assert entry.active_calories_kcal == 520.5
    assert entry.bmr_kcal == 1765.0
    assert entry.total_burned_kcal == round(1765.0 + 520.5, 1)
    assert entry.resting_hr_bpm == 56
    assert entry.sleep_score == 87
    assert entry.source == "health_connect"


def test_google_health_connect_webhook_hmac_and_bearer():
    """Teste la validation de sécurité HMAC-SHA256 et Bearer token de la passerelle Android."""
    import hashlib
    import hmac
    from src.connectors.health_connect import GoogleHealthConnectConnector

    secret = "my_health_secret_key"
    conn = GoogleHealthConnectConnector(config={"webhook_secret": secret, "bearer_token": "token_compagnon_123"})

    payload_bytes = b'{"date": "2026-10-18", "steps": 12500, "active_calories_kcal": 540}'
    sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()

    # HMAC valide et invalide
    assert conn.verify_webhook_hmac(payload_bytes, sig)
    assert conn.verify_webhook_hmac(payload_bytes, f"sha256={sig}")
    assert not conn.verify_webhook_hmac(payload_bytes, "mauvaise_signature")

    # Bearer token
    assert conn.verify_bearer_token("Bearer token_compagnon_123")
    assert not conn.verify_bearer_token("Bearer mauvais_token")

    # Traitement du payload
    weight, act = conn.process_webhook_payload({
        "date": "2026-10-18",
        "hourly_steps": {"08:00": 3000, "12:00": 4500, "18:00": 5200},
        "resting_hr_bpm": 58,
        "sleep_score": 86
    })
    assert act is not None
    assert act.steps == 12700  # Somme des pas horaires
    assert act.resting_hr_bpm == 58
    assert act.sleep_score == 86
    assert act.source == "health_connect"
