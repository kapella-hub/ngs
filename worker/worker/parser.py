"""Email parser for alert normalization."""
import hashlib
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
import yaml

from worker.database import get_pool

logger = structlog.get_logger()


class EmailParser:
    """Parses raw emails into normalized alert events."""

    def __init__(self):
        self.parsers: Dict[str, Dict] = {}
        self._load_parsers()

    def _load_parsers(self):
        """Load parser configurations from YAML."""
        try:
            with open("/app/configs/parsers.yml", "r") as f:
                config = yaml.safe_load(f)
                self.parsers = config.get("parsers", {})
            logger.info("Loaded parsers", count=len(self.parsers))
        except FileNotFoundError:
            logger.warning("No parsers config found, using defaults")
            self._load_default_parsers()
        except Exception as e:
            logger.error("Failed to load parsers", error=str(e))
            self._load_default_parsers()

    def _load_default_parsers(self):
        """Load default parser patterns."""
        self.parsers = {
            "op5": {
                "name": "OP5 Monitor",
                "subject_pattern": r"\*\*\s*(?P<state>PROBLEM|RECOVERY|ACKNOWLEDGEMENT)\*\*.*Host:\s*(?P<host>\S+)",
                "body_patterns": [
                    r"Service:\s*(?P<service>.+)",
                    r"State:\s*(?P<severity>CRITICAL|WARNING|OK|UNKNOWN)",
                    r"Additional Info:\s*(?P<info>.+)"
                ]
            },
            "nagios": {
                "name": "Nagios",
                "subject_pattern": r"\*\*\s*(?P<state>PROBLEM|RECOVERY)\*\*.*Host:\s*(?P<host>\S+)",
                "body_patterns": [
                    r"Service:\s*(?P<service>.+)",
                    r"State:\s*(?P<severity>CRITICAL|WARNING|OK|UNKNOWN)"
                ]
            },
            "xymon": {
                "name": "Xymon",
                "subject_pattern": r"(?P<host>\S+)\.(?P<service>\S+)\s+(?P<severity>red|yellow|green)",
                "severity_map": {"red": "critical", "yellow": "warning", "green": "info"}
            },
            "splunk": {
                "name": "Splunk Alert",
                "subject_pattern": r"Splunk Alert:\s*(?P<alert_name>.+)",
                "body_patterns": [
                    r"host=(?P<host>\S+)",
                    r"severity=(?P<severity>\w+)"
                ]
            },
            "prometheus": {
                "name": "Prometheus AlertManager",
                "subject_pattern": r"\[(?P<severity>FIRING|RESOLVED)\]\s*(?P<alert_name>.+)",
                "body_patterns": [
                    r"instance:\s*(?P<host>\S+)",
                    r"alertname:\s*(?P<check_name>\S+)"
                ]
            },
            "zabbix": {
                "name": "Zabbix",
                "subject_pattern": r"(?P<state>PROBLEM|OK):\s*(?P<trigger>.+)",
                "body_patterns": [
                    r"Host:\s*(?P<host>\S+)",
                    r"Severity:\s*(?P<severity>\w+)"
                ]
            },
            "generic": {
                "name": "Generic Alert",
                "subject_pattern": r"(?P<subject>.+)",
                "body_patterns": []
            }
        }

    async def parse_email(self, email_id: str, folder: str) -> Optional[Dict[str, Any]]:
        """Parse a raw email into an alert event."""
        pool = await get_pool()

        async with pool.acquire() as conn:
            email_row = await conn.fetchrow(
                """
                SELECT id, subject, from_address, body_text, body_html, date_header,
                       headers, attachments
                FROM raw_emails WHERE id = $1
                """,
                UUID(email_id)
            )

            if not email_row:
                return None

            subject = email_row["subject"] or ""
            body = email_row["body_text"] or email_row["body_html"] or ""

            # Determine source tool from folder name
            source_tool = self._determine_source_tool(folder, subject, body)

            # Get parser for this source
            parser_config = self.parsers.get(source_tool.lower(), self.parsers.get("generic", {}))

            try:
                # Parse using configured patterns
                parsed = self._apply_parser(parser_config, subject, body)

                # Build normalized event
                event = {
                    "raw_email_id": email_id,
                    "source_tool": source_tool,
                    "host": parsed.get("host"),
                    "check_name": parsed.get("check_name") or parsed.get("service") or parsed.get("trigger"),
                    "service": parsed.get("service"),
                    "severity": self._normalize_severity(parsed.get("severity")),
                    "state": self._determine_state(parsed.get("state")),
                    "environment": parsed.get("environment"),
                    "region": parsed.get("region"),
                    "occurred_at": email_row["date_header"] or datetime.utcnow(),
                    "payload": {
                        "subject": subject,
                        "from": email_row["from_address"],
                        "info": parsed.get("info"),
                        "alert_name": parsed.get("alert_name"),
                        **{k: v for k, v in parsed.items() if k not in ["host", "check_name", "severity", "state"]}
                    },
                    "tags": self._extract_tags(subject, body, parsed)
                }

                # Compute fingerprint
                event["normalized_signature"] = self._normalize_signature(subject, body)
                event["fingerprint"] = self._compute_fingerprint(event)

                # Update email status
                await conn.execute(
                    "UPDATE raw_emails SET parse_status = 'success', processed_at = NOW() WHERE id = $1",
                    UUID(email_id)
                )

                logger.debug("Email parsed", email_id=email_id, source=source_tool, host=event.get("host"))
                return event

            except Exception as e:
                logger.error("Parse failed", email_id=email_id, error=str(e))
                await conn.execute(
                    "UPDATE raw_emails SET parse_status = 'failed', parse_error = $2 WHERE id = $1",
                    UUID(email_id), str(e)
                )
                return None

    def _determine_source_tool(self, folder: str, subject: str, body: str) -> str:
        """Determine source tool from folder name and content."""
        folder_lower = folder.lower()

        # Check folder name first
        for tool in ["op5", "nagios", "xymon", "splunk", "prometheus", "zabbix"]:
            if tool in folder_lower:
                return tool

        # Check subject/body for tool signatures
        content = (subject + " " + body).lower()

        if "alertmanager" in content or "prometheus" in content:
            return "prometheus"
        if "splunk" in content:
            return "splunk"
        if "zabbix" in content:
            return "zabbix"
        if "xymon" in content:
            return "xymon"
        if "nagios" in content or "op5" in content:
            return "op5"

        return folder.replace("INBOX", "generic").replace("/", "_")

    def _apply_parser(self, config: Dict, subject: str, body: str) -> Dict[str, Any]:
        """Apply parser patterns to extract data."""
        result = {}

        # Parse subject
        subject_pattern = config.get("subject_pattern")
        if subject_pattern:
            match = re.search(subject_pattern, subject, re.IGNORECASE)
            if match:
                result.update(match.groupdict())

        # Parse body
        for pattern in config.get("body_patterns", []):
            match = re.search(pattern, body, re.IGNORECASE | re.MULTILINE)
            if match:
                result.update(match.groupdict())

        # Apply severity mapping if present
        severity_map = config.get("severity_map", {})
        if result.get("severity") and severity_map:
            result["severity"] = severity_map.get(result["severity"].lower(), result["severity"])

        return result

    def _normalize_severity(self, severity: Optional[str]) -> str:
        """Normalize severity to standard levels."""
        if not severity:
            return "medium"

        severity_lower = severity.lower()

        severity_map = {
            "critical": "critical",
            "crit": "critical",
            "emergency": "critical",
            "alert": "critical",
            "firing": "high",
            "high": "high",
            "major": "high",
            "error": "high",
            "warning": "medium",
            "warn": "medium",
            "medium": "medium",
            "minor": "low",
            "low": "low",
            "info": "info",
            "informational": "info",
            "ok": "info",
            "resolved": "info",
            "recovery": "info",
            "green": "info",
            "yellow": "medium",
            "red": "critical"
        }

        return severity_map.get(severity_lower, "medium")

    def _determine_state(self, state: Optional[str]) -> str:
        """Determine alert state."""
        if not state:
            return "firing"

        state_lower = state.lower()

        if state_lower in ["ok", "resolved", "recovery", "green"]:
            return "resolved"
        if state_lower in ["problem", "critical", "warning", "firing", "red", "yellow"]:
            return "firing"

        return "unknown"

    def _normalize_signature(self, subject: str, body: str) -> str:
        """Normalize signature for deduplication."""
        content = subject + " " + body[:500]

        # Lowercase
        content = content.lower()

        # Remove GUIDs
        content = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<guid>", content)

        # Remove request IDs
        content = re.sub(r"(request[_-]?id|req[_-]?id|trace[_-]?id)[=:]\s*\S+", "<id>", content)

        # Remove timestamps
        content = re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?Z?", "<ts>", content)
        content = re.sub(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s+\d{1,2}:\d{2}(:\d{2})?", "<ts>", content)

        # Remove volatile numbers (ports, pids, counts)
        content = re.sub(r"(pid|port|count|duration|latency)[=:]\s*\d+", r"\1=<n>", content)

        # Collapse whitespace
        content = re.sub(r"\s+", " ", content).strip()

        return content

    def _compute_fingerprint(self, event: Dict[str, Any]) -> str:
        """Compute fingerprint for incident correlation."""
        components = [
            event.get("environment") or "",
            event.get("host") or "",
            event.get("check_name") or event.get("service") or "",
            event.get("normalized_signature", "")[:200]
        ]

        fingerprint_str = "|".join(components).lower()
        return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]

    def _extract_tags(self, subject: str, body: str, parsed: Dict) -> List[str]:
        """Extract tags from email content."""
        tags = []

        # Add source-based tags
        if parsed.get("environment"):
            tags.append(f"env:{parsed['environment']}")
        if parsed.get("region"):
            tags.append(f"region:{parsed['region']}")

        # Look for common tag patterns in body
        tag_matches = re.findall(r"tag[s]?[=:]\s*([^\s,;]+)", body, re.IGNORECASE)
        tags.extend(tag_matches)

        return list(set(tags))
