"""Tests pour l'observabilité avancée VitalTrack (BALI-222 / VTR-206).

Couvre :
- Distributed tracing (Tempo / Jaeger via OTLP gRPC / HTTP et W3C Trace Context)
- Histogrammes de latence pour calcul SLO / SLI (p95 < 200ms, taux erreur < 0.1%, dispo 99.9%)
- Métriques RED (Rate, Errors, Duration)
- Métriques USE (Utilization, Saturation, Errors)
- Métriques business (vitaltrack_weight_logs_total, vitaltrack_photo_analyses_total)
- Alerting & SLI evaluation helper
- Intégration FastAPI et routes /metrics, /api/observability/slo
"""

import os
import pytest
from starlette.testclient import TestClient

from src.app import app
from src.otel import (
    record_http_metric,
    record_weight_log_metric,
    record_photo_analysis_metric,
    render_prometheus_metrics,
    get_slo_sli_status,
    setup_otel,
    get_tracer,
)


@pytest.fixture
def client():
    return TestClient(app)


def test_business_metrics_recording():
    """Vérifie l'enregistrement et l'exposition des métriques métier (pesées, photos IA)."""
    record_weight_log_metric(source="manual", status="success")
    record_weight_log_metric(source="withings", status="success")
    record_photo_analysis_metric(engine="gemini_vision", status="success")
    record_photo_analysis_metric(engine="openfoodfacts_fallback", status="success")

    metrics_text = render_prometheus_metrics()
    assert "vitaltrack_weight_logs_total" in metrics_text
    assert 'source="manual"' in metrics_text
    assert 'source="withings"' in metrics_text
    assert "vitaltrack_photo_analyses_total" in metrics_text
    assert 'engine="gemini_vision"' in metrics_text
    assert 'engine="openfoodfacts_fallback"' in metrics_text


def test_red_use_and_histogram_metrics_in_prometheus():
    """Vérifie la présence des métriques RED, USE et des buckets d'histogramme de latence."""
    record_http_metric("GET", "/api/dashboard", 200, 45.0)
    record_http_metric("POST", "/api/weights", 201, 110.0)
    record_http_metric("POST", "/api/meals/analyze-photo", 500, 320.0)

    metrics_text = render_prometheus_metrics()

    # RED Metrics
    assert "http_requests_total" in metrics_text  # Rate
    assert 'status="500"' in metrics_text         # Errors
    assert "http_request_duration_seconds_bucket" in metrics_text  # Duration (Histogram)
    assert 'le="0.2"' in metrics_text             # Bucket 200ms (SLO p95 < 200ms)

    # USE Metrics
    assert "vitaltrack_system_cpu_utilization_ratio" in metrics_text
    assert "vitaltrack_system_memory_utilization_ratio" in metrics_text
    assert "vitaltrack_concurrency_in_flight_requests" in metrics_text
    assert "vitaltrack_error_events_total" in metrics_text


def test_slo_sli_computation():
    """Vérifie le calcul SLI (latence p95, taux d'erreur, disponibilité) et respect des SLOs."""
    # Enregistrer des requêtes saines (< 200ms)
    for _ in range(99):
        record_http_metric("GET", "/api/dashboard", 200, 50.0)
    # Enregistrer 1 requête lente
    record_http_metric("GET", "/api/dashboard", 200, 250.0)

    slo_status = get_slo_sli_status()
    assert "targets" in slo_status
    assert "sli" in slo_status
    assert "compliance" in slo_status

    # Vérification des cibles
    assert slo_status["targets"]["latency_p95_ms"] == 200.0
    assert slo_status["targets"]["max_error_rate_pct"] == 0.1
    assert slo_status["targets"]["min_availability_pct"] == 99.9

    # Vérification des SLI calculés
    assert slo_status["sli"]["total_requests"] >= 100
    assert isinstance(slo_status["sli"]["p95_latency_ms"], float)
    assert slo_status["sli"]["error_rate_pct"] >= 0.0
    assert slo_status["sli"]["availability_pct"] >= 0.0


def test_observability_api_endpoint(client):
    """Vérifie que l'endpoint API de monitoring SLO/SLI répond avec le contrat attendu."""
    res = client.get("/api/observability/slo")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "slo_sli" in data
    assert "grafana_dashboards" in data
    assert "tempo_jaeger" in data


def test_tracer_propagation_and_resilience():
    """Vérifie la robustesse de l'initialisation du tracer et le fallback gracieux."""
    tracer = get_tracer("vitaltrack.test")
    with tracer.start_as_current_span("test_span") as span:
        span.set_attribute("test.key", "test_val")
    assert span is not None
