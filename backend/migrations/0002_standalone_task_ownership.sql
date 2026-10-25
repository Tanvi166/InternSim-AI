-- ============================================================================
-- Migration: 0002_standalone_task_ownership.sql
-- Project: InternSim AI (Phase 3 Security)
-- Purpose:
--   1. Add nullable `user_id` to `public.tasks` referencing `auth.users(id)`.
--   2. Safely backfill standalone task ownership from historical submissions
--      (strictly for tasks where historical submitters resolve to exactly ONE distinct user).
--   3. Provide pre/post migration audit queries and ambiguous task inspection.
--   4. Implement atomic PostgreSQL RPC `claim_and_submit_standalone_task`
--      using FOR UPDATE row-level locking.
--   5. Restrict RPC execution strictly to Supabase `service_role` (backend caller).
--
-- STATUS: DRAFT FOR REVIEW ONLY. DO NOT APPLY AUTOMATICALLY TO PRODUCTION.
-- ============================================================================

-- ============================================================================
-- SECTION 0: PRE-MIGRATION AUDIT (Read-Only)
-- Run these queries prior to running the migration to inspect current data.
-- ============================================================================

-- 0.1 Total standalone tasks vs project-owned tasks
-- SELECT
--     COUNT(*) FILTER (WHERE project_id IS NULL) AS total_standalone_tasks,
--     COUNT(*) FILTER (WHERE project_id IS NOT NULL) AS total_project_tasks
-- FROM public.tasks;

-- 0.2 Check distinct submitter distribution for standalone tasks
-- WITH standalone_submitters AS (
--     SELECT
--         t.task_id,
--         COUNT(DISTINCT s.user_id) AS distinct_user_count,
--         COUNT(s.submission_id) AS total_submissions
--     FROM public.tasks t
--     LEFT JOIN public.submissions s ON t.task_id = s.task_id
--     WHERE t.project_id IS NULL
--     GROUP BY t.task_id
-- )
-- SELECT
--     COUNT(*) FILTER (WHERE total_submissions = 0) AS zero_submissions_count,
--     COUNT(*) FILTER (WHERE distinct_user_count = 1) AS eligible_single_user_count,
--     COUNT(*) FILTER (WHERE distinct_user_count > 1) AS ambiguous_multi_user_count
-- FROM standalone_submitters;

-- 0.3 Inspect ambiguous standalone tasks (submissions from >1 distinct users)
-- SELECT
--     t.task_id,
--     t.title,
--     array_agg(DISTINCT s.user_id) AS submitter_user_ids,
--     COUNT(s.submission_id) AS submission_count
-- FROM public.tasks t
-- JOIN public.submissions s ON t.task_id = s.task_id
-- WHERE t.project_id IS NULL
-- GROUP BY t.task_id, t.title
-- HAVING COUNT(DISTINCT s.user_id) > 1;

-- 0.4 Capture baseline for project-owned tasks (to verify post-migration immutability)
-- SELECT
--     COUNT(*) AS baseline_project_tasks_with_user_id
-- FROM public.tasks
-- WHERE project_id IS NOT NULL
--   AND (CASE WHEN EXISTS (
--         SELECT 1 FROM information_schema.columns
--         WHERE table_schema = 'public' AND table_name = 'tasks' AND column_name = 'user_id'
--       ) THEN user_id IS NOT NULL ELSE FALSE END);


-- ============================================================================
-- SECTION 1: SCHEMA MIGRATION & BACKFILL TRANSACTION
-- ============================================================================

BEGIN;

-- 1.1 Add user_id column to tasks table if it does not already exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'tasks'
          AND column_name = 'user_id'
    ) THEN
        ALTER TABLE public.tasks
        ADD COLUMN user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL;

        COMMENT ON COLUMN public.tasks.user_id IS
          'Owner of standalone task. For project-owned tasks, project ownership resides in public.projects.user_id.';
    END IF;
END $$;

