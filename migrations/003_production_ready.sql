-- Migration 003: Production-Ready Refactor
-- P0/P1 requirements for correlation correctness, LLM safety, and operational reliability

-- ============================================================================
-- P0: Add 'resolving' state to incident_status enum
-- ============================================================================

-- Add 'resolving' to incident_status enum (for resolution state machine)
-- PostgreSQL ALTER TYPE ADD VALUE cannot be used in a transaction
-- Run this separately if needed:
-- ALTER TYPE incident_status ADD VALUE IF NOT EXISTS 'resolving' BEFORE 'resolved';

-- ============================================================================
-- P0: Fingerprint v2 and Severity Tracking
-- ============================================================================

-- Add fingerprint_v2 to alert_events (excludes severity for stable correlation)
ALTER TABLE alert_events ADD COLUMN IF NOT EXISTS fingerprint_v2 VARCHAR(32);

-- Add fingerprint_v2 and severity tracking to incidents
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS fingerprint_v2 VARCHAR(32);
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS severity_current VARCHAR(20);
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS severity_max VARCHAR(20);
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS last_state VARCHAR(20);
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS resolution_reason VARCHAR(50);

-- ============================================================================
-- P0: Quarantine for Low-Confidence Extractions
-- ============================================================================

CREATE TABLE IF NOT EXISTS quarantine_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_email_id UUID REFERENCES raw_emails(id) ON DELETE CASCADE,
    extraction_data JSONB,
    confidence FLOAT,
    quarantine_reason VARCHAR(100),
    reviewed_at TIMESTAMPTZ,
    reviewed_by VARCHAR(100),
    action_taken VARCHAR(50),  -- 'approved', 'rejected', 'edited'
    edited_data JSONB,         -- If edited, store corrected data
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE quarantine_events IS 'Events quarantined for human review due to low LLM confidence or validation failures';

-- ============================================================================
-- P1: Dead-Letter Queue for Failed Processing
-- ============================================================================

CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    error_message TEXT,
    error_traceback TEXT,
    retry_count INT DEFAULT 0,
    max_retries INT DEFAULT 3,
    last_retry_at TIMESTAMPTZ,
    next_retry_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'retrying', 'failed', 'resolved'
    resolved_at TIMESTAMPTZ,
    resolved_by VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE dead_letter_queue IS 'Failed events for retry or manual resolution';

-- ============================================================================
-- P1: Idempotency Keys for Retry-Safe Processing
-- ============================================================================

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key VARCHAR(64) PRIMARY KEY,
    result JSONB,
    status VARCHAR(20) DEFAULT 'completed',  -- 'processing', 'completed', 'failed'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '24 hours'
);

COMMENT ON TABLE idempotency_keys IS 'Idempotency keys for exactly-once processing semantics';

-- ============================================================================
-- P1: Config Versioning
-- ============================================================================

CREATE TABLE IF NOT EXISTS config_versions (
    id SERIAL PRIMARY KEY,
    config_type VARCHAR(50) NOT NULL,  -- 'parsers', 'redaction', 'notifications', etc.
    config_hash VARCHAR(64) NOT NULL,
    config_data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(100),
    is_active BOOLEAN DEFAULT FALSE,
    activated_at TIMESTAMPTZ,
    deactivated_at TIMESTAMPTZ,
    notes TEXT
);

COMMENT ON TABLE config_versions IS 'Versioned configuration with rollback support';

-- ============================================================================
-- P1: Notification Channels and Logging
-- ============================================================================

CREATE TABLE IF NOT EXISTS notification_channels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    channel_type VARCHAR(20) NOT NULL,  -- 'slack', 'webhook', 'email', 'pagerduty'
    config JSONB NOT NULL,              -- Channel-specific config (webhook_url, etc.)
    severity_filter VARCHAR(20)[],      -- Only notify for these severities
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE notification_channels IS 'Configured notification channels (Slack, webhook, etc.)';

