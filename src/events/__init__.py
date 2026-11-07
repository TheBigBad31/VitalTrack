"""Module Event Sourcing / CQRS de VitalTrack."""

from src.events.domain_events import (
    DomainEvent,
    WeightRecorded,
    MealLogged,
    ActivitySynced,
    MetricsSynced,
)
from src.events.event_bus import (
    EventBus,
    EventStore,
    InMemoryEventStore,
    StreamBrokerAdapter,
    InMemoryStreamBroker,
    global_event_bus,
)
from src.events.projections import (
    CQRSProjectionEngine,
    UserDashboardProjection,
    UserAnalyticsProjection,
    BiometricsExportProjection,
    global_projection_engine,
)

__all__ = [
    "DomainEvent",
    "WeightRecorded",
    "MealLogged",
    "ActivitySynced",
    "MetricsSynced",
    "EventBus",
    "EventStore",
    "InMemoryEventStore",
    "StreamBrokerAdapter",
    "InMemoryStreamBroker",
    "global_event_bus",
    "CQRSProjectionEngine",
    "UserDashboardProjection",
    "UserAnalyticsProjection",
    "BiometricsExportProjection",
    "global_projection_engine",
]
