-- =============================================================================
-- NGS (NoiseGate Service) - Initial Schema Migration
-- =============================================================================
-- Version: 001
-- Description: Core tables for alert ingestion, correlation, and incident management
-- =============================================================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- ENUM TYPES
-- =============================================================================

CREATE TYPE severity_level AS ENUM ('critical', 'high', 'medium', 'low', 'info');
CREATE TYPE incident_status AS ENUM ('open', 'acknowledged', 'resolved', 'suppressed');
CREATE TYPE alert_state AS ENUM ('firing', 'resolved', 'unknown');
CREATE TYPE suppress_mode AS ENUM ('mute', 'downgrade', 'digest');
CREATE TYPE maintenance_source AS ENUM ('email', 'manual', 'graph');
CREATE TYPE user_role AS ENUM ('viewer', 'operator', 'admin');

-- =============================================================================
-- USERS & AUTHENTICATION
-- =============================================================================

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),
    role user_role NOT NULL DEFAULT 'viewer',
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_username ON users(username);

-- =============================================================================
-- RAW EMAIL STORAGE (Immutable Audit Trail)
-- =============================================================================

CREATE TABLE raw_emails (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    folder VARCHAR(255) NOT NULL,
    uid BIGINT NOT NULL,
    message_id VARCHAR(512),
    subject TEXT,
    from_address VARCHAR(512),
    to_addresses TEXT[],
    cc_addresses TEXT[],
    date_header TIMESTAMPTZ,
    headers JSONB NOT NULL DEFAULT '{}',
    body_text TEXT,
    body_html TEXT,
    raw_mime BYTEA,
    ics_content TEXT,
    attachments JSONB DEFAULT '[]',
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    parse_status VARCHAR(50) NOT NULL DEFAULT 'pending',
    parse_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT unique_folder_uid UNIQUE (folder, uid)
);

CREATE INDEX idx_raw_emails_folder ON raw_emails(folder);
CREATE INDEX idx_raw_emails_message_id ON raw_emails(message_id);
CREATE INDEX idx_raw_emails_parse_status ON raw_emails(parse_status);
CREATE INDEX idx_raw_emails_received_at ON raw_emails(received_at DESC);
CREATE INDEX idx_raw_emails_date_header ON raw_emails(date_header DESC);

-- =============================================================================
-- FOLDER CURSORS (IMAP Polling State)
-- =============================================================================

CREATE TABLE folder_cursors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    folder VARCHAR(255) NOT NULL UNIQUE,
    last_uid BIGINT NOT NULL DEFAULT 0,
    last_poll_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_error TEXT,
    error_count INT NOT NULL DEFAULT 0,
    emails_processed BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_folder_cursors_folder ON folder_cursors(folder);

-- =============================================================================
-- ALERT EVENTS (Normalized from Raw Emails)
-- =============================================================================

CREATE TABLE alert_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_email_id UUID REFERENCES raw_emails(id) ON DELETE SET NULL,
    source_tool VARCHAR(100) NOT NULL,
    environment VARCHAR(100),
    region VARCHAR(100),
    host VARCHAR(255),
    check_name VARCHAR(255),
    service VARCHAR(255),
    severity severity_level NOT NULL DEFAULT 'medium',
    state alert_state NOT NULL DEFAULT 'firing',
    occurred_at TIMESTAMPTZ NOT NULL,
    normalized_signature TEXT NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    is_suppressed BOOLEAN NOT NULL DEFAULT false,
    suppression_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_alert_events_fingerprint ON alert_events(fingerprint);
CREATE INDEX idx_alert_events_source_tool ON alert_events(source_tool);
CREATE INDEX idx_alert_events_host ON alert_events(host);
CREATE INDEX idx_alert_events_check_name ON alert_events(check_name);
CREATE INDEX idx_alert_events_severity ON alert_events(severity);
CREATE INDEX idx_alert_events_state ON alert_events(state);
CREATE INDEX idx_alert_events_occurred_at ON alert_events(occurred_at DESC);
CREATE INDEX idx_alert_events_created_at ON alert_events(created_at DESC);
CREATE INDEX idx_alert_events_tags ON alert_events USING GIN(tags);

-- =============================================================================
-- INCIDENTS (Correlated Alert Clusters)
-- =============================================================================

