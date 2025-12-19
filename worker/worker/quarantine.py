"""Quarantine management for low-confidence LLM extractions.

Events are quarantined when:
- LLM extraction confidence is below QUARANTINE_THRESHOLD (0.4)
- Pydantic validation fails
- Required fields are missing

Quarantined events require human review before being processed.
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog

from worker.database import get_pool
from worker.schemas import QuarantineAction, QuarantineReason

logger = structlog.get_logger()


async def quarantine_event(
    raw_email_id: UUID,
    extraction_data: Dict[str, Any],
    confidence: float,
    reason: QuarantineReason
) -> UUID:
    """
    Add an event to quarantine for human review.

    Args:
        raw_email_id: ID of the raw email
        extraction_data: LLM extraction result (may be partial/invalid)
        confidence: Confidence score from LLM
        reason: Reason for quarantine

    Returns:
        UUID of the quarantine record
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        quarantine_id = await conn.fetchval("""
            INSERT INTO quarantine_events
            (raw_email_id, extraction_data, confidence, quarantine_reason)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """, raw_email_id, json.dumps(extraction_data), confidence, reason.value)

        logger.info(
            "Event quarantined",
            quarantine_id=str(quarantine_id),
            email_id=str(raw_email_id),
            confidence=confidence,
            reason=reason.value
        )

        return quarantine_id


async def get_pending_quarantine(
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Get pending quarantine items for review.

    Args:
        limit: Maximum number of items to return
        offset: Offset for pagination

    Returns:
        List of quarantine records with email details
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                q.id,
                q.raw_email_id,
                q.extraction_data,
                q.confidence,
                q.quarantine_reason,
                q.created_at,
                e.subject,
                e.from_address,
                e.body_text
            FROM quarantine_events q
            JOIN raw_emails e ON e.id = q.raw_email_id
            WHERE q.reviewed_at IS NULL
            ORDER BY q.created_at ASC
            LIMIT $1 OFFSET $2
        """, limit, offset)

        return [
            {
                "id": str(row["id"]),
                "raw_email_id": str(row["raw_email_id"]),
                "extraction_data": json.loads(row["extraction_data"]) if row["extraction_data"] else {},
                "confidence": row["confidence"],
                "quarantine_reason": row["quarantine_reason"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "email": {
                    "subject": row["subject"],
                    "from_address": row["from_address"],
                    "body_preview": row["body_text"][:500] if row["body_text"] else None
                }
            }
            for row in rows
        ]


async def get_quarantine_count() -> int:
    """Get count of pending quarantine items."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        count = await conn.fetchval("""
            SELECT COUNT(*) FROM quarantine_events
            WHERE reviewed_at IS NULL
        """)
        return count


async def review_quarantined(
    quarantine_id: UUID,
    action: QuarantineAction,
    reviewer: str,
    edited_data: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Process a quarantine review decision.

    Args:
        quarantine_id: ID of the quarantine record
        action: Action taken (approved, rejected, edited)
        reviewer: Who reviewed the item
        edited_data: If action is 'edited', the corrected extraction data

    Returns:
        True if review was processed successfully
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Update quarantine record
            result = await conn.execute("""
                UPDATE quarantine_events
                SET reviewed_at = NOW(),
                    reviewed_by = $2,
                    action_taken = $3,
                    edited_data = $4
                WHERE id = $1 AND reviewed_at IS NULL
            """, quarantine_id, reviewer, action.value,
                json.dumps(edited_data) if edited_data else None)

            if result == "UPDATE 0":
                logger.warning(
                    "Quarantine item not found or already reviewed",
                    quarantine_id=str(quarantine_id)
                )
                return False

            # If approved or edited, re-process the event
            if action in (QuarantineAction.APPROVED, QuarantineAction.EDITED):
                quarantine_row = await conn.fetchrow("""
                    SELECT raw_email_id, extraction_data, edited_data
                    FROM quarantine_events
                    WHERE id = $1
                """, quarantine_id)

                if quarantine_row:
                    # Get the data to use (edited takes priority)
                    data_to_use = (
                        json.loads(quarantine_row["edited_data"])
                        if quarantine_row["edited_data"]
                        else json.loads(quarantine_row["extraction_data"])
                    )

                    # Queue for reprocessing
                    # This will be picked up by the normal processing pipeline
                    await conn.execute("""
                        UPDATE raw_emails
                        SET parse_status = 'pending',
                            parse_error = NULL,
                            processed_at = NULL
                        WHERE id = $1
                    """, quarantine_row["raw_email_id"])

                    logger.info(
                        "Quarantine item approved for reprocessing",
                        quarantine_id=str(quarantine_id),
                        email_id=str(quarantine_row["raw_email_id"]),
                        action=action.value
                    )

            elif action == QuarantineAction.REJECTED:
                # Mark email as permanently failed
                quarantine_row = await conn.fetchrow("""
                    SELECT raw_email_id FROM quarantine_events WHERE id = $1
                """, quarantine_id)

                if quarantine_row:
                    await conn.execute("""
                        UPDATE raw_emails
                        SET parse_status = 'rejected',
                            parse_error = 'Rejected during quarantine review'
                        WHERE id = $1
                    """, quarantine_row["raw_email_id"])

                    logger.info(
                        "Quarantine item rejected",
                        quarantine_id=str(quarantine_id),
                        email_id=str(quarantine_row["raw_email_id"])
                    )

            return True


async def get_quarantine_stats() -> Dict[str, Any]:
    """
    Get quarantine statistics.

    Returns:
        Dictionary with quarantine statistics
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        stats = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE reviewed_at IS NULL) as pending,
                COUNT(*) FILTER (WHERE action_taken = 'approved') as approved,
                COUNT(*) FILTER (WHERE action_taken = 'rejected') as rejected,
                COUNT(*) FILTER (WHERE action_taken = 'edited') as edited,
                AVG(confidence) FILTER (WHERE reviewed_at IS NULL) as avg_pending_confidence
            FROM quarantine_events
        """)

        by_reason = await conn.fetch("""
            SELECT quarantine_reason, COUNT(*) as count
            FROM quarantine_events
            WHERE reviewed_at IS NULL
            GROUP BY quarantine_reason
        """)

        return {
            "pending": stats["pending"] or 0,
            "approved": stats["approved"] or 0,
            "rejected": stats["rejected"] or 0,
            "edited": stats["edited"] or 0,
            "avg_pending_confidence": float(stats["avg_pending_confidence"]) if stats["avg_pending_confidence"] else 0.0,
            "by_reason": {row["quarantine_reason"]: row["count"] for row in by_reason}
        }


async def cleanup_old_quarantine(days: int = 30) -> int:
    """
    Clean up old reviewed quarantine records.

    Args:
        days: Delete reviewed records older than this many days

    Returns:
        Number of records deleted
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        result = await conn.execute("""
            DELETE FROM quarantine_events
            WHERE reviewed_at IS NOT NULL
              AND reviewed_at < NOW() - INTERVAL '%s days'
        """ % days)

        deleted = int(result.split()[-1])
        if deleted > 0:
            logger.info("Cleaned up old quarantine records", deleted=deleted)

        return deleted
