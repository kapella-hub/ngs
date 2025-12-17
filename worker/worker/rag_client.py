"""RAG enrichment client."""
import re
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from worker.config import get_settings
from worker.database import get_pool

logger = structlog.get_logger()


class RAGClient:
    """Client for external RAG enrichment service."""

    def __init__(self, endpoint: str, timeout: int = 30):
        self.endpoint = endpoint
        self.timeout = timeout
        self.settings = get_settings()
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def enrich_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Request enrichment for an incident."""
        pool = await get_pool()

        async with pool.acquire() as conn:
            # Get incident data
            incident = await conn.fetchrow(
                "SELECT * FROM incidents WHERE id = $1",
                UUID(incident_id)
            )

            if not incident:
                return None

            # Get sample events
            events = await conn.fetch(
                """
                SELECT ae.*, re.body_text, re.subject
                FROM alert_events ae
                LEFT JOIN raw_emails re ON re.id = ae.raw_email_id
                JOIN incident_events ie ON ie.alert_event_id = ae.id
                WHERE ie.incident_id = $1
                ORDER BY ae.occurred_at DESC
                LIMIT 5
                """,
                UUID(incident_id)
            )

            # Build payload
            payload = self._build_payload(incident, events)

            # Call RAG service
            start_time = time.time()
            try:
                client = await self._get_client()
                response = await client.post(
                    self.endpoint,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )

                duration = time.time() - start_time

                if response.status_code == 200:
                    result = response.json()
                    logger.info(
                        "RAG enrichment successful",
                        incident_id=incident_id,
                        duration=duration
                    )

                    # Store enrichment result
                    await self._store_enrichment(conn, incident_id, result)
                    return result
                else:
                    logger.warning(
                        "RAG enrichment failed",
                        incident_id=incident_id,
                        status=response.status_code,
                        body=response.text[:500]
                    )
                    return None

            except httpx.TimeoutException:
                logger.error("RAG request timed out", incident_id=incident_id)
                raise
            except Exception as e:
                logger.error("RAG request failed", incident_id=incident_id, error=str(e))
                raise

    def _build_payload(self, incident: Dict, events: List[Dict]) -> Dict[str, Any]:
        """Build RAG request payload."""
        # Redact sensitive data
        redacted_events = []
        for event in events:
            redacted = {
                "source_tool": event["source_tool"],
                "host": event["host"],
                "check_name": event["check_name"],
                "service": event["service"],
                "severity": event["severity"],
                "state": event["state"],
                "occurred_at": event["occurred_at"].isoformat() if event["occurred_at"] else None,
                "subject": self._redact(event.get("subject", "")),
                "body_sample": self._redact((event.get("body_text") or "")[:1000])
            }
            redacted_events.append(redacted)

        return {
            "incident": {
                "id": str(incident["id"]),
                "title": incident["title"],
                "source_tool": incident["source_tool"],
                "environment": incident["environment"],
                "region": incident["region"],
                "host": incident["host"],
                "check_name": incident["check_name"],
                "service": incident["service"],
                "severity": incident["severity"],
                "status": incident["status"],
                "event_count": incident["event_count"],
                "first_seen_at": incident["first_seen_at"].isoformat() if incident["first_seen_at"] else None,
                "last_seen_at": incident["last_seen_at"].isoformat() if incident["last_seen_at"] else None,
                "tags": incident["tags"] or []
            },
            "events": redacted_events,
            "request_type": "enrichment",
            "max_suggestions": 5
        }

    def _redact(self, text: str) -> str:
        """Redact sensitive data from text."""
        if not text:
            return ""

        for pattern in self.settings.redaction_patterns_list:
            try:
                text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE)
            except re.error:
                pass

        # Default redactions
        default_patterns = [
            r"password[=:]\s*\S+",
            r"api[_-]?key[=:]\s*\S+",
            r"secret[=:]\s*\S+",
            r"token[=:]\s*\S+",
            r"bearer\s+\S+",
            r"authorization[=:]\s*\S+"
        ]

        for pattern in default_patterns:
            text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE)

        return text

    async def _store_enrichment(self, conn, incident_id: str, result: Dict):
        """Store enrichment result on incident."""
        import json

        await conn.execute(
            """
            UPDATE incidents SET
                ai_summary = $2,
                ai_category = $3,
                ai_owner_team = $4,
                ai_recommended_checks = $5,
                ai_suggested_runbooks = $6,
                ai_safe_actions = $7,
                ai_confidence = $8,
                ai_evidence = $9,
                ai_enriched_at = NOW(),
                ai_labels = $10,
                updated_at = NOW()
            WHERE id = $1
            """,
            UUID(incident_id),
            result.get("summary"),
            result.get("category"),
            result.get("owner_team"),
            json.dumps(result.get("recommended_checks", [])),
            json.dumps(result.get("suggested_runbooks", [])),
            json.dumps(result.get("safe_actions", [])),
            result.get("confidence"),
            json.dumps(result.get("evidence", [])),
            json.dumps(result.get("labels", {}))
        )


class RAGResponseSchema:
    """Expected response schema from RAG service."""

    SCHEMA = {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Bullet point summary of the incident"},
            "category": {"type": "string", "description": "Category classification"},
            "owner_team": {"type": "string", "description": "Suggested owner team"},
            "recommended_checks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of recommended diagnostic checks"
            },
            "suggested_runbooks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "url": {"type": "string"}
                    }
                },
                "description": "Suggested runbook references"
            },
            "safe_actions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Safe actions that could be taken (NOT executed)"
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Confidence score"
            },
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "snippet": {"type": "string"}
                    }
                },
                "description": "Evidence citations"
            },
            "labels": {
                "type": "object",
                "description": "Additional labels/metadata"
            }
        }
    }
