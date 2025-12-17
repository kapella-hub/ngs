"""
NGS RAG Mock Service

A mock RAG (Retrieval Augmented Generation) service for local development.
Simulates AI-powered incident enrichment without requiring actual LLM infrastructure.
"""
import random
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="NGS RAG Mock Service",
    description="Mock RAG service for incident enrichment during development",
    version="0.1.0"
)

# =============================================================================
# Request/Response Models
# =============================================================================

class IncidentData(BaseModel):
    """Incident data from NGS."""
    id: str
    title: str
    source_tool: Optional[str] = None
    environment: Optional[str] = None
    region: Optional[str] = None
    host: Optional[str] = None
    check_name: Optional[str] = None
    service: Optional[str] = None
    severity: str
    status: str
    event_count: int
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class EventData(BaseModel):
    """Event data sample."""
    source_tool: Optional[str] = None
    host: Optional[str] = None
    check_name: Optional[str] = None
    service: Optional[str] = None
    severity: str
    state: str
    occurred_at: Optional[str] = None
    subject: Optional[str] = None
    body_sample: Optional[str] = None


class EnrichmentRequest(BaseModel):
    """Request for incident enrichment."""
    incident: IncidentData
    events: List[EventData] = Field(default_factory=list)
    request_type: str = "enrichment"
    max_suggestions: int = 5


class RunbookRef(BaseModel):
    """Runbook reference."""
    id: str
    title: str
    url: Optional[str] = None


class Evidence(BaseModel):
    """Evidence citation."""
    source: str
    snippet: str


class EnrichmentResponse(BaseModel):
    """Enrichment response."""
    summary: str
    category: str
    owner_team: str
    recommended_checks: List[str]
    suggested_runbooks: List[RunbookRef]
    safe_actions: List[str]
    confidence: float = Field(ge=0, le=1)
    evidence: List[Evidence]
    labels: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Mock Data
# =============================================================================

CATEGORIES = {
    "cpu": "Performance - CPU",
    "memory": "Performance - Memory",
    "disk": "Performance - Disk",
    "network": "Network",
    "database": "Database",
    "application": "Application",
    "security": "Security",
    "availability": "Availability",
    "configuration": "Configuration",
}

TEAMS = {
    "cpu": "Platform Team",
    "memory": "Platform Team",
    "disk": "Platform Team",
    "network": "Network Operations",
    "database": "DBA Team",
    "application": "Application Team",
    "security": "Security Team",
    "availability": "SRE Team",
    "configuration": "DevOps Team",
}

RUNBOOKS = {
    "cpu": [
        RunbookRef(id="rb-cpu-001", title="High CPU Investigation Guide", url="https://wiki.example.com/runbooks/cpu-high"),
        RunbookRef(id="rb-cpu-002", title="Process CPU Profiling", url="https://wiki.example.com/runbooks/cpu-profiling"),
    ],
    "memory": [
        RunbookRef(id="rb-mem-001", title="Memory Leak Investigation", url="https://wiki.example.com/runbooks/memory-leak"),
        RunbookRef(id="rb-mem-002", title="OOM Killer Analysis", url="https://wiki.example.com/runbooks/oom-killer"),
    ],
    "disk": [
        RunbookRef(id="rb-disk-001", title="Disk Space Cleanup Guide", url="https://wiki.example.com/runbooks/disk-cleanup"),
        RunbookRef(id="rb-disk-002", title="Disk I/O Investigation", url="https://wiki.example.com/runbooks/disk-io"),
    ],
    "network": [
        RunbookRef(id="rb-net-001", title="Network Connectivity Troubleshooting", url="https://wiki.example.com/runbooks/network-connectivity"),
        RunbookRef(id="rb-net-002", title="DNS Resolution Issues", url="https://wiki.example.com/runbooks/dns-issues"),
    ],
    "database": [
        RunbookRef(id="rb-db-001", title="Database Connection Pool Exhaustion", url="https://wiki.example.com/runbooks/db-connections"),
        RunbookRef(id="rb-db-002", title="Slow Query Investigation", url="https://wiki.example.com/runbooks/slow-queries"),
    ],
    "application": [
        RunbookRef(id="rb-app-001", title="Application Error Investigation", url="https://wiki.example.com/runbooks/app-errors"),
        RunbookRef(id="rb-app-002", title="Service Restart Procedure", url="https://wiki.example.com/runbooks/service-restart"),
    ],
    "default": [
        RunbookRef(id="rb-gen-001", title="General Incident Response", url="https://wiki.example.com/runbooks/incident-response"),
    ],
}

CHECKS = {
    "cpu": [
        "Check process CPU usage with 'top' or 'htop'",
        "Review recent deployments that may have introduced CPU regression",
        "Check for runaway processes or infinite loops",
        "Verify auto-scaling is functioning correctly",
    ],
    "memory": [
        "Check memory usage with 'free -m'",
        "Look for memory leaks using profiling tools",
        "Review application logs for OOM events",
        "Check swap usage and configuration",
    ],
    "disk": [
        "Check disk usage with 'df -h'",
        "Identify large files with 'du -sh /*'",
        "Review log rotation configuration",
        "Check for zombie processes holding deleted files",
    ],
    "network": [
        "Verify network connectivity with ping/traceroute",
        "Check DNS resolution",
        "Review firewall rules and security groups",
        "Check for network interface errors",
    ],
    "database": [
        "Check database connection count",
        "Review slow query logs",
        "Verify database replication status",
        "Check database disk space and I/O",
    ],
    "application": [
        "Review application logs for errors",
        "Check application health endpoints",
        "Verify configuration changes",
        "Check dependent service availability",
    ],
    "default": [
        "Review relevant logs",
        "Check service status",
        "Verify recent changes",
    ],
}

