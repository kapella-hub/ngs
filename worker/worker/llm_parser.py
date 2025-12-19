"""LLM-based learning parser for alert emails.

This module implements a self-learning parser that:
1. Computes a "format signature" for each incoming email
2. Checks if a cached extraction pattern exists for that signature
3. If cached: applies the extraction rules (fast, no LLM)
4. If not cached: calls LLM to extract fields AND generate extraction rules
5. Caches the new pattern for future use
6. Validates LLM output with Pydantic schemas
7. Applies confidence gating and quarantine for low-confidence extractions
"""
import hashlib
import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import httpx
import structlog
from pydantic import ValidationError

from worker.database import get_pool
from worker.redactor import redact_email_content
from worker.schemas import (
    LLMExtractionResult,
    CONFIDENCE_THRESHOLD,
    QUARANTINE_THRESHOLD,
    QuarantineReason,
)
from worker.quarantine import quarantine_event

logger = structlog.get_logger()

# Extraction prompt for the LLM
EXTRACTION_PROMPT = """You are an alert email parser. Analyze this monitoring alert email and extract structured information.

EMAIL SUBJECT:
{subject}

EMAIL BODY (full content):
{body}

Extract the following fields and provide extraction rules for similar emails:

1. **host**: The server, device, or hostname being monitored (null for business service alerts)
2. **service**: The service, check, or metric name being monitored
3. **severity**: The alert severity (e.g., CRITICAL, WARNING, Excessive, Major, RED)
4. **state**: Whether this is a new alert or resolution (e.g., PROBLEM, RECOVERY, Closed, recovered, Triggered)
5. **summary**: A brief description of the alert (e.g., "35 service test problems impacting 11 sites")
6. **source_name**: A human-readable name for this alert source (e.g., "Xymon", "NetScout Pulse", "Splunk Alert")

Also provide regex patterns that can extract these fields from similar emails.

Respond ONLY with valid JSON in this exact format:
{{
  "extracted": {{
    "host": "hostname or null if not found",
    "service": "service name or null if not found",
    "severity": "severity word or null",
    "state": "state word or null",
    "summary": "brief description or null"
  }},
  "source_name": "Name of the monitoring system",
  "extraction_rules": {{
    "host": {{
      "source": "subject or body",
      "regex": "regex pattern with capture group",
      "group": 1
    }},
    "service": {{
      "source": "subject or body",
      "regex": "regex pattern with capture group",
      "group": 1
    }},
    "severity": {{
      "source": "subject or body",
      "regex": "regex pattern with capture group",
      "group": 1,
      "normalize": {{"WORD": "normalized_value"}}
    }},
    "state": {{
      "source": "subject or body",
      "regex": "regex pattern with capture group or null",
      "group": 1,
      "normalize": {{"WORD": "firing or resolved"}}
    }},
    "summary": {{
      "source": "body",
      "regex": "regex pattern with capture group",
      "group": 1
    }}
  }},
  "confidence": 0.95
}}

Important:
- Use Python regex syntax in the regex strings
- In JSON, escape backslashes as \\\\ (e.g., "\\\\d+" for digits, "\\\\s+" for whitespace)
- Do NOT use Python r"" raw strings - JSON doesn't support them
- If a field cannot be determined, set it to null
- The normalize map converts extracted words to standard values
- For "state", map alert words to "firing" and recovery words to "resolved"
"""


