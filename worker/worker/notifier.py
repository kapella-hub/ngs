"""Notification service for Slack and webhook integrations.

Supports:
- Immediate notifications for critical alerts
- Digest notifications for batched summaries
- Multiple channels (Slack, webhooks, email)
"""
import asyncio
import json
import os
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

import aiohttp
import structlog

from worker.database import get_pool

logger = structlog.get_logger()

# Configuration from environment
DEFAULT_DIGEST_INTERVAL_MINUTES = int(os.environ.get("NOTIFICATION_DIGEST_INTERVAL", "15"))


class NotificationType(str, Enum):
    """Types of notifications."""
    IMMEDIATE = "immediate"  # Send right away (critical)
    DIGEST = "digest"        # Batch and send periodically


class NotificationStatus(str, Enum):
    """Status of notification attempts."""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class Notifier:
    """Manages notification channels and sending."""

    def __init__(self):
        self.channels: List[Dict[str, Any]] = []
        self._http_session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._http_session is None or self._http_session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._http_session = aiohttp.ClientSession(timeout=timeout)
        return self._http_session

    async def close(self):
        """Close HTTP session."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

    async def load_channels(self):
        """Load enabled notification channels from database."""
        pool = await get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, name, channel_type, config, severity_filter
                FROM notification_channels
                WHERE enabled = TRUE
            """)

            self.channels = [
                {
                    "id": str(row["id"]),
                    "name": row["name"],
                    "channel_type": row["channel_type"],
                    "config": json.loads(row["config"]) if isinstance(row["config"], str) else row["config"],
                    "severity_filter": row["severity_filter"]
                }
                for row in rows
            ]

            logger.info("Loaded notification channels", count=len(self.channels))

    async def notify_incident(
        self,
        incident: Dict[str, Any],
        notification_type: NotificationType = NotificationType.DIGEST
    ):
        """
        Send notification for an incident.

        Critical severity always sends immediately.
        Other severities follow the specified type.

        Args:
            incident: Incident data
            notification_type: Type of notification
        """
        # Critical always goes immediate
        if incident.get("severity") == "critical":
            notification_type = NotificationType.IMMEDIATE

        # Reload channels if needed
        if not self.channels:
            await self.load_channels()

        for channel in self.channels:
            # Check severity filter
            severity_filter = channel.get("severity_filter")
            if severity_filter and incident.get("severity") not in severity_filter:
                continue

            if notification_type == NotificationType.IMMEDIATE:
                await self._send_immediate(channel, incident)
            else:
                await self._queue_for_digest(channel, incident)

    async def _send_immediate(self, channel: Dict[str, Any], incident: Dict[str, Any]):
        """Send immediate notification."""
        try:
            payload = self._format_payload(channel, incident)

            if channel["channel_type"] == "slack":
                success = await self._send_slack(channel["config"], payload)
            elif channel["channel_type"] == "webhook":
                success = await self._send_webhook(channel["config"], payload)
            else:
                logger.warning("Unknown channel type", channel_type=channel["channel_type"])
                return

            # Log the attempt
            await self._log_notification(
                channel_id=UUID(channel["id"]),
                incident_id=UUID(incident["id"]) if incident.get("id") else None,
                notification_type="immediate",
                payload=payload,
                status=NotificationStatus.SENT if success else NotificationStatus.FAILED
            )

        except Exception as e:
            logger.error(
                "Failed to send immediate notification",
                channel=channel["name"],
                error=str(e)
            )
            await self._log_notification(
                channel_id=UUID(channel["id"]),
                incident_id=UUID(incident["id"]) if incident.get("id") else None,
                notification_type="immediate",
                payload={"error": str(e)},
                status=NotificationStatus.FAILED,
                error_message=str(e)
            )

    async def _queue_for_digest(self, channel: Dict[str, Any], incident: Dict[str, Any]):
        """Queue notification for digest batching."""
        pool = await get_pool()

        payload = self._format_payload(channel, incident)

        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO notification_queue
                (channel_id, incident_id, notification_type, payload, scheduled_for)
                VALUES ($1, $2, 'digest', $3, NOW() + INTERVAL '%s minutes')
            """ % DEFAULT_DIGEST_INTERVAL_MINUTES,
                UUID(channel["id"]),
                UUID(incident["id"]) if incident.get("id") else None,
                json.dumps(payload)
            )

        logger.debug(
            "Queued notification for digest",
            channel=channel["name"],
            incident_id=incident.get("id")
        )

    async def send_digest(self, channel_id: Optional[str] = None):
        """
        Send batched digest notifications.

        Args:
            channel_id: Specific channel to send for, or all if None
        """
        pool = await get_pool()

        async with pool.acquire() as conn:
            # Get queued notifications
            query = """
                SELECT q.id, q.channel_id, q.incident_id, q.payload,
                       c.name as channel_name, c.channel_type, c.config
                FROM notification_queue q
                JOIN notification_channels c ON c.id = q.channel_id
                WHERE q.scheduled_for <= NOW()
            """
            if channel_id:
                query += " AND q.channel_id = $1"
                rows = await conn.fetch(query, UUID(channel_id))
            else:
                rows = await conn.fetch(query)

            if not rows:
                return

            # Group by channel
            by_channel: Dict[str, List[Dict]] = {}
            for row in rows:
                cid = str(row["channel_id"])
                if cid not in by_channel:
                    by_channel[cid] = {
                        "channel_name": row["channel_name"],
                        "channel_type": row["channel_type"],
                        "config": json.loads(row["config"]) if isinstance(row["config"], str) else row["config"],
                        "items": []
                    }
                by_channel[cid]["items"].append({
                    "queue_id": row["id"],
                    "incident_id": row["incident_id"],
                    "payload": json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
                })

            # Send digest for each channel
            for cid, channel_data in by_channel.items():
                try:
                    digest_payload = self._format_digest(channel_data)

                    if channel_data["channel_type"] == "slack":
                        success = await self._send_slack(channel_data["config"], digest_payload)
                    elif channel_data["channel_type"] == "webhook":
                        success = await self._send_webhook(channel_data["config"], digest_payload)
                    else:
                        success = False

                    # Remove from queue
                    queue_ids = [item["queue_id"] for item in channel_data["items"]]
                    await conn.execute("""
                        DELETE FROM notification_queue WHERE id = ANY($1)
                    """, queue_ids)

                    # Log
                    await self._log_notification(
                        channel_id=UUID(cid),
                        incident_id=None,
                        notification_type="digest",
                        payload=digest_payload,
                        status=NotificationStatus.SENT if success else NotificationStatus.FAILED
                    )

                    logger.info(
                        "Sent digest notification",
                        channel=channel_data["channel_name"],
                        incident_count=len(channel_data["items"]),
                        success=success
                    )

                except Exception as e:
                    logger.error(
                        "Failed to send digest",
                        channel=channel_data["channel_name"],
                        error=str(e)
                    )

    def _format_payload(self, channel: Dict[str, Any], incident: Dict[str, Any]) -> Dict[str, Any]:
        """Format notification payload based on channel type."""
        if channel["channel_type"] == "slack":
            return self._format_slack_message(incident)
        else:
            return self._format_webhook_payload(incident)

    def _format_slack_message(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        """Format Slack message payload."""
        severity = incident.get("severity", "unknown")
        severity_emoji = {
            "critical": ":red_circle:",
            "high": ":large_orange_circle:",
            "medium": ":large_yellow_circle:",
            "low": ":large_blue_circle:",
            "info": ":white_circle:"
        }.get(severity, ":grey_question:")

        state = incident.get("state", "unknown")
        state_text = "FIRING" if state == "firing" else "RESOLVED"

        text = f"{severity_emoji} *[{severity.upper()}]* {incident.get('host', 'Unknown')} - {incident.get('check_name', 'Unknown')}"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{state_text}: {incident.get('check_name', 'Alert')}"
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Host:*\n{incident.get('host', 'Unknown')}"},
                    {"type": "mrkdwn", "text": f"*Severity:*\n{severity.upper()}"},
                    {"type": "mrkdwn", "text": f"*State:*\n{state_text}"},
                    {"type": "mrkdwn", "text": f"*Source:*\n{incident.get('source_tool', 'Unknown')}"}
                ]
            }
        ]

        # Add summary if available
        summary = incident.get("payload", {}).get("summary")
        if summary:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Summary:*\n{summary[:500]}"}
            })

        return {"text": text, "blocks": blocks}

    def _format_webhook_payload(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        """Format generic webhook payload."""
        return {
            "incident_id": incident.get("id"),
            "host": incident.get("host"),
            "check_name": incident.get("check_name"),
            "severity": incident.get("severity"),
            "state": incident.get("state"),
            "source_tool": incident.get("source_tool"),
            "occurred_at": incident.get("occurred_at"),
            "summary": incident.get("payload", {}).get("summary"),
            "event_count": incident.get("event_count", 1)
        }

    def _format_digest(self, channel_data: Dict[str, Any]) -> Dict[str, Any]:
        """Format digest payload with multiple incidents."""
        items = channel_data["items"]
        count = len(items)

        if channel_data["channel_type"] == "slack":
            # Slack digest format
            by_severity: Dict[str, int] = {}
            for item in items:
                sev = item["payload"].get("severity", "unknown")
                by_severity[sev] = by_severity.get(sev, 0) + 1

            severity_summary = ", ".join(f"{v} {k}" for k, v in sorted(by_severity.items()))

            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"Alert Digest: {count} incidents"}
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Summary:* {severity_summary}"}
                },
                {"type": "divider"}
            ]

            # Add top 10 items
            for item in items[:10]:
                payload = item["payload"]
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{payload.get('host', 'Unknown')}* - {payload.get('check_name', 'Unknown')} ({payload.get('severity', 'unknown')})"
                    }
                })

            if count > 10:
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"_...and {count - 10} more_"}]
                })

            return {"text": f"Alert Digest: {count} incidents", "blocks": blocks}

        else:
            # Generic webhook digest
            return {
                "type": "digest",
                "count": count,
                "incidents": [item["payload"] for item in items]
            }

    async def _send_slack(self, config: Dict[str, Any], payload: Dict[str, Any]) -> bool:
        """Send Slack webhook notification."""
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            logger.error("Slack webhook URL not configured")
            return False

        session = await self._get_session()
        try:
            async with session.post(webhook_url, json=payload) as resp:
                if resp.status == 200:
                    return True
                else:
                    text = await resp.text()
                    logger.error("Slack webhook failed", status=resp.status, response=text[:200])
                    return False
        except Exception as e:
            logger.error("Slack webhook error", error=str(e))
            return False

    async def _send_webhook(self, config: Dict[str, Any], payload: Dict[str, Any]) -> bool:
        """Send generic webhook notification."""
        url = config.get("url")
        if not url:
            logger.error("Webhook URL not configured")
            return False

        headers = config.get("headers", {})
        session = await self._get_session()

        try:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status < 400:
                    return True
                else:
                    text = await resp.text()
                    logger.error("Webhook failed", status=resp.status, response=text[:200])
                    return False
        except Exception as e:
            logger.error("Webhook error", error=str(e))
            return False

    async def _log_notification(
        self,
        channel_id: UUID,
        incident_id: Optional[UUID],
        notification_type: str,
        payload: Dict[str, Any],
        status: NotificationStatus,
        error_message: Optional[str] = None
    ):
        """Log notification attempt."""
        pool = await get_pool()

        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO notification_log
                (channel_id, incident_id, notification_type, payload, status, error_message, sent_at)
                VALUES ($1, $2, $3, $4, $5, $6, NOW())
            """, channel_id, incident_id, notification_type,
                json.dumps(payload), status.value, error_message)


# Global notifier instance
_notifier: Optional[Notifier] = None


async def get_notifier() -> Notifier:
    """Get or create the global Notifier instance."""
    global _notifier
    if _notifier is None:
        _notifier = Notifier()
        await _notifier.load_channels()
    return _notifier


async def notify_incident(incident: Dict[str, Any], notification_type: NotificationType = NotificationType.DIGEST):
    """Convenience function to notify about an incident."""
    notifier = await get_notifier()
    await notifier.notify_incident(incident, notification_type)
