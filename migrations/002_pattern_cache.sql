-- =============================================================================
-- NGS (NoiseGate Service) - Pattern Cache Migration
-- =============================================================================
-- Version: 002
-- Description: Learning parser pattern cache for AI-assisted email parsing
-- =============================================================================

-- =============================================================================
-- PATTERN CACHE (Learned extraction patterns)
-- =============================================================================
-- Stores learned extraction patterns from LLM analysis
-- When a new email format is encountered, LLM extracts fields AND generates
-- extraction rules. These rules are cached and reused for similar emails.

CREATE TABLE pattern_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Signature fields for matching incoming emails
    signature_hash VARCHAR(64) NOT NULL UNIQUE,  -- SHA256 of signature components
    from_domain VARCHAR(255),                     -- e.g., "xymon-alerts.company.com"
    subject_prefix VARCHAR(255),                  -- First N chars or pattern, e.g., "Xymon ["
    subject_pattern VARCHAR(512),                 -- Detected pattern structure
    body_markers TEXT[],                          -- Key phrases found in body

    -- Source identification
    source_name VARCHAR(100) NOT NULL,           -- e.g., "Xymon", "Business Service Alert"
    source_tool VARCHAR(100),                    -- Normalized tool name for incidents

    -- Extraction rules (JSON structure)
    extraction_rules JSONB NOT NULL,
    -- Example:
    -- {
    --   "host": {"source": "subject", "regex": "...", "group": 1},
    --   "service": {"source": "subject", "regex": "...", "group": 1},
    --   "severity": {"source": "body", "regex": "...", "map": {"RED": "critical"}},
    --   "state": {"source": "subject", "keywords": {"CRITICAL": "firing", "recovered": "resolved"}}
    -- }

    -- LLM analysis metadata
    llm_model VARCHAR(100),                      -- Model used for analysis
    llm_prompt_tokens INT,                       -- Tokens used in prompt
    llm_completion_tokens INT,                   -- Tokens in response
    analysis_duration_ms INT,                    -- How long LLM took

    -- Usage statistics
    match_count INT NOT NULL DEFAULT 0,          -- How many emails matched this pattern
    last_matched_at TIMESTAMPTZ,                 -- Last time pattern was used
    success_rate DECIMAL(5,2) DEFAULT 100.00,    -- % of successful extractions

    -- Review/approval status
    is_approved BOOLEAN NOT NULL DEFAULT false,  -- Human-reviewed and approved
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMPTZ,

    -- Audit fields
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_from_email_id UUID REFERENCES raw_emails(id)  -- Email that triggered learning
);

CREATE INDEX idx_pattern_cache_signature ON pattern_cache(signature_hash);
CREATE INDEX idx_pattern_cache_from_domain ON pattern_cache(from_domain);
CREATE INDEX idx_pattern_cache_subject_prefix ON pattern_cache(subject_prefix);
CREATE INDEX idx_pattern_cache_source_name ON pattern_cache(source_name);
CREATE INDEX idx_pattern_cache_match_count ON pattern_cache(match_count DESC);

-- =============================================================================
-- PATTERN EXTRACTION LOG (Audit trail of LLM extractions)
-- =============================================================================
-- Logs each time LLM is used for extraction (both learning and fallback)

CREATE TABLE pattern_extraction_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    raw_email_id UUID NOT NULL REFERENCES raw_emails(id),
    pattern_cache_id UUID REFERENCES pattern_cache(id),  -- NULL if new pattern learned

    -- What happened
    extraction_type VARCHAR(50) NOT NULL,        -- 'learned_new', 'cached_match', 'llm_fallback'

    -- Extracted values
    extracted_host VARCHAR(255),
    extracted_service VARCHAR(255),
    extracted_severity VARCHAR(50),
    extracted_state VARCHAR(50),
    extraction_confidence DECIMAL(3,2),          -- 0.00 to 1.00

    -- Full extraction response from LLM (for debugging)
    llm_response JSONB,

    -- Performance
    duration_ms INT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_extraction_log_email ON pattern_extraction_log(raw_email_id);
CREATE INDEX idx_extraction_log_pattern ON pattern_extraction_log(pattern_cache_id);
CREATE INDEX idx_extraction_log_type ON pattern_extraction_log(extraction_type);
CREATE INDEX idx_extraction_log_created ON pattern_extraction_log(created_at DESC);

-- =============================================================================
-- LLM SERVICE CONFIGURATION
-- =============================================================================
-- Stores configuration for LLM service connection

CREATE TABLE llm_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    name VARCHAR(100) NOT NULL UNIQUE,           -- 'default', 'parsing', 'rag'
    endpoint_url VARCHAR(512) NOT NULL,          -- e.g., "http://rag:8001"
    model_name VARCHAR(255),                     -- e.g., "mistral-7b-instruct"

    -- Generation parameters
    temperature DECIMAL(3,2) DEFAULT 0.1,
    max_tokens INT DEFAULT 1024,

    -- Rate limiting
    requests_per_minute INT DEFAULT 60,

    is_active BOOLEAN NOT NULL DEFAULT true,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Insert default configuration pointing to RAG service
INSERT INTO llm_config (name, endpoint_url, model_name, temperature, max_tokens)
VALUES ('default', 'http://rag:8001', 'mistral-7b-instruct-v0.2', 0.1, 1024);

-- =============================================================================
-- HELPER FUNCTION: Update pattern match statistics
-- =============================================================================

CREATE OR REPLACE FUNCTION update_pattern_match_stats()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.pattern_cache_id IS NOT NULL THEN
        UPDATE pattern_cache
        SET
            match_count = match_count + 1,
            last_matched_at = NOW(),
            updated_at = NOW()
        WHERE id = NEW.pattern_cache_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_pattern_stats
    AFTER INSERT ON pattern_extraction_log
    FOR EACH ROW
    EXECUTE FUNCTION update_pattern_match_stats();
