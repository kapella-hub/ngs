"""Fingerprint v2 algorithm for stable incident correlation.

This module implements fingerprint v2 which EXCLUDES severity from the hash,
ensuring that severity changes on the same alert don't create new incidents.

Fingerprint v2 = SHA256(environment|host|check_name|normalized_signature)[:16]
"""
import hashlib
import re
from typing import Any, Dict, Optional

import structlog

from worker.database import get_pool

logger = structlog.get_logger()

# Version identifier for fingerprint algorithm
FINGERPRINT_VERSION = 2


def compute_fingerprint_v2(event: Dict[str, Any]) -> str:
    """
    Compute fingerprint v2 excluding severity for stable correlation.

    This ensures that severity changes (e.g., warning -> critical -> warning)
    on the same alert all correlate to the same incident.

    Args:
        event: Alert event dictionary with host, check_name, etc.

    Returns:
        16-character hex fingerprint
    """
    components = [
        _normalize_component(event.get("environment")),
        _normalize_component(event.get("host")),
        _normalize_component(event.get("check_name") or event.get("service")),
        _normalize_signature_component(event.get("normalized_signature", ""))
    ]

    fingerprint_str = "|".join(components)
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]


def _normalize_component(value: Optional[str]) -> str:
    """Normalize a fingerprint component."""
    if not value:
        return ""
    return value.lower().strip()


def _normalize_signature_component(signature: str) -> str:
    """Normalize the signature component, truncating to 200 chars."""
    if not signature:
        return ""
    return signature[:200].lower()


def compute_normalized_signature(subject: str, body: str) -> str:
    """
    Normalize signature for deduplication.

    Removes volatile elements like timestamps, GUIDs, request IDs, etc.
    to create a stable signature for similar alerts.

    Args:
        subject: Email subject
        body: Email body text

    Returns:
        Normalized signature string
    """
    content = subject + " " + body[:500]

    # Lowercase
    content = content.lower()

    # Remove GUIDs
    content = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "<guid>",
        content
    )

    # Remove request IDs
    content = re.sub(
        r"(request[_-]?id|req[_-]?id|trace[_-]?id)[=:]\s*\S+",
        "<id>",
        content
    )

    # Remove ISO timestamps
    content = re.sub(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?Z?",
        "<ts>",
        content
    )

    # Remove common date/time formats
    content = re.sub(
        r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s+\d{1,2}:\d{2}(:\d{2})?",
        "<ts>",
        content
    )

    # Remove volatile numbers (ports, pids, counts)
    content = re.sub(
        r"(pid|port|count|duration|latency|uptime)[=:]\s*\d+",
        r"\1=<n>",
        content
    )

    # Remove IP addresses (but keep hostname structure)
    content = re.sub(
        r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
        "<ip>",
        content
    )

    # Collapse whitespace
    content = re.sub(r"\s+", " ", content).strip()

    return content


def compute_fingerprint_v1(event: Dict[str, Any]) -> str:
    """
    Compute fingerprint v1 (legacy, includes severity).

    Kept for backwards compatibility during migration.

    Args:
        event: Alert event dictionary

    Returns:
        16-character hex fingerprint
    """
    components = [
        event.get("environment") or "",
        event.get("host") or "",
        event.get("check_name") or event.get("service") or "",
        event.get("normalized_signature", "")[:200]
    ]

    fingerprint_str = "|".join(components).lower()
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]


async def backfill_fingerprint_v2(batch_size: int = 100, dry_run: bool = False) -> Dict[str, int]:
    """
    Backfill fingerprint_v2 for existing incidents and events.

    This should be run after the migration to populate the new column
    for existing data.

    Args:
        batch_size: Number of records to process at a time
        dry_run: If True, don't actually update records

    Returns:
        Dictionary with counts of updated records
    """
    pool = await get_pool()

    stats = {
        "incidents_updated": 0,
        "events_updated": 0,
        "errors": 0
    }

    async with pool.acquire() as conn:
        # Get incidents that need backfill
        while True:
            incidents = await conn.fetch("""
                SELECT id, fingerprint, environment, source_tool
                FROM incidents
                WHERE fingerprint_v2 IS NULL
                LIMIT $1
            """, batch_size)

            if not incidents:
                break

            for incident in incidents:
                try:
                    # Get the first event for this incident to compute v2 fingerprint
                    first_event = await conn.fetchrow("""
                        SELECT host, check_name, service, normalized_signature, environment
                        FROM alert_events
                        WHERE incident_id = $1
                        ORDER BY occurred_at ASC
                        LIMIT 1
                    """, incident["id"])

                    if first_event:
                        event_data = dict(first_event)
                        fingerprint_v2 = compute_fingerprint_v2(event_data)

                        if not dry_run:
                            # Update incident
                            await conn.execute("""
                                UPDATE incidents
                                SET fingerprint_v2 = $2
                                WHERE id = $1
                            """, incident["id"], fingerprint_v2)

                            # Update all events for this incident
                            updated_events = await conn.execute("""
                                UPDATE alert_events
                                SET fingerprint_v2 = $2
                                WHERE incident_id = $1
                            """, incident["id"], fingerprint_v2)

                            stats["events_updated"] += int(updated_events.split()[-1])

                        stats["incidents_updated"] += 1

                except Exception as e:
                    logger.error(
                        "Failed to backfill fingerprint_v2",
                        incident_id=str(incident["id"]),
                        error=str(e)
                    )
                    stats["errors"] += 1

            logger.info(
                "Backfill progress",
                incidents_updated=stats["incidents_updated"],
                events_updated=stats["events_updated"],
                dry_run=dry_run
            )

    logger.info(
        "Backfill complete",
        **stats,
        dry_run=dry_run
    )

    return stats
