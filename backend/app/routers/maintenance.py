"""Maintenance windows router."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import get_db_connection
from app.routers.auth import get_current_user
from app.schemas.maintenance import (
    MaintenanceWindowCreate, MaintenanceWindowUpdate, MaintenanceWindowResponse,
    MaintenanceWindowDetail, MaintenanceMatchResponse, MaintenanceFilters
)
from app.schemas.common import MaintenanceSource, PaginatedResponse
from app.services.audit import log_audit

logger = structlog.get_logger()
router = APIRouter()


@router.get("", response_model=PaginatedResponse[MaintenanceWindowResponse])
async def list_maintenance_windows(
    source: Optional[List[MaintenanceSource]] = Query(None),
    is_active: Optional[bool] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    search: Optional[str] = Query(None),
    include_past: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """List maintenance windows with filters."""
    conditions = []
    params = []
    param_idx = 1

    if source:
        placeholders = [f"${param_idx + i}" for i in range(len(source))]
        conditions.append(f"source IN ({', '.join(placeholders)})")
        params.extend([s.value for s in source])
        param_idx += len(source)

    if is_active is not None:
        conditions.append(f"is_active = ${param_idx}")
        params.append(is_active)
        param_idx += 1

    if not include_past:
        conditions.append(f"end_ts >= ${param_idx}")
        params.append(datetime.utcnow())
        param_idx += 1

    if from_date:
        conditions.append(f"start_ts >= ${param_idx}")
        params.append(from_date)
        param_idx += 1

    if to_date:
        conditions.append(f"end_ts <= ${param_idx}")
        params.append(to_date)
        param_idx += 1

    if search:
        conditions.append(f"(title ILIKE ${param_idx} OR description ILIKE ${param_idx})")
        params.append(f"%{search}%")
        param_idx += 1

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    total = await conn.fetchval(f"SELECT COUNT(*) FROM maintenance_windows WHERE {where_clause}", *params)

    offset = (page - 1) * page_size
    query = f"""
        SELECT * FROM maintenance_windows
        WHERE {where_clause}
        ORDER BY start_ts DESC
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
    """
    params.extend([page_size, offset])

    rows = await conn.fetch(query, *params)
    total_pages = (total + page_size - 1) // page_size

    return PaginatedResponse(
        items=[MaintenanceWindowResponse(**dict(row)) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/active", response_model=List[MaintenanceWindowResponse])
async def get_active_maintenance_windows(
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get currently active maintenance windows."""
    now = datetime.utcnow()
    rows = await conn.fetch(
        """
        SELECT * FROM maintenance_windows
        WHERE is_active = true AND start_ts <= $1 AND end_ts >= $1
        ORDER BY start_ts
        """,
        now
    )
    return [MaintenanceWindowResponse(**dict(row)) for row in rows]


