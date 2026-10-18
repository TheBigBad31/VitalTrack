"""Registre et Factory des connecteurs de santé."""

import importlib
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

from src.connectors.base import BaseHealthConnector
from src.connectors.withings import WithingsScaleConnector
from src.connectors.oura import OuraRingConnector
from src.connectors.webhook import MobileHealthWebhookConnector
from src.connectors.template import TemplateHealthConnector


CONNECTOR_REGISTRY = {
    "withings": WithingsScaleConnector,
    "oura": OuraRingConnector,
    "mobile_webhook": MobileHealthWebhookConnector,
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
