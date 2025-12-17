"""Database connection for worker."""
from typing import Optional

import asyncpg
import structlog

from worker.config import get_settings

logger = structlog.get_logger()

_pool: Optional[asyncpg.Pool] = None


async def init_db() -> asyncpg.Pool:
    """Initialize the database connection pool."""
    global _pool
    settings = get_settings()

    logger.info("Initializing database connection pool")

    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=2,
        max_size=10,
        command_timeout=60,
    )

    logger.info("Database connection pool initialized")
    return _pool


async def close_db():
    """Close the database connection pool."""
    global _pool
    if _pool:
        logger.info("Closing database connection pool")
        await _pool.close()
        _pool = None


async def get_pool() -> asyncpg.Pool:
    """Get the database connection pool."""
    global _pool
    if _pool is None:
        _pool = await init_db()
    return _pool
