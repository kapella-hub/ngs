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


@router.get("/stats/timeline")
async def get_timeline_stats(
    days: int = 30,
    granularity: str = "day",
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get incident timeline statistics for charts."""
    if granularity not in ("hour", "day", "week"):
        granularity = "day"

    # Determine the date truncation and interval
    if granularity == "hour":
        date_trunc = "hour"
        max_days = min(days, 7)  # Limit to 7 days for hourly
    elif granularity == "week":
        date_trunc = "week"
        max_days = min(days, 365)
    else:
        date_trunc = "day"
        max_days = min(days, 90)

    # Incidents over time
    incidents_timeline = await conn.fetch(
        f"""
        SELECT
            date_trunc('{date_trunc}', created_at) as period,
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE severity = 'critical') as critical,
            COUNT(*) FILTER (WHERE severity = 'high') as high,
            COUNT(*) FILTER (WHERE severity = 'medium') as medium,
            COUNT(*) FILTER (WHERE severity = 'low') as low,
            COUNT(*) FILTER (WHERE severity = 'info') as info
        FROM incidents
        WHERE created_at >= NOW() - INTERVAL '{max_days} days'
        GROUP BY date_trunc('{date_trunc}', created_at)
        ORDER BY period
        """
    )

    # Events over time
    events_timeline = await conn.fetch(
        f"""
        SELECT
            date_trunc('{date_trunc}', occurred_at) as period,
            COUNT(*) as total,
            COUNT(DISTINCT incident_events.incident_id) as unique_incidents
        FROM alert_events
        LEFT JOIN incident_events ON alert_events.id = incident_events.alert_event_id
        WHERE occurred_at >= NOW() - INTERVAL '{max_days} days'
        GROUP BY date_trunc('{date_trunc}', occurred_at)
        ORDER BY period
        """
    )

    # Resolution time stats
    resolution_stats = await conn.fetch(
        f"""
        SELECT
            date_trunc('{date_trunc}', resolved_at) as period,
            AVG(EXTRACT(EPOCH FROM (resolved_at - first_seen_at)) / 60) as avg_resolution_minutes,
            COUNT(*) as resolved_count
        FROM incidents
        WHERE resolved_at IS NOT NULL
          AND resolved_at >= NOW() - INTERVAL '{max_days} days'
        GROUP BY date_trunc('{date_trunc}', resolved_at)
        ORDER BY period
        """
    )

    return {
        "incidents": [
            {
                "period": row["period"].isoformat() if row["period"] else None,
                "total": row["total"],
                "critical": row["critical"],
                "high": row["high"],
                "medium": row["medium"],
                "low": row["low"],
                "info": row["info"]
            }
            for row in incidents_timeline
        ],
        "events": [
            {
                "period": row["period"].isoformat() if row["period"] else None,
                "total": row["total"],
                "unique_incidents": row["unique_incidents"]
            }
            for row in events_timeline
        ],
        "resolution": [
            {
                "period": row["period"].isoformat() if row["period"] else None,
                "avg_minutes": round(row["avg_resolution_minutes"], 1) if row["avg_resolution_minutes"] else None,
                "count": row["resolved_count"]
            }
            for row in resolution_stats
        ],
        "granularity": granularity,
        "days": max_days
    }


@router.get("/stats/top-hosts")
async def get_top_hosts(
    days: int = 30,
    limit: int = 10,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get top hosts by incident count."""
    stats = await conn.fetch(
        """
        SELECT
            COALESCE(host, '(no host)') as host,
            COUNT(*) as incident_count,
            COUNT(*) FILTER (WHERE status = 'open') as open_count,
            COUNT(*) FILTER (WHERE severity IN ('critical', 'high')) as critical_high_count,
            MAX(last_seen_at) as last_incident
        FROM incidents
        WHERE created_at >= NOW() - INTERVAL '1 day' * $1
        GROUP BY COALESCE(host, '(no host)')
        ORDER BY incident_count DESC
        LIMIT $2
        """,
        days, limit
    )

    return {
        "hosts": [
            {
                "host": row["host"],
                "incident_count": row["incident_count"],
                "open_count": row["open_count"],
                "critical_high_count": row["critical_high_count"],
                "last_incident": row["last_incident"].isoformat() if row["last_incident"] else None
            }
            for row in stats
        ],
        "days": days
    }


