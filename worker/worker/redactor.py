"""PII and secret redaction for content sent to LLM.

This module provides redaction of sensitive information before sending
alert content to the LLM for parsing. Patterns can be configured via
environment variables.
"""
import os
import re
from typing import Dict, List, Pattern, Tuple

import structlog

logger = structlog.get_logger()

# Default redaction patterns (regex, replacement)
DEFAULT_PATTERNS: List[Tuple[str, str]] = [
    # Email addresses
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]'),

    # Phone numbers (various formats)
    (r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b', '[PHONE]'),
    (r'\b\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b', '[PHONE]'),

    # SSN
    (r'\b\d{3}-\d{2}-\d{4}\b', '[SSN]'),

    # Credit card numbers (basic patterns)
    (r'\b(?:4[0-9]{12}(?:[0-9]{3})?)\b', '[CARD]'),  # Visa
    (r'\b(?:5[1-5][0-9]{14})\b', '[CARD]'),  # Mastercard
    (r'\b(?:3[47][0-9]{13})\b', '[CARD]'),  # Amex
    (r'\b(?:6(?:011|5[0-9]{2})[0-9]{12})\b', '[CARD]'),  # Discover

    # API keys and tokens (common patterns)
    (r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', r'\1=[REDACTED_KEY]'),
    (r'(?i)(secret[_-]?key|secretkey)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', r'\1=[REDACTED_SECRET]'),
    (r'(?i)(access[_-]?token|accesstoken)\s*[=:]\s*["\']?([a-zA-Z0-9_\-\.]{20,})["\']?', r'\1=[REDACTED_TOKEN]'),

    # Password fields
    (r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']?(\S+)["\']?', r'\1=[REDACTED_PASSWORD]'),

    # Bearer tokens
    (r'(?i)bearer\s+[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+', '[REDACTED_JWT]'),

    # AWS credentials
    (r'(?i)(aws[_-]?access[_-]?key[_-]?id)\s*[=:]\s*["\']?([A-Z0-9]{20})["\']?', r'\1=[REDACTED_AWS_KEY]'),
    (r'(?i)(aws[_-]?secret[_-]?access[_-]?key)\s*[=:]\s*["\']?([a-zA-Z0-9/+=]{40})["\']?', r'\1=[REDACTED_AWS_SECRET]'),

    # Private keys (PEM format markers)
    (r'-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |DSA )?PRIVATE KEY-----', '[REDACTED_PRIVATE_KEY]'),

    # Connection strings with passwords
    (r'(?i)(mysql|postgresql|postgres|mongodb|redis|amqp)://[^:]+:([^@]+)@', r'\1://[user]:[REDACTED_PASSWORD]@'),

    # Generic secret patterns
    (r'(?i)(secret|token|credential|auth)\s*[=:]\s*["\']?([a-zA-Z0-9_\-\.]{16,})["\']?', r'\1=[REDACTED]'),
]


class Redactor:
    """Redacts PII and secrets from text content."""

    def __init__(self):
        self.patterns: List[Tuple[Pattern, str]] = []
        self._load_patterns()
        self._stats: Dict[str, int] = {}

    def _load_patterns(self):
        """Load default patterns and any environment-configured patterns."""
        # Load default patterns
        for pattern_str, replacement in DEFAULT_PATTERNS:
            try:
                compiled = re.compile(pattern_str, re.IGNORECASE)
                self.patterns.append((compiled, replacement))
            except re.error as e:
                logger.warning(
                    "Failed to compile default redaction pattern",
                    pattern=pattern_str,
                    error=str(e)
                )

        # Load additional patterns from environment
        # Format: pattern1|replacement1;pattern2|replacement2
        env_patterns = os.environ.get('REDACTION_PATTERNS', '')
        if env_patterns:
            for item in env_patterns.split(';'):
                item = item.strip()
                if not item:
                    continue
                if '|' in item:
                    pattern_str, replacement = item.split('|', 1)
                    try:
                        compiled = re.compile(pattern_str.strip(), re.IGNORECASE)
                        self.patterns.append((compiled, replacement.strip()))
                        logger.info(
                            "Loaded custom redaction pattern",
                            pattern=pattern_str[:50]
                        )
                    except re.error as e:
                        logger.warning(
                            "Failed to compile custom redaction pattern",
                            pattern=pattern_str,
                            error=str(e)
                        )

        logger.info("Redactor initialized", pattern_count=len(self.patterns))

    def redact(self, text: str) -> str:
        """
        Apply all redaction patterns to text.

        Args:
            text: Text to redact

        Returns:
            Redacted text
        """
        if not text:
            return text

        result = text
        for pattern, replacement in self.patterns:
            result = pattern.sub(replacement, result)

        return result

    def redact_with_stats(self, text: str) -> Tuple[str, Dict[str, int]]:
        """
        Apply redaction and return statistics about what was redacted.

        Args:
            text: Text to redact

        Returns:
            Tuple of (redacted_text, stats_dict)
        """
        if not text:
            return text, {}

        stats: Dict[str, int] = {}
        result = text

        for pattern, replacement in self.patterns:
            matches = pattern.findall(result)
            if matches:
                count = len(matches)
                # Use replacement as key (cleaned up)
                key = replacement.strip('[]').lower()
                stats[key] = stats.get(key, 0) + count
                result = pattern.sub(replacement, result)

        return result, stats

    def add_pattern(self, pattern: str, replacement: str):
        """
        Add a new redaction pattern at runtime.

        Args:
            pattern: Regex pattern string
            replacement: Replacement text
        """
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            self.patterns.append((compiled, replacement))
            logger.info("Added redaction pattern", pattern=pattern[:50])
        except re.error as e:
            logger.error(
                "Failed to add redaction pattern",
                pattern=pattern,
                error=str(e)
            )
            raise ValueError(f"Invalid regex pattern: {e}")


# Global singleton instance
_redactor: Redactor = None


def get_redactor() -> Redactor:
    """Get the global Redactor instance."""
    global _redactor
    if _redactor is None:
        _redactor = Redactor()
    return _redactor


def redact(text: str) -> str:
    """
    Convenience function to redact text using the global redactor.

    Args:
        text: Text to redact

    Returns:
        Redacted text
    """
    return get_redactor().redact(text)


def redact_email_content(subject: str, body: str) -> Tuple[str, str]:
    """
    Redact both subject and body of an email.

    Args:
        subject: Email subject
        body: Email body

    Returns:
        Tuple of (redacted_subject, redacted_body)
    """
    redactor = get_redactor()
    return redactor.redact(subject), redactor.redact(body)
