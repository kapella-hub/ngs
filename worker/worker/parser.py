"""Email parser for alert normalization."""
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
import yaml

from worker.database import get_pool
from worker.fingerprint import (
    compute_fingerprint_v2,
    compute_fingerprint_v1,
    compute_normalized_signature,
)

logger = structlog.get_logger()

# Check if LLM parsing is enabled
LLM_PARSING_ENABLED = os.environ.get("LLM_PARSING_ENABLED", "true").lower() == "true"

# Import LLM parser if enabled
if LLM_PARSING_ENABLED:
    from worker.llm_parser import get_llm_parser


class EmailParser:
    """Parses raw emails into normalized alert events."""

    def __init__(self):
        self.parsers: Dict[str, Dict] = {}
        self._load_parsers()

    def _load_parsers(self):
        """Load parser configurations from YAML, merging with defaults."""
        # Always load defaults first
        self._load_default_parsers()

        # Then try to load and merge config file parsers
        try:
            with open("/app/configs/parsers.yml", "r") as f:
                config = yaml.safe_load(f)
                file_parsers = config.get("parsers", {})
                # Merge file parsers on top of defaults (file takes priority for conflicts)
                self.parsers.update(file_parsers)
            logger.info("Loaded parsers", count=len(self.parsers))
        except FileNotFoundError:
            logger.info("No parsers config found, using defaults", count=len(self.parsers))
        except Exception as e:
            logger.warning("Failed to load parsers config, using defaults", error=str(e))

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
            "xmatters": {
                "name": "xMatters",
                "subject_pattern": r"(?:Immediate assistance REQ[:\-]?\s*)(?P<location>[^-]*?)\s*-\s*(?P<ticket_number>INC\d+)",
                "body_patterns": [
                    r"Quick Description:(?:</strong>)?\s*(?P<check_name>[^<\r\n]+)",
                    r"Ticket Number:(?:</strong>)?\s*(?P<incident_id>INC\d+)",
                    r"(?:Severity|severity):(?:</strong>)?\s*(?P<severity>\w+)",
                    r"Condition:(?:</strong>)?\s*(?P<condition>\w+)",
                    r"Event Start Time:(?:</strong>)?\s*(?P<event_time>[^<\r\n]+)",
                    r"City,?\s*State:(?:</strong>)?\s*(?P<location>[^<\r\n]+)",
                    r"Escalated by:(?:</strong>)?\s*(?P<escalated_by>[^<\r\n]+)",
                    r"Escalation Notes:(?:</strong>)?\s*(?P<notes>[^<\r\n]+)"
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
            from_address = email_row["from_address"] or ""

            # Try LLM learning parser first (if enabled)
            llm_parsed = None
            if LLM_PARSING_ENABLED:
                try:
                    llm_parser = await get_llm_parser()
                    llm_parsed = await llm_parser.parse_email(
                        email_id=email_id,
                        subject=subject,
                        from_address=from_address,
                        body=body
                    )
                    logger.debug(
                        "LLM parser result",
                        email_id=email_id,
                        extraction_type=llm_parsed.get("extraction_type"),
                        source=llm_parsed.get("source_name")
                    )
                except Exception as e:
                    logger.warning("LLM parser failed, falling back to regex", error=str(e))
                    llm_parsed = None

            # Determine source tool - prefer LLM result, fall back to folder detection
            if llm_parsed and llm_parsed.get("source_tool") and llm_parsed.get("source_tool") != "unknown":
                source_tool = llm_parsed["source_tool"]
            else:
                source_tool = self._determine_source_tool(folder, subject, body, from_address)

            # Get parser for this source (used as fallback or supplement)
            parser_config = self.parsers.get(source_tool.lower(), self.parsers.get("generic", {}))

            try:
                # Parse using configured patterns (as fallback/supplement)
                regex_parsed = self._apply_parser(parser_config, subject, body)

                # Merge results: LLM takes priority, regex fills gaps
                if llm_parsed:
                    parsed = {
                        "host": llm_parsed.get("host") or regex_parsed.get("host"),
                        "service": llm_parsed.get("service") or regex_parsed.get("service") or regex_parsed.get("service_name"),
                        "severity": llm_parsed.get("severity") or regex_parsed.get("severity") or regex_parsed.get("severity_text"),
                        "state": llm_parsed.get("state") or regex_parsed.get("state") or regex_parsed.get("state_closed"),
                        "summary": llm_parsed.get("summary") or regex_parsed.get("summary"),
                        "check_name": regex_parsed.get("check_name") or llm_parsed.get("service"),
                        "alert_name": regex_parsed.get("alert_name"),
                        "trigger": regex_parsed.get("trigger"),
                        "environment": regex_parsed.get("environment"),
                        "region": regex_parsed.get("region"),
                        "info": regex_parsed.get("info"),
                        "source_name": llm_parsed.get("source_name"),
                        "extraction_type": llm_parsed.get("extraction_type"),
                        **{k: v for k, v in regex_parsed.items() if k not in ["host", "service", "severity", "state", "check_name", "summary"]}
                    }
                else:
                    parsed = regex_parsed

                # Build normalized event
                event = {
                    "raw_email_id": email_id,
                    "source_tool": source_tool,
                    "host": parsed.get("host"),
                    "check_name": parsed.get("check_name") or parsed.get("service") or parsed.get("service_name") or parsed.get("alert_name") or parsed.get("trigger"),
                    "service": parsed.get("service") or parsed.get("service_name"),
                    "severity": self._normalize_severity(parsed.get("severity") or parsed.get("severity_text") or parsed.get("severity_detail")),
                    "state": self._determine_state(parsed.get("state") or parsed.get("state_closed")),
                    "environment": parsed.get("environment"),
                    "region": parsed.get("region"),
                    "occurred_at": email_row["date_header"] or datetime.utcnow(),
                    "payload": {
                        "subject": subject,
                        "from": from_address,
                        "summary": parsed.get("summary"),
                        "info": parsed.get("info"),
                        "alert_name": parsed.get("alert_name"),
                        "source_name": parsed.get("source_name"),
                        "extraction_type": parsed.get("extraction_type"),
                        **{k: v for k, v in parsed.items() if k not in ["host", "check_name", "severity", "state", "source_name", "extraction_type", "summary"]}
                    },
                    "tags": self._extract_tags(subject, body, parsed)
                }

                # Compute fingerprints (v2 is primary, v1 for backwards compatibility)
                event["normalized_signature"] = compute_normalized_signature(subject, body)
                event["fingerprint_v2"] = compute_fingerprint_v2(event)
                event["fingerprint"] = compute_fingerprint_v1(event)  # Legacy, for backwards compatibility

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

    def _determine_source_tool(self, folder: str, subject: str, body: str, from_address: str = "") -> str:
        """Determine source tool from folder name, content, and sender."""
        folder_lower = folder.lower()
        from_lower = from_address.lower()

        # Check from_address for specific tool signatures first
        if "pulse.netscout@" in from_lower or "ngenius" in from_lower:
            return "netscout_pulse"
        if "xmatters.com" in from_lower or "xmatters" in from_lower:
            return "xmatters"

        # Check folder name
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
        if "business service alert" in content:
            # Check if it's NetScout Pulse by body content
            if "ngeniuspulse" in content or "ngenius" in content or "pulse.charter.com" in content:
                return "netscout_pulse"
            return "business_service"
        if "pagerduty" in content:
            return "pagerduty"
        if "datadog" in content:
            return "datadog"

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
            "excessive": "high",
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

        state_lower = state.lower().strip()

        if state_lower in ["ok", "resolved", "recovery", "green", "closed"]:
            return "resolved"
        if state_lower in ["problem", "critical", "warning", "firing", "red", "yellow", "triggered"]:
            return "firing"

        return "unknown"

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
