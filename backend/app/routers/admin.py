"""Admin router for configuration and system management."""
import hashlib
from typing import Any, Dict, List

import structlog
import yaml
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.database import get_db_connection
from app.routers.auth import get_current_user
from app.services.audit import log_audit

logger = structlog.get_logger()
router = APIRouter()


@router.get("/config/parsers")
async def get_parser_config(
    current_user: dict = Depends(get_current_user)
):
    """Get current parser configuration."""
    try:
        with open("/app/configs/parsers.yml", "r") as f:
            config = yaml.safe_load(f)
        return {"config": config, "source": "file"}
    except FileNotFoundError:
        return {"config": {}, "source": "default", "message": "No custom config found"}


@router.get("/config/correlation")
async def get_correlation_config(
    current_user: dict = Depends(get_current_user)
):
    """Get current correlation configuration."""
    try:
        with open("/app/configs/correlation.yml", "r") as f:
            config = yaml.safe_load(f)
        return {"config": config, "source": "file"}
    except FileNotFoundError:
        return {"config": {}, "source": "default", "message": "No custom config found"}


@router.get("/config/maintenance")
async def get_maintenance_config(
    current_user: dict = Depends(get_current_user)
):
    """Get current maintenance detection configuration."""
    try:
        with open("/app/configs/maintenance.yml", "r") as f:
            config = yaml.safe_load(f)
        return {"config": config, "source": "file"}
    except FileNotFoundError:
        return {"config": {}, "source": "default", "message": "No custom config found"}


@router.post("/config/upload")
async def upload_config(
    config_type: str,
    file: UploadFile = File(...),
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Upload a new configuration file (admin only, PoC)."""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admins can upload configs")

    if config_type not in ("parsers", "correlation", "maintenance"):
        raise HTTPException(status_code=400, detail="Invalid config type")

    content = await file.read()
    content_str = content.decode("utf-8")

    # Validate YAML
    try:
        yaml.safe_load(content_str)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {str(e)}")

    # Store snapshot in database for audit
    checksum = hashlib.sha256(content).hexdigest()
    await conn.execute(
        """
        INSERT INTO config_snapshots (config_type, config_name, content, checksum, uploaded_by)
        VALUES ($1, $2, $3, $4, $5)
        """,
        config_type, file.filename, content_str, checksum, current_user["id"]
    )

    # In production, this would write to shared storage or trigger config reload
    logger.info("Config uploaded", type=config_type, by=current_user["username"], checksum=checksum)

    return {
        "status": "uploaded",
        "config_type": config_type,
        "checksum": checksum,
        "message": "Config stored. Restart worker to apply changes (PoC limitation)."
    }


@router.post("/reload-config")
async def reload_config(
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Trigger configuration reload (PoC - placeholder)."""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admins can reload config")

    # In production, this would signal workers to reload config
    logger.info("Config reload requested", by=current_user["username"])

    return {
        "status": "requested",
        "message": "Config reload requested. Worker will pick up changes on next poll cycle."
    }


@router.get("/ingestion/status")
async def get_ingestion_status(
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get ingestion status for all folders."""
    cursors = await conn.fetch(
        """
        SELECT folder, last_uid, last_poll_at, last_success_at,
               last_error, error_count, emails_processed, updated_at
        FROM folder_cursors
        ORDER BY folder
        """
    )

    # Get recent email counts
    email_stats = await conn.fetch(
        """
        SELECT folder, COUNT(*) as total,
               COUNT(*) FILTER (WHERE parse_status = 'success') as parsed,
               COUNT(*) FILTER (WHERE parse_status IN ('failed', 'quarantine')) as failed,
               MAX(received_at) as latest_email
        FROM raw_emails
        GROUP BY folder
        """
    )

    email_stats_map = {s["folder"]: dict(s) for s in email_stats}

    result = []
    for cursor in cursors:
        cursor_dict = dict(cursor)
        cursor_dict["email_stats"] = email_stats_map.get(cursor["folder"], {})
        result.append(cursor_dict)

    return {"folders": result}


@router.get("/audit-log")
async def get_audit_log(
    entity_type: str = None,
    entity_id: str = None,
    action: str = None,
    limit: int = 100,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get audit log entries."""
    if current_user["role"] not in ("operator", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    conditions = []
    params = []
    param_idx = 1

    if entity_type:
        conditions.append(f"entity_type = ${param_idx}")
        params.append(entity_type)
        param_idx += 1

    if entity_id:
        conditions.append(f"entity_id = ${param_idx}")
        params.append(entity_id)
        param_idx += 1

    if action:
        conditions.append(f"action = ${param_idx}")
        params.append(action)
        param_idx += 1

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    logs = await conn.fetch(
        f"""
        SELECT al.*, u.username
        FROM audit_log al
        LEFT JOIN users u ON u.id = al.user_id
        WHERE {where_clause}
        ORDER BY al.created_at DESC
        LIMIT ${param_idx}
        """,
        *params, limit
    )

    return {"entries": [dict(log) for log in logs]}


@router.get("/stats/overview")
async def get_system_stats(
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get system-wide statistics."""
    stats = {}

    # Incident stats
    incident_stats = await conn.fetchrow(
        """
        SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE status = 'open') as open,
            COUNT(*) FILTER (WHERE status = 'acknowledged') as acknowledged,
            COUNT(*) FILTER (WHERE status = 'resolved') as resolved,
            COUNT(*) FILTER (WHERE status = 'suppressed') as suppressed,
            COUNT(*) FILTER (WHERE is_in_maintenance) as in_maintenance
        FROM incidents
        """
    )
    stats["incidents"] = dict(incident_stats)

    # Email stats
    email_stats = await conn.fetchrow(
        """
        SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE parse_status = 'success') as parsed,
            COUNT(*) FILTER (WHERE parse_status IN ('failed', 'quarantine')) as quarantined
        FROM raw_emails
        """
    )
    stats["emails"] = dict(email_stats)

    # Maintenance window stats
    mw_stats = await conn.fetchrow(
        """
        SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE is_active AND start_ts <= NOW() AND end_ts >= NOW()) as currently_active
        FROM maintenance_windows
        """
    )
    stats["maintenance_windows"] = dict(mw_stats)

    # Recent activity
    recent_incidents = await conn.fetchval(
        "SELECT COUNT(*) FROM incidents WHERE created_at > NOW() - INTERVAL '24 hours'"
    )
    recent_events = await conn.fetchval(
        "SELECT COUNT(*) FROM alert_events WHERE created_at > NOW() - INTERVAL '24 hours'"
    )
    stats["last_24h"] = {
        "new_incidents": recent_incidents,
        "new_events": recent_events
    }

    return stats


@router.get("/stats/severity")
async def get_severity_breakdown(
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get incident breakdown by severity."""
    stats = await conn.fetch(
        """
        SELECT severity, status, COUNT(*) as count
        FROM incidents
        GROUP BY severity, status
        ORDER BY severity, status
        """
    )

    return {"breakdown": [dict(s) for s in stats]}


@router.get("/stats/sources")
async def get_source_breakdown(
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get incident breakdown by source tool."""
    stats = await conn.fetch(
        """
        SELECT source_tool, COUNT(*) as total,
               COUNT(*) FILTER (WHERE status = 'open') as open
        FROM incidents
        WHERE source_tool IS NOT NULL
        GROUP BY source_tool
        ORDER BY total DESC
        """
    )

    return {"sources": [dict(s) for s in stats]}
