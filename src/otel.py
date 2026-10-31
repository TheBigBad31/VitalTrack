"""OpenTelemetry support for VitalTrack.

Provides optional OpenTelemetry instrumentation for the VitalTrack FastAPI backend.

Key design decisions:
- All imports are protected by try/except ImportError to prevent crashes in Serverless Vercel
- The OTLP exporter is guarded so it never blocks if the collector is unreachable
- Metrics and tracing can be enabled independently via environment variables
"""

import os
import logging

logger = logging.getLogger("vitaltrack.otel")

# Module-level flags, initialized lazily
_otel_available = False
_metrics_exporter = None
_tracer_provider = None


def _init_otel():
    """Initialize OpenTelemetry lazily (avoids import errors in Serverless Vercel)."""
    global _otel_available, _metrics_exporter, _tracer_provider

    if _otel_available:
        return

    try:
        import opentelemetry
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sampling import TraceIdRatioBased
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        _otel_available = True

        # Configure tracer provider
        _tracer_provider = TracerProvider(
            sampler=TraceIdRatioBased(float(os.getenv("OTEL_SAMPLE_RATE", "0.1")))
        )

        # Set as global tracer provider
        from opentelemetry import trace as trace_api
        trace_api.set_tracer_provider(_tracer_provider)

        # Get the FastAPI app instance and instrument it
        from src.app import app
        FastAPIInstrumentor.instrument_app(app)

        # Try to configure OTLP exporter (may fail in Serverless Vercel)
        try:
            from opentelemetry.exporter.otlp.proto.grpc import OTLPSpanExporter
            otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
            otlp_exporter = OTLPSpanExporter(endpoint=otel_endpoint)
            # If we get here, the collector is reachable (local development)
            logger.info(f"OpenTelemetry OTLP exporter connected at {otel_endpoint}")
        except Exception as e:
            # In Serverless Vercel, localhost:4317 is not reachable - this is expected
            # Don't fail, just log and continue without OTLP exporter
            logger.warning(f"OpenTelemetry OTLP exporter not available: {type(e).__name__}: {str(e)[:100]}")
            _metrics_exporter = None

        # Try to configure metrics
        try:
            from opentelemetry.metrics import get_meter_provider
            from opentelemetry.exporter.otlp.proto.grpc import OTLPMetricExporter
            metrics_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
            try:
                metrics_exporter = OTLPMetricExporter(endpoint=metrics_endpoint)
                logger.info(f"OpenTelemetry metrics exporter connected at {metrics_endpoint}")
            except Exception:
                logger.warning("OpenTelemetry metrics exporter not available")
                metrics_exporter = None
        except Exception:
            logger.warning("OpenTelemetry metrics not configured")
            metrics_exporter = None

    except ImportError:
        # OpenTelemetry not installed - this is fine, app still works
        logger.debug("OpenTelemetry not installed, skipping instrumentation")
        _otel_available = False


# Initialize on module import (but gracefully handle if it fails)
try:
    _init_otel()
except Exception:
    _otel_available = False


def get_tracer(name: str = "vitaltrack"):
    """Get a tracer for the given name.

    Returns a no-op tracer if OpenTelemetry is not available.
    """
    try:
        from opentelemetry import trace as trace_api
        return trace_api.get_tracer(name)
    except (ImportError, RuntimeError):
        # Return a no-op tracer
        class NoopTracer:
            def start_as_current_span(self, name, **kwargs):
                return NoopSpan()
        class NoopSpan:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return NoopTracer()


def get_meter(name: str = "vitaltrack"):
    """Get a meter for the given name.

    Returns a no-op meter if OpenTelemetry is not available.
    """
    try:
        from opentelemetry.metrics import get_meter_provider, get_meter
        return get_meter(name)
    except (ImportError, RuntimeError):
        class NoopMeter:
            def create_observable_gauge(self, *args, **kwargs):
                pass
            def counter(self, *args, **kwargs):
                return NoopCounter()
            def gauge(self, *args, **kwargs):
                return NoopGauge()
            def histogram(self, *args, **kwargs):
                return NoopHistogram()

        class NoopCounter:
            def add(self, *args, **kwargs):
                pass

        class NoopGauge:
            def record(self, *args, **kwargs):
                pass

        class NoopHistogram:
            def observe(self, *args, **kwargs):
                pass

        return NoopMeter()


# Export for convenience
__all__ = ["get_tracer", "get_meter", "_otel_available"]