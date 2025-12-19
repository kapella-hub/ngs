"""Database connection and pool management."""
import json
from typing import Optional

import asyncpg
import structlog

from app.config import get_settings

logger = structlog.get_logger()

_pool: Optional[asyncpg.Pool] = None


async def _init_connection(conn: asyncpg.Connection):
    """Initialize connection with JSON codec."""
    await conn.set_type_codec(
        'jsonb',
        encoder=json.dumps,
        decoder=json.loads,
        schema='pg_catalog'
    )
    await conn.set_type_codec(
        'json',
        encoder=json.dumps,
        decoder=json.loads,
        schema='pg_catalog'
    )


async def init_db() -> asyncpg.Pool:
    """Initialize the database connection pool."""
    global _pool
    settings = get_settings()

    logger.info("Initializing database connection pool")

    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=5,
        max_size=20,
        command_timeout=60,
        init=_init_connection,
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


async def get_db_pool() -> asyncpg.Pool:
    """Get the database connection pool."""
    global _pool
    if _pool is None:
        _pool = await init_db()
    return _pool


async def get_db_connection():
    """Dependency to get a database connection."""
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        yield connection
