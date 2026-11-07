"""Projections CQRS (Read Models) pour le tableau de bord, analytics et exports biométriques."""

from datetime import date as DateType
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from src.events.domain_events import (
    ActivitySynced,
    DomainEvent,
    MealLogged,
    MetricsSynced,
    WeightRecorded,
)
from src.events.event_bus import EventBus, global_event_bus


class UserDashboardProjection(BaseModel):
    """Read model optimisé pour l'affichage temps réel du tableau de bord utilisateur."""
    user_id: int
    latest_weight_kg: Optional[float] = None
    latest_weight_date: Optional[str] = None
    latest_bmi: Optional[float] = None
    latest_body_fat_pct: Optional[float] = None
    trend_7d_kg: Optional[float] = None
    today_calories_consumed: float = 0.0
    today_calories_burned: float = 0.0
    today_steps: int = 0
    today_sleep_score: Optional[int] = None
    total_events_processed: int = 0


class UserAnalyticsProjection(BaseModel):
    """Read model pour l'agrégation analytique et les calculs de bilans énergétiques."""
    user_id: int
    weight_history: List[Dict[str, Any]] = Field(default_factory=list)
    daily_summaries: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    total_meals_logged: int = 0
    total_activities_synced: int = 0


class BiometricsExportProjection(BaseModel):
    """Read model dédié aux exports RGPD / CSV / JSON."""
    user_id: int
    timeline: List[Dict[str, Any]] = Field(default_factory=list)


class CQRSProjectionEngine:
    """Moteur de gestion des projections CQRS : écoute les événements et met à jour les read models."""

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self.dashboard_views: Dict[int, UserDashboardProjection] = {}
        self.analytics_views: Dict[int, UserAnalyticsProjection] = {}
        self.export_views: Dict[int, BiometricsExportProjection] = {}
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.event_bus.subscribe("WeightRecorded", self.on_weight_recorded)
        self.event_bus.subscribe("MealLogged", self.on_meal_logged)
        self.event_bus.subscribe("ActivitySynced", self.on_activity_synced)
        self.event_bus.subscribe("MetricsSynced", self.on_metrics_synced)

    def get_dashboard(self, user_id: int) -> UserDashboardProjection:
        if user_id not in self.dashboard_views:
            self.dashboard_views[user_id] = UserDashboardProjection(user_id=user_id)
        return self.dashboard_views[user_id]

    def get_analytics(self, user_id: int) -> UserAnalyticsProjection:
        if user_id not in self.analytics_views:
            self.analytics_views[user_id] = UserAnalyticsProjection(user_id=user_id)
        return self.analytics_views[user_id]

    def get_export(self, user_id: int) -> BiometricsExportProjection:
        if user_id not in self.export_views:
            self.export_views[user_id] = BiometricsExportProjection(user_id=user_id)
        return self.export_views[user_id]

    async def on_weight_recorded(self, event: DomainEvent) -> None:
        if not isinstance(event, WeightRecorded):
            return
        dash = self.get_dashboard(event.user_id)
        dash.latest_weight_kg = event.weight_kg
        dash.latest_weight_date = str(event.date)
        dash.latest_bmi = event.bmi
        dash.latest_body_fat_pct = event.body_fat_pct
        dash.total_events_processed += 1

        analytics = self.get_analytics(event.user_id)
        analytics.weight_history.append({
            "date": str(event.date),
            "weight_kg": event.weight_kg,
            "body_fat_pct": event.body_fat_pct,
            "source": event.source
        })

        export = self.get_export(event.user_id)
        export.timeline.append({
            "type": "weight",
            "date": str(event.date),
            "value": event.weight_kg,
            "unit": "kg",
            "timestamp": event.occurred_at.isoformat()
        })

    async def on_meal_logged(self, event: DomainEvent) -> None:
        if not isinstance(event, MealLogged):
            return
        dash = self.get_dashboard(event.user_id)
        dash.today_calories_consumed += event.total_calories_kcal
        dash.total_events_processed += 1

        analytics = self.get_analytics(event.user_id)
        analytics.total_meals_logged += 1
        d_str = str(event.date)
        if d_str not in analytics.daily_summaries:
            analytics.daily_summaries[d_str] = {"calories_in": 0.0, "calories_out": 0.0, "steps": 0}
        analytics.daily_summaries[d_str]["calories_in"] += event.total_calories_kcal

        export = self.get_export(event.user_id)
        export.timeline.append({
            "type": "meal",
            "date": str(event.date),
            "value": event.total_calories_kcal,
            "unit": "kcal",
            "timestamp": event.occurred_at.isoformat()
        })

    async def on_activity_synced(self, event: DomainEvent) -> None:
        if not isinstance(event, ActivitySynced):
            return
        dash = self.get_dashboard(event.user_id)
        dash.today_calories_burned += event.total_burned_kcal
        dash.today_steps += event.steps
        if event.sleep_score is not None:
            dash.today_sleep_score = event.sleep_score
        dash.total_events_processed += 1

        analytics = self.get_analytics(event.user_id)
        analytics.total_activities_synced += 1
        d_str = str(event.date)
        if d_str not in analytics.daily_summaries:
            analytics.daily_summaries[d_str] = {"calories_in": 0.0, "calories_out": 0.0, "steps": 0}
        analytics.daily_summaries[d_str]["calories_out"] += event.total_burned_kcal
        analytics.daily_summaries[d_str]["steps"] += event.steps

        export = self.get_export(event.user_id)
        export.timeline.append({
            "type": "activity",
            "date": str(event.date),
            "steps": event.steps,
            "calories_burned": event.total_burned_kcal,
            "timestamp": event.occurred_at.isoformat()
        })

    async def on_metrics_synced(self, event: DomainEvent) -> None:
        if not isinstance(event, MetricsSynced):
            return
        dash = self.get_dashboard(event.user_id)
        if event.steps > 0:
            dash.today_steps = max(dash.today_steps, event.steps)
        if event.total_calories_kcal > 0:
            dash.today_calories_burned = max(dash.today_calories_burned, event.total_calories_kcal)
        if event.sleep_score is not None:
            dash.today_sleep_score = event.sleep_score
        dash.total_events_processed += 1

        analytics = self.get_analytics(event.user_id)
        d_str = str(event.date)
        if d_str not in analytics.daily_summaries:
            analytics.daily_summaries[d_str] = {"calories_in": 0.0, "calories_out": 0.0, "steps": 0}
        analytics.daily_summaries[d_str]["steps"] = max(analytics.daily_summaries[d_str]["steps"], event.steps)

        export = self.get_export(event.user_id)
        export.timeline.append({
            "type": "metrics",
            "date": str(event.date),
            "source": event.source,
            "steps": event.steps,
            "hrv": event.hrv_rmssd_ms,
            "timestamp": event.occurred_at.isoformat()
        })

    async def replay_from_store(self) -> None:
        """Rejoue l'ensemble des événements stockés pour reconstruire les projections de zéro."""
        self.dashboard_views.clear()
        self.analytics_views.clear()
        self.export_views.clear()

        events = await self.event_bus.event_store.get_all_events(limit=50000)
        for ev in events:
            if ev.event_type == "WeightRecorded":
                await self.on_weight_recorded(ev)
            elif ev.event_type == "MealLogged":
                await self.on_meal_logged(ev)
            elif ev.event_type == "ActivitySynced":
                await self.on_activity_synced(ev)
            elif ev.event_type == "MetricsSynced":
                await self.on_metrics_synced(ev)


# Projection engine global branché au bus par défaut
global_projection_engine = CQRSProjectionEngine(global_event_bus)
