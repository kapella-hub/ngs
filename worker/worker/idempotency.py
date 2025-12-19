"""Idempotency and retry-safe processing with dead-letter queue.

This module provides:
- Idempotency keys for exactly-once processing semantics
- Dead-letter queue for failed operations
- Retry logic with exponential backoff
"""
import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar
from uuid import UUID

import structlog

from worker.database import get_pool

logger = structlog.get_logger()

T = TypeVar('T')


def compute_idempotency_key(email_id: str, message_id: str) -> str:
    """
    Compute a stable idempotency key for email processing.

    Args:
        email_id: Raw email ID
        message_id: Message-ID header from email

    Returns:
        32-character hex idempotency key
    """
    combined = f"{email_id}:{message_id}"
    return hashlib.sha256(combined.encode()).hexdigest()[:32]


async def check_idempotency(key: str) -> Optional[Dict[str, Any]]:
    """
    Check if an operation has already been completed.

    Args:
        key: Idempotency key

    Returns:
        Cached result if exists and not expired, None otherwise
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT result, status
            FROM idempotency_keys
            WHERE key = $1 AND expires_at > NOW()
        """, key)

        if row:
            if row["status"] == "completed":
                return json.loads(row["result"]) if row["result"] else None
            elif row["status"] == "processing":
                # Another worker is processing this
                logger.info("Idempotency key in processing state", key=key[:16])
                return {"_status": "processing"}

        return None