-- 1.2 Create index for faster task ownership and lookup queries
CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON public.tasks(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_project_id ON public.tasks(project_id);

-- 1.3 Safe backfill for standalone tasks
-- Rule:
--   - ONLY backfill if public.tasks.project_id IS NULL.
--   - ONLY backfill if public.tasks.user_id IS CURRENTLY NULL (avoid overwriting).
--   - ONLY backfill if historical submissions belong to EXACTLY ONE distinct user.
--   - Ambiguous tasks (>1 distinct submitters) and tasks with 0 submissions remain NULL.
WITH single_distinct_submitters AS (
    SELECT
        s.task_id,
        MIN(s.user_id) AS sole_user_id
    FROM public.submissions s
    JOIN public.tasks t ON s.task_id = t.task_id
    WHERE t.project_id IS NULL
      AND t.user_id IS NULL
      AND s.user_id IS NOT NULL
    GROUP BY s.task_id
    HAVING COUNT(DISTINCT s.user_id) = 1
)
UPDATE public.tasks t
SET user_id = s.sole_user_id
FROM single_distinct_submitters s
WHERE t.task_id = s.task_id
  AND t.project_id IS NULL
  AND t.user_id IS NULL;

COMMIT;


-- ============================================================================
-- SECTION 2: ATOMIC CLAIM & SUBMIT POSTGRESQL RPC
-- Function: claim_and_submit_standalone_task
-- Behavior:
--   1. Executed in a single transaction.
--   2. Locks the target task row via SELECT ... FOR UPDATE.
--   3. Validates that the task is standalone (project_id IS NULL).
--   4. If task.user_id IS NULL: claims ownership atomically for p_user_id.
--   5. If task.user_id = p_user_id: permits submission (re-submission by owner).
--   6. If task.user_id <> p_user_id: rejects with 403-equivalent exception.
--   7. Inserts the submission row in the same transaction.
--   8. Returns the inserted submission row as JSON.
-- ============================================================================

CREATE OR REPLACE FUNCTION public.claim_and_submit_standalone_task(
    p_task_id TEXT,
    p_user_id UUID,
    p_submitted_code TEXT,
    p_language TEXT,
    p_correctness_score INTEGER,
    p_quality_score INTEGER,
    p_total_score INTEGER,
    p_feedback JSONB
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_task RECORD;
    v_new_sub RECORD;
BEGIN
    -- 1. Input sanitization / validation
    IF p_task_id IS NULL OR p_user_id IS NULL THEN
        RAISE EXCEPTION 'Invalid parameters: task_id and user_id are required'
            USING ERRCODE = '22023'; -- invalid_parameter_value
    END IF;

    -- 2. Lock target task row for update to eliminate race conditions.
    -- Note on task_id type compatibility:
    -- If tasks.task_id is TEXT, task_id = p_task_id utilizes the primary key index directly.
    -- If tasks.task_id is UUID or TEXT, casting both sides via (task_id::text = p_task_id::text)
    -- guarantees comparison compatibility across schemas. To ensure index usage on large tables,
    -- tasks should have an index on task_id or an expression index on (task_id::text).
    SELECT task_id, project_id, user_id
    INTO v_task
    FROM public.tasks
    WHERE task_id::text = p_task_id::text
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Task not found: %', p_task_id
            USING ERRCODE = 'P0002'; -- no_data_found
    END IF;

    -- 3. Verify task is standalone
    IF v_task.project_id IS NOT NULL THEN
        RAISE EXCEPTION 'Cannot use standalone claim on a project-owned ticket (project_id: %)', v_task.project_id
            USING ERRCODE = '42809'; -- wrong_object_type
    END IF;

    -- 4. Ownership verification & atomic claim
    IF v_task.user_id IS NULL THEN
        -- Task is unclaimed: claim ownership for p_user_id
        UPDATE public.tasks
        SET user_id = p_user_id
        WHERE task_id::text = p_task_id::text;
    ELSIF v_task.user_id <> p_user_id THEN
        -- Task is claimed by a different user: fail closed
        RAISE EXCEPTION 'Access denied: Standalone ticket is owned by another user'
            USING ERRCODE = '42501'; -- insufficient_privilege
    END IF;

    -- 5. Insert submission record within the same transaction
    INSERT INTO public.submissions (
        task_id,
        user_id,
        submitted_code,
        language,
        correctness_score,
        quality_score,
        total_score,
        feedback,
        created_at
    )
    VALUES (
        p_task_id,
        p_user_id,
        p_submitted_code,
        p_language,
        p_correctness_score,
        p_quality_score,
        p_total_score,
        p_feedback,
        NOW()
    )
    RETURNING
        submission_id,
        task_id,
        user_id,
        submitted_code,
        language,
        correctness_score,
        quality_score,
        total_score,
        feedback,
        created_at
    INTO v_new_sub;

    -- 6. Return inserted submission as JSONB
    RETURN to_jsonb(v_new_sub);
END;
$$;

COMMENT ON FUNCTION public.claim_and_submit_standalone_task IS
  'Atomically claims an unclaimed standalone task for a user and records their submission within a single transaction using row-level locking.';


-- ============================================================================
-- SECTION 3: PERMISSION GRANTS & REVOCATIONS
-- Trust boundary:
--   - The backend connects using SUPABASE_SERVICE_ROLE_KEY.
--   - The backend validates the caller JWT in FastAPI via auth_service.py.
--   - Execution of this RPC is REVOKED from public, anon, and authenticated roles
--     to prevent any direct frontend or unauthenticated execution bypassing backend checks.
--   - Execution is GRANTED ONLY to service_role.
-- ============================================================================

-- Revoke all permissions from untrusted roles
REVOKE ALL ON FUNCTION public.claim_and_submit_standalone_task(
    TEXT, UUID, TEXT, TEXT, INTEGER, INTEGER, INTEGER, JSONB
) FROM PUBLIC;

REVOKE ALL ON FUNCTION public.claim_and_submit_standalone_task(
    TEXT, UUID, TEXT, TEXT, INTEGER, INTEGER, INTEGER, JSONB
) FROM anon;

REVOKE ALL ON FUNCTION public.claim_and_submit_standalone_task(
    TEXT, UUID, TEXT, TEXT, INTEGER, INTEGER, INTEGER, JSONB
) FROM authenticated;

-- Grant execution strictly to service_role
GRANT EXECUTE ON FUNCTION public.claim_and_submit_standalone_task(
    TEXT, UUID, TEXT, TEXT, INTEGER, INTEGER, INTEGER, JSONB
) TO service_role;


-- ============================================================================
-- SECTION 4: POST-MIGRATION VERIFICATION QUERIES (Read-Only)
-- ============================================================================

-- 4.1 Confirm user_id column existence and constraints
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_schema = 'public' AND table_name = 'tasks' AND column_name = 'user_id';

-- 4.2 Confirm standalone tasks ownership status after backfill
-- SELECT
--     COUNT(*) FILTER (WHERE user_id IS NOT NULL) AS claimed_standalone_tasks,
--     COUNT(*) FILTER (WHERE user_id IS NULL) AS unassigned_standalone_tasks
-- FROM public.tasks
-- WHERE project_id IS NULL;

-- 4.3 Verify project-owned task ownership immutability
-- Compare post-migration count against pre-migration baseline (Query 0.4):
-- The count of project-owned tasks with user_id MUST equal baseline_project_tasks_with_user_id.
-- SELECT
--     COUNT(*) AS post_project_tasks_with_user_id
-- FROM public.tasks
-- WHERE project_id IS NOT NULL AND user_id IS NOT NULL;

-- 4.4 List remaining unassigned tasks that require manual review
-- SELECT
--     t.task_id,
--     t.title,
--     COUNT(s.submission_id) AS total_submissions,
--     array_agg(DISTINCT s.user_id) AS submitters
-- FROM public.tasks t
-- LEFT JOIN public.submissions s ON t.task_id = s.task_id
-- WHERE t.project_id IS NULL AND t.user_id IS NULL
-- GROUP BY t.task_id, t.title;


-- ============================================================================
-- SECTION 5: ROLLBACK PROCEDURES
-- ============================================================================

-- OPTION A: NON-DESTRUCTIVE ROLLBACK (RECOMMENDED)
-- Revokes RPC execution and drops the function, returning the system to
-- application-level concurrency handling while preserving all backfilled
-- and newly claimed standalone task ownership records in public.tasks.user_id.
--
-- BEGIN;
-- REVOKE EXECUTE ON FUNCTION public.claim_and_submit_standalone_task(
--     TEXT, UUID, TEXT, TEXT, INTEGER, INTEGER, INTEGER, JSONB
-- ) FROM service_role;
-- DROP FUNCTION IF EXISTS public.claim_and_submit_standalone_task(
--     TEXT, UUID, TEXT, TEXT, INTEGER, INTEGER, INTEGER, JSONB
-- );
-- COMMIT;

-- OPTION B: DESTRUCTIVE COLUMN REMOVAL (CAUTION: PERMANENT DATA LOSS)
-- WARNING: This permanently deletes the tasks.user_id column and all ownership
-- data recorded since migration. Only run with explicit architectural approval
-- and after taking a verified database snapshot/backup.
--
-- BEGIN;
-- DROP FUNCTION IF EXISTS public.claim_and_submit_standalone_task(
--     TEXT, UUID, TEXT, TEXT, INTEGER, INTEGER, INTEGER, JSONB
-- );
-- DROP INDEX IF EXISTS public.idx_tasks_user_id;
-- ALTER TABLE public.tasks DROP COLUMN IF EXISTS user_id;
-- COMMIT;
