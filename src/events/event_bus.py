"""Bus d'événements et interfaces d'Event Store pour l'Event Sourcing."""

import abc
import asyncio
import json
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional
from src.events.domain_events import DomainEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[DomainEvent], Coroutine[Any, Any, None]]


class EventStore(abc.ABC):
    """Interface abstraite de persistance d'événements (Event Store)."""

    @abc.abstractmethod
    async def append(self, event: DomainEvent) -> None:
        """Ajoute un événement au journal immuable."""
        pass

    @abc.abstractmethod
    async def get_events(self, aggregate_id: str, after_version: Optional[int] = None) -> List[DomainEvent]:
        """Récupère la séquence ordonnée d'événements d'un agrégat."""
        pass

    @abc.abstractmethod
    async def get_all_events(self, limit: int = 1000) -> List[DomainEvent]:
        """Récupère l'ensemble des événements du store pour rejeu ou projections."""
        pass


class InMemoryEventStore(EventStore):
    """Event Store in-memory par défaut (utilisé pour les tests et exécution serverless rapide)."""

    def __init__(self) -> None:
        self._events: List[DomainEvent] = []

    async def append(self, event: DomainEvent) -> None:
        self._events.append(event)

    async def get_events(self, aggregate_id: str, after_version: Optional[int] = None) -> List[DomainEvent]:
        res = [e for e in self._events if e.aggregate_id == aggregate_id]
        if after_version is not None:
            res = [e for e in res if e.version > after_version]
        return res

    async def get_all_events(self, limit: int = 1000) -> List[DomainEvent]:
        return list(self._events[:limit])


class StreamBrokerAdapter(abc.ABC):
    """Interface pour les brokers de streaming d'événements (Kafka / Redis Streams / NATS)."""

    @abc.abstractmethod
    async def publish(self, topic: str, event: DomainEvent) -> None:
        """Publie un événement sérialisé sur un stream ou topic."""
        pass


class InMemoryStreamBroker(StreamBrokerAdapter):
    """Broker simulé en mémoire pour environnement de test ou fallback serverless sans broker externe."""

    def __init__(self) -> None:
        self.streams: Dict[str, List[Dict[str, Any]]] = {}

    async def publish(self, topic: str, event: DomainEvent) -> None:
        if topic not in self.streams:
            self.streams[topic] = []
        payload = {
            "topic": topic,
            "event_id": event.event_id,
            "event_type": event.event_type,
            "payload": event.model_dump(mode="json"),
        }
        self.streams[topic].append(payload)
        logger.debug(f"[StreamBroker] Publié {event.event_type} sur stream {topic}")


class EventBus:
    """Bus d'événements permettant de publier des DomainEvents aux abonnés (projections CQRS)."""

    def __init__(
        self,
        event_store: Optional[EventStore] = None,
        broker: Optional[StreamBrokerAdapter] = None
    ) -> None:
        self.event_store = event_store or InMemoryEventStore()
        self.broker = broker or InMemoryStreamBroker()
        self._subscribers: Dict[str, List[EventHandler]] = {}

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Enregistre un handler/projection pour un type d'événement donné."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    async def publish(self, event: DomainEvent) -> None:
        """Persiste dans l'Event Store, publie sur le stream broker, puis dispatche aux projections."""
        # 1. Write model -> Event Store
        await self.event_store.append(event)

        # 2. Diffusion vers Broker (Kafka / Redis Streams / NATS)
        topic = f"vitaltrack.biometrics.{event.event_type.lower()}"
        await self.broker.publish(topic, event)

        # 3. Notification des projections in-process
        handlers = self._subscribers.get(event.event_type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error(f"[EventBus] Erreur dans projection handler pour {event.event_type}: {e}", exc_info=True)


# Instance globale du bus d'événements pour le runtime de l'application
global_event_bus = EventBus()
