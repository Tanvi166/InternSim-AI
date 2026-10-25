-- Draft migration. Review and apply after migration 0007 through the normal process.
-- Records the isolated per-install network so interrupted installs can be cleaned.

BEGIN;

ALTER TABLE public.project_runtime_sessions
    ADD COLUMN IF NOT EXISTS install_network_name TEXT;

COMMIT;