class LLMParser:
    """Learning parser that uses LLM for extraction and pattern generation."""

    def __init__(self, llm_endpoint: str = "http://rag:8001"):
        self.llm_endpoint = llm_endpoint
        self.http_client = httpx.AsyncClient(timeout=180.0)  # 3 min for slow CPU inference

    async def close(self):
        """Close HTTP client."""
        await self.http_client.aclose()

    def compute_signature(self, subject: str, from_address: str, body: str) -> Tuple[str, Dict]:
        """
        Compute a format signature for an email.

        The signature is based on:
        - From address domain
        - Subject prefix/structure
        - Key markers in the body

        Returns: (signature_hash, signature_components)
        """
        # Extract from domain
        from_domain = ""
        if from_address:
            match = re.search(r'@([\w.-]+)', from_address)
            if match:
                from_domain = match.group(1).lower()

        # Extract subject prefix (first 30 chars, normalized)
        subject_prefix = ""
        if subject:
            # Remove variable parts like timestamps, IDs
            normalized = re.sub(r'\[\d+\]', '[*]', subject)  # [12345] -> [*]
            normalized = re.sub(r'\d{4}-\d{2}-\d{2}', '*DATE*', normalized)
            normalized = re.sub(r'\d+', '*N*', normalized)  # Numbers
            subject_prefix = normalized[:50].strip()

        # Extract body markers (key phrases)
        body_markers = []
        if body:
            body_lower = body.lower()[:2000]
            # Look for common monitoring keywords
            markers_to_check = [
                'severity', 'status', 'alert', 'host:', 'service:',
                'critical', 'warning', 'problem', 'recovery',
                'impact', 'duration', 'opened', 'closed'
            ]
            for marker in markers_to_check:
                if marker in body_lower:
                    body_markers.append(marker)

        # Create signature components
        components = {
            "from_domain": from_domain,
            "subject_prefix": subject_prefix,
            "body_markers": sorted(body_markers)
        }

        # Compute hash
        sig_str = f"{from_domain}|{subject_prefix}|{','.join(body_markers)}"
        sig_hash = hashlib.sha256(sig_str.encode()).hexdigest()[:16]

        return sig_hash, components

    async def find_cached_pattern(self, signature_hash: str) -> Optional[Dict]:
        """Look up a cached pattern by signature hash."""
        pool = await get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, source_name, source_tool, extraction_rules
                FROM pattern_cache
                WHERE signature_hash = $1
                """,
                signature_hash
            )

            if row:
                return {
                    "id": str(row["id"]),
                    "source_name": row["source_name"],
                    "source_tool": row["source_tool"],
                    "extraction_rules": row["extraction_rules"]
                }

        return None

    def apply_extraction_rules(
        self,
        rules: Dict,
        subject: str,
        body: str
    ) -> Dict[str, Any]:
        """Apply cached extraction rules to extract fields."""
        result = {}

        for field, rule in rules.items():
            if not rule or rule.get("regex") is None:
                continue

            try:
                source_text = subject if rule.get("source") == "subject" else body
                pattern = rule["regex"]
                group = rule.get("group", 1)

                match = re.search(pattern, source_text, re.IGNORECASE)
                if match:
                    value = match.group(group) if group <= len(match.groups()) else match.group(0)

                    # Apply normalization if present
                    normalize_map = rule.get("normalize", {})
                    if normalize_map and value:
                        value_upper = value.upper()
                        for key, normalized in normalize_map.items():
                            if key.upper() == value_upper:
                                value = normalized
                                break

                    result[field] = value

            except Exception as e:
                logger.warning(f"Rule extraction failed for {field}", error=str(e))

        return result

    async def call_llm_for_extraction(
        self,
        subject: str,
        body: str
    ) -> Optional[Dict]:
        """Call LLM to extract fields and generate extraction rules."""
        # Apply redaction before sending to LLM
        redacted_subject, redacted_body = redact_email_content(subject, body)

        # Include more body content for better extraction
        prompt = EXTRACTION_PROMPT.format(
            subject=redacted_subject[:500],
            body=redacted_body[:4000] if redacted_body else "(no body)"
        )

        try:
            start_time = time.time()

            # Call the RAG service's /generate endpoint (direct LLM, no RAG)
            response = await self.http_client.post(
                f"{self.llm_endpoint}/generate",
                json={
                    "prompt": prompt,
                    "system_prompt": "You are an expert alert email parser. Extract structured data and respond only with valid JSON."
                }
            )

            duration_ms = int((time.time() - start_time) * 1000)

            if response.status_code != 200:
                logger.error("LLM call failed", status=response.status_code, body=response.text[:200])
                return None

            data = response.json()
            answer = data.get("response", "")

            # Clean up the response - remove Python raw string notation that LLMs sometimes use
            # Convert r"..." to "..." and r'...' to '...'
            answer = re.sub(r'\br(["\'])', r'\1', answer)

            # Parse JSON from response
            # Try to find JSON in the response
            json_match = re.search(r'\{[\s\S]*\}', answer)
            if not json_match:
                logger.error("No JSON found in LLM response")
                return None

            json_str = json_match.group()

            # Fix invalid escape sequences that LLMs sometimes produce
            # Replace invalid escapes like \s, \d, \w with just the letter
            def fix_escapes(s):
                # First, protect valid JSON escapes by replacing them temporarily
                # Use unlikely placeholder strings (not escape sequences)
                s = s.replace('\\\\', '<<DBLBACK>>')
                s = s.replace('\\"', '<<QUOTE>>')
                s = s.replace('\\n', '<<NL>>')
                s = s.replace('\\r', '<<CR>>')
                s = s.replace('\\t', '<<TAB>>')
                s = s.replace('\\/', '<<SLASH>>')
                s = s.replace('\\b', '<<BS>>')
                s = s.replace('\\f', '<<FF>>')
                # Replace unicode escapes
                s = re.sub(r'\\u([0-9a-fA-F]{4})', r'<<U\1>>', s)
                # Now remove remaining invalid escapes (like \s, \d, etc)
                s = re.sub(r'\\(.)', r'\1', s)
                # Restore valid escapes
                s = s.replace('<<DBLBACK>>', '\\\\')
                s = s.replace('<<QUOTE>>', '\\"')
                s = s.replace('<<NL>>', '\\n')
                s = s.replace('<<CR>>', '\\r')
                s = s.replace('<<TAB>>', '\\t')
                s = s.replace('<<SLASH>>', '\\/')
                s = s.replace('<<BS>>', '\\b')
                s = s.replace('<<FF>>', '\\f')
                s = re.sub(r'<<U([0-9a-fA-F]{4})>>', r'\\u\1', s)
                return s

            json_str = fix_escapes(json_str)
            result = json.loads(json_str)
            result["duration_ms"] = duration_ms

            return result

        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM JSON response", error=str(e))
            return None
        except Exception as e:
            logger.error("LLM call error", error=str(e))
            return None

    async def cache_pattern(
        self,
        signature_hash: str,
        signature_components: Dict,
        source_name: str,
        extraction_rules: Dict,
        email_id: str,
        duration_ms: int
    ) -> Optional[str]:
        """Cache a new extraction pattern."""
        pool = await get_pool()

        # Determine source_tool from source_name
        source_tool = source_name.lower().replace(" ", "_")
        # Simplify common names
        tool_map = {
            "xymon": "xymon",
            "business_service_alert": "business_service",
            "splunk_alert": "splunk",
            "nagios": "nagios",
            "prometheus": "prometheus",
            "zabbix": "zabbix",
            "pagerduty": "pagerduty",
            "datadog": "datadog"
        }
        for key, value in tool_map.items():
            if key in source_tool:
                source_tool = value
                break

        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO pattern_cache (
                        signature_hash, from_domain, subject_prefix,
                        body_markers, source_name, source_tool,
                        extraction_rules, analysis_duration_ms,
                        created_from_email_id
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (signature_hash) DO UPDATE SET
                        match_count = pattern_cache.match_count + 1,
                        last_matched_at = NOW()
                    RETURNING id
                    """,
                    signature_hash,
                    signature_components.get("from_domain"),
                    signature_components.get("subject_prefix"),
                    signature_components.get("body_markers"),
                    source_name,
                    source_tool,
                    json.dumps(extraction_rules),
                    duration_ms,
                    UUID(email_id) if email_id else None
                )

                if row:
                    logger.info(
                        "Cached new extraction pattern",
                        signature=signature_hash,
                        source=source_name
                    )
                    return str(row["id"])

            except Exception as e:
                logger.error("Failed to cache pattern", error=str(e))

        return None

    async def log_extraction(
        self,
        email_id: str,
        pattern_id: Optional[str],
        extraction_type: str,
        extracted: Dict,
        confidence: float,
        llm_response: Optional[Dict],
        duration_ms: int
    ):
        """Log extraction for audit trail."""
        pool = await get_pool()

        async with pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO pattern_extraction_log (
                        raw_email_id, pattern_cache_id, extraction_type,
                        extracted_host, extracted_service,
                        extracted_severity, extracted_state,
                        extraction_confidence, llm_response, duration_ms
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    UUID(email_id),
                    UUID(pattern_id) if pattern_id else None,
                    extraction_type,
                    extracted.get("host"),
                    extracted.get("service"),
                    extracted.get("severity"),
                    extracted.get("state"),
                    confidence,
                    json.dumps(llm_response) if llm_response else None,
                    duration_ms
                )
            except Exception as e:
                logger.warning("Failed to log extraction", error=str(e))

    async def parse_email(
        self,
        email_id: str,
        subject: str,
        from_address: str,
        body: str
    ) -> Dict[str, Any]:
        """
        Parse an email using the learning system.

        1. Compute signature
        2. Check for cached pattern
        3. If cached: apply rules
        4. If not cached: call LLM, cache pattern
        5. Validate with Pydantic schema
        6. Apply confidence gating

        Returns extracted fields or None if quarantined.
        """
        start_time = time.time()

        # Compute signature
        sig_hash, sig_components = self.compute_signature(subject, from_address, body)

        # Check cache
        cached = await self.find_cached_pattern(sig_hash)

        if cached:
            # Apply cached extraction rules
            extracted = self.apply_extraction_rules(
                cached["extraction_rules"],
                subject,
                body
            )

            duration_ms = int((time.time() - start_time) * 1000)

            # Log extraction
            await self.log_extraction(
                email_id=email_id,
                pattern_id=cached["id"],
                extraction_type="cached_match",
                extracted=extracted,
                confidence=0.9,
                llm_response=None,
                duration_ms=duration_ms
            )

            logger.debug(
                "Used cached pattern",
                signature=sig_hash,
                source=cached["source_name"]
            )

            return {
                "host": extracted.get("host"),
                "service": extracted.get("service"),
                "severity": extracted.get("severity"),
                "state": extracted.get("state"),
                "summary": extracted.get("summary"),
                "source_tool": cached["source_tool"],
                "source_name": cached["source_name"],
                "extraction_type": "cached",
                "confidence": 0.9
            }

        # No cache - call LLM
        logger.info("No cached pattern, calling LLM", signature=sig_hash)

        llm_result = await self.call_llm_for_extraction(subject, body)

        if not llm_result:
            # LLM failed - return empty result
            return {
                "host": None,
                "service": None,
                "severity": None,
                "state": None,
                "source_tool": "unknown",
                "source_name": "Unknown",
                "extraction_type": "llm_failed",
                "confidence": 0.0
            }

        extracted = llm_result.get("extracted", {})
        source_name = llm_result.get("source_name", "Unknown Alert")
        extraction_rules = llm_result.get("extraction_rules", {})
        confidence = llm_result.get("confidence", 0.5)
        duration_ms = llm_result.get("duration_ms", 0)

        # Validate LLM output with Pydantic schema
        try:
            validated = LLMExtractionResult(
                host=extracted.get("host"),
                service=extracted.get("service"),
                severity=extracted.get("severity"),
                state=extracted.get("state"),
                summary=extracted.get("summary"),
                source_tool=source_name.lower().replace(" ", "_"),
                source_name=source_name,
                confidence=confidence
            )
            # Use validated data
            extracted = {
                "host": validated.host,
                "service": validated.service,
                "severity": validated.severity,
                "state": validated.state,
                "summary": validated.summary,
            }
            confidence = validated.confidence
        except ValidationError as e:
            logger.warning(
                "LLM output failed Pydantic validation",
                email_id=email_id,
                error=str(e)
            )
            # Quarantine invalid output
            await quarantine_event(
                raw_email_id=UUID(email_id),
                extraction_data=llm_result,
                confidence=confidence,
                reason=QuarantineReason.VALIDATION_FAILED
            )
            return {
                "host": None,
                "service": None,
                "severity": None,
                "state": None,
                "source_tool": "unknown",
                "source_name": "Unknown",
                "extraction_type": "quarantined",
                "confidence": 0.0
            }

        # Apply confidence gating
        if confidence < QUARANTINE_THRESHOLD:
            # Very low confidence - quarantine for human review
            logger.info(
                "Low confidence extraction quarantined",
                email_id=email_id,
                confidence=confidence
            )
            await quarantine_event(
                raw_email_id=UUID(email_id),
                extraction_data={"extracted": extracted, "source_name": source_name},
                confidence=confidence,
                reason=QuarantineReason.LOW_CONFIDENCE
            )
            return {
                "host": None,
                "service": None,
                "severity": None,
                "state": None,
                "source_tool": "unknown",
                "source_name": "Unknown",
                "extraction_type": "quarantined",
                "confidence": confidence
            }

        if confidence < CONFIDENCE_THRESHOLD:
            # Below threshold but not quarantine-worthy - don't cache, signal to use regex fallback
            logger.info(
                "Below confidence threshold, signaling regex fallback",
                email_id=email_id,
                confidence=confidence
            )
            # Still return the extraction but mark it appropriately
            # The caller (parser.py) will decide whether to use it

        # Cache the pattern (only for high-confidence extractions)
        pattern_id = None
        if confidence >= CONFIDENCE_THRESHOLD:
            pattern_id = await self.cache_pattern(
                signature_hash=sig_hash,
                signature_components=sig_components,
                source_name=source_name,
                extraction_rules=extraction_rules,
                email_id=email_id,
                duration_ms=duration_ms
            )

        # Log extraction
        await self.log_extraction(
            email_id=email_id,
            pattern_id=pattern_id,
            extraction_type="learned_new" if confidence >= CONFIDENCE_THRESHOLD else "low_confidence",
            extracted=extracted,
            confidence=confidence,
            llm_response=llm_result,
            duration_ms=duration_ms
        )

        # Determine source_tool
        source_tool = source_name.lower().replace(" ", "_")
        tool_map = {
            "xymon": "xymon",
            "business_service": "business_service",
            "splunk": "splunk",
            "nagios": "nagios",
            "prometheus": "prometheus"
        }
        for key, value in tool_map.items():
            if key in source_tool:
                source_tool = value
                break

        return {
            "host": extracted.get("host"),
            "service": extracted.get("service"),
            "severity": extracted.get("severity"),
            "state": extracted.get("state"),
            "summary": extracted.get("summary"),
            "source_tool": source_tool,
            "source_name": source_name,
            "extraction_type": "learned" if confidence >= CONFIDENCE_THRESHOLD else "low_confidence",
            "confidence": confidence
        }


# Singleton instance
_llm_parser: Optional[LLMParser] = None


async def get_llm_parser() -> LLMParser:
    """Get or create LLM parser instance."""
    global _llm_parser
    if _llm_parser is None:
        # Get endpoint from config or environment
        import os
        endpoint = os.environ.get("LLM_ENDPOINT", "http://rag:8001")
        _llm_parser = LLMParser(llm_endpoint=endpoint)
    return _llm_parser
