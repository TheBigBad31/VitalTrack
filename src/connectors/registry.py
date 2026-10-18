"""Registre et Factory des connecteurs de santé."""

from datetime import date, timedelta
import importlib
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from src.connectors.base import BaseHealthConnector
from src.connectors.withings import WithingsScaleConnector
from src.connectors.oura import OuraRingConnector
from src.connectors.webhook import MobileHealthWebhookConnector
from src.connectors.template import TemplateHealthConnector


from src.connectors.ringconn import RingConnConnector

CONNECTOR_REGISTRY = {
    "withings": WithingsScaleConnector,
    "oura": OuraRingConnector,
    "ringconn": RingConnConnector,
    "health_connect": MobileHealthWebhookConnector,
    "mobile_webhook": MobileHealthWebhookConnector,
    "apple_health": MobileHealthWebhookConnector,
    "template": TemplateHealthConnector,
}


def load_devices_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Charge le fichier YAML de configuration des appareils."""
    if not config_path:
        config_path = str(Path(__file__).resolve().parent.parent.parent / "config" / "devices.yaml")
    
    p = Path(config_path)
    if not p.exists():
        return {}
    
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_connector(device_key: str, custom_config: Optional[Dict[str, Any]] = None) -> BaseHealthConnector:
    """Instancie un connecteur par sa clé déclarative."""
    cfg = load_devices_config().get("devices", {}).get(device_key, {})
    device_cfg = cfg.get("config", {})
    if custom_config:
        device_cfg.update(custom_config)

    connector_cls = CONNECTOR_REGISTRY.get(device_key)
    if not connector_cls:
        raise ValueError(f"Connecteur inconnu pour la clé: {device_key}")

    return connector_cls(device_cfg)


class DeviceConnectorRegistry:
    """Registre dynamique et gestionnaire des connecteurs d'objets connectés."""

    def __init__(self):
        self._devices: Dict[str, Any] = {}
        self._load_from_config()

    def _load_from_config(self):
        cfg = load_devices_config()
        devices_dict = cfg.get("devices", {})
        for dev_id, dev_info in devices_dict.items():
            conn_cls = CONNECTOR_REGISTRY.get(dev_id, TemplateHealthConnector)
            inst = conn_cls(dev_info.get("config", {}))
            self._devices[dev_id] = {
                "id": dev_id,
                "name": dev_info.get("name", dev_id.capitalize()),
                "device_type": dev_info.get("type", "unknown"),
                "connector": inst,
                "enabled": dev_info.get("enabled", True),
                "is_configured": inst.is_configured
            }

    def register(self, connector: Any, device_id: Optional[str] = None, name: Optional[str] = None, device_type: str = "custom"):
        dev_id = device_id or getattr(connector, "id", None) or connector.__class__.__name__.lower()
        dev_name = name or getattr(connector, "name", None) or dev_id.capitalize()
        self._devices[dev_id] = {
            "id": dev_id,
            "name": dev_name,
            "device_type": device_type,
            "connector": connector,
            "enabled": True,
            "is_configured": getattr(connector, "is_configured", False)
        }

    def get(self, device_id: str) -> Optional[Any]:
        dev = self._devices.get(device_id)
        return dev["connector"] if dev else None

    def list_all(self) -> List[Any]:
        res = []
        for d in self._devices.values():
            inst = d["connector"]
            # Exposer un objet ou proxy avec id, name, device_type, is_configured, sync
            res.append(type("DeviceProxy", (), {
                "id": d["id"],
                "name": d["name"],
                "device_type": d["device_type"],
                "is_configured": lambda self=None, is_c=d["is_configured"]: is_c,
                "sync": lambda days=1, c=inst: c.sync_weights(date.today() - timedelta(days=days), date.today()) if hasattr(c, "sync_weights") else []
            })())
        return res

