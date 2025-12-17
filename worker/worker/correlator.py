"""Alert correlator for incident management."""
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import UUID

import structlog

from worker.config import get_settings
from worker.database import get_pool

logger = structlog.get_logger()


class Correlator:
    """Correlates alert events into incidents."""

    def __init__(self):
        self.settings = get_settings()

    async def process_event(self, event: Dict[str, Any]) -> Optional[str]:
        """Process an alert event and correlate into incident."""
        pool = await get_pool()

        fingerprint = event.get("fingerprint")
        if not fingerprint:
            logger.warning("Event missing fingerprint", event=event)
            return None

        async with pool.acquire() as conn:
            # Start transaction
            async with conn.transaction():
                # Store alert event
                event_id = await self._store_event(conn, event)

                # Check for existing open incident
                existing = await conn.fetchrow(
                    """
                    SELECT * FROM incidents
                    WHERE fingerprint = $1 AND status IN ('open', 'acknowledged')
                    FOR UPDATE
                    """,
                    fingerprint
                )

                if existing:
                    # Check if this is a duplicate within dedupe window
                    is_dedupe = await self._is_duplicate(conn, existing["id"], event)

                    # Update existing incident
                    incident_id = await self._update_incident(conn, existing, event, is_dedupe)

                    # Link event to incident
                    await self._link_event(conn, incident_id, event_id, is_dedupe)

                    logger.info(
                        "Event correlated to existing incident",
                        event_id=str(event_id),
                        incident_id=str(incident_id),
                        deduplicated=is_dedupe
                    )
                else:
                    # Check if this is a resolved state - maybe reopen recent incident
                    if event.get("state") == "resolved":
                        recent = await self._find_recent_incident(conn, fingerprint)
                        if recent:
                            # Just link to resolved incident
                            await self._link_event(conn, recent["id"], event_id, False)
                            return str(recent["id"])

                    # Create new incident
                    incident_id = await self._create_incident(conn, event)

                    # Link event to incident
                    await self._link_event(conn, incident_id, event_id, False)

                    logger.info(
                        "New incident created",
                        event_id=str(event_id),
                        incident_id=str(incident_id),
                        fingerprint=fingerprint
                    )

                return str(incident_id)

    async def _store_event(self, conn, event: Dict[str, Any]) -> UUID:
        """Store alert event in database."""
        result = await conn.fetchrow(
            """
            INSERT INTO alert_events (
                raw_email_id, source_tool, environment, region, host, check_name,
                service, severity, state, occurred_at, normalized_signature,
                fingerprint, payload, tags
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            RETURNING id
            """,
            UUID(event["raw_email_id"]) if event.get("raw_email_id") else None,
            event.get("source_tool"),
            event.get("environment"),
            event.get("region"),
            event.get("host"),
            event.get("check_name"),
            event.get("service"),
            event.get("severity", "medium"),
            event.get("state", "firing"),
            event.get("occurred_at", datetime.utcnow()),
            event.get("normalized_signature", ""),
            event.get("fingerprint"),
            json.dumps(event.get("payload", {})),
            event.get("tags", [])
        )
        return result["id"]

    async def _is_duplicate(self, conn, incident_id: UUID, event: Dict) -> bool:
        """Check if event is duplicate within dedupe window."""
        window_minutes = self.settings.dedupe_window_minutes

        recent = await conn.fetchval(
            """
            SELECT COUNT(*) FROM alert_events ae
            JOIN incident_events ie ON ie.alert_event_id = ae.id
            WHERE ie.incident_id = $1
            AND ae.occurred_at > NOW() - INTERVAL '1 minute' * $2
            AND ae.state = $3
            """,
            incident_id, window_minutes, event.get("state", "firing")
        )

        return recent > 0

    async def _update_incident(
        self, conn, incident: Dict, event: Dict, is_dedupe: bool
    ) -> UUID:
        """Update existing incident with new event."""
        incident_id = incident["id"]
        current_severity = incident["severity"]
        new_severity = event.get("severity", "medium")

        # Severity escalation
        severity_order = ["info", "low", "medium", "high", "critical"]
        if severity_order.index(new_severity) > severity_order.index(current_severity):
            escalate = True
        else:
            escalate = False
            new_severity = current_severity

        # Handle state changes
        new_state = event.get("state", "firing")
        status = incident["status"]

        if new_state == "resolved" and status in ("open", "acknowledged"):
            # Check flap handling - require quiet time
            quiet_time = self.settings.flap_quiet_time_minutes
            last_firing = await conn.fetchval(
                """
                SELECT MAX(occurred_at) FROM alert_events ae
                JOIN incident_events ie ON ie.alert_event_id = ae.id
                WHERE ie.incident_id = $1 AND ae.state = 'firing'
                """,
                incident_id
            )

            if last_firing and (datetime.utcnow() - last_firing) > timedelta(minutes=quiet_time):
                status = "resolved"
        elif new_state == "firing" and status == "resolved":
            # Reopen incident
            status = "open"
            await conn.execute(
                """
                UPDATE incidents SET flap_count = flap_count + 1 WHERE id = $1
                """,
                incident_id
            )

        # Update incident
        await conn.execute(
            """
            UPDATE incidents SET
                severity = $2,
                status = $3,
                last_seen_at = $4,
                event_count = event_count + 1,
                last_state_change_at = CASE WHEN status != $3 THEN NOW() ELSE last_state_change_at END,
                resolved_at = CASE WHEN $3 = 'resolved' THEN NOW() ELSE resolved_at END,
                updated_at = NOW()
            WHERE id = $1
            """,
            incident_id, new_severity, status, event.get("occurred_at", datetime.utcnow())
        )

        if escalate:
            logger.info("Incident severity escalated", incident_id=str(incident_id), severity=new_severity)

        return incident_id

    async def _create_incident(self, conn, event: Dict) -> UUID:
        """Create new incident from event."""
        title = self._generate_title(event)

        result = await conn.fetchrow(
            """
            INSERT INTO incidents (
                fingerprint, title, source_tool, environment, region, host,
                check_name, service, severity, status, first_seen_at, last_seen_at,
                event_count, tags
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'open', $10, $10, 1, $11)
            RETURNING id
            """,
            event.get("fingerprint"),
            title,
            event.get("source_tool"),
            event.get("environment"),
            event.get("region"),
            event.get("host"),
            event.get("check_name"),
            event.get("service"),
            event.get("severity", "medium"),
            event.get("occurred_at", datetime.utcnow()),
            event.get("tags", [])
        )

        return result["id"]

    def _generate_title(self, event: Dict) -> str:
        """Generate incident title from event."""
        parts = []

        if event.get("severity"):
            parts.append(f"[{event['severity'].upper()}]")

        if event.get("host"):
            parts.append(event["host"])

        if event.get("check_name"):
            parts.append(event["check_name"])
        elif event.get("service"):
            parts.append(event["service"])

        if not parts:
            parts.append("Alert")

        if event.get("source_tool"):
            parts.append(f"({event['source_tool']})")

        return " ".join(parts)[:500]

    async def _link_event(self, conn, incident_id: UUID, event_id: UUID, is_dedupe: bool):
        """Link event to incident."""
        await conn.execute(
            """
            INSERT INTO incident_events (incident_id, alert_event_id, is_deduplicated)
            VALUES ($1, $2, $3)
            ON CONFLICT (incident_id, alert_event_id) DO NOTHING
            """,
            incident_id, event_id, is_dedupe
        )

    async def _find_recent_incident(self, conn, fingerprint: str) -> Optional[Dict]:
        """Find recently resolved incident for fingerprint."""
        return await conn.fetchrow(
            """
            SELECT * FROM incidents
            WHERE fingerprint = $1 AND status = 'resolved'
            AND resolved_at > NOW() - INTERVAL '1 hour'
            ORDER BY resolved_at DESC
            LIMIT 1
            """,
            fingerprint
        )

    async def auto_resolve_stale_incidents(self):
        """Auto-resolve incidents with no recent events."""
        pool = await get_pool()
        hours = self.settings.incident_auto_resolve_hours

        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE incidents
                SET status = 'resolved', resolved_at = NOW(), updated_at = NOW()
                WHERE status IN ('open', 'acknowledged')
                AND last_seen_at < NOW() - INTERVAL '1 hour' * $1
                """,
                hours
            )

            if result != "UPDATE 0":
                count = int(result.split()[-1])
                logger.info("Auto-resolved stale incidents", count=count)

    async def get_incidents_for_enrichment(self, limit: int = 10):
        """Get incidents that need RAG enrichment."""
        pool = await get_pool()

        async with pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT * FROM incidents
                WHERE status IN ('open', 'acknowledged')
                AND (
                    ai_enriched_at IS NULL
                    OR (severity IN ('critical', 'high') AND ai_enriched_at < NOW() - INTERVAL '1 hour')
                    OR ai_enriched_at < NOW() - INTERVAL '24 hours'
                )
                ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        ELSE 4
                    END,
                    last_seen_at DESC
                LIMIT $1
                """,
                limit
            )
