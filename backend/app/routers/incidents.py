"""Incidents router."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import get_db_connection
from app.routers.auth import get_current_user
from app.schemas.incidents import (
    IncidentSummary, IncidentDetail, IncidentWithEvents,
    AlertEventResponse, IncidentComment, CommentCreate,
    AcknowledgeRequest, ResolveRequest, SuppressRequest,
    RawEmailResponse
)
from app.schemas.common import IncidentStatus, SeverityLevel, PaginatedResponse
from app.services.audit import log_audit

logger = structlog.get_logger()
router = APIRouter()


@router.get("", response_model=PaginatedResponse[IncidentSummary])
async def list_incidents(
    status: Optional[List[IncidentStatus]] = Query(None),
    severity: Optional[List[SeverityLevel]] = Query(None),
    source_tool: Optional[List[str]] = Query(None),
    environment: Optional[List[str]] = Query(None),
    host: Optional[str] = Query(None),
    in_maintenance: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    sort_by: str = Query("last_seen_at", regex="^(last_seen_at|first_seen_at|severity|event_count)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """List incidents with filters and pagination."""
    # Build dynamic query
    conditions = []
    params = []
    param_idx = 1

    if status:
        placeholders = [f"${param_idx + i}" for i in range(len(status))]
        conditions.append(f"status IN ({', '.join(placeholders)})")
        params.extend([s.value for s in status])
        param_idx += len(status)

    if severity:
        placeholders = [f"${param_idx + i}" for i in range(len(severity))]
        conditions.append(f"severity IN ({', '.join(placeholders)})")
        params.extend([s.value for s in severity])
        param_idx += len(severity)

    if source_tool:
        placeholders = [f"${param_idx + i}" for i in range(len(source_tool))]
        conditions.append(f"source_tool IN ({', '.join(placeholders)})")
        params.extend(source_tool)
        param_idx += len(source_tool)

    if environment:
        placeholders = [f"${param_idx + i}" for i in range(len(environment))]
        conditions.append(f"environment IN ({', '.join(placeholders)})")
        params.extend(environment)
        param_idx += len(environment)

    if host:
        conditions.append(f"host ILIKE ${param_idx}")
        params.append(f"%{host}%")
        param_idx += 1

    if in_maintenance is not None:
        conditions.append(f"is_in_maintenance = ${param_idx}")
        params.append(in_maintenance)
        param_idx += 1

    if search:
        conditions.append(f"(title ILIKE ${param_idx} OR host ILIKE ${param_idx} OR check_name ILIKE ${param_idx})")
        params.append(f"%{search}%")
        param_idx += 1

    if from_date:
        conditions.append(f"last_seen_at >= ${param_idx}")
        params.append(from_date)
        param_idx += 1

    if to_date:
        conditions.append(f"last_seen_at <= ${param_idx}")
        params.append(to_date)
        param_idx += 1

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Get total count
    count_query = f"SELECT COUNT(*) FROM incidents WHERE {where_clause}"
    total = await conn.fetchval(count_query, *params)

    # Get paginated results
    offset = (page - 1) * page_size
    order_col = sort_by
    order_dir = sort_order.upper()

    query = f"""
        SELECT id, fingerprint, title, source_tool, environment, region, host, check_name,
               service, severity, status, first_seen_at, last_seen_at, event_count,
               is_in_maintenance, ai_category, owner_team, tags, labels, description
        FROM incidents
        WHERE {where_clause}
        ORDER BY {order_col} {order_dir}
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
    """
    params.extend([page_size, offset])

    rows = await conn.fetch(query, *params)

    total_pages = (total + page_size - 1) // page_size

    return PaginatedResponse(
        items=[IncidentSummary(**dict(row)) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/{incident_id}", response_model=IncidentWithEvents)
async def get_incident(
    incident_id: UUID,
    include_all_events: bool = Query(False),
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get incident details with events."""
    incident = await conn.fetchrow(
        """
        SELECT * FROM incidents WHERE id = $1
        """,
        incident_id
    )

    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incident not found"
        )

    # Get events
    event_limit = 1000 if include_all_events else 50
    events = await conn.fetch(
        """
        SELECT ae.* FROM alert_events ae
        JOIN incident_events ie ON ie.alert_event_id = ae.id
        WHERE ie.incident_id = $1
        ORDER BY ae.occurred_at DESC
        LIMIT $2
        """,
        incident_id, event_limit
    )

    # Get recent events (last 10 non-deduplicated)
    recent_events = await conn.fetch(
        """
        SELECT ae.* FROM alert_events ae
        JOIN incident_events ie ON ie.alert_event_id = ae.id
        WHERE ie.incident_id = $1 AND ie.is_deduplicated = false
        ORDER BY ae.occurred_at DESC
        LIMIT 10
        """,
        incident_id
    )

    incident_dict = dict(incident)
    incident_dict["events"] = [AlertEventResponse(**dict(e)) for e in events]
    incident_dict["recent_events"] = [AlertEventResponse(**dict(e)) for e in recent_events]

    return IncidentWithEvents(**incident_dict)


