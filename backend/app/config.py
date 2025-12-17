"""Application configuration using Pydantic Settings."""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "postgresql://ngs:ngs@localhost:5432/ngs"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # RAG Integration
    rag_endpoint: str = "http://localhost:8080/enrich"
    rag_enabled: bool = True
    rag_timeout_seconds: int = 30

    # JWT Authentication
    jwt_secret: str = "dev_jwt_secret_change_in_production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24 hours

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # Retention
    raw_email_retention_days: int = 90
    incident_retention_days: int = 365
    audit_log_retention_days: int = 365

    # Redaction
    redaction_patterns: str = ""

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def redaction_patterns_list(self) -> List[str]:
        """Parse redaction patterns from comma-separated string."""
        if not self.redaction_patterns:
            return []
        return [p.strip() for p in self.redaction_patterns.split(",") if p.strip()]

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
