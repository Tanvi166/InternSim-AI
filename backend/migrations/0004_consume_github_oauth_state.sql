-- Atomic, single-use OAuth state consumption.
-- Prerequisite: 0003_github_integrations.sql must be applied first.
-- Apply through the normal database migration process; this file is not executed by the app.

BEGIN;

CREATE OR REPLACE FUNCTION public.consume_github_oauth_state(
    p_state TEXT,
    p_user_id UUID
)
RETURNS BOOLEAN
LANGUAGE SQL
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
    WITH consumed AS (
        DELETE FROM public.oauth_states AS oauth_state
        WHERE oauth_state.state = p_state
          AND oauth_state.user_id = p_user_id
          AND oauth_state.expires_at > clock_timestamp()
        RETURNING 1
    )
    SELECT EXISTS (SELECT 1 FROM consumed);
$function$;

REVOKE ALL ON FUNCTION public.consume_github_oauth_state(TEXT, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.consume_github_oauth_state(TEXT, UUID) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.consume_github_oauth_state(TEXT, UUID) TO service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;