CREATE TABLE IF NOT EXISTS notification_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id UUID REFERENCES notification_channels(id) ON DELETE CASCADE,
    incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
    notification_type VARCHAR(50) NOT NULL,  -- 'immediate', 'digest'
    priority INT DEFAULT 0,                   -- Higher = more urgent
    payload JSONB NOT NULL,
    scheduled_for TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE notification_queue IS 'Queue for batched/digest notifications';

CREATE TABLE IF NOT EXISTS notification_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id UUID REFERENCES notification_channels(id) ON DELETE SET NULL,
    incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,
    notification_type VARCHAR(50) NOT NULL,
    payload JSONB,
    sent_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL,  -- 'pending', 'sent', 'failed'
    error_message TEXT,
    retry_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE notification_log IS 'Log of all notification attempts';

-- ============================================================================
-- Indexes for Performance
-- ============================================================================

-- Quarantine indexes
CREATE INDEX IF NOT EXISTS idx_quarantine_pending
    ON quarantine_events(created_at)
    WHERE reviewed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_quarantine_by_email
    ON quarantine_events(raw_email_id);

-- Dead-letter queue indexes
CREATE INDEX IF NOT EXISTS idx_dlq_pending
    ON dead_letter_queue(next_retry_at, retry_count)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_dlq_status
    ON dead_letter_queue(status, created_at);

-- Idempotency indexes
CREATE INDEX IF NOT EXISTS idx_idempotency_expires
    ON idempotency_keys(expires_at);

-- Fingerprint v2 indexes
CREATE INDEX IF NOT EXISTS idx_events_fingerprint_v2
    ON alert_events(fingerprint_v2);

CREATE INDEX IF NOT EXISTS idx_incidents_fingerprint_v2
    ON incidents(fingerprint_v2)
    WHERE status != 'resolved';

-- Partial unique index for open incidents by fingerprint_v2
CREATE UNIQUE INDEX IF NOT EXISTS idx_incidents_fingerprint_v2_open
    ON incidents(fingerprint_v2)
    WHERE status = 'open';

-- Config versioning indexes
CREATE INDEX IF NOT EXISTS idx_config_active
    ON config_versions(config_type)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_config_history
    ON config_versions(config_type, created_at DESC);

-- Notification indexes
CREATE INDEX IF NOT EXISTS idx_notification_queue_scheduled
    ON notification_queue(scheduled_for)
    WHERE scheduled_for IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_notification_log_incident
    ON notification_log(incident_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_notification_log_status
    ON notification_log(status, created_at)
    WHERE status = 'failed';

-- ============================================================================
-- Functions for Cleanup/Maintenance
-- ============================================================================

-- Function to clean up expired idempotency keys
CREATE OR REPLACE FUNCTION cleanup_expired_idempotency_keys()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM idempotency_keys WHERE expires_at < NOW();
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Function to process DLQ items ready for retry
CREATE OR REPLACE FUNCTION get_dlq_items_for_retry(batch_size INTEGER DEFAULT 10)
RETURNS TABLE (
    id UUID,
    event_type VARCHAR(50),
    payload JSONB,
    retry_count INT
) AS $$
BEGIN
    RETURN QUERY
    UPDATE dead_letter_queue d
    SET status = 'retrying',
        last_retry_at = NOW(),
        retry_count = d.retry_count + 1
    WHERE d.id IN (
        SELECT dlq.id
        FROM dead_letter_queue dlq
        WHERE dlq.status = 'pending'
          AND (dlq.next_retry_at IS NULL OR dlq.next_retry_at <= NOW())
          AND dlq.retry_count < dlq.max_retries
        ORDER BY dlq.created_at
        LIMIT batch_size
        FOR UPDATE SKIP LOCKED
    )
    RETURNING d.id, d.event_type, d.payload, d.retry_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Backfill fingerprint_v2 (to be run after migration via Python script)
-- This is a placeholder comment - actual backfill done in Python for complex logic
-- ============================================================================

-- The fingerprint_v2 backfill requires:
-- 1. Reading each incident's associated events
-- 2. Recomputing fingerprint using the v2 algorithm (excluding severity)
-- 3. Updating both incidents and alert_events tables
--
-- This is handled by: worker/worker/fingerprint.py:backfill_fingerprint_v2()
