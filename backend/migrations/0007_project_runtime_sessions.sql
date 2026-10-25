-- Draft migration. Review and apply through the normal Supabase migration process.
-- Persists only runtime ownership and lifecycle metadata; never stores source,
-- dependency contents, credentials, or logs.

BEGIN;

CREATE TABLE IF NOT EXISTS public.project_runtime_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    container_id TEXT,
    install_container_id TEXT,
    workspace_dir TEXT,
    runtime_type TEXT CHECK (runtime_type IS NULL OR runtime_type IN ('python', 'node')),
    runtime_status TEXT NOT NULL DEFAULT 'queued'
        CHECK (runtime_status IN ('queued', 'preparing', 'installing', 'running', 'failed', 'stopped')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    preview_port INTEGER CHECK (preview_port IS NULL OR preview_port IN (3000, 5000, 8000, 8080)),
    host_port INTEGER CHECK (host_port IS NULL OR host_port BETWEEN 1 AND 65535),
    network_name TEXT,
    preview_token_hash TEXT,
    preview_token_used BOOLEAN NOT NULL DEFAULT FALSE,
    error TEXT,
    exit_code INTEGER,
    CONSTRAINT uq_project_runtime_sessions_owner_workspace UNIQUE (owner_id, workspace_id)
);

CREATE INDEX IF NOT EXISTS idx_project_runtime_sessions_expiry
    ON public.project_runtime_sessions(expires_at);

ALTER TABLE public.project_runtime_sessions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.project_runtime_sessions FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.project_runtime_sessions TO service_role;
DROP POLICY IF EXISTS project_runtime_sessions_service_role ON public.project_runtime_sessions;
CREATE POLICY project_runtime_sessions_service_role
    ON public.project_runtime_sessions
    FOR ALL
    USING (auth.jwt() ->> 'role' = 'service_role')
    WITH CHECK (auth.jwt() ->> 'role' = 'service_role');

COMMIT;
