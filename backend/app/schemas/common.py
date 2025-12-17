"""Common schemas and enums."""
from datetime import datetime
from enum import Enum
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field


class SeverityLevel(str, Enum):
    """Severity levels for alerts and incidents."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class IncidentStatus(str, Enum):
    """Status states for incidents."""
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class AlertState(str, Enum):
    """Alert state (firing or resolved)."""
    FIRING = "firing"
    RESOLVED = "resolved"
    UNKNOWN = "unknown"


class SuppressMode(str, Enum):
    """Suppression behavior mode."""
    MUTE = "mute"
    DOWNGRADE = "downgrade"
    DIGEST = "digest"


class MaintenanceSource(str, Enum):
    """Source of maintenance window."""
    EMAIL = "email"
    MANUAL = "manual"
    GRAPH = "graph"


class UserRole(str, Enum):
    """User role levels."""
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""
    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    version: str


class ErrorResponse(BaseModel):
    """Error response model."""
    detail: str
    code: Optional[str] = None


class AuditInfo(BaseModel):
    """Audit information for tracking changes."""
    action: str
    user_id: Optional[str] = None
    timestamp: datetime
    old_value: Optional[dict] = None
    new_value: Optional[dict] = None
