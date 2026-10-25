-- ============================================================================
-- Migration: 0003_github_integrations.sql
-- Project: InternSim AI (Phase 4 GitHub Integration Milestone 1)
-- Purpose:
--   1. Create `public.github_integrations` table to store connected GitHub user metadata
--      and the AES-256-GCM encrypted access token at rest.
--   2. Enforce strict foreign key cascade with auth.users(id).
--   3. Enforce UNIQUE (github_user_id) to prevent multi-tenant account linking conflicts.
--   4. Create `public.oauth_states` table for multi-worker distributed CSRF validation.
--   5. Enable Row-Level Security (RLS) and restrict direct access to service_role.
--
-- STATUS: DRAFT FOR REVIEW ONLY. DO NOT APPLY AUTOMATICALLY TO PRODUCTION.
-- ============================================================================

BEGIN;

-- 1. GitHub Integrations Table
CREATE TABLE IF NOT EXISTS public.github_integrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    github_user_id TEXT NOT NULL,
    github_username TEXT NOT NULL,
    avatar_url TEXT,
    installation_id TEXT,               -- Stored if using GitHub App installation flow
    encrypted_access_token TEXT NOT NULL, -- AES-256-GCM ciphertext + IV + tag
    token_scope TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_github_integrations_user_id UNIQUE (user_id),
    CONSTRAINT uq_github_integrations_github_user_id UNIQUE (github_user_id)
);

-- 2. Distributed Short-Lived OAuth State Table (Cross-worker & restart resilient)
CREATE TABLE IF NOT EXISTS public.oauth_states (
    state TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_oauth_states_expires_at ON public.oauth_states(expires_at);

-- Enable RLS
ALTER TABLE public.github_integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.oauth_states ENABLE ROW LEVEL SECURITY;

-- Table privileges are separate from RLS policies; grant backend CRUD access explicitly.
GRANT SELECT, INSERT, UPDATE, DELETE
    ON TABLE public.github_integrations, public.oauth_states
    TO service_role;

-- Deny all direct client access by default; operations routed via backend service_role
DROP POLICY IF EXISTS github_integrations_service_role ON public.github_integrations;
CREATE POLICY github_integrations_service_role ON public.github_integrations
    FOR ALL
    USING (auth.jwt() ->> 'role' = 'service_role');

DROP POLICY IF EXISTS oauth_states_service_role ON public.oauth_states;
CREATE POLICY oauth_states_service_role ON public.oauth_states
    FOR ALL
    USING (auth.jwt() ->> 'role' = 'service_role');

COMMIT;

-- Rollback Guidance:
-- BEGIN;
-- DROP TABLE IF EXISTS public.oauth_states CASCADE;
-- DROP TABLE IF EXISTS public.github_integrations CASCADE;
-- COMMIT;