CREATE TABLE incidents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    fingerprint VARCHAR(64) NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    source_tool VARCHAR(100),
    environment VARCHAR(100),
    region VARCHAR(100),
    host VARCHAR(255),
    check_name VARCHAR(255),
    service VARCHAR(255),
    severity severity_level NOT NULL DEFAULT 'medium',
    status incident_status NOT NULL DEFAULT 'open',
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by UUID REFERENCES users(id),
    resolved_by UUID REFERENCES users(id),
    event_count INT NOT NULL DEFAULT 1,
    tags TEXT[] DEFAULT '{}',
    labels JSONB DEFAULT '{}',
    owner_team VARCHAR(255),
    assigned_to UUID REFERENCES users(id),

    -- AI Enrichment Fields
    ai_summary TEXT,
    ai_category VARCHAR(255),
    ai_owner_team VARCHAR(255),
    ai_recommended_checks JSONB DEFAULT '[]',
    ai_suggested_runbooks JSONB DEFAULT '[]',
    ai_safe_actions JSONB DEFAULT '[]',
    ai_confidence DECIMAL(3,2),
    ai_evidence JSONB DEFAULT '[]',
    ai_enriched_at TIMESTAMPTZ,
    ai_labels JSONB DEFAULT '{}',

    -- Maintenance
    is_in_maintenance BOOLEAN NOT NULL DEFAULT false,
    maintenance_window_id UUID,

    -- Flap Detection
    flap_count INT NOT NULL DEFAULT 0,
    last_state_change_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Only one open incident per fingerprint
CREATE UNIQUE INDEX idx_incidents_fingerprint_open
    ON incidents(fingerprint)
    WHERE status IN ('open', 'acknowledged');

CREATE INDEX idx_incidents_status ON incidents(status);
CREATE INDEX idx_incidents_severity ON incidents(severity);
CREATE INDEX idx_incidents_source_tool ON incidents(source_tool);
CREATE INDEX idx_incidents_host ON incidents(host);
CREATE INDEX idx_incidents_first_seen ON incidents(first_seen_at DESC);
CREATE INDEX idx_incidents_last_seen ON incidents(last_seen_at DESC);
CREATE INDEX idx_incidents_tags ON incidents USING GIN(tags);
CREATE INDEX idx_incidents_labels ON incidents USING GIN(labels);
CREATE INDEX idx_incidents_maintenance ON incidents(is_in_maintenance) WHERE is_in_maintenance = true;

-- =============================================================================
-- INCIDENT EVENTS (Join Table)
-- =============================================================================

CREATE TABLE incident_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    alert_event_id UUID NOT NULL REFERENCES alert_events(id) ON DELETE CASCADE,
    is_deduplicated BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT unique_incident_event UNIQUE (incident_id, alert_event_id)
);

CREATE INDEX idx_incident_events_incident ON incident_events(incident_id);
CREATE INDEX idx_incident_events_alert ON incident_events(alert_event_id);

-- =============================================================================
-- INCIDENT COMMENTS
-- =============================================================================

CREATE TABLE incident_comments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id),
    content TEXT NOT NULL,
    is_system_generated BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_incident_comments_incident ON incident_comments(incident_id);
CREATE INDEX idx_incident_comments_created ON incident_comments(created_at DESC);

-- =============================================================================
-- AUDIT LOG
-- =============================================================================

CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    entity_id UUID,
    old_value JSONB,
    new_value JSONB,
    metadata JSONB DEFAULT '{}',
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_log_user ON audit_log(user_id);
CREATE INDEX idx_audit_log_action ON audit_log(action);
CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_log_created ON audit_log(created_at DESC);

-- =============================================================================
-- SUPPRESSION RULES
-- =============================================================================

CREATE TABLE suppression_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    scope JSONB NOT NULL DEFAULT '{}',
    suppress_mode suppress_mode NOT NULL DEFAULT 'mute',
    reason TEXT,
    start_at TIMESTAMPTZ,
    end_at TIMESTAMPTZ,
    is_permanent BOOLEAN NOT NULL DEFAULT false,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_suppression_rules_active ON suppression_rules(is_active) WHERE is_active = true;
CREATE INDEX idx_suppression_rules_dates ON suppression_rules(start_at, end_at);

-- =============================================================================
-- MAINTENANCE WINDOWS
-- =============================================================================

CREATE TABLE maintenance_windows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source maintenance_source NOT NULL DEFAULT 'manual',
    external_event_id VARCHAR(512),
    raw_email_id UUID REFERENCES raw_emails(id),
    title VARCHAR(500) NOT NULL,
    description TEXT,
    organizer VARCHAR(255),
    organizer_email VARCHAR(255),
    start_ts TIMESTAMPTZ NOT NULL,
    end_ts TIMESTAMPTZ NOT NULL,
    timezone VARCHAR(100) DEFAULT 'UTC',
    is_recurring BOOLEAN NOT NULL DEFAULT false,
    recurrence_rule TEXT,
    scope JSONB NOT NULL DEFAULT '{}',
    suppress_mode suppress_mode NOT NULL DEFAULT 'mute',
    reason TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT unique_external_event UNIQUE (source, external_event_id)
);

