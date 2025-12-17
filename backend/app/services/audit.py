"""Audit logging service."""
import json
from typing import Any, Dict, Optional
from uuid import UUID

import structlog

logger = structlog.get_logger()


async def log_audit(
    conn,
    user_id: Optional[UUID],
    action: str,
    entity_type: str,
    entity_id: Optional[UUID],
    old_value: Optional[Dict[str, Any]] = None,
    new_value: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
):
    """Log an audit entry."""
    try:
        # Convert values to JSON-compatible format
        def serialize(obj):
            if obj is None:
                return None
            if isinstance(obj, dict):
                return {k: str(v) if isinstance(v, UUID) else v for k, v in obj.items()}
            return obj

        await conn.execute(
            """
            INSERT INTO audit_log (
                user_id, action, entity_type, entity_id,
                old_value, new_value, metadata, ip_address, user_agent
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::inet, $9)
            """,
            user_id,
            action,
            entity_type,
            entity_id,
            json.dumps(serialize(old_value)) if old_value else None,
            json.dumps(serialize(new_value)) if new_value else None,
            json.dumps(metadata) if metadata else None,
            ip_address,
            user_agent
        )

        logger.debug(
            "Audit logged",
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            user_id=str(user_id) if user_id else None
        )

    except Exception as e:
        logger.error("Failed to log audit entry", error=str(e))
        # Don't raise - audit logging should not break main operations