async def with_idempotency(
    key: str,
    operation: Callable[[], Awaitable[T]],
    ttl_hours: int = 24
) -> T:
    """
    Execute an operation with idempotency guarantees.

    If the key exists, returns the cached result.
    If not, executes the operation and caches the result.

    Args:
        key: Idempotency key
        operation: Async function to execute
        ttl_hours: How long to keep the result

    Returns:
        Result of the operation (cached or fresh)
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        # Try to acquire the key
        try:
            await conn.execute("""
                INSERT INTO idempotency_keys (key, status, expires_at)
                VALUES ($1, 'processing', NOW() + INTERVAL '%s hours')
                ON CONFLICT (key) DO NOTHING
            """ % ttl_hours, key)
        except Exception:
            pass  # Key may already exist

        # Check if we got the lock or if result exists
        existing = await conn.fetchrow("""
            SELECT result, status FROM idempotency_keys
            WHERE key = $1
        """, key)

        if existing and existing["status"] == "completed" and existing["result"]:
            logger.debug("Returning cached result", key=key[:16])
            return json.loads(existing["result"])

        # Execute the operation
        try:
            result = await operation()

            # Store the result
            await conn.execute("""
                UPDATE idempotency_keys
                SET result = $2, status = 'completed'
                WHERE key = $1
            """, key, json.dumps(result) if result is not None else None)

            return result

        except Exception as e:
            # Mark as failed
            await conn.execute("""
                UPDATE idempotency_keys
                SET status = 'failed'
                WHERE key = $1
            """, key)
            raise


async def add_to_dlq(
    event_type: str,
    payload: Dict[str, Any],
    error: str,
    traceback: Optional[str] = None,
    max_retries: int = 3
) -> UUID:
    """
    Add a failed event to the dead-letter queue.

    Args:
        event_type: Type of event that failed
        payload: Event payload
        error: Error message
        traceback: Full error traceback
        max_retries: Maximum retry attempts

    Returns:
        UUID of the DLQ record
    """
    pool = await get_pool()

    # Calculate next retry time with exponential backoff (start at 1 minute)
    next_retry = datetime.utcnow() + timedelta(minutes=1)

    async with pool.acquire() as conn:
        dlq_id = await conn.fetchval("""
            INSERT INTO dead_letter_queue
            (event_type, payload, error_message, error_traceback, max_retries, next_retry_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """, event_type, json.dumps(payload), error, traceback, max_retries, next_retry)

        logger.warning(
            "Event added to dead-letter queue",
            dlq_id=str(dlq_id),
            event_type=event_type,
            error=error[:200]
        )

        return dlq_id


async def get_dlq_items_for_retry(batch_size: int = 10) -> List[Dict[str, Any]]:
    """
    Get DLQ items ready for retry.

    Args:
        batch_size: Maximum items to return

    Returns:
        List of DLQ items ready for retry
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            UPDATE dead_letter_queue
            SET status = 'retrying',
                last_retry_at = NOW(),
                retry_count = retry_count + 1
            WHERE id IN (
                SELECT id FROM dead_letter_queue
                WHERE status = 'pending'
                  AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                  AND retry_count < max_retries
                ORDER BY created_at
                LIMIT $1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, event_type, payload, retry_count
        """, batch_size)

        return [
            {
                "id": str(row["id"]),
                "event_type": row["event_type"],
                "payload": json.loads(row["payload"]),
                "retry_count": row["retry_count"]
            }
            for row in rows
        ]


async def mark_dlq_success(dlq_id: UUID) -> bool:
    """
    Mark a DLQ item as successfully processed.

    Args:
        dlq_id: DLQ record ID

    Returns:
        True if updated
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE dead_letter_queue
            SET status = 'resolved',
                resolved_at = NOW()
            WHERE id = $1
        """, dlq_id)

        success = result == "UPDATE 1"
        if success:
            logger.info("DLQ item resolved", dlq_id=str(dlq_id))

        return success


async def mark_dlq_failed(dlq_id: UUID, error: str) -> bool:
    """
    Mark a DLQ item as failed (will be retried or marked permanently failed).

    Args:
        dlq_id: DLQ record ID
        error: Error message from retry attempt

    Returns:
        True if updated
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        # Get current retry count
        row = await conn.fetchrow("""
            SELECT retry_count, max_retries FROM dead_letter_queue WHERE id = $1
        """, dlq_id)

        if not row:
            return False

        if row["retry_count"] >= row["max_retries"]:
            # Mark as permanently failed
            status = "failed"
            next_retry = None
        else:
            # Schedule next retry with exponential backoff
            status = "pending"
            backoff_minutes = 2 ** row["retry_count"]  # 1, 2, 4, 8, 16...
            next_retry = datetime.utcnow() + timedelta(minutes=backoff_minutes)

        result = await conn.execute("""
            UPDATE dead_letter_queue
            SET status = $2,
                error_message = $3,
                next_retry_at = $4
            WHERE id = $1
        """, dlq_id, status, error, next_retry)

        if status == "failed":
            logger.error(
                "DLQ item permanently failed",
                dlq_id=str(dlq_id),
                error=error[:200]
            )
        else:
            logger.info(
                "DLQ item scheduled for retry",
                dlq_id=str(dlq_id),
                next_retry=next_retry.isoformat() if next_retry else None
            )

        return result == "UPDATE 1"


async def get_dlq_stats() -> Dict[str, Any]:
    """
    Get dead-letter queue statistics.

    Returns:
        Dictionary with DLQ statistics
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        stats = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'pending') as pending,
                COUNT(*) FILTER (WHERE status = 'retrying') as retrying,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                COUNT(*) FILTER (WHERE status = 'resolved') as resolved
            FROM dead_letter_queue
        """)

        by_type = await conn.fetch("""
            SELECT event_type, COUNT(*) as count
            FROM dead_letter_queue
            WHERE status IN ('pending', 'retrying')
            GROUP BY event_type
        """)

        return {
            "pending": stats["pending"] or 0,
            "retrying": stats["retrying"] or 0,
            "failed": stats["failed"] or 0,
            "resolved": stats["resolved"] or 0,
            "by_type": {row["event_type"]: row["count"] for row in by_type}
        }


async def cleanup_expired_idempotency_keys() -> int:
    """
    Clean up expired idempotency keys.

    Returns:
        Number of keys deleted
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        result = await conn.execute("""
            DELETE FROM idempotency_keys WHERE expires_at < NOW()
        """)

        deleted = int(result.split()[-1])
        if deleted > 0:
            logger.info("Cleaned up expired idempotency keys", deleted=deleted)

        return deleted


async def cleanup_old_dlq(days: int = 30) -> int:
    """
    Clean up old resolved/failed DLQ items.

    Args:
        days: Delete items older than this many days

    Returns:
        Number of items deleted
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        result = await conn.execute("""
            DELETE FROM dead_letter_queue
            WHERE status IN ('resolved', 'failed')
              AND created_at < NOW() - INTERVAL '%s days'
        """ % days)

        deleted = int(result.split()[-1])
        if deleted > 0:
            logger.info("Cleaned up old DLQ items", deleted=deleted)

        return deleted
