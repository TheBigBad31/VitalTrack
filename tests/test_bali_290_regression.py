"""Test de non-régression pour BALI-290.

Vérifie :
1. Prise en compte du fuseau horaire local (ex: Europe/Paris) pour la résolution de la date des pesées
   ingérées via webhooks / Android Health Connect / Withings, évitant le décalage UTC et les pesées écrasées.
2. Ingestion des lots de pesées avec external_id et measured_at sans perte.
3. Disponibilité des pesées sur les endpoints /api/weights et /api/dashboard sur une fenêtre complète.
"""

from datetime import date, datetime, timezone
import zoneinfo
import pytest
from fastapi.testclient import TestClient

from src.models import WeightEntry
from src.connectors.webhook import MobileHealthWebhookConnector
from src.connectors.withings import WithingsScaleConnector


def test_webhook_timezone_paris_measured_at_resolution():
    """Vérifie qu'un timestamp UTC tardif (ex: 23:30 UTC) est résolu au jour local J+1 (00:30 Paris)."""
    connector = MobileHealthWebhookConnector()
    
    # 22 novembre 2026 à 23:30 UTC = 23 novembre 2026 à 00:30 Paris (UTC+1)
    payload_late_utc = {
        "weight_kg": 78.2,
        "measured_at": "2026-11-22T23:30:00Z",
        "source": "health_connect",
        "external_id": "weight_sync_101"
    }

    w_entry, _ = connector.process_webhook_payload(payload_late_utc, user_timezone="Europe/Paris")
    assert w_entry is not None
    assert w_entry.date == date(2026, 11, 23)
    assert w_entry.weight_kg == 78.2
    assert w_entry.external_id == "weight_sync_101"


def test_webhook_epoch_millis_measured_at_resolution():
    """Vérifie la conversion epoch millis avec fuseau horaire."""
    connector = MobileHealthWebhookConnector()
    
    # Epoch correspondant à 2026-11-22T23:30:00Z -> 1795390200000 ms
    epoch_ms = int(datetime(2026, 11, 22, 23, 30, 0, tzinfo=timezone.utc).timestamp() * 1000)

    payload_epoch = {
        "weight_kg": 77.9,
        "measured_at": epoch_ms,
        "source": "health_connect",
        "weight_external_id": "weight_hc_202"
    }

    w_entry, _ = connector.process_webhook_payload(payload_epoch, user_timezone="Europe/Paris")
    assert w_entry is not None
    assert w_entry.date == date(2026, 11, 23)
    assert w_entry.weight_kg == 77.9
    assert w_entry.external_id == "weight_hc_202"


def test_withings_measure_group_timezone_and_grpid():
    """Vérifie que le connecteur Withings extrait la date locale Paris et l'external_id grpid."""
    connector = WithingsScaleConnector()
    
    epoch_utc = int(datetime(2026, 11, 22, 23, 30, 0, tzinfo=timezone.utc).timestamp())
    mock_grp = {
        "grpid": 987654321,
        "date": epoch_utc,
        "category": 1,
        "measures": [
            {"value": 78500, "unit": -3, "type": 1},  # 78.5 kg
            {"value": 1650, "unit": -2, "type": 6},   # 16.5 %
        ]
    }

    entry = connector.parse_withings_measure_group(mock_grp, user_timezone="Europe/Paris")
    assert entry is not None
    assert entry.date == date(2026, 11, 23)
    assert entry.weight_kg == 78.5
    assert entry.body_fat_pct == 16.5
    assert entry.external_id == "987654321"


def test_daily_weights_not_truncated_in_dashboard(client, db):
    """Vérifie que /api/dashboard et /api/weights conservent plus de 30 pesées quotidiennes consécutives."""

    # Inscription
    reg = client.post("/api/auth/register", json={
        "email": "daily_weights_user@vitaltrack.io",
        "password": "Password123!",
        "name": "Daily User"
    })
    token = reg.json()["access_token"]
    user_id = reg.json()["user"]["id"]
    headers = {"Authorization": f"Bearer {token}"}

    # Insérer 45 pesées quotidiennes successives (45 jours)
    from datetime import timedelta
    start_d = date(2026, 10, 1)
    for i in range(45):
        d = start_d + timedelta(days=i)
        w = WeightEntry(
            date=d,
            weight_kg=round(78.0 + (i * 0.05), 2),
            source="manual",
            is_simulated=False
        )
        db.insert_weight(w, user_id=user_id)

    # 1. Vérifier /api/weights par défaut
    res_weights = client.get("/api/weights", headers=headers)
    assert res_weights.status_code == 200
    weights_list = res_weights.json()
    assert len(weights_list) >= 45, f"Attendu au moins 45 pesées, reçu {len(weights_list)}"

    # 2. Vérifier /api/dashboard
    res_dash = client.get("/api/dashboard", headers=headers)
    assert res_dash.status_code == 200
    dash_data = res_dash.json()
    history = dash_data.get("weights_history", [])
    assert len(history) >= 45, f"Dashboard doit retourner au moins 45 pesées sans troncature à 30, reçu {len(history)}"