@router.get("/{incident_id}/events", response_model=List[AlertEventResponse])
async def get_incident_events(
    incident_id: UUID,
    deduplicated: Optional[bool] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get events for an incident."""
    # Verify incident exists
    exists = await conn.fetchval(
        "SELECT 1 FROM incidents WHERE id = $1", incident_id
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Incident not found")

    conditions = ["ie.incident_id = $1"]
    params = [incident_id]

    if deduplicated is not None:
        conditions.append("ie.is_deduplicated = $2")
        params.append(deduplicated)

    where_clause = " AND ".join(conditions)

    events = await conn.fetch(
        f"""
        SELECT ae.* FROM alert_events ae
        JOIN incident_events ie ON ie.alert_event_id = ae.id
        WHERE {where_clause}
        ORDER BY ae.occurred_at DESC
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """,
        *params, limit, offset
    )

    return [AlertEventResponse(**dict(e)) for e in events]


@router.get("/{incident_id}/raw-email/{event_id}", response_model=RawEmailResponse)
async def get_raw_email(
    incident_id: UUID,
    event_id: UUID,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get raw email for an event."""
    email = await conn.fetchrow(
        """
        SELECT re.* FROM raw_emails re
        JOIN alert_events ae ON ae.raw_email_id = re.id
        JOIN incident_events ie ON ie.alert_event_id = ae.id
        WHERE ie.incident_id = $1 AND ae.id = $2
        """,
        incident_id, event_id
    )

    if not email:
        raise HTTPException(status_code=404, detail="Raw email not found")

    return RawEmailResponse(**dict(email))


@router.post("/{incident_id}/ack", response_model=IncidentDetail)
async def acknowledge_incident(
    incident_id: UUID,
    request: AcknowledgeRequest,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Acknowledge an incident."""
    incident = await conn.fetchrow(
        "SELECT * FROM incidents WHERE id = $1", incident_id
    )

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    if incident["status"] not in ("open",):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot acknowledge incident with status {incident['status']}"
        )

    updated = await conn.fetchrow(
        """
        UPDATE incidents
        SET status = 'acknowledged', acknowledged_at = NOW(), acknowledged_by = $2, updated_at = NOW()
        WHERE id = $1
        RETURNING *
        """,
        incident_id, current_user["id"]
    )

    # Add system comment
    if request.comment:
        await conn.execute(
            """
            INSERT INTO incident_comments (incident_id, user_id, content, is_system_generated)
            VALUES ($1, $2, $3, false)
            """,
            incident_id, current_user["id"], request.comment
        )

    await conn.execute(
        """
        INSERT INTO incident_comments (incident_id, user_id, content, is_system_generated)
        VALUES ($1, $2, $3, true)
        """,
        incident_id, current_user["id"], f"Incident acknowledged by {current_user['username']}"
    )

    # Audit log
    await log_audit(
        conn, current_user["id"], "acknowledge", "incident", incident_id,
        {"status": incident["status"]}, {"status": "acknowledged"}
    )

    logger.info("Incident acknowledged", incident_id=str(incident_id), by=current_user["username"])

    return IncidentDetail(**dict(updated))


@router.post("/{incident_id}/resolve", response_model=IncidentDetail)
async def resolve_incident(
    incident_id: UUID,
    request: ResolveRequest,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Resolve an incident."""
    incident = await conn.fetchrow(
        "SELECT * FROM incidents WHERE id = $1", incident_id
    )

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    if incident["status"] == "resolved":
        raise HTTPException(status_code=400, detail="Incident is already resolved")

    updated = await conn.fetchrow(
        """
        UPDATE incidents
        SET status = 'resolved', resolved_at = NOW(), resolved_by = $2, updated_at = NOW()
        WHERE id = $1
        RETURNING *
        """,
        incident_id, current_user["id"]
    )

    if request.comment:
        await conn.execute(
            """
            INSERT INTO incident_comments (incident_id, user_id, content, is_system_generated)
            VALUES ($1, $2, $3, false)
            """,
            incident_id, current_user["id"], request.comment
        )

    await conn.execute(
        """
        INSERT INTO incident_comments (incident_id, user_id, content, is_system_generated)
        VALUES ($1, $2, $3, true)
        """,
        incident_id, current_user["id"], f"Incident resolved by {current_user['username']}"
    )

    await log_audit(
        conn, current_user["id"], "resolve", "incident", incident_id,
        {"status": incident["status"]}, {"status": "resolved"}
    )

    logger.info("Incident resolved", incident_id=str(incident_id), by=current_user["username"])

    return IncidentDetail(**dict(updated))


@router.post("/{incident_id}/suppress", response_model=IncidentDetail)
async def suppress_incident(
    incident_id: UUID,
    request: SuppressRequest,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Suppress an incident."""
    incident = await conn.fetchrow(
        "SELECT * FROM incidents WHERE id = $1", incident_id
    )

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    updated = await conn.fetchrow(
        """
        UPDATE incidents
        SET status = 'suppressed', updated_at = NOW()
        WHERE id = $1
        RETURNING *
        """,
        incident_id
    )

    # Create suppression rule if duration specified
    if request.duration_minutes:
        await conn.execute(
            """
            INSERT INTO suppression_rules (name, scope, reason, start_at, end_at, created_by)
            VALUES ($1, $2, $3, NOW(), NOW() + INTERVAL '1 minute' * $4, $5)
            """,
            f"Suppress incident {incident_id}",
            {"fingerprint": incident["fingerprint"]},
            request.reason,
            request.duration_minutes,
            current_user["id"]
        )

    await conn.execute(
        """
        INSERT INTO incident_comments (incident_id, user_id, content, is_system_generated)
        VALUES ($1, $2, $3, true)
        """,
        incident_id, current_user["id"],
        f"Incident suppressed by {current_user['username']}: {request.reason}"
    )

    await log_audit(
        conn, current_user["id"], "suppress", "incident", incident_id,
        {"status": incident["status"]}, {"status": "suppressed", "reason": request.reason}
    )

    logger.info("Incident suppressed", incident_id=str(incident_id), by=current_user["username"])

    return IncidentDetail(**dict(updated))


@router.get("/{incident_id}/comments", response_model=List[IncidentComment])
async def get_incident_comments(
    incident_id: UUID,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get comments for an incident."""
    exists = await conn.fetchval("SELECT 1 FROM incidents WHERE id = $1", incident_id)
    if not exists:
        raise HTTPException(status_code=404, detail="Incident not found")

    comments = await conn.fetch(
        """
        SELECT * FROM incident_comments
        WHERE incident_id = $1
        ORDER BY created_at DESC
        """,
        incident_id
    )

    return [IncidentComment(**dict(c)) for c in comments]


@router.post("/{incident_id}/comment", response_model=IncidentComment, status_code=201)
async def add_incident_comment(
    incident_id: UUID,
    request: CommentCreate,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Add a comment to an incident."""
    exists = await conn.fetchval("SELECT 1 FROM incidents WHERE id = $1", incident_id)
    if not exists:
        raise HTTPException(status_code=404, detail="Incident not found")

    comment = await conn.fetchrow(
        """
        INSERT INTO incident_comments (incident_id, user_id, content, is_system_generated)
        VALUES ($1, $2, $3, false)
        RETURNING *
        """,
        incident_id, current_user["id"], request.content
    )

    logger.info("Comment added", incident_id=str(incident_id), by=current_user["username"])

    return IncidentComment(**dict(comment))


@router.get("/{incident_id}/maintenance", response_model=dict)
async def get_incident_maintenance(
    incident_id: UUID,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get maintenance window info for an incident."""
    incident = await conn.fetchrow(
        "SELECT * FROM incidents WHERE id = $1", incident_id
    )

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    if not incident["is_in_maintenance"]:
        return {"in_maintenance": False, "window": None, "matches": []}

    window = None
    if incident["maintenance_window_id"]:
        window = await conn.fetchrow(
            "SELECT * FROM maintenance_windows WHERE id = $1",
            incident["maintenance_window_id"]
        )

    matches = await conn.fetch(
        """
        SELECT * FROM maintenance_matches
        WHERE incident_id = $1
        ORDER BY matched_at DESC
        """,
        incident_id
    )

    return {
        "in_maintenance": True,
        "window": dict(window) if window else None,
        "matches": [dict(m) for m in matches]
    }
