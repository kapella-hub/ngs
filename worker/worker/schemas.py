"""Pydantic schemas for LLM output validation and confidence gating.

This module provides strict schema validation for LLM extraction results,
ensuring type safety and preventing malformed data from entering the system.
"""
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Confidence thresholds
CONFIDENCE_THRESHOLD = 0.75  # Above this: use LLM result
QUARANTINE_THRESHOLD = 0.4   # Below this: send to quarantine


class Severity(str, Enum):
    """Normalized severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class State(str, Enum):
    """Alert state enumeration."""
    FIRING = "firing"
    RESOLVED = "resolved"
    UNKNOWN = "unknown"


class LLMExtractionResult(BaseModel):
    """
    Validated schema for LLM extraction output.

    All fields are optional since LLM may not extract all fields,
    but confidence is required to enable gating decisions.
    """
    host: Optional[str] = Field(None, max_length=255)
    service: Optional[str] = Field(None, max_length=255)
    severity: Optional[str] = Field(None, max_length=50)
    state: Optional[str] = Field(None, max_length=50)
    summary: Optional[str] = Field(None, max_length=1000)
    source_tool: Optional[str] = Field(None, max_length=100)
    source_name: Optional[str] = Field(None, max_length=255)
    extraction_type: Optional[str] = Field(None, max_length=50)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)

    # Additional extracted fields (flexible)
    extra_fields: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @field_validator('host', 'service', 'source_tool', mode='before')
    @classmethod
    def sanitize_strings(cls, v):
        """Sanitize string fields by stripping and truncating."""
        if v is not None and isinstance(v, str):
            return v.strip()[:255]
        return v

    @field_validator('severity', mode='before')
    @classmethod
    def normalize_severity(cls, v):
        """Normalize severity to standard levels."""
        if v is None:
            return None

        severity_lower = str(v).lower().strip()

        severity_map = {
            "critical": "critical",
            "crit": "critical",
            "emergency": "critical",
            "alert": "critical",
            "excessive": "high",
            "firing": "high",
            "high": "high",
            "major": "high",
            "error": "high",
            "warning": "medium",
            "warn": "medium",
            "medium": "medium",
            "minor": "low",
            "low": "low",
            "info": "info",
            "informational": "info",
            "ok": "info",
            "resolved": "info",
            "recovery": "info",
            "green": "info",
            "yellow": "medium",
            "red": "critical"
        }

        return severity_map.get(severity_lower, "medium")

    @field_validator('state', mode='before')
    @classmethod
    def normalize_state(cls, v):
        """Normalize state to standard values."""
        if v is None:
            return None

        state_lower = str(v).lower().strip()

        if state_lower in ["ok", "resolved", "recovery", "green", "closed", "clear"]:
            return "resolved"
        if state_lower in ["problem", "critical", "warning", "firing", "red", "yellow", "triggered", "open"]:
            return "firing"

        return "unknown"

    @field_validator('summary', mode='before')
    @classmethod
    def truncate_summary(cls, v):
        """Truncate summary to max length."""
        if v is not None and isinstance(v, str):
            return v.strip()[:1000]
        return v

    @model_validator(mode='after')
    def validate_extraction_quality(self):
        """Validate that extraction has minimum required data."""
        # At least one identifying field should be present for useful extraction
        has_identification = any([
            self.host,
            self.service,
            self.source_tool
        ])

        # If no identification and confidence is low, this is a poor extraction
        if not has_identification and self.confidence < QUARANTINE_THRESHOLD:
            # Don't reject, but flag via confidence
            pass

        return self

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        result = {}
        for field_name in self.model_fields:
            value = getattr(self, field_name)
            if value is not None and field_name != 'extra_fields':
                result[field_name] = value

        # Merge extra fields
        if self.extra_fields:
            result.update(self.extra_fields)

        return result


class QuarantineReason(str, Enum):
    """Reasons for quarantining an extraction."""
    LOW_CONFIDENCE = "low_confidence"
    VALIDATION_FAILED = "validation_failed"
    MISSING_REQUIRED_FIELDS = "missing_required_fields"
    SUSPICIOUS_CONTENT = "suspicious_content"
    LLM_ERROR = "llm_error"


class QuarantineAction(str, Enum):
    """Actions that can be taken on quarantined items."""
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


class NotificationChannel(BaseModel):
    """Configuration for a notification channel."""
    id: Optional[str] = None
    name: str = Field(max_length=100)
    channel_type: str = Field(max_length=20)  # 'slack', 'webhook', 'email'
    config: Dict[str, Any] = Field(default_factory=dict)
    severity_filter: Optional[list] = None
    enabled: bool = True

    @field_validator('channel_type', mode='before')
    @classmethod
    def validate_channel_type(cls, v):
        valid_types = ['slack', 'webhook', 'email', 'pagerduty']
        if v not in valid_types:
            raise ValueError(f"channel_type must be one of {valid_types}")
        return v


class NotificationPayload(BaseModel):
    """Payload for sending notifications."""
    incident_id: str
    title: str = Field(max_length=200)
    message: str = Field(max_length=2000)
    severity: str = Field(max_length=20)
    state: str = Field(max_length=20)
    host: Optional[str] = None
    service: Optional[str] = None
    occurred_at: Optional[str] = None
    url: Optional[str] = None  # Link to incident in UI


class ResolutionReason(str, Enum):
    """Reasons for incident resolution."""
    EXPLICIT_CLEAR = "explicit_clear"      # Clear event received
    QUIET_PERIOD = "quiet_period"          # No events for threshold
    MANUAL = "manual"                       # User marked resolved
    MAINTENANCE = "maintenance"             # Within maintenance window
    STALE = "stale"                         # Auto-resolved due to age


class IncidentStatus(str, Enum):
    """Incident status states."""
    OPEN = "open"
    RESOLVING = "resolving"  # Clear received, waiting for quiet period
    RESOLVED = "resolved"