@router.get("/{window_id}", response_model=MaintenanceWindowDetail)
async def get_maintenance_window(
    window_id: UUID,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get maintenance window details."""
    window = await conn.fetchrow(
        "SELECT * FROM maintenance_windows WHERE id = $1",
        window_id
    )

    if not window:
        raise HTTPException(status_code=404, detail="Maintenance window not found")

    # Get affected incidents count
    affected_count = await conn.fetchval(
        """
        SELECT COUNT(DISTINCT incident_id) FROM maintenance_matches
        WHERE maintenance_window_id = $1
        """,
        window_id
    )

    # Get affected incidents summary
    affected_incidents = await conn.fetch(
        """
        SELECT DISTINCT i.id, i.title, i.severity, i.status, i.host, i.check_name
        FROM incidents i
        JOIN maintenance_matches mm ON mm.incident_id = i.id
        WHERE mm.maintenance_window_id = $1
        ORDER BY i.last_seen_at DESC
        LIMIT 20
        """,
        window_id
    )

    window_dict = dict(window)
    window_dict["affected_incident_count"] = affected_count
    window_dict["affected_incidents"] = [dict(i) for i in affected_incidents]

    return MaintenanceWindowDetail(**window_dict)


@router.post("", response_model=MaintenanceWindowResponse, status_code=201)
async def create_maintenance_window(
    request: MaintenanceWindowCreate,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Create a new maintenance window."""
    if current_user["role"] not in ("operator", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    window = await conn.fetchrow(
        """
        INSERT INTO maintenance_windows (
            source, title, description, start_ts, end_ts, timezone,
            scope, suppress_mode, reason, created_by
        )
        VALUES ('manual', $1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING *
        """,
        request.title, request.description, request.start_ts, request.end_ts,
        request.timezone, request.scope.model_dump(), request.suppress_mode.value,
        request.reason, current_user["id"]
    )

    await log_audit(
        conn, current_user["id"], "create", "maintenance_window", window["id"],
        None, dict(window)
    )

    logger.info("Maintenance window created", window_id=str(window["id"]), by=current_user["username"])

    return MaintenanceWindowResponse(**dict(window))


@router.patch("/{window_id}", response_model=MaintenanceWindowResponse)
async def update_maintenance_window(
    window_id: UUID,
    request: MaintenanceWindowUpdate,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Update a maintenance window."""
    if current_user["role"] not in ("operator", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    existing = await conn.fetchrow(
        "SELECT * FROM maintenance_windows WHERE id = $1", window_id
    )

    if not existing:
        raise HTTPException(status_code=404, detail="Maintenance window not found")

    # Build update query dynamically
    updates = []
    params = []
    param_idx = 1

    update_data = request.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        if field == "scope" and value is not None:
            updates.append(f"scope = ${param_idx}")
            params.append(value.model_dump() if hasattr(value, "model_dump") else value)
        elif field == "suppress_mode" and value is not None:
            updates.append(f"suppress_mode = ${param_idx}")
            params.append(value.value if hasattr(value, "value") else value)
        else:
            updates.append(f"{field} = ${param_idx}")
            params.append(value)
        param_idx += 1

    if not updates:
        return MaintenanceWindowResponse(**dict(existing))

    updates.append("updated_at = NOW()")
    params.append(window_id)

    query = f"""
        UPDATE maintenance_windows
        SET {', '.join(updates)}
        WHERE id = ${param_idx}
        RETURNING *
    """

    updated = await conn.fetchrow(query, *params)

    await log_audit(
        conn, current_user["id"], "update", "maintenance_window", window_id,
        dict(existing), dict(updated)
    )

    logger.info("Maintenance window updated", window_id=str(window_id), by=current_user["username"])

    return MaintenanceWindowResponse(**dict(updated))


@router.delete("/{window_id}", status_code=204)
async def delete_maintenance_window(
    window_id: UUID,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Delete a maintenance window."""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete maintenance windows")

    existing = await conn.fetchrow(
        "SELECT * FROM maintenance_windows WHERE id = $1", window_id
    )

    if not existing:
        raise HTTPException(status_code=404, detail="Maintenance window not found")

    await conn.execute("DELETE FROM maintenance_windows WHERE id = $1", window_id)

    await log_audit(
        conn, current_user["id"], "delete", "maintenance_window", window_id,
        dict(existing), None
    )

    logger.info("Maintenance window deleted", window_id=str(window_id), by=current_user["username"])


@router.get("/{window_id}/matches", response_model=List[MaintenanceMatchResponse])
async def get_maintenance_matches(
    window_id: UUID,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get match details for a maintenance window."""
    exists = await conn.fetchval(
        "SELECT 1 FROM maintenance_windows WHERE id = $1", window_id
    )

    if not exists:
        raise HTTPException(status_code=404, detail="Maintenance window not found")

    matches = await conn.fetch(
        """
        SELECT * FROM maintenance_matches
        WHERE maintenance_window_id = $1
        ORDER BY matched_at DESC
        """,
        window_id
    )

    return [MaintenanceMatchResponse(**dict(m)) for m in matches]
