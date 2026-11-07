"""Classe de base abstraite et protocole pour les connecteurs d'appareils et plateformes de santé."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, timedelta
import os
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from src.models import ActivityEntry, WeightEntry


@dataclass
class SyncResult:
    """Résultat standardisé d'une opération de synchronisation d'un appareil."""
    device_id: str
    success: bool = True
    weights: List[WeightEntry] = field(default_factory=list)
    activities: List[ActivityEntry] = field(default_factory=list)
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def weights_count(self) -> int:
        return len(self.weights)

    @property
    def activities_count(self) -> int:
        return len(self.activities)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "success": self.success,
            "weights_count": self.weights_count,
            "activities_count": self.activities_count,
            "error": self.error,
            "details": self.details,
            "weights": [w.model_dump() if hasattr(w, "model_dump") else w for w in self.weights],
            "activities": [a.model_dump() if hasattr(a, "model_dump") else a for a in self.activities]
        }


@runtime_checkable
class DeviceConnector(Protocol):
    """Protocole commun pour tous les connecteurs d'objets connectés et plateformes de santé."""
    device_id: str
    name: str
    device_type: str

    def is_configured(self) -> bool:
        """Indique si le connecteur dispose des identifiants nécessaires pour fonctionner."""
        ...

    def sync(
        self,
        credentials: Dict[str, Any],
        user_id: int,
        db: Any = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> SyncResult:
        """Exécute une synchronisation standardisée pour un utilisateur avec ses credentials."""
        ...

    def get_auth_url(self, redirect_uri: Optional[str] = None, state: Optional[str] = None) -> Optional[str]:
        """Retourne l'URL d'autorisation OAuth si applicable, ou None."""
        ...


class SimulationNotAllowedInProductionError(RuntimeError):
    """Exception levée lorsqu'une simulation de connecteur IoT est déclenchée en environnement de production sans profil de démonstration confirmé."""
    pass


class BaseHealthConnector(ABC):
    """Interface standardisée pour tous les connecteurs de santé (Balance, Bague, Montre, App).
    
    Implémente le contrat DeviceConnector (Protocol) et fournit les comportements de base.
    """

    device_id: str = "base"
    name: str = "Base Health Connector"
    device_type: str = "health_sensor"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.is_configured: bool = self._check_configuration()

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

    def get_auth_url(self, redirect_uri: Optional[str] = None, state: Optional[str] = None) -> Optional[str]:
        """Retourne l'URL d'autorisation OAuth si applicable, ou None."""
        return None

    def sync(
        self,
        credentials: Dict[str, Any],
        user_id: int,
        db: Any = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> SyncResult:
        """Implémentation générique de sync() conforme au protocole DeviceConnector."""
        today = date.today()
        end_d = end_date or today
        start_d = start_date or (end_d - timedelta(days=7))

        # Fusionner temporairement les credentials dans self.config si fournis
        orig_config = dict(self.config)
        if credentials:
            self.config.update(credentials)
            self.is_configured = self._check_configuration()

        try:
            weights: List[WeightEntry] = []
            activities: List[ActivityEntry] = []

            if hasattr(self, "sync_weights"):
                try:
                    weights = self.sync_weights(start_d, end_d)
                except Exception as e:
                    # Ne pas masquer si c'est SimulationNotAllowedInProductionError
                    if isinstance(e, SimulationNotAllowedInProductionError):
                        raise
                    pass

            if hasattr(self, "sync_activities"):
                try:
                    activities = self.sync_activities(start_d, end_d)
                except Exception as e:
                    if isinstance(e, SimulationNotAllowedInProductionError):
                        raise
                    pass

            # Persister en base si fournie
            if db:
                if weights:
                    if hasattr(db, "batch_insert_weights"):
                        db.batch_insert_weights(weights, user_id=user_id)
                    elif hasattr(db, "insert_weight"):
                        for w in weights:
                            db.insert_weight(w, user_id=user_id)

                if activities:
                    if hasattr(db, "batch_insert_activities"):
                        db.batch_insert_activities(activities, user_id=user_id)
                    elif hasattr(db, "insert_activity"):
                        for a in activities:
                            db.insert_activity(a, user_id=user_id)

                if hasattr(db, "update_device_sync_status"):
                    db.update_device_sync_status(self.device_id, sync_status="connected", user_id=user_id)

            return SyncResult(
                device_id=self.device_id,
                success=True,
                weights=weights,
                activities=activities,
                details={"weights_count": len(weights), "activities_count": len(activities)}
            )
        except Exception as e:
            return SyncResult(
                device_id=self.device_id,
                success=False,
                error=str(e),
                details={"error_type": e.__class__.__name__}
            )
        finally:
            self.config = orig_config
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
