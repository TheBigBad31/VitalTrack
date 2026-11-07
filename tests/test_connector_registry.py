"""Tests unitaires pour src/connectors/registry.py (VTR-001)."""

import pytest
from src.connectors.registry import (
    DeviceConnectorRegistry,
    create_device_registry,
    get_connector,
    CONNECTOR_REGISTRY,
)
from src.connectors.withings import WithingsScaleConnector
from src.connectors.oura import OuraRingConnector
from src.connectors.ringconn import RingConnConnector
from src.connectors.health_connect import GoogleHealthConnectConnector
from src.connectors.webhook import MobileHealthWebhookConnector


def test_registry_factory_creates_default_connectors():
    """Vérifie que create_device_registry() enregistre les 5 connecteurs requis."""
    registry = create_device_registry()
    assert isinstance(registry, DeviceConnectorRegistry)

    devices = registry.list_all()
    device_ids = {d.id for d in devices}

    assert "ringconn" in device_ids
    assert "health_connect" in device_ids
    assert "withings" in device_ids
    assert "oura" in device_ids
    assert "apple_health" in device_ids


def test_registry_factory_allows_dependency_injection():
    """Vérifie que create_device_registry permet l'injection de connecteurs personnalisés."""
    custom_withings = WithingsScaleConnector(config={"client_id": "test_id"})
    registry = create_device_registry(
        connectors=[
            (custom_withings, "withings", "Custom Withings", "scale"),
        ],
        load_from_config=False,
    )
    devices = registry.list_all()
    assert len(devices) == 1
    assert devices[0].id == "withings"
    assert devices[0].name == "Custom Withings"
    assert registry.get("withings") is custom_withings


def test_registry_get_and_list_all():
    """Vérifie les méthodes get et list_all."""
    registry = DeviceConnectorRegistry(load_from_config=False)
    assert len(registry.list_all()) == 0

    ringconn = RingConnConnector()
    registry.register(ringconn, device_id="ringconn", name="RingConn Gen 3", device_type="ring")

    assert registry.get("ringconn") is ringconn
    assert registry.get("unknown") is None

    devices = registry.list_all()
    assert len(devices) == 1
    d = devices[0]
    assert d.id == "ringconn"
    assert d.name == "RingConn Gen 3"
    assert d.device_type == "ring"
    assert callable(d.is_configured)
