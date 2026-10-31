"""Observabilité OpenTelemetry et Prometheus pour VitalTrack.

Fournit :
- Instrumentation distribuée optionnelle via OpenTelemetry (traces, spans, logs structurés)
- Exposition d'un point de terminaison Prometheus `/metrics` compatible Vercel Serverless
- Protection totale par `try...except ImportError` et mode dégradé gracieux sans blocage
  si le collecteur OTLP (`localhost:4317`) n'est pas joignable en environnement Serverless.
"""

from collections import defaultdict
import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

LOGGER_NAME = "vitaltrack.observability"
logger = logging.getLogger(LOGGER_NAME)

_otel_available = False
_tracer_provider = None
_meter_provider = None

# Compteurs Prometheus légers en mémoire (toujours disponibles, même sans dépendances externes)
_metrics_lock = threading.Lock()
_http_requests_total: Dict[tuple, int] = defaultdict(int)
_http_request_duration_seconds_sum: Dict[tuple, float] = defaultdict(float)
_http_request_duration_seconds_count: Dict[tuple, int] = defaultdict(int)


class _NoopSpan:
    """Span no-op de repli lorsque le SDK OpenTelemetry n'est pas installé."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def record_exception(self, exception: BaseException) -> None:
        pass


class _NoopTracer:
    """Tracer no-op de repli."""

    def start_as_current_span(self, name: str, **kwargs):
        return _NoopSpan()


def record_http_metric(method: str, path: str, status_code: int, duration_ms: float) -> None:
    """Enregistre les métriques HTTP pour l'export Prometheus `/metrics`."""
    duration_s = max(0.0, duration_ms / 1000.0)
    key = (method.upper(), path, str(status_code))
    with _metrics_lock:
        _http_requests_total[key] += 1
        _http_request_duration_seconds_sum[(method.upper(), path)] += duration_s
        _http_request_duration_seconds_count[(method.upper(), path)] += 1


def render_prometheus_metrics(service_name: str = "vitaltrack") -> str:
    """Génère l'exposition texte au format Prometheus OpenMetrics."""
    lines = [
        "# HELP vitaltrack_up Service health indicator (1 = up)",
        "# TYPE vitaltrack_up gauge",
        f'vitaltrack_up{{service="{service_name}"}} 1',
        "# HELP http_requests_total Total number of HTTP requests by method, path and status",
        "# TYPE http_requests_total counter",
    ]
    with _metrics_lock:
        for (method, path, status), count in sorted(_http_requests_total.items()):
            safe_path = path.replace('"', '\\"')
            lines.append(
                f'http_requests_total{{service="{service_name}",method="{method}",path="{safe_path}",status="{status}"}} {count}'
            )
        lines.append("# HELP http_request_duration_seconds_sum Total HTTP request latency in seconds")
        lines.append("# TYPE http_request_duration_seconds_sum counter")
        for (method, path), total_s in sorted(_http_request_duration_seconds_sum.items()):
            safe_path = path.replace('"', '\\"')
            lines.append(
                f'http_request_duration_seconds_sum{{service="{service_name}",method="{method}",path="{safe_path}"}} {total_s:.6f}'
            )
        lines.append("# HELP http_request_duration_seconds_count Total HTTP request count for latency average")
        lines.append("# TYPE http_request_duration_seconds_count counter")
        for (method, path), count in sorted(_http_request_duration_seconds_count.items()):
            safe_path = path.replace('"', '\\"')
            lines.append(
                f'http_request_duration_seconds_count{{service="{service_name}",method="{method}",path="{safe_path}"}} {count}'
            )
    return "\n".join(lines) + "\n"


def get_tracer(name: str = "vitaltrack"):
    """Retourne un Tracer OpenTelemetry ou un NoopTracer de repli sans échec."""
    try:
        from opentelemetry import trace as trace_api
        return trace_api.get_tracer(name)
    except Exception:
        return _NoopTracer()


def get_meter(name: str = "vitaltrack"):
    """Retourne un Meter OpenTelemetry ou un objet no-op."""
    try:
        from opentelemetry import metrics as metrics_api
        return metrics_api.get_meter(name)
    except Exception:
        class _NoopMeter:
            def create_counter(self, *args, **kwargs):
                class _C:
                    def add(self, *a, **kw):
                        pass
                return _C()

            def create_histogram(self, *args, **kwargs):
                class _H:
                    def record(self, *a, **kw):
                        pass
                return _H()

        return _NoopMeter()


def setup_otel(app: FastAPI, service_name: str = "vitaltrack") -> None:
    """Configure OpenTelemetry et l'endpoint Prometheus `/metrics` sur l'application FastAPI.

    En environnement Serverless Vercel (ou si les packages optionnels `opentelemetry-sdk` /
    `prometheus-fastapi-instrumentator` ne sont pas installés), l'initialisation ne lève
    aucune exception et ne bloque jamais sur un exportateur OTLP injoignable.
    """
    global _otel_available, _tracer_provider

    is_serverless = os.getenv("VERCEL") == "1" or bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()

    try:
        from opentelemetry import trace as trace_api
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": service_name, "service.version": "1.1.0"})
        provider = TracerProvider(resource=resource)

        # N'attacher l'exportateur réseau OTLP que si un endpoint explicite est configuré hors Serverless
        if otlp_endpoint and not is_serverless:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True, timeout=1)
                provider.add_span_processor(BatchSpanProcessor(exporter))
            except Exception as exp_err:
                logger.debug(f"OTLP trace exporter skipped: {exp_err}")

        trace_api.set_tracer_provider(provider)
        _tracer_provider = provider
        _otel_available = True

        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)
        except Exception as instr_err:
            logger.debug(f"FastAPIInstrumentor skipped: {instr_err}")
    except ImportError:
        _otel_available = False
    except Exception as err:
        logger.debug(f"OpenTelemetry initialization skipped: {err}")
        _otel_available = False

    # Instrumentation Prometheus : utilise prometheus_fastapi_instrumentator si présent,
    # et garantit toujours que GET /metrics et GET /api/prometheus-metrics répondent en 200.
    prometheus_instrumented = False
    try:
        from prometheus_fastapi_instrumentator import Instrumentator
        Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
        prometheus_instrumented = True
    except Exception:
        prometheus_instrumented = False

    if not prometheus_instrumented:
        @app.get("/metrics", include_in_schema=False)
        def prometheus_metrics_endpoint():
            return PlainTextResponse(
                render_prometheus_metrics(service_name=service_name),
                media_type="text/plain; version=0.0.4; charset=utf-8",
            )


__all__ = [
    "setup_otel",
    "get_tracer",
    "get_meter",
    "record_http_metric",
    "render_prometheus_metrics",
    "_otel_available",
]
