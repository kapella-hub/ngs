"""Incident-related schemas."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import SeverityLevel, IncidentStatus, AlertState


class AlertEventBase(BaseModel):
    """Base alert event schema."""
    source_tool: str
    environment: Optional[str] = None
    region: Optional[str] = None
    host: Optional[str] = None
    check_name: Optional[str] = None
    service: Optional[str] = None
    severity: SeverityLevel = SeverityLevel.MEDIUM
    state: AlertState = AlertState.FIRING
    occurred_at: datetime
    payload: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


class AlertEventResponse(AlertEventBase):
    """Alert event response schema."""
    id: UUID
    raw_email_id: Optional[UUID] = None
    normalized_signature: str
    fingerprint: str
    is_suppressed: bool
    suppression_reason: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AIEnrichment(BaseModel):
    """AI enrichment data for an incident."""
    summary: Optional[str] = None
    category: Optional[str] = None
    owner_team: Optional[str] = None
    recommended_checks: List[str] = Field(default_factory=list)
    suggested_runbooks: List[Dict[str, Any]] = Field(default_factory=list)
    safe_actions: List[str] = Field(default_factory=list)
    confidence: Optional[float] = Field(None, ge=0, le=1)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    enriched_at: Optional[datetime] = None


class IncidentBase(BaseModel):
    """Base incident schema."""
    title: str
    description: Optional[str] = None
    source_tool: Optional[str] = None
    environment: Optional[str] = None
    region: Optional[str] = None
    host: Optional[str] = None
    check_name: Optional[str] = None
    service: Optional[str] = None
    severity: SeverityLevel = SeverityLevel.MEDIUM
    tags: List[str] = Field(default_factory=list)
    labels: Dict[str, str] = Field(default_factory=dict)


class IncidentSummary(IncidentBase):
    """Incident summary for list views."""
    id: UUID
    fingerprint: str
    status: IncidentStatus
    first_seen_at: datetime
    last_seen_at: datetime
    event_count: int
    is_in_maintenance: bool
    ai_category: Optional[str] = None
    owner_team: Optional[str] = None

    class Config:
        from_attributes = True


class IncidentDetail(IncidentSummary):
    """Full incident detail schema."""
    resolved_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[UUID] = None
    resolved_by: Optional[UUID] = None
    assigned_to: Optional[UUID] = None
    maintenance_window_id: Optional[UUID] = None
    flap_count: int = 0
    last_state_change_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # AI enrichment
    ai_summary: Optional[str] = None
    ai_owner_team: Optional[str] = None
    ai_recommended_checks: List[str] = Field(default_factory=list)
    ai_suggested_runbooks: List[Dict[str, Any]] = Field(default_factory=list)
    ai_safe_actions: List[str] = Field(default_factory=list)
    ai_confidence: Optional[float] = None
    ai_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    ai_enriched_at: Optional[datetime] = None
    ai_labels: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class IncidentWithEvents(IncidentDetail):
    """Incident with associated events."""
    events: List[AlertEventResponse] = Field(default_factory=list)
    recent_events: List[AlertEventResponse] = Field(default_factory=list)


class IncidentComment(BaseModel):
    """Incident comment schema."""
    id: UUID
    incident_id: UUID
    user_id: Optional[UUID] = None
    content: str
    is_system_generated: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CommentCreate(BaseModel):
    """Create comment request."""
    content: str = Field(..., min_length=1, max_length=10000)


class AcknowledgeRequest(BaseModel):
    """Acknowledge incident request."""
    comment: Optional[str] = None


class ResolveRequest(BaseModel):
    """Resolve incident request."""
    comment: Optional[str] = None


class SuppressRequest(BaseModel):
    """Suppress incident request."""
    duration_minutes: Optional[int] = Field(None, gt=0, le=43200)  # Max 30 days
    reason: str = Field(..., min_length=1, max_length=1000)


class IncidentFilters(BaseModel):
    """Filters for incident list queries."""
    status: Optional[List[IncidentStatus]] = None
    severity: Optional[List[SeverityLevel]] = None
    source_tool: Optional[List[str]] = None
    environment: Optional[List[str]] = None
    region: Optional[List[str]] = None
    host: Optional[str] = None
    in_maintenance: Optional[bool] = None
    search: Optional[str] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None


class RawEmailResponse(BaseModel):
    """Raw email data for viewing."""
    id: UUID
    folder: str
    uid: int
    message_id: Optional[str] = None
    subject: Optional[str] = None
    from_address: Optional[str] = None
    to_addresses: List[str] = Field(default_factory=list)
    date_header: Optional[datetime] = None
    headers: Dict[str, Any] = Field(default_factory=dict)
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    received_at: datetime

    class Config:
        from_attributes = True
