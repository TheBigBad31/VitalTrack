"""Tests TDD pour l'interface DeviceConnector (Protocol) et le polymorphisme du DeviceConnectorRegistry."""

from datetime import date, timedelta
from typing import Dict, Any, List, Optional
import pytest

from src.connectors.base import DeviceConnector, SyncResult, BaseHealthConnector
from src.connectors.withings import WithingsScaleConnector
from src.connectors.oura import OuraRingConnector
from src.connectors.ringconn import RingConnConnector
from src.connectors.health_connect import GoogleHealthConnectConnector
from src.connectors.webhook import MobileHealthWebhookConnector
from src.connectors.template import TemplateHealthConnector
from src.connectors.registry import DeviceConnectorRegistry, get_connector
from src.models import WeightEntry, ActivityEntry


def test_device_connector_protocol_runtime_checkable():
    """Vérifie que DeviceConnector est bien un @runtime_checkable Protocol."""
    assert hasattr(DeviceConnector, "_is_runtime_protocol") or issubclass(type(DeviceConnector), type)

    # Création d'une classe minimale conforme
    class DummyConnector:
        device_id: str = "dummy"
        name: str = "Dummy Device"
        device_type: str = "scale"

        def is_configured(self) -> bool:
            return True

        def sync(self, credentials: Dict[str, Any], user_id: int, db: Any = None,
                 start_date: Optional[date] = None, end_date: Optional[date] = None) -> SyncResult:
            return SyncResult(device_id=self.device_id, weights=[], activities=[])

        def get_auth_url(self, redirect_uri: Optional[str] = None, state: Optional[str] = None) -> Optional[str]:
            return None

    dummy = DummyConnector()
    assert isinstance(dummy, DeviceConnector)


def test_all_connectors_implement_device_connector_protocol():
    """Vérifie que chaque connecteur implémente DeviceConnector."""
    connectors = [
        WithingsScaleConnector(),
        OuraRingConnector(),
        RingConnConnector(),
        GoogleHealthConnectConnector(),
        MobileHealthWebhookConnector(),
        TemplateHealthConnector(),
    ]

    for conn in connectors:
        assert isinstance(conn, DeviceConnector), f"{conn.__class__.__name__} n'implémente pas DeviceConnector"
        assert hasattr(conn, "device_id")
        assert hasattr(conn, "name")
        assert hasattr(conn, "device_type")
        assert hasattr(conn, "is_configured")
        assert callable(conn.sync)
        assert callable(conn.get_auth_url)


def test_sync_result_dataclass():
    """Vérifie les attributs et la sérialisation de SyncResult."""
    res = SyncResult(
        device_id="test_dev",
        success=True,
        weights=[WeightEntry(date=date.today(), weight_kg=75.0, source="manual")],
        activities=[ActivityEntry(date=date.today(), steps=10000, source="oura")],
        error=None,
        details={"custom": "info"}
    )
    assert res.device_id == "test_dev"
    assert res.success is True
    assert len(res.weights) == 1
    assert len(res.activities) == 1
    assert res.weights_count == 1
    assert res.activities_count == 1
    assert res.to_dict()["device_id"] == "test_dev"


def test_connector_sync_method_polymorphism():
    """Vérifie l'exécution polymorphique de sync() sur les connecteurs."""
    # Withings
    withings = WithingsScaleConnector()
    res_w = withings.sync(credentials={}, user_id=1, start_date=date.today() - timedelta(days=2), end_date=date.today())
    assert isinstance(res_w, SyncResult)
    assert res_w.device_id == "withings"
    assert res_w.success is True
    assert len(res_w.weights) == 3

    # Oura
    oura = OuraRingConnector()
    res_o = oura.sync(credentials={}, user_id=1, start_date=date.today() - timedelta(days=2), end_date=date.today())
    assert isinstance(res_o, SyncResult)
    assert res_o.device_id == "oura"
    assert res_o.success is True
    assert len(res_o.activities) == 3

    # RingConn
    ringconn = RingConnConnector()
    res_r = ringconn.sync(credentials={}, user_id=1, start_date=date.today() - timedelta(days=2), end_date=date.today())
    assert isinstance(res_r, SyncResult)
    assert res_r.device_id == "ringconn"
    assert res_r.success is True
    assert len(res_r.activities) == 3

    # Health Connect
    hc = GoogleHealthConnectConnector()
    res_hc = hc.sync(credentials={}, user_id=1, start_date=date.today() - timedelta(days=2), end_date=date.today())
    assert isinstance(res_hc, SyncResult)
    assert res_hc.device_id == "health_connect"
    assert res_hc.success is True
    assert len(res_hc.weights) == 3
    assert len(res_hc.activities) == 3


def test_registry_register_and_get_polymorphic():
    """Vérifie l'enregistrement et la récupération polymorphique dans DeviceConnectorRegistry."""
    registry = DeviceConnectorRegistry()
    conn = registry.get("withings")
    assert conn is not None
    assert isinstance(conn, DeviceConnector)
    assert conn.device_id == "withings"
    assert conn.device_type == "scale"

    # Enregistrer un nouveau connecteur
    class CustomRing(BaseHealthConnector):
        device_id = "custom_ring"
        name = "Custom Ring"
        device_type = "ring"

        def _check_configuration(self) -> bool:
            return True

        def sync_weights(self, start_date: date, end_date: date) -> List[WeightEntry]:
            return []

        def sync_activities(self, start_date: date, end_date: date) -> List[ActivityEntry]:
            return []

    custom = CustomRing()
    registry.register(custom)
    retrieved = registry.get("custom_ring")
    assert retrieved is not None
    assert isinstance(retrieved, DeviceConnector)
    assert retrieved.name == "Custom Ring"