COMMENT ON COLUMN maintenance_windows.scope IS 'JSON object with keys: hosts (array/regex), services (array/regex), tags (array), environments (array), regions (array)';

CREATE INDEX idx_maintenance_windows_active ON maintenance_windows(is_active) WHERE is_active = true;
CREATE INDEX idx_maintenance_windows_dates ON maintenance_windows(start_ts, end_ts);
CREATE INDEX idx_maintenance_windows_source ON maintenance_windows(source);
CREATE INDEX idx_maintenance_windows_external ON maintenance_windows(external_event_id) WHERE external_event_id IS NOT NULL;

-- =============================================================================
-- MAINTENANCE MATCHES (Explainability)
-- =============================================================================

CREATE TABLE maintenance_matches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    maintenance_window_id UUID NOT NULL REFERENCES maintenance_windows(id) ON DELETE CASCADE,
    incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
    alert_event_id UUID REFERENCES alert_events(id) ON DELETE CASCADE,
    match_reason JSONB NOT NULL DEFAULT '{}',
    matched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT check_entity_present CHECK (incident_id IS NOT NULL OR alert_event_id IS NOT NULL)
);

COMMENT ON COLUMN maintenance_matches.match_reason IS 'JSON explaining why this matched: {field: "host", pattern: "cmts-*", value: "cmts-01"}';

CREATE INDEX idx_maintenance_matches_window ON maintenance_matches(maintenance_window_id);
CREATE INDEX idx_maintenance_matches_incident ON maintenance_matches(incident_id) WHERE incident_id IS NOT NULL;
CREATE INDEX idx_maintenance_matches_event ON maintenance_matches(alert_event_id) WHERE alert_event_id IS NOT NULL;

-- =============================================================================
-- PROPOSED ACTIONS (Future Self-Healing Placeholder)
-- =============================================================================

CREATE TABLE proposed_actions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    action_type VARCHAR(100) NOT NULL,
    action_name VARCHAR(255) NOT NULL,
    description TEXT,
    payload JSONB NOT NULL DEFAULT '{}',
    is_safe BOOLEAN NOT NULL DEFAULT false,
    requires_approval BOOLEAN NOT NULL DEFAULT true,
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ,
    execution_result JSONB,
    status VARCHAR(50) NOT NULL DEFAULT 'proposed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE proposed_actions IS 'Placeholder for future self-healing. Actions are proposed but NOT executed in PoC.';

CREATE INDEX idx_proposed_actions_incident ON proposed_actions(incident_id);
CREATE INDEX idx_proposed_actions_status ON proposed_actions(status);

-- =============================================================================
-- CONFIGURATION SNAPSHOTS (For Audit)
-- =============================================================================

CREATE TABLE config_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    config_type VARCHAR(100) NOT NULL,
    config_name VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    uploaded_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_config_snapshots_type ON config_snapshots(config_type);
CREATE INDEX idx_config_snapshots_created ON config_snapshots(created_at DESC);

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply updated_at triggers
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_folder_cursors_updated_at BEFORE UPDATE ON folder_cursors
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_incidents_updated_at BEFORE UPDATE ON incidents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_incident_comments_updated_at BEFORE UPDATE ON incident_comments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_suppression_rules_updated_at BEFORE UPDATE ON suppression_rules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_maintenance_windows_updated_at BEFORE UPDATE ON maintenance_windows
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- SEED DATA
-- =============================================================================

-- Default admin user (password: admin123 - CHANGE IN PRODUCTION)
INSERT INTO users (username, email, password_hash, display_name, role) VALUES
    ('admin', 'admin@ngs.local', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.Hv.p.0Q5q0zJwG', 'NGS Admin', 'admin');

-- =============================================================================
-- METRICS VIEWS
-- =============================================================================

CREATE VIEW v_incident_metrics AS
SELECT
    date_trunc('hour', created_at) as hour,
    status,
    severity,
    source_tool,
    COUNT(*) as count
FROM incidents
GROUP BY 1, 2, 3, 4;

CREATE VIEW v_ingestion_metrics AS
SELECT
    folder,
    last_poll_at,
    last_success_at,
    emails_processed,
    error_count,
    last_error
FROM folder_cursors;
