# ABOUTME: OpenTelemetry instrumentation for forkhub — traces, metrics, log bridge.
# ABOUTME: No-op when the OTel SDK is absent (zero runtime cost); configure() once at startup.

"""OpenTelemetry instrumentation for forkhub.

Design:
  - **No-op when absent.** If the OTel SDK isn't installed, `tracer`/`meter` are cheap
    stand-ins and every record call is a no-op — so instrumentation can live in hot paths
    with zero cost in production. Install the real thing with `uv add` (or `uv sync --group otel`).
  - **Module-attribute access.** Import the module and use `otel.tracer` / `otel.meter`,
    NOT `from otel import tracer`. `configure()` reassigns these after wiring the real SDK;
    a `from`-import would capture the stale no-op binding.
  - **Log bridge with both gates handled.** `configure()` attaches a LoggingHandler AND lowers
    the root logger to INFO — otherwise the root's WARNING default filters INFO records before
    the handler ever sees them (a silent "logs sink stays empty" bug).

Usage:
    import forkhub.otel as otel
    otel.configure()                       # once, at app startup
    with otel.span("handle_request"):      # tracing
        otel.record_<instrument>(...)      # metrics — see DOMAIN INSTRUMENTS below
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_logger = logging.getLogger("forkhub")

_OTEL_AVAILABLE = False
try:
    from opentelemetry import metrics as _metrics_api
    from opentelemetry import trace as _trace_api
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover — only when OTel SDK is absent
    pass


# --- No-op stand-ins (used when the SDK isn't installed) -----------------------
# These use __getattr__ to absorb the WHOLE OTel API surface, not just the few methods
# this module happens to call. The real Meter exposes 7 create_* factories and Span ~11
# methods; enumerating a subset would make `otel.meter.create_gauge(...)` or
# `span.set_status(...)` raise AttributeError ONLY on machines without the SDK — an
# environment-dependent divergence that defeats the "calling code can't tell" promise.


class _NoOpSpan:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __getattr__(self, _name):  # set_attribute, add_event, set_status, record_exception, ...
        return lambda *a, **k: None


class _NoOpTracer:
    @contextmanager
    def start_as_current_span(self, name: str, **kwargs) -> Iterator[_NoOpSpan]:
        yield _NoOpSpan()


class _NoOpInstrument:
    """Stands in for any OTel instrument — counter, histogram, gauge, up/down counter."""

    def __getattr__(self, _name):  # add, record, set, ...
        return lambda *a, **k: None


class _NoOpMeter:
    def __getattr__(self, _name):  # create_counter, create_histogram, create_gauge, ...
        return lambda *a, **k: _NoOpInstrument()


# --- Module-level handles — resolve via attribute, not from-import --------------

SERVICE_NAME = "forkhub"
OTLP_HTTP_ENDPOINT = os.getenv("OTLP_HTTP_ENDPOINT", "http://127.0.0.1:4418")
_configured = False

tracer = _trace_api.get_tracer(SERVICE_NAME) if _OTEL_AVAILABLE else _NoOpTracer()
meter = _metrics_api.get_meter(SERVICE_NAME) if _OTEL_AVAILABLE else _NoOpMeter()


def configure(endpoint: str | None = None) -> bool:
    """Wire OTLP HTTP exporters for traces, metrics, and logs. Idempotent.

    Returns True if OTel was configured, False if the SDK isn't installed.
    """
    global tracer, meter, _configured  # noqa: PLW0603
    if not _OTEL_AVAILABLE:
        # debug, not warning: configure() runs on every CLI command, and the OTel
        # SDK is a dev-only dependency group — so a default install would otherwise
        # print this on every invocation. The False return is the real signal; this
        # is a quiet breadcrumb for anyone who enabled debug logging while wiring it.
        _logger.debug(
            "OTel SDK not installed — instrumentation is no-op. Install with: uv sync --group otel"
        )
        return False
    if _configured:
        return True

    ep = endpoint or OTLP_HTTP_ENDPOINT
    resource = Resource.create({"service.name": SERVICE_NAME})

    # Traces
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{ep}/v1/traces")))
    _trace_api.set_tracer_provider(tp)
    tracer = _trace_api.get_tracer(SERVICE_NAME)

    # Metrics (push every 5s so data shows up quickly during development)
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{ep}/v1/metrics"), export_interval_millis=5_000
    )
    _metrics_api.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
    meter = _metrics_api.get_meter(SERVICE_NAME)

    # Logs — bridge stdlib logging so the logs sink fills and records carry trace IDs.
    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{ep}/v1/logs")))
    set_logger_provider(lp)
    root = logging.getLogger()
    root.addHandler(LoggingHandler(level=logging.INFO, logger_provider=lp))
    # Root defaults to WARNING, which would gate INFO before the handler sees it.
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)

    _build_instruments()
    _configured = True
    # "configured", not "exporting": the exporters are wired, but delivery happens in
    # background batch threads that silently drop if the collector is down. Wired ≠ delivered.
    _logger.info("OTel configured for %s — target %s (delivery not verified)", SERVICE_NAME, ep)
    return True


@contextmanager
def span(name: str, **attrs: str) -> Iterator[object]:
    """Convenience span with string attributes. No-op when OTel is absent."""
    with tracer.start_as_current_span(name) as s:
        for k, v in attrs.items():
            s.set_attribute(k, v)
        yield s


# ============================ DOMAIN INSTRUMENTS ===============================
# The instrumentation scan fills this section with project-specific instruments and
# their record_* helpers. Build instruments inside _build_instruments() (so they bind
# to the real meter after configure()), expose module-level handles, and add a thin
# record_* function per instrument that no-ops until configured.
#
# Example (delete and replace with what the scan proposes):
#
#   _request_latency = None
#   def _build_instruments() -> None:
#       global _request_latency  # noqa: PLW0603
#       _request_latency = meter.create_histogram(
#           "request.latency", unit="ms", description="Wall-clock per request")
#   def record_request_latency(route: str, ms: float) -> None:
#       if _request_latency is None: return
#       _request_latency.record(ms, {"route": route})


def _build_instruments() -> None:
    """Create domain instruments. Called by configure() after the meter is real."""
    global _tool_calls, _tool_latency, _session_cost, _session_turns, _signals_stored  # noqa: PLW0603
    _tool_calls = meter.create_counter(
        "forkhub.tool.calls", description="Agent MCP tool invocations by tool and outcome"
    )
    _tool_latency = meter.create_histogram(
        "forkhub.tool.latency", unit="ms", description="Agent MCP tool wall-clock latency"
    )
    _session_cost = meter.create_histogram(
        "forkhub.agent.session.cost_usd", unit="usd", description="Cost per agent analysis session"
    )
    _session_turns = meter.create_histogram(
        "forkhub.agent.session.turns", description="Turns per agent analysis session"
    )
    _signals_stored = meter.create_counter(
        "forkhub.signals.stored", description="Signals persisted by the agent, by category"
    )


_tool_calls = None
_tool_latency = None
_session_cost = None
_session_turns = None
_signals_stored = None


# record_* helpers swallow their own exceptions: these run on the business
# path (record_tool_call fires from a tool wrapper's `finally`), so a throwing
# exporter must never convert a working tool call into a failure. Telemetry
# fails open. The no-op stand-ins can't raise, so this only matters once a real
# (possibly misconfigured) provider is wired.


def record_tool_call(tool: str, ok: bool, ms: float) -> None:
    """Count one MCP tool call and its latency, labelled by tool name and outcome."""
    try:
        if _tool_calls is not None:
            _tool_calls.add(1, {"tool": tool, "ok": str(ok).lower()})
        if _tool_latency is not None:
            _tool_latency.record(ms, {"tool": tool})
    except Exception:  # pragma: no cover — telemetry must not break the caller
        _logger.debug("record_tool_call failed", exc_info=True)


def record_session(cost_usd: float, turns: int) -> None:
    """Record the cost and turn count of one completed agent analysis session."""
    try:
        if _session_cost is not None:
            _session_cost.record(cost_usd)
        if _session_turns is not None:
            _session_turns.record(turns)
    except Exception:  # pragma: no cover — telemetry must not break the caller
        _logger.debug("record_session failed", exc_info=True)


def record_signal_stored(category: str) -> None:
    """Count one signal the agent successfully persisted, labelled by category."""
    try:
        if _signals_stored is not None:
            _signals_stored.add(1, {"category": category})
    except Exception:  # pragma: no cover — telemetry must not break the caller
        _logger.debug("record_signal_stored failed", exc_info=True)


# ===============================================================================
