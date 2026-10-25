-- Migration: 0005_github_student_projects.sql
-- Purpose: Persist each authenticated student's mapping to their fork of the
--          server-configured GitHub starter repository.
-- Prerequisites: 0003_github_integrations.sql and 0004_consume_github_oauth_state.sql.
-- STATUS: DRAFT FOR REVIEW ONLY. Do not apply until reviewed and approved.

BEGIN;

CREATE TABLE IF NOT EXISTS public.github_student_projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    starter_owner TEXT NOT NULL,
    starter_repository TEXT NOT NULL,
    github_repository_id BIGINT NOT NULL,
    github_owner TEXT NOT NULL,
    github_repository_name TEXT NOT NULL,
    github_full_name TEXT NOT NULL,
    repository_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CONSTRAINT github_student_projects_status_check CHECK (status IN ('pending', 'ready')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_github_student_projects_user_starter
        UNIQUE (user_id, starter_owner, starter_repository),
    CONSTRAINT uq_github_student_projects_repository_id
        UNIQUE (github_repository_id)
);

ALTER TABLE public.github_student_projects ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.github_student_projects FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON TABLE public.github_student_projects
    TO service_role;

DROP POLICY IF EXISTS github_student_projects_service_role
    ON public.github_student_projects;
CREATE POLICY github_student_projects_service_role
    ON public.github_student_projects
    FOR ALL
    USING (auth.jwt() ->> 'role' = 'service_role')
    WITH CHECK (auth.jwt() ->> 'role' = 'service_role');

COMMIT;

-- Rollback guidance (review the data before using):
-- BEGIN;
-- DROP TABLE IF EXISTS public.github_student_projects;
-- COMMIT;
