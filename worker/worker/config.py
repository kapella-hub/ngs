"""Worker configuration."""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings


class WorkerSettings(BaseSettings):
    """Worker settings from environment."""

    # Database
    database_url: str = "postgresql://ngs:ngs@localhost:5432/ngs"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Email Provider: "imap" or "graph"
    email_provider: str = "imap"

    # IMAP Configuration (when email_provider=imap)
    imap_host: str = ""
    imap_port: int = 993
    imap_ssl: bool = True
    imap_user: str = ""
    imap_password: str = ""
    imap_folders: str = "INBOX"
    imap_poll_interval_seconds: int = 60
    imap_initial_backfill_days: int = 7

    # Microsoft Graph Configuration (when email_provider=graph)
    # For Office 365 / Outlook with OAuth 2.0
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""
    graph_user_email: str = ""  # The mailbox to read from

    # File-based Configuration (when email_provider=file)
    # For local testing - watch a folder for .eml/.msg files
    file_watch_path: str = "./watch"

    # Outlook COM Configuration (when email_provider=outlook)
    # For Windows local testing - read directly from Outlook desktop
    outlook_folders: str = "Inbox"  # Comma-separated Outlook folder names

    # RAG Integration
    rag_endpoint: str = "http://localhost:8080/enrich"
    rag_enabled: bool = True
    rag_timeout_seconds: int = 30

    # Logging
    log_level: str = "INFO"

    # Correlation settings
    dedupe_window_minutes: int = 10
    flap_quiet_time_minutes: int = 30
    incident_auto_resolve_hours: int = 24

    # Redaction
    redaction_patterns: str = ""

    # Retention
    raw_email_retention_days: int = 90

    @property
    def imap_folders_list(self) -> List[str]:
        """Parse IMAP folders from comma-separated string."""
        return [f.strip() for f in self.imap_folders.split(",") if f.strip()]

    @property
    def redaction_patterns_list(self) -> List[str]:
        """Parse redaction patterns."""
        if not self.redaction_patterns:
            return []
        return [p.strip() for p in self.redaction_patterns.split(",") if p.strip()]

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> WorkerSettings:
    """Get cached settings."""
    return WorkerSettings()
