"""Maintenance window detection and matching engine."""
import re
from datetime import datetime, timedelta, tzinfo
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
import yaml

try:
    from icalendar import Calendar
except ImportError:
    Calendar = None

try:
    from dateutil.rrule import rrulestr
    from dateutil import tz as dateutil_tz
except ImportError:
    rrulestr = None
    dateutil_tz = None

try:
    import pytz
except ImportError:
    pytz = None

from worker.database import get_pool

logger = structlog.get_logger()

# Default RRULE expansion horizon (days into the future)
RRULE_EXPANSION_HORIZON_DAYS = 90


class MaintenanceEngine:
    """Detects and manages maintenance windows."""

    def __init__(self):
        self.detection_patterns = {}
        self._load_config()

    def _load_config(self):
        """Load maintenance detection configuration."""
        try:
            with open("/app/configs/maintenance.yml", "r") as f:
                config = yaml.safe_load(f)
                self.detection_patterns = config.get("detection", {})
            logger.info("Loaded maintenance config")
        except FileNotFoundError:
            logger.warning("No maintenance config found, using defaults")
            self._load_defaults()
        except Exception as e:
            logger.error("Failed to load maintenance config", error=str(e))
            self._load_defaults()

    def _load_defaults(self):
        """Load default detection patterns."""
        self.detection_patterns = {
            "subject_prefixes": ["[MW]", "[Maintenance]", "Maintenance:", "MAINTENANCE:"],
            "body_patterns": {
                "scope": r"Scope:\s*(.+?)(?:\n|$)",
                "mode": r"Mode:\s*(mute|downgrade|digest)",
                "title": r"Title:\s*(.+?)(?:\n|$)",
                "start": r"Start:\s*(.+?)(?:\n|$)",
                "end": r"End:\s*(.+?)(?:\n|$)",
                "timezone": r"Timezone:\s*(.+?)(?:\n|$)"
            },
            "scope_patterns": {
                "host": r"host=([^;]+)",
                "service": r"service=([^;]+)",
                "env": r"env=([^;]+)",
                "region": r"region=([^;]+)",
                "tags": r"tags=([^;]+)"
            }
        }

    async def process_email(self, email_id: str):
        """Process email for maintenance window detection."""
        pool = await get_pool()

        async with pool.acquire() as conn:
            email = await conn.fetchrow(
                """
                SELECT id, subject, from_address, body_text, body_html, ics_content,
                       date_header, attachments
                FROM raw_emails WHERE id = $1
                """,
                UUID(email_id)
            )

            if not email:
                return

            subject = email["subject"] or ""
            body = email["body_text"] or email["body_html"] or ""
            ics_content = email["ics_content"]

            # Check if this looks like a maintenance notification
            if not self._is_maintenance_email(subject, body, ics_content):
                logger.debug("Email not identified as maintenance", email_id=email_id)
                return

            # Extract maintenance window details
            window_data = await self._extract_window_data(email)

            if window_data:
                # Create maintenance window
                await self._create_maintenance_window(conn, email_id, window_data)
                logger.info("Maintenance window created from email", email_id=email_id)

            # Mark email as processed
            await conn.execute(
                "UPDATE raw_emails SET parse_status = 'success', processed_at = NOW() WHERE id = $1",
                UUID(email_id)
            )

    def _is_maintenance_email(self, subject: str, body: str, ics_content: str) -> bool:
        """Check if email is a maintenance notification."""
        # Check subject prefixes
        subject_lower = subject.lower()
        for prefix in self.detection_patterns.get("subject_prefixes", []):
            if prefix.lower() in subject_lower:
                return True

        # Check for ICS content (calendar invite)
        if ics_content:
            return True

        # Check body for maintenance keywords
        body_lower = body.lower()
        maintenance_keywords = ["maintenance window", "scheduled maintenance", "planned outage"]
        for keyword in maintenance_keywords:
            if keyword in body_lower:
                return True

        return False

    async def _extract_window_data(self, email: Dict) -> Optional[Dict[str, Any]]:
        """Extract maintenance window data from email."""
        subject = email["subject"] or ""
        body = email["body_text"] or email["body_html"] or ""
        ics_content = email["ics_content"]
        from_address = email["from_address"] or ""

        result = {
            "title": subject,
            "organizer": from_address.split("<")[0].strip() if "<" in from_address else from_address,
            "organizer_email": from_address,
            "scope": {},
            "suppress_mode": "mute",
            "reason": body[:500]
        }

        # Try ICS parsing first
        if ics_content and Calendar:
            ics_data = self._parse_ics(ics_content)
            if ics_data:
                result.update(ics_data)

        # Parse body for structured data
        body_data = self._parse_body(body)
        if body_data.get("title"):
            result["title"] = body_data["title"]
        if body_data.get("scope"):
            result["scope"] = body_data["scope"]
        if body_data.get("suppress_mode"):
            result["suppress_mode"] = body_data["suppress_mode"]
        if body_data.get("start_ts"):
            result["start_ts"] = body_data["start_ts"]
        if body_data.get("end_ts"):
            result["end_ts"] = body_data["end_ts"]
        if body_data.get("timezone"):
            result["timezone"] = body_data["timezone"]

        # Default times if not found
        if not result.get("start_ts"):
            result["start_ts"] = email.get("date_header") or datetime.utcnow()
        if not result.get("end_ts"):
            result["end_ts"] = result["start_ts"] + timedelta(hours=2)
        if not result.get("timezone"):
            result["timezone"] = "UTC"

        return result

    def _parse_ics(self, ics_content: str) -> Optional[Dict[str, Any]]:
        """Parse ICS calendar content with RRULE expansion, timezone, and cancellation support."""
        if not Calendar:
            return None

        try:
            cal = Calendar.from_ical(ics_content)

            for component in cal.walk():
                if component.name == "VEVENT":
                    # Check for cancellation
                    status = str(component.get("STATUS", "")).upper()
                    if status == "CANCELLED":
                        logger.info("Maintenance window cancelled via ICS STATUS:CANCELLED")
                        return {
                            "cancelled": True,
                            "external_event_id": str(component.get("uid", "")),
                            "recurrence_id": component.get("recurrence-id")
                        }

                    # Get timezone from DTSTART
                    dtstart = component.get("dtstart")
                    event_tz = self._get_event_timezone(dtstart, component, cal)

                    # Get start and end times
                    start_dt = dtstart.dt if dtstart else None
                    end_dt = component.get("dtend").dt if component.get("dtend") else None

                    # Ensure timezone-aware datetimes
                    if start_dt and not hasattr(start_dt, 'tzinfo') or (hasattr(start_dt, 'tzinfo') and start_dt.tzinfo is None):
                        if event_tz and pytz:
                            start_dt = event_tz.localize(start_dt) if hasattr(event_tz, 'localize') else start_dt.replace(tzinfo=event_tz)
                    if end_dt and not hasattr(end_dt, 'tzinfo') or (hasattr(end_dt, 'tzinfo') and end_dt.tzinfo is None):
                        if event_tz and pytz:
                            end_dt = event_tz.localize(end_dt) if hasattr(event_tz, 'localize') else end_dt.replace(tzinfo=event_tz)

                    result = {
                        "title": str(component.get("summary", "")),
                        "start_ts": start_dt,
                        "end_ts": end_dt,
                        "external_event_id": str(component.get("uid", "")),
                        "timezone": str(event_tz) if event_tz else "UTC",
                        "is_recurring": component.get("rrule") is not None,
                        "recurrence_rule": None,
                        "expanded_occurrences": []
                    }

                    # Handle RRULE expansion
                    rrule = component.get("rrule")
                    if rrule and rrulestr and start_dt:
                        rrule_str = rrule.to_ical().decode('utf-8')
                        result["recurrence_rule"] = rrule_str
                        result["expanded_occurrences"] = self._expand_rrule(
                            rrule_str, start_dt, end_dt, event_tz
                        )

                    organizer = component.get("organizer")
                    if organizer:
                        result["organizer_email"] = str(organizer).replace("mailto:", "")

                    # Check description for scope
                    description = str(component.get("description", ""))
                    if description:
                        scope_data = self._parse_scope(description)
                        if scope_data:
                            result["scope"] = scope_data

                    return result

        except Exception as e:
            logger.error("Failed to parse ICS", error=str(e))

        return None

    def _get_event_timezone(self, dtstart, component, cal) -> Optional[tzinfo]:
        """Extract timezone from DTSTART or VTIMEZONE component."""
        if dtstart and hasattr(dtstart.dt, 'tzinfo') and dtstart.dt.tzinfo:
            return dtstart.dt.tzinfo

        # Check for TZID parameter
        if dtstart:
            tzid = dtstart.params.get('TZID')
            if tzid and pytz:
                try:
                    return pytz.timezone(tzid)
                except Exception:
                    pass

        # Check for VTIMEZONE in calendar
        for comp in cal.walk():
            if comp.name == "VTIMEZONE":
                tzid = str(comp.get("TZID", ""))
                if tzid and pytz:
                    try:
                        return pytz.timezone(tzid)
                    except Exception:
                        pass

        return pytz.UTC if pytz else None

    def _expand_rrule(
        self,
        rrule_str: str,
        dtstart: datetime,
        dtend: datetime,
        event_tz: Optional[tzinfo],
        horizon_days: int = RRULE_EXPANSION_HORIZON_DAYS
    ) -> List[Dict[str, datetime]]:
        """
        Expand RRULE into individual occurrences.

        Args:
            rrule_str: RRULE string from ICS
            dtstart: Event start time
            dtend: Event end time
            event_tz: Event timezone
            horizon_days: How many days into the future to expand

        Returns:
            List of occurrence dicts with start_ts and end_ts
        """
        if not rrulestr:
            return []

        try:
            # Calculate duration
            duration = dtend - dtstart if dtend else timedelta(hours=1)

            # Build the rule
            rule = rrulestr(rrule_str, dtstart=dtstart)

            # Calculate horizon
            if pytz:
                now = datetime.now(pytz.UTC)
            else:
                now = datetime.utcnow()

            if event_tz and hasattr(now, 'astimezone'):
                now = now.astimezone(event_tz)

            horizon = now + timedelta(days=horizon_days)

            # Expand occurrences
            occurrences = []
            for occurrence in rule.between(now, horizon, inc=True):
                # Ensure timezone-aware
                if event_tz and occurrence.tzinfo is None:
                    if hasattr(event_tz, 'localize'):
                        occurrence = event_tz.localize(occurrence)
                    else:
                        occurrence = occurrence.replace(tzinfo=event_tz)

                occurrences.append({
                    "start_ts": occurrence,
                    "end_ts": occurrence + duration
                })

            logger.debug(
                "Expanded RRULE",
                rule=rrule_str[:50],
                occurrences=len(occurrences),
                horizon_days=horizon_days
            )

            return occurrences

        except Exception as e:
            logger.error("Failed to expand RRULE", error=str(e), rule=rrule_str[:100])
            return []

    def _parse_body(self, body: str) -> Dict[str, Any]:
        """Parse email body for maintenance data."""
        result = {}
        patterns = self.detection_patterns.get("body_patterns", {})

        for field, pattern in patterns.items():
            match = re.search(pattern, body, re.IGNORECASE | re.MULTILINE)
            if match:
                if field == "scope":
                    result["scope"] = self._parse_scope(match.group(1))
                elif field == "mode":
                    result["suppress_mode"] = match.group(1).lower()
                elif field in ("start", "end"):
                    try:
                        from dateutil import parser as date_parser
                        result[f"{field}_ts"] = date_parser.parse(match.group(1))
                    except Exception:
                        pass
                else:
                    result[field] = match.group(1).strip()

        return result

    def _parse_scope(self, scope_str: str) -> Dict[str, Any]:
        """Parse scope string into structured format."""
        scope = {
            "hosts": [],
            "host_regex": None,
            "services": [],
            "service_regex": None,
            "environments": [],
            "regions": [],
            "tags": []
        }

        patterns = self.detection_patterns.get("scope_patterns", {})

        for field, pattern in patterns.items():
            match = re.search(pattern, scope_str, re.IGNORECASE)
            if match:
                value = match.group(1).strip()

                if field == "host":
                    if "*" in value or "?" in value:
                        scope["host_regex"] = value.replace("*", ".*").replace("?", ".")
                    else:
                        scope["hosts"] = [h.strip() for h in value.split(",")]
                elif field == "service":
                    if "*" in value or "?" in value:
                        scope["service_regex"] = value.replace("*", ".*").replace("?", ".")
                    else:
                        scope["services"] = [s.strip() for s in value.split(",")]
                elif field == "env":
                    scope["environments"] = [e.strip() for e in value.split(",")]
                elif field == "region":
                    scope["regions"] = [r.strip() for r in value.split(",")]
                elif field == "tags":
                    scope["tags"] = [t.strip() for t in value.split(",")]

        return scope

    async def _create_maintenance_window(
        self, conn, email_id: str, data: Dict[str, Any]
    ):
        """Create maintenance window record."""
        import json

        await conn.execute(
            """
            INSERT INTO maintenance_windows (
                source, raw_email_id, external_event_id, title, description,
                organizer, organizer_email, start_ts, end_ts, timezone,
                is_recurring, recurrence_rule, scope, suppress_mode, reason
            )
            VALUES (
                'email', $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14
            )
            ON CONFLICT (source, external_event_id) WHERE external_event_id IS NOT NULL
            DO UPDATE SET
                title = EXCLUDED.title,
                start_ts = EXCLUDED.start_ts,
                end_ts = EXCLUDED.end_ts,
                scope = EXCLUDED.scope,
                updated_at = NOW()
            """,
            UUID(email_id),
            data.get("external_event_id"),
            data.get("title", "Maintenance Window")[:500],
            data.get("reason"),
            data.get("organizer"),
            data.get("organizer_email"),
            data.get("start_ts"),
            data.get("end_ts"),
            data.get("timezone", "UTC"),
            data.get("is_recurring", False),
            data.get("recurrence_rule"),
            json.dumps(data.get("scope", {})),
            data.get("suppress_mode", "mute"),
            data.get("reason")
        )

    async def match_incidents_to_maintenance(self):
        """Match open incidents to active maintenance windows."""
        pool = await get_pool()

        async with pool.acquire() as conn:
            # Get active maintenance windows
            windows = await conn.fetch(
                """
                SELECT * FROM maintenance_windows
                WHERE is_active = true AND start_ts <= NOW() AND end_ts >= NOW()
                """
            )

            if not windows:
                return

            # Get open incidents not yet matched
            incidents = await conn.fetch(
                """
                SELECT * FROM incidents
                WHERE status IN ('open', 'acknowledged')
                AND is_in_maintenance = false
                """
            )

            for incident in incidents:
                for window in windows:
                    if self._matches_scope(incident, window["scope"]):
                        # Record match
                        match_reason = self._get_match_reason(incident, window["scope"])

                        await conn.execute(
                            """
                            INSERT INTO maintenance_matches (
                                maintenance_window_id, incident_id, match_reason
                            )
                            VALUES ($1, $2, $3)
                            ON CONFLICT DO NOTHING
                            """,
                            window["id"], incident["id"], match_reason
                        )

                        # Update incident
                        await conn.execute(
                            """
                            UPDATE incidents
                            SET is_in_maintenance = true, maintenance_window_id = $2
                            WHERE id = $1
                            """,
                            incident["id"], window["id"]
                        )

                        logger.info(
                            "Incident matched to maintenance",
                            incident_id=str(incident["id"]),
                            window_id=str(window["id"])
                        )

    async def clear_expired_maintenance(self):
        """Clear maintenance flag from incidents where window expired."""
        pool = await get_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE incidents i
                SET is_in_maintenance = false, maintenance_window_id = NULL
                WHERE is_in_maintenance = true
                AND NOT EXISTS (
                    SELECT 1 FROM maintenance_windows mw
                    WHERE mw.id = i.maintenance_window_id
                    AND mw.is_active = true
                    AND mw.start_ts <= NOW()
                    AND mw.end_ts >= NOW()
                )
                """
            )

    def _matches_scope(self, incident: Dict, scope: Dict) -> bool:
        """Check if incident matches maintenance scope."""
        import json

        if isinstance(scope, str):
            scope = json.loads(scope)

        # Check hosts
        hosts = scope.get("hosts", [])
        host_regex = scope.get("host_regex")
        incident_host = incident.get("host", "")

        if hosts and incident_host:
            if incident_host not in hosts:
                if host_regex:
                    if not re.match(host_regex, incident_host, re.IGNORECASE):
                        return False
                else:
                    return False
        elif host_regex and incident_host:
            if not re.match(host_regex, incident_host, re.IGNORECASE):
                return False

        # Check services
        services = scope.get("services", [])
        service_regex = scope.get("service_regex")
        incident_service = incident.get("service") or incident.get("check_name") or ""

        if services and incident_service:
            if incident_service not in services:
                if service_regex:
                    if not re.match(service_regex, incident_service, re.IGNORECASE):
                        return False
                else:
                    return False
        elif service_regex and incident_service:
            if not re.match(service_regex, incident_service, re.IGNORECASE):
                return False

        # Check environment
        environments = scope.get("environments", [])
        if environments and incident.get("environment"):
            if incident["environment"] not in environments:
                return False

        # Check region
        regions = scope.get("regions", [])
        if regions and incident.get("region"):
            if incident["region"] not in regions:
                return False

        # Check tags
        scope_tags = scope.get("tags", [])
        incident_tags = incident.get("tags", [])
        if scope_tags:
            if not any(t in incident_tags for t in scope_tags):
                return False

        # If no scope defined, match everything
        if not any([hosts, host_regex, services, service_regex, environments, regions, scope_tags]):
            return True

        return True

    def _get_match_reason(self, incident: Dict, scope: Dict) -> Dict:
        """Get explanation of why incident matched."""
        import json

        if isinstance(scope, str):
            scope = json.loads(scope)

        reasons = []

        if scope.get("hosts") and incident.get("host") in scope["hosts"]:
            reasons.append({"field": "host", "pattern": scope["hosts"], "value": incident["host"]})
        if scope.get("host_regex") and incident.get("host"):
            reasons.append({"field": "host", "pattern": scope["host_regex"], "value": incident["host"]})
        if scope.get("environments") and incident.get("environment") in scope["environments"]:
            reasons.append({"field": "environment", "pattern": scope["environments"], "value": incident["environment"]})

        return json.dumps({"reasons": reasons})
