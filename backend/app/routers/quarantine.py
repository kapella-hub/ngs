"""Quarantine router for parse failures."""
from typing import List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_db_connection
from app.routers.auth import get_current_user
from app.schemas.common import PaginatedResponse
from app.schemas.incidents import RawEmailResponse

logger = structlog.get_logger()
router = APIRouter()


class QuarantinedEmail(RawEmailResponse):
    """Quarantined email with parse error info."""
    parse_status: str
    parse_error: Optional[str] = None


@router.get("", response_model=PaginatedResponse[QuarantinedEmail])
async def list_quarantined_emails(
    folder: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """List emails that failed parsing (quarantine)."""
    conditions = ["parse_status IN ('failed', 'quarantine')"]
    params = []
    param_idx = 1

    if folder:
        conditions.append(f"folder = ${param_idx}")
        params.append(folder)
        param_idx += 1

    if search:
        conditions.append(f"(subject ILIKE ${param_idx} OR from_address ILIKE ${param_idx})")
        params.append(f"%{search}%")
        param_idx += 1

    where_clause = " AND ".join(conditions)

    total = await conn.fetchval(
        f"SELECT COUNT(*) FROM raw_emails WHERE {where_clause}",
        *params
    )

    offset = (page - 1) * page_size
    rows = await conn.fetch(
        f"""
        SELECT id, folder, uid, message_id, subject, from_address, to_addresses,
               date_header, headers, body_text, body_html, attachments, received_at,
               parse_status, parse_error
        FROM raw_emails
        WHERE {where_clause}
        ORDER BY received_at DESC
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """,
        *params, page_size, offset
    )

    total_pages = (total + page_size - 1) // page_size

    return PaginatedResponse(
        items=[QuarantinedEmail(**dict(row)) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/{email_id}", response_model=QuarantinedEmail)
async def get_quarantined_email(
    email_id: UUID,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get a specific quarantined email."""
    email = await conn.fetchrow(
        """
        SELECT id, folder, uid, message_id, subject, from_address, to_addresses,
               date_header, headers, body_text, body_html, attachments, received_at,
               parse_status, parse_error
        FROM raw_emails
        WHERE id = $1 AND parse_status IN ('failed', 'quarantine')
        """,
        email_id
    )

    if not email:
        raise HTTPException(status_code=404, detail="Quarantined email not found")

    return QuarantinedEmail(**dict(email))


@router.post("/{email_id}/retry", status_code=202)
async def retry_parse_email(
    email_id: UUID,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Mark a quarantined email for retry parsing."""
    if current_user["role"] not in ("operator", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await conn.execute(
        """
        UPDATE raw_emails
        SET parse_status = 'pending', parse_error = NULL
        WHERE id = $1 AND parse_status IN ('failed', 'quarantine')
        """,
        email_id
    )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Quarantined email not found")

    logger.info("Email marked for retry", email_id=str(email_id), by=current_user["username"])

    return {"status": "queued", "message": "Email marked for retry parsing"}


@router.delete("/{email_id}", status_code=204)
async def delete_quarantined_email(
    email_id: UUID,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Delete a quarantined email (admin only)."""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete emails")

    result = await conn.execute(
        """
        DELETE FROM raw_emails
        WHERE id = $1 AND parse_status IN ('failed', 'quarantine')
        """,
        email_id
    )

    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Quarantined email not found")

    logger.info("Quarantined email deleted", email_id=str(email_id), by=current_user["username"])


@router.get("/stats", response_model=dict)
async def get_quarantine_stats(
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get quarantine statistics."""
    stats = await conn.fetch(
        """
        SELECT folder, COUNT(*) as count, MAX(received_at) as latest
        FROM raw_emails
        WHERE parse_status IN ('failed', 'quarantine')
        GROUP BY folder
        ORDER BY count DESC
        """
    )

    total = await conn.fetchval(
        "SELECT COUNT(*) FROM raw_emails WHERE parse_status IN ('failed', 'quarantine')"
    )

    return {
        "total": total,
        "by_folder": [dict(s) for s in stats]
    }