SAFE_ACTIONS = {
    "cpu": [
        "Identify and terminate runaway processes",
        "Trigger horizontal auto-scaling",
        "Enable CPU throttling for non-critical workloads",
    ],
    "memory": [
        "Clear application caches",
        "Trigger garbage collection (if applicable)",
        "Restart affected service with memory limits",
    ],
    "disk": [
        "Clear temporary files older than 7 days",
        "Rotate and compress old logs",
        "Remove old deployment artifacts",
    ],
    "network": [
        "Restart network interface (with caution)",
        "Flush DNS cache",
        "Reload firewall rules",
    ],
    "database": [
        "Kill idle connections older than 1 hour",
        "Run VACUUM ANALYZE (PostgreSQL)",
        "Clear query cache",
    ],
    "application": [
        "Graceful service restart",
        "Clear application cache",
        "Reload configuration",
    ],
    "default": [
        "Escalate to on-call engineer",
    ],
}


# =============================================================================
# Helper Functions
# =============================================================================

def detect_category(incident: IncidentData, events: List[EventData]) -> str:
    """Detect incident category from content."""
    content = " ".join([
        incident.title or "",
        incident.check_name or "",
        incident.service or "",
        " ".join([e.subject or "" for e in events]),
        " ".join([e.body_sample or "" for e in events]),
    ]).lower()

    if any(w in content for w in ["cpu", "load", "processor"]):
        return "cpu"
    if any(w in content for w in ["memory", "mem", "oom", "heap", "ram"]):
        return "memory"
    if any(w in content for w in ["disk", "storage", "filesystem", "inode", "space"]):
        return "disk"
    if any(w in content for w in ["network", "dns", "connectivity", "ping", "timeout", "connection"]):
        return "network"
    if any(w in content for w in ["database", "db", "mysql", "postgres", "redis", "mongo", "sql"]):
        return "database"
    if any(w in content for w in ["application", "app", "error", "exception", "500", "crash"]):
        return "application"
    if any(w in content for w in ["security", "auth", "ssl", "cert", "unauthorized"]):
        return "security"

    return "default"


def generate_summary(incident: IncidentData, category: str) -> str:
    """Generate a summary for the incident."""
    severity = incident.severity.upper()
    host = incident.host or "multiple hosts"
    check = incident.check_name or incident.service or "system check"

    summaries = {
        "cpu": f"- {severity} CPU utilization detected on {host}\n- Check '{check}' triggered {incident.event_count} times\n- May indicate runaway process or insufficient capacity",
        "memory": f"- {severity} memory pressure on {host}\n- Check '{check}' triggered {incident.event_count} times\n- Possible memory leak or OOM condition",
        "disk": f"- {severity} disk space/IO issue on {host}\n- Check '{check}' triggered {incident.event_count} times\n- Review disk usage and log rotation",
        "network": f"- {severity} network issue affecting {host}\n- Check '{check}' triggered {incident.event_count} times\n- May be connectivity, DNS, or firewall related",
        "database": f"- {severity} database issue detected for {host}\n- Check '{check}' triggered {incident.event_count} times\n- Review connection pools and query performance",
        "application": f"- {severity} application error on {host}\n- Check '{check}' triggered {incident.event_count} times\n- Review application logs for root cause",
    }

    return summaries.get(category, f"- {severity} alert on {host}\n- Check '{check}' triggered {incident.event_count} times\n- Review system logs for details")


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/healthz")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "rag-mock"}


@app.post("/enrich", response_model=EnrichmentResponse)
async def enrich_incident(request: EnrichmentRequest):
    """
    Mock incident enrichment endpoint.

    Returns simulated AI-generated insights based on incident content.
    """
    # Simulate processing time
    time.sleep(random.uniform(0.5, 2.0))

    # Detect category
    category = detect_category(request.incident, request.events)
    category_name = CATEGORIES.get(category, "General")
    owner_team = TEAMS.get(category, "Operations Team")

    # Generate response
    summary = generate_summary(request.incident, category)
    checks = CHECKS.get(category, CHECKS["default"])[:request.max_suggestions]
    runbooks = RUNBOOKS.get(category, RUNBOOKS["default"])[:3]
    actions = SAFE_ACTIONS.get(category, SAFE_ACTIONS["default"])[:3]

    # Generate evidence
    evidence = []
    if request.events:
        for event in request.events[:2]:
            if event.subject:
                evidence.append(Evidence(
                    source="email_subject",
                    snippet=event.subject[:200]
                ))
            if event.body_sample:
                evidence.append(Evidence(
                    source="email_body",
                    snippet=event.body_sample[:200]
                ))

    # Confidence based on data quality
    confidence = 0.7
    if request.incident.host:
        confidence += 0.1
    if request.incident.check_name or request.incident.service:
        confidence += 0.1
    if len(request.events) > 0:
        confidence += 0.05
    confidence = min(confidence, 0.95)

    return EnrichmentResponse(
        summary=summary,
        category=category_name,
        owner_team=owner_team,
        recommended_checks=checks,
        suggested_runbooks=runbooks,
        safe_actions=actions,
        confidence=round(confidence, 2),
        evidence=evidence[:5],
        labels={
            "auto_category": category,
            "severity_confirmed": request.incident.severity,
        }
    )


@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "NGS RAG Mock Service",
        "version": "0.1.0",
        "description": "Mock service for incident enrichment during development",
        "endpoints": {
            "health": "/healthz",
            "enrich": "POST /enrich"
        }
    }
