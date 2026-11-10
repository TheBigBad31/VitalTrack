"""Tests unitaires et d'intégration pour le module Event Sourcing / CQRS de VitalTrack (BALI-218)."""

from datetime import date
import pytest

from src.events import (
    ActivitySynced,
    CQRSProjectionEngine,
    DomainEvent,
    EventBus,
    InMemoryEventStore,
    InMemoryStreamBroker,
    MealLogged,
    MetricsSynced,
    WeightRecorded,
)


@pytest.mark.asyncio
async def test_domain_events_instantiation():
    """Vérifie l'instanciation valide et typée des événements du domaine biométrique."""
    d = date(2026, 11, 7)
    w_ev = WeightRecorded(
        aggregate_id="user_1",
        user_id=1,
        date=d,
        weight_kg=75.5,
        body_fat_pct=15.2,
        muscle_mass_kg=35.0,
        bmi=23.1,
        source="withings",
    )
    assert w_ev.event_type == "WeightRecorded"
    assert w_ev.weight_kg == 75.5
    assert w_ev.user_id == 1
    assert w_ev.event_id is not None

    m_ev = MealLogged(
        aggregate_id="user_1",
        user_id=1,
        date=d,
        meal_type="lunch",
        total_calories_kcal=650.0,
        protein_g=40.0,
        carbs_g=60.0,
        fat_g=20.0,
    )
    assert m_ev.event_type == "MealLogged"
    assert m_ev.total_calories_kcal == 650.0

    a_ev = ActivitySynced(
        aggregate_id="user_1",
        user_id=1,
        date=d,
        steps=8500,
        total_burned_kcal=450.0,
        sleep_score=85,
    )
    assert a_ev.event_type == "ActivitySynced"
    assert a_ev.steps == 8500

    met_ev = MetricsSynced(
        aggregate_id="user_1",
        user_id=1,
        date=d,
        source="ringconn",
        steps=9200,
        hrv_rmssd_ms=45.2,
        sleep_score=88,
    )
    assert met_ev.event_type == "MetricsSynced"
    assert met_ev.source == "ringconn"


@pytest.mark.asyncio
async def test_event_store_and_bus_pipeline():
    """Vérifie l'envoi d'événements dans le bus, le stockage immuable et la diffusion stream."""
    store = InMemoryEventStore()
    broker = InMemoryStreamBroker()
    bus = EventBus(event_store=store, broker=broker)

    recorded_events = []

    async def sample_handler(event: DomainEvent):
        recorded_events.append(event)

    bus.subscribe("WeightRecorded", sample_handler)

    ev = WeightRecorded(
        aggregate_id="user_42",
        user_id=42,
        date=date(2026, 11, 7),
        weight_kg=80.0,
    )

    await bus.publish(ev)

    # 1. Vérifie la persistance dans le store
    stored = await store.get_events("user_42")
    assert len(stored) == 1
    assert stored[0].event_id == ev.event_id

    # 2. Vérifie la publication sur le stream
    topic = "vitaltrack.biometrics.weightrecorded"
    assert topic in broker.streams
    assert len(broker.streams[topic]) == 1
    assert broker.streams[topic][0]["event_id"] == ev.event_id

    # 3. Vérifie l'exécution du handler abonné
    assert len(recorded_events) == 1
    assert recorded_events[0].event_id == ev.event_id


@pytest.mark.asyncio
async def test_cqrs_projections_dashboard_analytics_export():
    """Vérifie la mise à jour des vues en lecture (Dashboard, Analytics, Export) via les projections."""
    store = InMemoryEventStore()
    broker = InMemoryStreamBroker()
    bus = EventBus(event_store=store, broker=broker)
    projection_engine = CQRSProjectionEngine(bus)

    d = date(2026, 11, 7)

    # Simulation d'une journée d'événements
    w_ev = WeightRecorded(aggregate_id="user_1", user_id=1, date=d, weight_kg=72.4, bmi=22.5, body_fat_pct=14.0)
    m_ev = MealLogged(aggregate_id="user_1", user_id=1, date=d, meal_type="lunch", total_calories_kcal=750.0)
    a_ev = ActivitySynced(aggregate_id="user_1", user_id=1, date=d, steps=6000, total_burned_kcal=350.0, sleep_score=82)
    met_ev = MetricsSynced(aggregate_id="user_1", user_id=1, date=d, source="ringconn", steps=7500, total_calories_kcal=400.0)

    await bus.publish(w_ev)
    await bus.publish(m_ev)
    await bus.publish(a_ev)
    await bus.publish(met_ev)

    # 1. Dashboard Projection
    dash = projection_engine.get_dashboard(user_id=1)
    assert dash.latest_weight_kg == 72.4
    assert dash.latest_bmi == 22.5
    assert dash.today_calories_consumed == 750.0
    assert dash.today_calories_burned == 400.0
    assert dash.today_steps == 7500
    assert dash.today_sleep_score == 82
    assert dash.total_events_processed == 4

    # 2. Analytics Projection
    analytics = projection_engine.get_analytics(user_id=1)
    assert len(analytics.weight_history) == 1
    assert analytics.total_meals_logged == 1
    assert analytics.total_activities_synced == 1
    d_summary = analytics.daily_summaries[str(d)]
    assert d_summary["calories_in"] == 750.0
    assert d_summary["calories_out"] == 350.0
    assert d_summary["steps"] == 7500

    # 3. Export Projection
    exp = projection_engine.get_export(user_id=1)
    assert len(exp.timeline) == 4
    types = [item["type"] for item in exp.timeline]
    assert "weight" in types
    assert "meal" in types
    assert "activity" in types
    assert "metrics" in types


@pytest.mark.asyncio
async def test_cqrs_projections_replay():
    """Vérifie le rejeu complet (replay) des projections depuis l'Event Store."""
    store = InMemoryEventStore()
    broker = InMemoryStreamBroker()
    bus = EventBus(event_store=store, broker=broker)
    projection_engine = CQRSProjectionEngine(bus)

    d = date(2026, 11, 7)
    ev1 = WeightRecorded(aggregate_id="user_99", user_id=99, date=d, weight_kg=68.0)
    ev2 = MealLogged(aggregate_id="user_99", user_id=99, date=d, meal_type="dinner", total_calories_kcal=520.0)

    # Insertion directe dans le store pour simuler un historique froid
    await store.append(ev1)
    await store.append(ev2)

    # Avant replay : vues vides
    dash_before = projection_engine.get_dashboard(99)
    assert dash_before.latest_weight_kg is None
    assert dash_before.today_calories_consumed == 0.0

    # Replay
    await projection_engine.replay_from_store()

    # Après replay : vues projetées reconstruites fidèlement
    dash_after = projection_engine.get_dashboard(99)
    assert dash_after.latest_weight_kg == 68.0
    assert dash_after.today_calories_consumed == 520.0
    assert dash_after.total_events_processed == 2