@router.get("/stats/top-services")
async def get_top_services(
    days: int = 30,
    limit: int = 10,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get top services/checks by incident count."""
    stats = await conn.fetch(
        """
        SELECT
            COALESCE(check_name, service, '(unknown)') as service,
            source_tool,
            COUNT(*) as incident_count,
            COUNT(*) FILTER (WHERE status = 'open') as open_count,
            COUNT(DISTINCT host) as affected_hosts,
            MAX(last_seen_at) as last_incident
        FROM incidents
        WHERE created_at >= NOW() - INTERVAL '1 day' * $1
        GROUP BY COALESCE(check_name, service, '(unknown)'), source_tool
        ORDER BY incident_count DESC
        LIMIT $2
        """,
        days, limit
    )

    return {
        "services": [
            {
                "service": row["service"],
                "source_tool": row["source_tool"],
                "incident_count": row["incident_count"],
                "open_count": row["open_count"],
                "affected_hosts": row["affected_hosts"],
                "last_incident": row["last_incident"].isoformat() if row["last_incident"] else None
            }
            for row in stats
        ],
        "days": days
    }


@router.get("/stats/mttr")
async def get_mttr_stats(
    days: int = 30,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Get Mean Time To Resolution (MTTR) statistics."""
    # Overall MTTR
    overall = await conn.fetchrow(
        """
        SELECT
            AVG(EXTRACT(EPOCH FROM (resolved_at - first_seen_at)) / 60) as avg_minutes,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (resolved_at - first_seen_at)) / 60) as median_minutes,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (resolved_at - first_seen_at)) / 60) as p95_minutes,
            MIN(EXTRACT(EPOCH FROM (resolved_at - first_seen_at)) / 60) as min_minutes,
            MAX(EXTRACT(EPOCH FROM (resolved_at - first_seen_at)) / 60) as max_minutes,
            COUNT(*) as resolved_count
        FROM incidents
        WHERE resolved_at IS NOT NULL
          AND resolved_at >= NOW() - INTERVAL '1 day' * $1
        """,
        days
    )

    # MTTR by severity
    by_severity = await conn.fetch(
        """
        SELECT
            severity,
            AVG(EXTRACT(EPOCH FROM (resolved_at - first_seen_at)) / 60) as avg_minutes,
            COUNT(*) as count
        FROM incidents
        WHERE resolved_at IS NOT NULL
          AND resolved_at >= NOW() - INTERVAL '1 day' * $1
        GROUP BY severity
        ORDER BY
            CASE severity
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                WHEN 'low' THEN 4
                ELSE 5
            END
        """,
        days
    )

    # MTTR by source
    by_source = await conn.fetch(
        """
        SELECT
            COALESCE(source_tool, 'unknown') as source,
            AVG(EXTRACT(EPOCH FROM (resolved_at - first_seen_at)) / 60) as avg_minutes,
            COUNT(*) as count
        FROM incidents
        WHERE resolved_at IS NOT NULL
          AND resolved_at >= NOW() - INTERVAL '1 day' * $1
        GROUP BY COALESCE(source_tool, 'unknown')
        ORDER BY count DESC
        """,
        days
    )

    return {
        "overall": {
            "avg_minutes": round(overall["avg_minutes"], 1) if overall["avg_minutes"] else None,
            "median_minutes": round(overall["median_minutes"], 1) if overall["median_minutes"] else None,
            "p95_minutes": round(overall["p95_minutes"], 1) if overall["p95_minutes"] else None,
            "min_minutes": round(overall["min_minutes"], 1) if overall["min_minutes"] else None,
            "max_minutes": round(overall["max_minutes"], 1) if overall["max_minutes"] else None,
            "resolved_count": overall["resolved_count"]
        },
        "by_severity": [
            {"severity": row["severity"], "avg_minutes": round(row["avg_minutes"], 1) if row["avg_minutes"] else None, "count": row["count"]}
            for row in by_severity
        ],
        "by_source": [
            {"source": row["source"], "avg_minutes": round(row["avg_minutes"], 1) if row["avg_minutes"] else None, "count": row["count"]}
            for row in by_source
        ],
        "days": days
    }


@router.get("/stats/search")
async def search_incidents(
    q: str,
    days: int = 30,
    status: str = None,
    severity: str = None,
    source: str = None,
    limit: int = 50,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Search incidents with filters."""
    conditions = ["created_at >= NOW() - INTERVAL '1 day' * $1"]
    params = [days]
    param_idx = 2

    # Text search
    if q:
        conditions.append(f"""
            (title ILIKE ${param_idx}
             OR host ILIKE ${param_idx}
             OR check_name ILIKE ${param_idx}
             OR service ILIKE ${param_idx}
             OR fingerprint ILIKE ${param_idx})
        """)
        params.append(f"%{q}%")
        param_idx += 1

    if status:
        conditions.append(f"status = ${param_idx}")
        params.append(status)
        param_idx += 1

    if severity:
        conditions.append(f"severity = ${param_idx}")
        params.append(severity)
        param_idx += 1

    if source:
        conditions.append(f"source_tool = ${param_idx}")
        params.append(source)
        param_idx += 1

    where_clause = " AND ".join(conditions)

    results = await conn.fetch(
        f"""
        SELECT
            id, fingerprint, title, source_tool, host, check_name, service,
            severity, status, first_seen_at, last_seen_at, event_count,
            is_in_maintenance
        FROM incidents
        WHERE {where_clause}
        ORDER BY last_seen_at DESC
        LIMIT ${param_idx}
        """,
        *params, limit
    )

    total = await conn.fetchval(
        f"SELECT COUNT(*) FROM incidents WHERE {where_clause}",
        *params
    )

    return {
        "results": [dict(r) for r in results],
        "total": total,
        "query": q,
        "filters": {"status": status, "severity": severity, "source": source, "days": days}
    }
