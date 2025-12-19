-- Migration 003a: Add 'resolving' to incident_status enum
-- This must be run separately from the main migration due to PostgreSQL restrictions
ALTER TYPE incident_status ADD VALUE IF NOT EXISTS 'resolving' BEFORE 'resolved';
