"""Maintenance window schemas."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import SuppressMode, MaintenanceSource


class MaintenanceScope(BaseModel):
    """Scope definition for maintenance windows."""
    hosts: List[str] = Field(default_factory=list)
    host_regex: Optional[str] = None
    services: List[str] = Field(default_factory=list)
    service_regex: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    environments: List[str] = Field(default_factory=list)
    regions: List[str] = Field(default_factory=list)
    check_names: List[str] = Field(default_factory=list)


class MaintenanceWindowBase(BaseModel):
    """Base maintenance window schema."""
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    start_ts: datetime
    end_ts: datetime
    timezone: str = "UTC"
    scope: MaintenanceScope = Field(default_factory=MaintenanceScope)
    suppress_mode: SuppressMode = SuppressMode.MUTE
    reason: Optional[str] = None

    @field_validator("end_ts")
    @classmethod
    def end_after_start(cls, v, info):
        if "start_ts" in info.data and v <= info.data["start_ts"]:
            raise ValueError("end_ts must be after start_ts")
        return v


class MaintenanceWindowCreate(MaintenanceWindowBase):
    """Create maintenance window request."""
    pass


class MaintenanceWindowUpdate(BaseModel):
    """Update maintenance window request."""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    start_ts: Optional[datetime] = None
    end_ts: Optional[datetime] = None
    timezone: Optional[str] = None
    scope: Optional[MaintenanceScope] = None
    suppress_mode: Optional[SuppressMode] = None
    reason: Optional[str] = None
    is_active: Optional[bool] = None


class MaintenanceWindowResponse(MaintenanceWindowBase):
    """Maintenance window response schema."""
    id: UUID
    source: MaintenanceSource
    external_event_id: Optional[str] = None
    raw_email_id: Optional[UUID] = None
    organizer: Optional[str] = None
    organizer_email: Optional[str] = None
    is_recurring: bool = False
    recurrence_rule: Optional[str] = None
    is_active: bool = True
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MaintenanceWindowDetail(MaintenanceWindowResponse):
    """Detailed maintenance window with match info."""
    affected_incident_count: int = 0
    affected_incidents: List[Dict[str, Any]] = Field(default_factory=list)


class MaintenanceMatchResponse(BaseModel):
    """Maintenance match explanation."""
    id: UUID
    maintenance_window_id: UUID
    incident_id: Optional[UUID] = None
    alert_event_id: Optional[UUID] = None
    match_reason: Dict[str, Any]
    matched_at: datetime

    class Config:
        from_attributes = True


class MaintenanceFilters(BaseModel):
    """Filters for maintenance window queries."""
    source: Optional[List[MaintenanceSource]] = None
    is_active: Optional[bool] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    search: Optional[str] = None
