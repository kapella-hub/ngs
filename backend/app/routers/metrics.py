"""Metrics router - Prometheus-compatible metrics."""
from prometheus_client import Counter, Gauge, Histogram

# Define Prometheus metrics
INCIDENTS_TOTAL = Counter(
    "ngs_incidents_total",
    "Total incidents created",
    ["severity", "source_tool"]
)

INCIDENTS_CURRENT = Gauge(
    "ngs_incidents_current",
    "Current incidents by status",
    ["status", "severity"]
)

EVENTS_PROCESSED = Counter(
    "ngs_events_processed_total",
    "Total alert events processed",
    ["source_tool", "parse_status"]
)

EMAILS_INGESTED = Counter(
    "ngs_emails_ingested_total",
    "Total emails ingested",
    ["folder"]
)

MAINTENANCE_WINDOWS_ACTIVE = Gauge(
    "ngs_maintenance_windows_active",
    "Currently active maintenance windows"
)

RAG_REQUESTS = Counter(
    "ngs_rag_requests_total",
    "Total RAG enrichment requests",
    ["status"]
)

RAG_LATENCY = Histogram(
    "ngs_rag_request_duration_seconds",
    "RAG request latency",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)

DEDUP_COUNT = Counter(
    "ngs_deduplicated_events_total",
    "Total deduplicated events",
    ["source_tool"]
)

PARSE_FAILURES = Counter(
    "ngs_parse_failures_total",
    "Total parse failures",
    ["folder", "error_type"]
)


def increment_incidents_created(severity: str, source_tool: str):
    """Increment incidents created counter."""
    INCIDENTS_TOTAL.labels(severity=severity, source_tool=source_tool or "unknown").inc()


def set_incidents_gauge(status: str, severity: str, count: int):
    """Set current incidents gauge."""
    INCIDENTS_CURRENT.labels(status=status, severity=severity).set(count)


def increment_events_processed(source_tool: str, parse_status: str):
    """Increment events processed counter."""
    EVENTS_PROCESSED.labels(source_tool=source_tool or "unknown", parse_status=parse_status).inc()


def increment_emails_ingested(folder: str):
    """Increment emails ingested counter."""
    EMAILS_INGESTED.labels(folder=folder).inc()


def set_maintenance_active(count: int):
    """Set active maintenance windows gauge."""
    MAINTENANCE_WINDOWS_ACTIVE.set(count)


def record_rag_request(status: str, duration: float):
    """Record RAG request metrics."""
    RAG_REQUESTS.labels(status=status).inc()
    RAG_LATENCY.observe(duration)


def increment_dedup_count(source_tool: str):
    """Increment dedup counter."""
    DEDUP_COUNT.labels(source_tool=source_tool or "unknown").inc()


def increment_parse_failure(folder: str, error_type: str):
    """Increment parse failure counter."""
    PARSE_FAILURES.labels(folder=folder, error_type=error_type).inc()
