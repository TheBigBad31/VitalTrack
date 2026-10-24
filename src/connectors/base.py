"""Classe de base abstraite pour les connecteurs d'appareils et plateformes de santé."""

from abc import ABC, abstractmethod
from datetime import date
import os
from typing import Any, Dict, List, Optional
from src.models import ActivityEntry, WeightEntry


class SimulationNotAllowedInProductionError(RuntimeError):
    """Exception levée lorsqu'une simulation de connecteur IoT est déclenchée en environnement de production sans profil de démonstration confirmé."""
    pass


class BaseHealthConnector(ABC):
    """Interface standardisée pour tous les connecteurs de santé (Balance, Bague, Montre, App)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.is_configured = self._check_configuration()

    @property
    def is_production(self) -> bool:
        """Détermine si le connecteur s'exécute dans un environnement de production."""
        env = (os.getenv("ENVIRONMENT") or os.getenv("VERCEL_ENV") or os.getenv("ENV") or "").lower()
        return env in ("production", "prod")

    def assert_simulation_allowed(self) -> None:
        """Vérifie que l'injection ou génération de données simulées est autorisée.
        
        En production, la simulation est strictement interdite sauf si confirmation explicite
        d'un profil de démonstration via `allow_simulation=True` ou `is_demo_profile=True`
        dans la configuration du connecteur.
        """
        if self.is_production:
            allow_demo = (
                self.config.get("allow_simulation") is True
                or self.config.get("is_demo_profile") is True
                or self.config.get("demo_profile") is True
                or os.getenv("ALLOW_DEMO_SIMULATION", "").lower() in ("1", "true", "yes")
            )
            if not allow_demo:
                raise SimulationNotAllowedInProductionError(
                    f"Génération de simulation interdite en production pour {self.__class__.__name__} "
                    "sans confirmation explicite d'un profil de démonstration."
                )

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
