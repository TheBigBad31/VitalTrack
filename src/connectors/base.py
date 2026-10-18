"""Classe de base abstraite pour les connecteurs d'appareils et plateformes de santé."""

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Dict, List, Optional
from src.models import ActivityEntry, WeightEntry


class BaseHealthConnector(ABC):
    """Interface standardisée pour tous les connecteurs de santé (Balance, Bague, Montre, App)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.is_configured = self._check_configuration()

    @abstractmethod
    def _check_configuration(self) -> bool:
        """Vérifie si le connecteur a les identifiants / clés nécessaires pour opérer en direct."""
        pass

    @abstractmethod
    def sync_weights(self, start_date: date, end_date: date) -> List[WeightEntry]:
        """Récupère les mesures de pesée sur une plage de dates."""
        pass

    @abstractmethod
    def sync_activities(self, start_date: date, end_date: date) -> List[ActivityEntry]:
        """Récupère les résumés d'activités quotidiennes sur une plage de dates."""
        pass
