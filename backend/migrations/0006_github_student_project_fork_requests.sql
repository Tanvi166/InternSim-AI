-- Migration: 0006_github_student_project_fork_requests.sql
-- Purpose: Persist fork-creation intent so an accepted asynchronous GitHub fork
--          is never submitted again while its account-specific repository is pending.
-- Prerequisite: 0005_github_student_projects.sql.
-- STATUS: DRAFT FOR REVIEW ONLY. Do not apply until reviewed and approved.

BEGIN;

CREATE TABLE IF NOT EXISTS public.github_student_project_fork_requests (
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    starter_owner TEXT NOT NULL,
    starter_repository TEXT NOT NULL,
    github_user_id BIGINT NOT NULL CHECK (github_user_id > 0),
    github_owner TEXT NOT NULL,
    github_repository_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_github_student_project_fork_requests_user_starter
        UNIQUE (user_id, starter_owner, starter_repository),
    CONSTRAINT uq_github_student_project_fork_requests_repository
        UNIQUE (github_owner, github_repository_name)
);

ALTER TABLE public.github_student_project_fork_requests ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.github_student_project_fork_requests FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON TABLE public.github_student_project_fork_requests
    TO service_role;

DROP POLICY IF EXISTS github_student_project_fork_requests_service_role
    ON public.github_student_project_fork_requests;
CREATE POLICY github_student_project_fork_requests_service_role
    ON public.github_student_project_fork_requests
    FOR ALL
    USING (auth.jwt() ->> 'role' = 'service_role')
    WITH CHECK (auth.jwt() ->> 'role' = 'service_role');

COMMIT;

-- Rollback guidance (review pending requests before using):
-- BEGIN;
-- DROP TABLE IF EXISTS public.github_student_project_fork_requests;
-- COMMIT;
