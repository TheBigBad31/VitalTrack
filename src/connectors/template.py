"""Modèle de référence pour l'implémentation de futurs connecteurs IoT Santé.

Exemples d'appareils cibles :
- Garmin Index S2 / Garmin Connect
- Xiaomi / Mi Body Composition Scale
- Ultrahuman Ring Air
- RingConn Smart Ring
- Whoop 4.0
- Polar Flow
"""

from datetime import date
from typing import Any, Dict, List, Optional

from src.connectors.base import BaseHealthConnector
from src.models import ActivityEntry, WeightEntry


class TemplateHealthConnector(BaseHealthConnector):
    """Template prêt à l'emploi pour nouveau connecteur de santé.

    Étapes pour implémenter votre connecteur :
    1. Définir les clés de configuration obligatoires dans `_check_configuration()`.
    2. Implémenter l'authentification (OAuth2, API Key, Basic Auth ou Webhook).
    3. Mapper les données brutes de l'API constructeur vers `WeightEntry` ou `ActivityEntry`.
    4. Enregistrer la classe dans `src/connectors/registry.py` et dans `config/devices.yaml`.
    """

    def _check_configuration(self) -> bool:
        """Exemple : vérifier la présence d'une clé API constructeur."""
        api_key = self.config.get("api_key")
        return bool(api_key)

    def sync_weights(self, start_date: date, end_date: date) -> List[WeightEntry]:
        """Récupération et normalisation des pesées."""
        if not self.is_configured:
            # Toujours prévoir un fallback ou mode démo pour fluidifier l'expérience utilisateur
            return []
        
        # TODO: Effectuer l'appel API (requests, httpx, etc.)
        # TODO: Mapper les champs vers WeightEntry(date, weight_kg, body_fat_pct, ...)
        return []

    def sync_activities(self, start_date: date, end_date: date) -> List[ActivityEntry]:
        """Récupération et normalisation des activités quotidiennes."""
        if not self.is_configured:
            return []

        # TODO: Effectuer l'appel API
        # TODO: Mapper les champs vers ActivityEntry(date, steps, active_calories_kcal, ...)
        return []
