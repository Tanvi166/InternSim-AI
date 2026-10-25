"""
Comprehensive Unit and Integration Tests for GitHub Integration (Milestone 1).
Tests:
- Token encryption and decryption (AES-256-GCM integrity, format validation, and tamper resistance)
- Strict encryption key validation (fails closed when key is missing/invalid)
- OAuth state generation, user binding, and atomic single-use consumption
- Protection against CSRF, account linking, and cross-user state injection
- Upstream OAuth grant revocation (success and graceful fallback)
- Duplicate GitHub account linking conflict detection
- Safe repository listing with pagination, rate limit handling, and decryption errors
- Unauthenticated access rejection across all GitHub endpoints
"""

import os
import unittest
import asyncio
import threading
import base64
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from main import app
from services.encryption_service import encrypt_token, decrypt_token, _get_encryption_key
from services.github_service import (
    generate_oauth_authorization_url,
    validate_oauth_state,
    revoke_github_app_grant,
    save_github_integration,
    list_authorized_repositories,
    delete_github_integration,
    create_github_feature_branch,
    GitHubBranchConflictError,
    GitHubRepositoryAccessError,
    GitHubAuthenticationError,
    GitHubRateLimitError,
    create_or_get_student_starter_fork,
    get_student_starter_fork_status,
    GitHubForkNotFoundError,
    GitHubForkConflictError,
    GitHubForkError,
    GitHubForkRateLimitError,
    GitHubStudentProjectStoreError,
    GitHubStudentProjectFileNotFoundError,
    GitHubStudentProjectPathIsDirectoryError,
    GitHubStudentProjectFileTooLargeError,
    GitHubStudentProjectBinaryFileError,
    GitHubStudentProjectListingTooLargeError,
    list_student_project_files,
    get_student_project_file,
    OAuthStateStoreError,
)

client = TestClient(app)

# Explicit 32-byte hex key for tests
VALID_TEST_HEX_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


class _SharedOAuthStateStore:
    """Explicit shared database fake; independent clients share rows and atomic RPC."""
    def __init__(self):
        self.rows = {}
        self.lock = threading.Lock()


class _FakeSupabaseClient:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        if name != "oauth_states":
            raise AssertionError(f"Unexpected table access in OAuth tests: {name}")
        return _FakeOAuthStateTable(self.store)

    def rpc(self, name, params):
        if name != "consume_github_oauth_state":
            raise AssertionError(f"Unexpected RPC: {name}")
        return _FakeConsumeOAuthState(self.store, params)


class _FakeOAuthStateTable:
    def __init__(self, store):
        self.store = store

    def insert(self, row):
        self.row = dict(row)
        return self

    def execute(self):
        with self.store.lock:
            if self.row["state"] in self.store.rows:
                raise RuntimeError("duplicate OAuth state")
            self.store.rows[self.row["state"]] = self.row
        return type("Result", (), {"data": [self.row]})()


class _FakeConsumeOAuthState:
    def __init__(self, store, params):
        self.store = store
        self.params = params

    def execute(self):
        with self.store.lock:
            row = self.store.rows.get(self.params["p_state"])
            consumed = bool(
                row
                and str(row["user_id"]) == str(self.params["p_user_id"])
                and datetime.fromisoformat(row["expires_at"])
                > datetime.now(timezone.utc)
            )
            if consumed:
                del self.store.rows[self.params["p_state"]]
        return type("Result", (), {"data": consumed})()


class _FakeStudentProjectDatabase:
    """Explicit shared fake for mapping tests; never used as an app fallback."""
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.requests = []
        self.lock = threading.Lock()

    def table(self, name):
        if name not in {"github_student_projects", "github_student_project_fork_requests"}:
            raise AssertionError(f"Unexpected table in student-project test: {name}")
        return _FakeStudentProjectQuery(self, name)

    def rpc(self, _name, _params):
        raise AssertionError("Student-project tests should use table operations only")


class _MockSupabaseDatabaseError(RuntimeError):
    code = "PGRST205"
    message = "Could not find the table 'public.github_student_project_fork_requests' in the schema cache"


class _FailingPendingRequestQuery:
    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        raise _MockSupabaseDatabaseError(_MockSupabaseDatabaseError.message)


class _MissingPendingRequestTableDatabase(_FakeStudentProjectDatabase):
    def table(self, name):
        if name == "github_student_project_fork_requests":
            return _FailingPendingRequestQuery()
        return super().table(name)


class _FakeStudentProjectQuery:
    def __init__(self, database, table_name):
        self.database = database
        self.table_name = table_name
        self.rows = database.rows if table_name == "github_student_projects" else database.requests
        self.filters = {}
        self.operation = "select"
        self.values = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, name, value):
        self.filters[name] = value
        return self

    def limit(self, _count):
        return self

    def insert(self, values):
        self.operation = "insert"
        self.values = dict(values)
        return self

    def update(self, values):
        self.operation = "update"
        self.values = dict(values)
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def execute(self):
        with self.database.lock:
            if self.operation == "insert":
                if any(
                    row["user_id"] == self.values["user_id"]
                    and row["starter_owner"] == self.values["starter_owner"]
                    and row["starter_repository"] == self.values["starter_repository"]
                    for row in self.rows
                ):
                    raise RuntimeError("unique mapping constraint")
                if self.table_name == "github_student_project_fork_requests" and any(
                    row.get("github_owner") == self.values.get("github_owner")
                    and row.get("github_repository_name") == self.values.get("github_repository_name")
                    for row in self.rows
                ):
                    raise RuntimeError("unique pending repository constraint")
                row = {"id": f"mapping-{len(self.rows) + 1}", **self.values}
                self.rows.append(row)
                return type("Result", (), {"data": [dict(row)]})()

            selected = [
                row for row in self.rows
                if all(str(row.get(key)) == str(value) for key, value in self.filters.items())
            ]
            if self.operation == "update":
                for row in selected:
                    row.update(self.values)
            elif self.operation == "delete":
                for row in selected:
                    self.rows.remove(row)
            return type("Result", (), {"data": [dict(row) for row in selected]})()

class TestGitHubIntegrationMilestone1(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        os.environ["GITHUB_TOKEN_ENCRYPTION_KEY"] = VALID_TEST_HEX_KEY

    # --- 1. Encryption & Decryption Integrity Tests ---

    def test_token_encryption_and_decryption_success(self):
        sample_token = "ghp_secureTokenMockValue1234567890abcdef"
        encrypted = encrypt_token(sample_token)

        self.assertNotEqual(sample_token, encrypted)
        self.assertNotIn("ghp_", encrypted)

        decrypted = decrypt_token(encrypted)
        self.assertEqual(sample_token, decrypted)

    def test_token_decryption_tamper_detection(self):
        sample_token = "ghp_secureTokenMockValue1234567890abcdef"
        encrypted = encrypt_token(sample_token)

        # Tamper with the base64 ciphertext
        import base64
        raw = bytearray(base64.b64decode(encrypted))
        raw[-1] ^= 0xFF # Flip bits in GCM tag
        tampered_b64 = base64.b64encode(raw).decode()

        with self.assertRaises(ValueError):
            decrypt_token(tampered_b64)

    def test_encryption_empty_payload_fails(self):
        with self.assertRaises(ValueError):
            encrypt_token("")
        with self.assertRaises(ValueError):
            decrypt_token("")

    def test_missing_encryption_key_fails_closed(self):
        """A missing dedicated key fails even if legacy/test variables are present."""
        with patch.dict(os.environ, {"GITHUB_TOKEN_ENCRYPTION_KEY": "", "TOKEN_ENCRYPTION_KEY": VALID_TEST_HEX_KEY, "TESTING": "1", "PYTEST_CURRENT_TEST": "test"}):
            with self.assertRaises(RuntimeError) as ctx:
                _get_encryption_key()
            self.assertIn("GITHUB_TOKEN_ENCRYPTION_KEY", str(ctx.exception))

    def test_valid_hex_and_base64_encryption_keys(self):
        expected = bytes(range(32))
        encoded_keys = (expected.hex(), base64.b64encode(expected).decode("ascii"))
        for encoded in encoded_keys:
            with self.subTest(encoding=encoded[-4:]), patch.dict(os.environ, {"GITHUB_TOKEN_ENCRYPTION_KEY": encoded}):
                self.assertEqual(_get_encryption_key(), expected)

    def test_misleading_testing_values_do_not_enable_a_fallback_key(self):
        for testing_value in ("0", "false", "no", "1", "arbitrary"):
            with self.subTest(testing=testing_value), patch.dict(
                os.environ,
                {"GITHUB_TOKEN_ENCRYPTION_KEY": "", "TOKEN_ENCRYPTION_KEY": "", "TESTING": testing_value, "PYTEST_CURRENT_TEST": ""},
            ):
                with self.assertRaises(RuntimeError):
                    _get_encryption_key()

    def test_invalid_encryption_key_format_fails(self):
        """Malformed hex and Base64 values raise ValueError."""
        for malformed in ("g" * 64, "!" * 44):
            with self.subTest(key_length=len(malformed)), patch.dict(os.environ, {"GITHUB_TOKEN_ENCRYPTION_KEY": malformed}):
                with self.assertRaises(ValueError):
                    _get_encryption_key()

    def test_encoded_key_with_wrong_decoded_length_fails(self):
        encoded_31_bytes = base64.b64encode(b"x" * 31).decode("ascii")
        with patch.dict(os.environ, {"GITHUB_TOKEN_ENCRYPTION_KEY": encoded_31_bytes}):
            with self.assertRaises(ValueError) as ctx:
                _get_encryption_key()
            self.assertIn("32-byte key", str(ctx.exception))

    # --- 2. OAuth State Generation & CSRF Protection ---

    async def test_oauth_url_generation_binds_to_authenticated_user(self):
        self.oauth_store = _SharedOAuthStateStore()
        with patch("services.github_service.os.environ.get", return_value="mock_client_id"), \
             patch("services.github_service.get_supabase_client", side_effect=lambda: _FakeSupabaseClient(self.oauth_store)):
            res = await generate_oauth_authorization_url(user_id="user-alice-123")

            self.assertIn("authorization_url", res)
            self.assertIn("state", res)
            self.assertIn("client_id=mock_client_id", res["authorization_url"])
            self.assertIn(f"state={res['state']}", res["authorization_url"])

            # Verify state was saved with correct user_id
            is_valid = await validate_oauth_state(res["state"], expected_user_id="user-alice-123")
            self.assertTrue(is_valid)

    async def test_state_validation_rejects_mismatched_user_id(self):
        """CSRF attack simulation: Bob tries to use a state generated by Alice to link Bob's GitHub to Alice's account"""
        self.oauth_store = _SharedOAuthStateStore()
        with patch("services.github_service.os.environ.get", return_value="mock_client_id"), \
             patch("services.github_service.get_supabase_client", side_effect=lambda: _FakeSupabaseClient(self.oauth_store)):
            res = await generate_oauth_authorization_url(user_id="user-alice-123")
            state = res["state"]

            # Bob tries to validate Alice's state
            is_valid = await validate_oauth_state(state, expected_user_id="user-bob-999")
            self.assertFalse(is_valid)

    async def test_state_is_single_use_consumed(self):
        self.oauth_store = _SharedOAuthStateStore()
        with patch("services.github_service.os.environ.get", return_value="mock_client_id"), \
             patch("services.github_service.get_supabase_client", side_effect=lambda: _FakeSupabaseClient(self.oauth_store)):
            res = await generate_oauth_authorization_url(user_id="user-alice-123")
            state = res["state"]

            # First validation succeeds
            is_valid = await validate_oauth_state(state, expected_user_id="user-alice-123")
            self.assertTrue(is_valid)

            # Replay attempt fails immediately
            is_replay_valid = await validate_oauth_state(state, expected_user_id="user-alice-123")
            self.assertFalse(is_replay_valid)

    async def test_state_expiry_is_rejected_and_not_consumed(self):
        self.oauth_store = _SharedOAuthStateStore()
        with patch("services.github_service.os.environ.get", return_value="mock_client_id"), \
             patch("services.github_service.get_supabase_client", side_effect=lambda: _FakeSupabaseClient(self.oauth_store)):
            res = await generate_oauth_authorization_url(user_id="user-alice-123")
            self.oauth_store.rows[res["state"]]["expires_at"] = (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            ).isoformat()
            self.assertFalse(await validate_oauth_state(res["state"], "user-alice-123"))

    async def test_state_consumption_is_atomic_under_concurrent_requests(self):
        self.oauth_store = _SharedOAuthStateStore()
        with patch("services.github_service.os.environ.get", return_value="mock_client_id"), \
             patch("services.github_service.get_supabase_client", side_effect=lambda: _FakeSupabaseClient(self.oauth_store)):
            res = await generate_oauth_authorization_url(user_id="user-alice-123")
            barrier = threading.Barrier(8)

            def consume():
                barrier.wait(timeout=2)
                return asyncio.run(validate_oauth_state(res["state"], "user-alice-123"))

            outcomes = await asyncio.gather(*[
                asyncio.to_thread(consume) for _ in range(8)
            ])
            self.assertEqual(sum(outcomes), 1)

    async def test_state_created_and_consumed_by_independent_clients(self):
        shared_store = _SharedOAuthStateStore()
        with patch("services.github_service.os.environ.get", return_value="mock_client_id"), \
             patch("services.github_service.get_supabase_client", side_effect=lambda: _FakeSupabaseClient(shared_store)):
            res = await generate_oauth_authorization_url(user_id="user-alice-123")
            self.assertTrue(await validate_oauth_state(res["state"], "user-alice-123"))

    async def test_state_store_failure_fails_closed(self):
        with patch("services.github_service.os.environ.get", return_value="mock_client_id"), \
             patch("services.github_service.get_supabase_client", side_effect=RuntimeError("db unavailable")):
            with self.assertRaises(OAuthStateStoreError):
                await generate_oauth_authorization_url(user_id="user-alice-123")
            with self.assertRaises(OAuthStateStoreError):
                await validate_oauth_state("state-that-was-not-stored", "user-alice-123")

    async def test_state_rpc_failure_fails_closed(self):
        client = MagicMock()
        client.rpc.side_effect = RuntimeError("RPC unavailable")
        with patch("services.github_service.get_supabase_client", return_value=client):
            with self.assertRaises(OAuthStateStoreError):
                await validate_oauth_state("persisted-state", "user-alice-123")

    async def test_in_memory_database_stub_cannot_claim_state_persisted(self):
        client_without_rpc = MagicMock(spec=["table"])
        with patch("services.github_service.os.environ.get", return_value="mock_client_id"), \
             patch("services.github_service.get_supabase_client", return_value=client_without_rpc):
            with self.assertRaises(OAuthStateStoreError):
                await generate_oauth_authorization_url("user-alice-123")
        client_without_rpc.table.assert_not_called()

    async def test_disconnect_confirms_deleted_user_row(self):
        database = MagicMock()
        database.table.return_value.delete.return_value.eq.return_value.select.return_value.execute.return_value.data = [
            {"user_id": "user-alice-123"}
        ]
        with patch("services.github_service.get_supabase_client", return_value=database), \
             patch("services.github_service.get_github_integration", AsyncMock(return_value=None)):
            result = await delete_github_integration("user-alice-123")

        self.assertTrue(result["local_deleted"])
        self.assertFalse(result["upstream_revoked"])
        database.table.assert_called_once_with("github_integrations")
        database.table.return_value.delete.return_value.eq.assert_called_once_with("user_id", "user-alice-123")
        database.table.return_value.delete.return_value.eq.return_value.select.assert_called_once_with("user_id")

    async def test_disconnect_reports_false_when_no_user_row_was_deleted(self):
        database = MagicMock()
        database.table.return_value.delete.return_value.eq.return_value.select.return_value.execute.return_value.data = []
        with patch("services.github_service.get_supabase_client", return_value=database), \
             patch("services.github_service.get_github_integration", AsyncMock(return_value=None)):
            result = await delete_github_integration("user-alice-123")

        self.assertFalse(result["local_deleted"])
        self.assertFalse(result["upstream_revoked"])

    async def test_disconnect_propagates_database_delete_failure(self):
        database = MagicMock()
        database.table.return_value.delete.return_value.eq.return_value.select.return_value.execute.side_effect = RuntimeError(
            "database failure with sensitive details"
        )
        with patch("services.github_service.get_supabase_client", return_value=database), \
             patch("services.github_service.get_github_integration", AsyncMock(return_value=None)):
            with self.assertRaises(RuntimeError):
                await delete_github_integration("user-alice-123")

    # --- 3. Account Linking Conflict Guard ---

    async def test_duplicate_github_account_linking_raises_conflict(self):
        """If a GitHub account is already linked to Alice, Bob cannot link the same GitHub account"""
        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"user_id": "user-alice-123"}
        ]
        with patch("services.github_service.get_supabase_client", return_value=mock_db):
            with self.assertRaises(ValueError) as ctx:
                await save_github_integration(
                    user_id="user-bob-999",
                    access_token="ghp_bob_token",
                    github_user={"id": 12345, "login": "shared-github-account"}
                )
            self.assertIn("already linked to another InternSim profile", str(ctx.exception))

    # --- 4. Upstream Token Revocation Tests ---

    async def test_revoke_github_app_grant_success(self):
        with patch("services.github_service.os.environ.get", side_effect=lambda k: "val" if "GITHUB" in k else None):
            with patch("httpx.AsyncClient.request", AsyncMock(return_value=MagicMock(status_code=204))):
                revoked = await revoke_github_app_grant("ghp_mock_token")
                self.assertTrue(revoked)

    async def test_revoke_github_app_grant_handles_network_failure_safely(self):
        with patch("services.github_service.os.environ.get", return_value="val"):
            with patch("httpx.AsyncClient.request", AsyncMock(side_effect=Exception("Connection reset"))):
                revoked = await revoke_github_app_grant("ghp_mock_token")
                self.assertFalse(revoked) # Fails safely without raising uncaught exception

    # --- 5. Repository Listing & Edge Cases ---

    async def test_list_repositories_rate_limit_handled(self):
        mock_resp = MagicMock(status_code=403)
        mock_resp.headers = {"x-ratelimit-remaining": "0"}
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)):
            with self.assertRaises(TimeoutError) as ctx:
                await list_authorized_repositories("ghp_mock_token")
            self.assertIn("rate limit exceeded", str(ctx.exception))

    async def test_list_repositories_revoked_token_handled(self):
        mock_resp = MagicMock(status_code=401)
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)):
            with self.assertRaises(PermissionError) as ctx:
                await list_authorized_repositories("ghp_revoked_token")
            self.assertIn("invalid or have been revoked", str(ctx.exception))

    # --- Feature branch creation (all GitHub HTTP calls are mocked) ---

    async def test_feature_branch_uses_default_branch_tip_and_creates_only_feature_ref(self):
        default_branch = MagicMock(status_code=200, headers={}, json=MagicMock(return_value={"default_branch": "main"}))
        latest_ref = MagicMock(
            status_code=200,
            headers={},
            json=MagicMock(return_value={"object": {"sha": "a" * 40}}),
        )
        created = MagicMock(status_code=201, headers={})
        with patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=[default_branch, latest_ref])) as get, \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock(return_value=created)) as post:
            result = await create_github_feature_branch(
                "mock-token", "octocat", "hello-world", "feature/add-dashboard"
            )

        self.assertEqual(result, {"branch_name": "feature/add-dashboard", "base_branch": "main"})
        self.assertEqual(get.await_count, 2)
        self.assertIn("/git/ref/heads/main", get.await_args_list[1].args[0])
        self.assertEqual(post.await_args.kwargs["json"], {
            "ref": "refs/heads/feature/add-dashboard",
            "sha": "a" * 40,
        })
        self.assertEqual(post.await_args.kwargs["headers"]["Authorization"], "Bearer mock-token")

    async def test_feature_branch_rejects_malformed_inputs_before_github_request(self):
        with patch("services.github_service.httpx.AsyncClient.get", AsyncMock()) as get:
            for owner, repository, branch in (
                ("octocat/other", "repo", "feature/new"),
                ("octocat", "../repo", "feature/new"),
                ("octocat", "repo", "main"),
                ("octocat", "repo", "feature/../main"),
                ("octocat", "repo", "feature/name//part"),
            ):
                with self.subTest(owner=owner, repository=repository, branch=branch):
                    with self.assertRaises(ValueError):
                        await create_github_feature_branch("mock-token", owner, repository, branch)
            get.assert_not_awaited()

    async def test_feature_branch_conflict_is_reported_without_upstream_body(self):
        default_branch = MagicMock(status_code=200, headers={}, json=MagicMock(return_value={"default_branch": "main"}))
        latest_ref = MagicMock(
            status_code=200,
            headers={},
            json=MagicMock(return_value={"object": {"sha": "b" * 40}}),
        )
        conflict = MagicMock(status_code=422, headers={}, text="sensitive upstream detail")
        with patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=[default_branch, latest_ref])), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock(return_value=conflict)):
            with self.assertRaises(GitHubBranchConflictError) as ctx:
                await create_github_feature_branch("mock-token", "octocat", "repo", "feature/existing")
        self.assertNotIn("sensitive upstream detail", str(ctx.exception))

    async def test_feature_branch_repository_access_and_rate_limit_fail_safely(self):
        forbidden = MagicMock(status_code=404, headers={})
        with patch("services.github_service.httpx.AsyncClient.get", AsyncMock(return_value=forbidden)):
            with self.assertRaises(GitHubRepositoryAccessError):
                await create_github_feature_branch("mock-token", "octocat", "private-repo", "feature/change")

        rate_limited = MagicMock(status_code=403, headers={"x-ratelimit-remaining": "0"})
        with patch("services.github_service.httpx.AsyncClient.get", AsyncMock(return_value=rate_limited)):
            with self.assertRaises(GitHubRateLimitError):
                await create_github_feature_branch("mock-token", "octocat", "repo", "feature/change")

        invalid_credential = MagicMock(status_code=401, headers={})
        with patch("services.github_service.httpx.AsyncClient.get", AsyncMock(return_value=invalid_credential)):
            with self.assertRaises(GitHubAuthenticationError):
                await create_github_feature_branch("mock-token", "octocat", "repo", "feature/change")

    async def test_feature_branch_endpoint_requires_authentication(self):
        from fastapi import HTTPException
        from routers.github import CreateFeatureBranchRequest, create_github_repository_branch

        with self.assertRaises(HTTPException) as ctx:
            await create_github_repository_branch(
                CreateFeatureBranchRequest(owner="octocat", repository="repo", branch_name="feature/change"),
                None,
            )
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_feature_branch_endpoint_uses_only_authenticated_users_integration(self):
        from routers.github import CreateFeatureBranchRequest, create_github_repository_branch

        payload = CreateFeatureBranchRequest(owner="octocat", repository="repo", branch_name="feature/change")
        with patch("routers.github.get_github_integration", AsyncMock(return_value={
            "encrypted_access_token": "ciphertext-for-user-alice"
        })) as lookup, \
             patch("routers.github.decrypt_token", return_value="alice-github-token") as decrypt, \
             patch("routers.github.create_github_feature_branch", AsyncMock(return_value={
                 "branch_name": "feature/change", "base_branch": "main"
             })) as create:
            result = await create_github_repository_branch(payload, "user-alice-123")

        lookup.assert_awaited_once_with("user-alice-123")
        decrypt.assert_called_once_with("ciphertext-for-user-alice")
        create.assert_awaited_once_with("alice-github-token", "octocat", "repo", "feature/change")
        self.assertEqual(result["branch_name"], "feature/change")

    def test_repositories_endpoint_decryption_failure_returns_reconnect_prompt(self):
        """When token ciphertext cannot be decrypted (e.g. rotated key), return clear 401 prompt"""
        from services.auth_service import get_authenticated_user_id
        app.dependency_overrides[get_authenticated_user_id] = lambda: "user-alice-123"
        try:
            with patch("routers.github.get_github_integration", AsyncMock(return_value={"encrypted_access_token": "corrupt_base64_data_1234567890"})):
                headers = {"Authorization": "Bearer mock-token"}
                res = client.get("/api/github/repositories", headers=headers)
                self.assertEqual(res.status_code, 401)
                self.assertIn("could not be decrypted", res.json()["detail"])
        finally:
            app.dependency_overrides.pop(get_authenticated_user_id, None)

    # --- 6. Disconnect Endpoint Integration ---

    def test_disconnect_deletes_stored_credentials_and_reports_revocation(self):
        from services.auth_service import get_authenticated_user_id
        app.dependency_overrides[get_authenticated_user_id] = lambda: "user-alice-123"
        try:
            with patch("routers.github.delete_github_integration", AsyncMock(return_value={"local_deleted": True, "upstream_revoked": True})) as mock_del:
                headers = {"Authorization": "Bearer mock-token"}
                res = client.delete("/api/github/disconnect", headers=headers)
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertIn("disconnected successfully", data["message"])
                self.assertTrue(data["local_deleted"])
                self.assertTrue(data["upstream_revoked"])
                mock_del.assert_called_once_with("user-alice-123")
        finally:
            app.dependency_overrides.pop(get_authenticated_user_id, None)

    def test_disconnect_reports_local_removal_when_upstream_revocation_fails(self):
        from services.auth_service import get_authenticated_user_id
        app.dependency_overrides[get_authenticated_user_id] = lambda: "user-alice-123"
        try:
            result = {"local_deleted": True, "upstream_revoked": False}
            with patch("routers.github.delete_github_integration", AsyncMock(return_value=result)):
                res = client.delete("/api/github/disconnect", headers={"Authorization": "Bearer mock-token"})
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data["local_deleted"])
            self.assertFalse(data["upstream_revoked"])
            self.assertIn("Revoke it in GitHub settings", data["message"])
        finally:
            app.dependency_overrides.pop(get_authenticated_user_id, None)

    def test_disconnect_response_preserves_revocation_result_when_local_row_missing(self):
        from services.auth_service import get_authenticated_user_id
        app.dependency_overrides[get_authenticated_user_id] = lambda: "user-alice-123"
        try:
            result = {"local_deleted": False, "upstream_revoked": True}
            with patch("routers.github.delete_github_integration", AsyncMock(return_value=result)):
                res = client.delete("/api/github/disconnect", headers={"Authorization": "Bearer mock-token"})
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertFalse(data["local_deleted"])
            self.assertTrue(data["upstream_revoked"])
            self.assertIn("not removed", data["message"])
            self.assertIn("was revoked", data["message"])
        finally:
            app.dependency_overrides.pop(get_authenticated_user_id, None)


class TestGitHubStarterFork(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.database = _FakeStudentProjectDatabase()
        self.user = {"login": "student-alice", "id": 321}
        self.student_repo_name = "trendhive-internsim-student-alice-321"
        self.starter = {"full_name": "Tanvi166/trendhive", "private": False}
        self.fork = {
            "id": 987654,
            "name": self.student_repo_name,
            "full_name": f"student-alice/{self.student_repo_name}",
            "html_url": f"https://github.com/student-alice/{self.student_repo_name}",
            "owner": {"login": "student-alice"},
            "fork": True,
            "parent": {"full_name": "Tanvi166/trendhive"},
            "default_branch": "main",
        }
        self.ready_ref = {"object": {"sha": "c" * 40}}

    @staticmethod
    def response(status, data=None, headers=None):
        if headers is None:
            headers = {"x-oauth-scopes": "repo, read:user"}
        return MagicMock(status_code=status, json=MagicMock(return_value=data), headers=headers)

    def with_database(self):
        return patch("services.github_service.get_supabase_client", return_value=self.database)

    async def test_starter_fork_is_created_in_authenticated_github_account(self):
        responses = [
            self.response(200, self.user),
            self.response(200, self.starter),
            self.response(404),
            self.response(404),
            self.response(200, self.fork),
            self.response(200, self.ready_ref),
        ]
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)) as get, \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock(return_value=self.response(201, self.fork))) as post:
            result = await create_or_get_student_starter_fork("user-alice", "alice-only-token")

        self.assertEqual(result, {
            "owner": "student-alice",
            "name": self.student_repo_name,
            "full_name": f"student-alice/{self.student_repo_name}",
            "url": f"https://github.com/student-alice/{self.student_repo_name}",
            "status": "ready",
        })
        self.assertEqual(get.await_args_list[0].args[0], "https://api.github.com/user")
        self.assertEqual(get.await_args_list[1].args[0], "https://api.github.com/repos/Tanvi166/trendhive")
        self.assertEqual(get.await_args_list[2].args[0], f"https://api.github.com/repos/student-alice/{self.student_repo_name}")
        self.assertEqual(get.await_args_list[3].args[0], "https://api.github.com/repos/student-alice/trendhive")
        self.assertEqual(post.await_args.args[0], "https://api.github.com/repos/Tanvi166/trendhive/forks")
        self.assertEqual(post.await_args.kwargs["json"], {"name": self.student_repo_name})
        self.assertEqual(post.await_args.kwargs["headers"]["Authorization"], "Bearer alice-only-token")
        self.assertEqual(self.database.rows[0]["user_id"], "user-alice")
        self.assertNotIn("token", self.database.rows[0])

    async def test_async_fork_is_persisted_as_pending_until_default_branch_exists(self):
        responses = [
            self.response(200, self.user), self.response(200, self.starter), self.response(404), self.response(404),
            self.response(200, self.fork), self.response(200, self.fork), self.response(404),
        ]
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock(return_value=self.response(202, {"message": "Accepted"}))):
            result = await create_or_get_student_starter_fork("user-alice", "alice-only-token")
        self.assertEqual(result["status"], "pending")
        self.assertEqual(self.database.rows[0]["status"], "pending")

    async def test_minimal_202_is_pending_and_a_retry_does_not_repeat_fork_creation(self):
        responses = [
            self.response(200, self.user), self.response(200, self.starter), self.response(404), self.response(404),
            self.response(404),
            self.response(200, self.user), self.response(200, self.starter), self.response(404), self.response(404),
        ]
        post_response = self.response(202, {"message": "Accepted"})
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock(return_value=post_response)) as post:
            first = await create_or_get_student_starter_fork("user-alice", "alice-only-token")
            second = await create_or_get_student_starter_fork("user-alice", "alice-only-token")

        self.assertEqual(first["status"], "pending")
        self.assertEqual(second["status"], "pending")
        self.assertEqual(self.database.rows, [])
        self.assertEqual(len(self.database.requests), 1)
        post.assert_awaited_once()

    async def test_pending_fork_lookup_saves_only_eventually_verified_repository(self):
        initial_gets = [
            self.response(200, self.user), self.response(200, self.starter), self.response(404), self.response(404),
            self.response(404),
        ]
        followup_gets = [
            self.response(200, self.user), self.response(200, self.starter), self.response(200, self.fork),
            self.response(200, self.fork), self.response(200, self.ready_ref),
        ]
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=initial_gets + followup_gets)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock(return_value=self.response(202, {}))) as post:
            pending = await create_or_get_student_starter_fork("user-alice", "alice-only-token")
            ready = await get_student_starter_fork_status("user-alice", "alice-only-token")

        self.assertEqual(pending["status"], "pending")
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(self.database.rows[0]["github_repository_id"], 987654)
        self.assertEqual(self.database.rows[0]["github_full_name"], f"student-alice/{self.student_repo_name}")
        self.assertEqual(self.database.requests, [])
        post.assert_awaited_once()

    async def test_202_lookup_with_invalid_parent_never_saves_repository_mapping(self):
        invalid_fork = {**self.fork, "parent": {"full_name": "someone-else/other-repo"}}
        responses = [
            self.response(200, self.user), self.response(200, self.starter), self.response(404), self.response(404),
            self.response(200, invalid_fork),
        ]
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock(return_value=self.response(202, {}))) as post:
            with self.assertRaises(GitHubForkConflictError):
                await create_or_get_student_starter_fork("user-alice", "alice-only-token")

        post.assert_awaited_once()
        self.assertEqual(self.database.rows, [])
        self.assertEqual(len(self.database.requests), 1)

    async def test_202_lookup_failure_keeps_intent_and_prevents_a_second_post(self):
        first_responses = [
            self.response(200, self.user), self.response(200, self.starter), self.response(404), self.response(404),
            self.response(500, {"message": "temporarily unavailable"}),
        ]
        retry_responses = [
            self.response(200, self.user), self.response(200, self.starter), self.response(404), self.response(404),
        ]
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=first_responses + retry_responses)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock(return_value=self.response(202, {}))) as post:
            with self.assertRaises(GitHubForkError):
                await create_or_get_student_starter_fork("user-alice", "alice-only-token")
            pending = await create_or_get_student_starter_fork("user-alice", "alice-only-token")

        self.assertEqual(pending["status"], "pending")
        self.assertEqual(self.database.rows, [])
        self.assertEqual(len(self.database.requests), 1)
        post.assert_awaited_once()

    async def test_missing_pending_request_table_logs_database_category_and_fails_before_fork_post(self):
        database = _MissingPendingRequestTableDatabase()
        github_responses = [
            self.response(200, self.user), self.response(200, self.starter),
            self.response(404), self.response(404),
        ]
        with patch("services.github_service.get_supabase_client", return_value=database), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=github_responses)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock()) as post, \
             self.assertLogs("services.github_service", level="ERROR") as logs:
            with self.assertRaises(GitHubStudentProjectStoreError):
                await create_or_get_student_starter_fork("user-alice", "alice-only-token")

        diagnostic = " ".join(logs.output)
        self.assertIn("operation=select_pending_fork_request", diagnostic)
        self.assertIn("category=_MockSupabaseDatabaseError", diagnostic)
        self.assertIn("code=PGRST205", diagnostic)
        self.assertIn("github_student_project_fork_requests", diagnostic)
        self.assertNotIn("alice-only-token", diagnostic)
        post.assert_not_awaited()

    async def test_existing_fork_is_reused_without_posting_a_duplicate(self):
        responses = [
            self.response(200, self.user), self.response(200, self.starter),
            self.response(200, self.fork), self.response(200, self.fork),
            self.response(200, self.ready_ref),
        ]
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock()) as post:
            result = await create_or_get_student_starter_fork("user-alice", "alice-only-token")
        self.assertEqual(result["status"], "ready")
        post.assert_not_awaited()

    async def test_create_conflict_recovers_only_verified_authenticated_users_starter_fork(self):
        responses = [
            self.response(200, self.user),
            self.response(200, self.starter),
            self.response(404),
            self.response(404),
            self.response(200, self.fork),
            self.response(200, self.fork),
            self.response(200, self.ready_ref),
        ]
        conflict = self.response(422, {"message": "Already forked; Authorization: Bearer ghp_mock_secret"})
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)) as get, \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock(return_value=conflict)) as post, \
             self.assertLogs("services.github_service", level="ERROR") as logs:
            result = await create_or_get_student_starter_fork("user-alice", "alice-only-token")

        self.assertEqual(result["full_name"], f"student-alice/{self.student_repo_name}")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(post.await_args.args[0], "https://api.github.com/repos/Tanvi166/trendhive/forks")
        self.assertEqual(get.await_args_list[4].args[0], f"https://api.github.com/repos/student-alice/{self.student_repo_name}")
        self.assertEqual(self.database.rows[0]["user_id"], "user-alice")
        self.assertEqual(self.database.rows[0]["github_repository_id"], 987654)
        diagnostic = " ".join(logs.output)
        self.assertIn("status=422", diagnostic)
        self.assertIn("Already forked", diagnostic)
        self.assertNotIn("ghp_mock_secret", diagnostic)

    async def test_preexisting_name_collision_logs_upstream_response_before_conflict(self):
        unrelated_repo = {**self.fork, "fork": False, "parent": None}
        responses = [
            self.response(200, self.user),
            self.response(200, self.starter),
            self.response(200, unrelated_repo),
        ]
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock()) as post, \
             self.assertLogs("services.github_service", level="ERROR") as logs:
            with self.assertRaises(GitHubForkConflictError):
                await create_or_get_student_starter_fork("user-alice", "alice-only-token")

        diagnostic = " ".join(logs.output)
        self.assertIn("operation=existing_repository_conflict", diagnostic)
        self.assertIn("status=200", diagnostic)
        self.assertNotIn("Authorization", diagnostic)
        post.assert_not_awaited()
        self.assertEqual(self.database.rows, [])

    async def test_create_conflict_does_not_map_fork_of_different_starter(self):
        unrelated_fork = {
            **self.fork,
            "parent": {"full_name": "someone-else/other-repository"},
        }
        responses = [
            self.response(200, self.user),
            self.response(200, self.starter),
            self.response(404),
            self.response(404),
            self.response(200, unrelated_fork),
        ]
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock(return_value=self.response(409))) as post:
            with self.assertRaises(GitHubForkConflictError):
                await create_or_get_student_starter_fork("user-alice", "alice-only-token")

        post.assert_awaited_once()
        self.assertEqual(self.database.rows, [])

    async def test_existing_copy_with_different_owner_is_rejected(self):
        other_owner_copy = {
            **self.fork,
            "full_name": f"someone-else/{self.student_repo_name}",
            "html_url": f"https://github.com/someone-else/{self.student_repo_name}",
            "owner": {"login": "someone-else"},
        }
        responses = [self.response(200, self.user), self.response(200, self.starter), self.response(200, other_owner_copy)]
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock()) as post:
            with self.assertRaises(GitHubForkConflictError):
                await create_or_get_student_starter_fork("user-alice", "alice-only-token")

        post.assert_not_awaited()
        self.assertEqual(self.database.rows, [])

    async def test_create_conflict_recovery_permission_error_is_not_misreported_as_conflict(self):
        responses = [
            self.response(200, self.user),
            self.response(200, self.starter),
            self.response(404),
            self.response(404),
            self.response(403, {"message": "Resource not accessible by integration"}),
        ]
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock(return_value=self.response(422))):
            with self.assertRaises(GitHubRepositoryAccessError):
                await create_or_get_student_starter_fork("user-alice", "alice-only-token")

        self.assertEqual(self.database.rows, [])

    async def test_success_status_with_invalid_fork_payload_logs_validation_reason_without_mapping(self):
        invalid_fork = {
            **self.fork,
            "parent": {"full_name": "different-owner/different-source"},
        }
        responses = [
            self.response(200, self.user), self.response(200, self.starter),
            self.response(404), self.response(404),
        ]
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock(return_value=self.response(201, invalid_fork))) as post, \
             self.assertLogs("services.github_service", level="ERROR") as logs:
            with self.assertRaises(GitHubForkError):
                await create_or_get_student_starter_fork("user-alice", "alice-only-token")

        post.assert_awaited_once()
        self.assertIn("status=201", " ".join(logs.output))
        self.assertIn("failed validation", " ".join(logs.output))
        self.assertEqual(self.database.rows, [])

    async def test_unexpected_fork_api_status_logs_sanitized_message_before_502_mapping(self):
        responses = [
            self.response(200, self.user), self.response(200, self.starter),
            self.response(404), self.response(404),
        ]
        api_failure = self.response(
            500,
            {
                "message": "upstream failed Authorization: Bearer ghp_mock_secret; "
                "GITHUB_TOKEN_ENCRYPTION_KEY=mock_encryption_key"
            },
        )
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock(return_value=api_failure)), \
             self.assertLogs("services.github_service", level="ERROR") as logs:
            with self.assertRaises(GitHubForkError):
                await create_or_get_student_starter_fork("user-alice", "alice-only-token")

        diagnostic = " ".join(logs.output)
        self.assertIn("status=500", diagnostic)
        self.assertIn("upstream failed", diagnostic)
        self.assertNotIn("ghp_mock_secret", diagnostic)
        self.assertNotIn("mock_encryption_key", diagnostic)
        self.assertEqual(self.database.rows, [])

    async def test_status_retry_promotes_pending_fork_to_ready(self):
        row = {
            "id": "mapping-alice", "user_id": "user-alice",
            "starter_owner": "Tanvi166", "starter_repository": "trendhive",
            "github_repository_id": 987654, "github_owner": "student-alice",
            "github_repository_name": self.student_repo_name,
            "github_full_name": f"student-alice/{self.student_repo_name}",
            "repository_url": f"https://github.com/student-alice/{self.student_repo_name}", "status": "pending",
        }
        self.database.rows.append(row)
        responses = [self.response(200, self.user), self.response(200, self.fork), self.response(200, self.ready_ref)]
        with self.with_database(), patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)):
            result = await get_student_starter_fork_status("user-alice", "alice-only-token")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(self.database.rows[0]["status"], "ready")

    async def test_same_name_non_fork_is_not_overwritten(self):
        unrelated_repo = {**self.fork, "fork": False, "parent": None}
        responses = [
            self.response(200, self.user), self.response(200, self.starter),
            self.response(404), self.response(200, unrelated_repo),
            self.response(200, self.fork), self.response(200, self.fork), self.response(200, self.ready_ref),
        ]
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock(return_value=self.response(202, {"message": "Accepted"}))) as post:
            result = await create_or_get_student_starter_fork("user-alice", "alice-only-token")
        post.assert_awaited_once()
        self.assertEqual(result["name"], self.student_repo_name)
        self.assertEqual(self.database.rows[0]["user_id"], "user-alice")

    async def test_legacy_valid_fork_is_recovered_without_creating_another_fork(self):
        legacy_fork = {
            **self.fork,
            "name": "trendhive",
            "full_name": "student-alice/trendhive",
            "html_url": "https://github.com/student-alice/trendhive",
        }
        responses = [
            self.response(200, self.user), self.response(200, self.starter),
            self.response(404), self.response(200, legacy_fork),
            self.response(200, legacy_fork), self.response(200, self.ready_ref),
        ]
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock()) as post:
            result = await create_or_get_student_starter_fork("user-alice", "alice-only-token")
        self.assertEqual(result["full_name"], "student-alice/trendhive")
        post.assert_not_awaited()
        self.assertEqual(self.database.rows[0]["user_id"], "user-alice")

    async def test_invalid_credentials_and_insufficient_permissions_fail_safely(self):
        with self.with_database(), patch(
            "services.github_service.httpx.AsyncClient.get",
            AsyncMock(return_value=self.response(401)),
        ):
            with self.assertRaises(GitHubAuthenticationError):
                await create_or_get_student_starter_fork("user-alice", "invalid-token")

        responses = [self.response(200, self.user), self.response(403, headers={"x-ratelimit-remaining": "1"})]
        with self.with_database(), patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)):
            with self.assertRaises(GitHubRepositoryAccessError):
                await create_or_get_student_starter_fork("user-alice", "read-only-token")

        user_without_repo_scope = self.response(200, self.user, headers={"x-oauth-scopes": "read:user"})
        responses = [user_without_repo_scope, self.response(200, self.starter)]
        with self.with_database(), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)), \
             patch("services.github_service.httpx.AsyncClient.post", AsyncMock()) as post:
            with self.assertRaises(GitHubRepositoryAccessError):
                await create_or_get_student_starter_fork("user-alice", "read-only-token")
        post.assert_not_awaited()

    async def test_github_rate_limit_is_safe_and_actionable(self):
        responses = [self.response(200, self.user), self.response(403, headers={"x-ratelimit-remaining": "0"})]
        with self.with_database(), patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)):
            with self.assertRaises(GitHubForkRateLimitError):
                await create_or_get_student_starter_fork("user-alice", "alice-only-token")

    async def test_mapping_lookup_never_returns_another_users_project(self):
        row = {
            "id": "mapping-alice", "user_id": "user-alice",
            "starter_owner": "Tanvi166", "starter_repository": "trendhive",
            "github_repository_id": 987654, "github_owner": "student-alice",
            "github_repository_name": "trendhive", "github_full_name": "student-alice/trendhive",
            "repository_url": "https://github.com/student-alice/trendhive", "status": "ready",
        }
        self.database.rows.append(row)
        with self.with_database(), patch("services.github_service.httpx.AsyncClient.get", AsyncMock()) as get:
            with self.assertRaises(GitHubForkNotFoundError):
                await get_student_starter_fork_status("user-bob", "bob-token")
        get.assert_not_awaited()

    async def test_endpoint_has_no_client_controlled_starter_and_uses_users_token(self):
        import inspect
        from routers.github import create_student_starter_fork

        self.assertEqual(list(inspect.signature(create_student_starter_fork).parameters), ["authenticated_user_id"])
        with patch("routers.github._get_authenticated_github_token", AsyncMock(return_value="alice-only-token")), \
             patch("routers.github.create_or_get_student_starter_fork", AsyncMock(return_value={
                 "owner": "student-alice", "name": "trendhive", "full_name": "student-alice/trendhive",
                 "url": "https://github.com/student-alice/trendhive", "status": "pending",
             })) as create:
            result = await create_student_starter_fork("user-alice")
        create.assert_awaited_once_with("user-alice", "alice-only-token")
        self.assertEqual(result["full_name"], "student-alice/trendhive")

    async def test_fork_endpoint_requires_connected_github_account(self):
        from fastapi import HTTPException
        from routers.github import create_student_starter_fork

        with patch("routers.github.get_github_integration", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await create_student_starter_fork("user-alice")
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_student_project_store_without_supabase_rpc_fails_closed(self):
        local_only_client = MagicMock(spec=["table"])
        with patch("services.github_service.get_supabase_client", return_value=local_only_client), \
             patch("services.github_service.httpx.AsyncClient.get", AsyncMock()) as get:
            with self.assertRaises(GitHubStudentProjectStoreError):
                await create_or_get_student_starter_fork("user-alice", "alice-token")
        local_only_client.table.assert_not_called()
        get.assert_not_awaited()

    async def test_api_server_failure_is_not_forwarded_as_upstream_detail(self):
        response = self.response(200, self.user)
        source_failure = self.response(500, {"message": "sensitive upstream response"})
        with self.with_database(), patch(
            "services.github_service.httpx.AsyncClient.get",
            AsyncMock(side_effect=[response, source_failure]),
        ):
            with self.assertRaises(Exception) as ctx:
                await create_or_get_student_starter_fork("user-alice", "alice-token")
        self.assertNotIn("sensitive upstream response", str(ctx.exception))

    async def test_token_helper_loads_only_authenticated_users_integration(self):
        from routers.github import _get_authenticated_github_token

        with patch("routers.github.get_github_integration", AsyncMock(return_value={
            "encrypted_access_token": "alice-ciphertext"
        })) as lookup, patch("routers.github.decrypt_token", return_value="alice-token") as decrypt:
            token = await _get_authenticated_github_token("user-alice")
        lookup.assert_awaited_once_with("user-alice")
        decrypt.assert_called_once_with("alice-ciphertext")
        self.assertEqual(token, "alice-token")


class TestGitHubStudentProjectFiles(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repository_name = "trendhive-internsim-student-alice-321"
        self.repository = {
            "id": 987654,
            "name": self.repository_name,
            "full_name": f"student-alice/{self.repository_name}",
            "html_url": f"https://github.com/student-alice/{self.repository_name}",
            "owner": {"login": "student-alice"},
            "fork": True,
            "parent": {"full_name": "Tanvi166/trendhive"},
            "default_branch": "main",
        }
        self.mapping = {
            "user_id": "internsim-alice",
            "starter_owner": "Tanvi166",
            "starter_repository": "trendhive",
            "github_repository_id": 987654,
            "github_owner": "student-alice",
            "github_repository_name": self.repository_name,
            "github_full_name": self.repository["full_name"],
            "repository_url": self.repository["html_url"],
            "status": "ready",
        }
        self.database = _FakeStudentProjectDatabase([dict(self.mapping)])

    @staticmethod
    def response(status, payload=None, headers=None):
        return MagicMock(
            status_code=status,
            json=MagicMock(return_value=payload),
            headers=headers or {},
        )

    def github_responses(self, final_response):
        return [
            self.response(200, {"login": "student-alice"}),
            self.response(200, self.repository),
            self.response(200, {"object": {"sha": "a" * 40}}),
            self.response(200, {"tree": {"sha": "b" * 40}}),
            final_response,
        ]

    def file_responses(self, final_response):
        return [
            self.response(200, {"login": "student-alice"}),
            self.response(200, self.repository),
            final_response,
        ]

    def with_database(self):
        return patch("services.github_service.get_supabase_client", return_value=self.database)

    async def test_nested_directory_listing_uses_only_user_mapped_fork(self):
        nested = self.response(200, {"tree": [
            {"path": "main.py", "type": "blob", "size": 42},
            {"path": "assets", "type": "tree", "sha": "c" * 40},
            {"path": ".env", "type": "blob", "size": 10},
        ], "truncated": False})
        responses = self.github_responses(self.response(200, {
            "tree": [{"path": "src", "type": "tree", "sha": "d" * 40}], "truncated": False
        }))[:-1] + [
            self.response(200, {"tree": [{"path": "src", "type": "tree", "sha": "d" * 40}], "truncated": False}),
            self.response(200, {"tree": [{"path": "nested", "type": "tree", "sha": "e" * 40}], "truncated": False}),
            nested,
        ]
        with self.with_database(), patch(
            "services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)
        ) as get:
            result = await list_student_project_files("internsim-alice", "alice-token", path="src/nested")

        self.assertEqual(result["repository"], self.mapping["github_full_name"])
        self.assertEqual([item["name"] for item in result["items"]], ["assets", "main.py"])
        self.assertEqual(result["items"][1]["path"], "src/nested/main.py")
        self.assertTrue(all("/repos/student-alice/" + self.repository_name in call.args[0] for call in get.await_args_list if "/git/" in call.args[0]))
        self.assertFalse(any("Tanvi166/trendhive/git" in call.args[0] for call in get.await_args_list))

    async def test_mapping_is_scoped_to_authenticated_internalsim_user(self):
        with self.with_database(), patch("services.github_service.httpx.AsyncClient.get", AsyncMock()) as get:
            with self.assertRaises(GitHubForkNotFoundError):
                await list_student_project_files("internsim-bob", "bob-token")
        get.assert_not_awaited()

    async def test_connected_account_must_match_mapping_owner(self):
        responses = self.github_responses(self.response(200, {"tree": [], "truncated": False}))
        responses[0] = self.response(200, {"login": "someone-else"})
        with self.with_database(), patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=responses)):
            with self.assertRaises(GitHubRepositoryAccessError):
                await list_student_project_files("internsim-alice", "other-account-token")

    async def test_file_retrieval_returns_text_from_mapped_repository(self):
        import base64 as _base64
        content_response = self.response(200, {
            "type": "file", "size": 12, "encoding": "base64",
            "content": _base64.b64encode(b"print('hi')\n").decode("ascii"),
        })
        with self.with_database(), patch(
            "services.github_service.httpx.AsyncClient.get",
            AsyncMock(side_effect=self.file_responses(content_response)),
        ) as get:
            result = await get_student_project_file("internsim-alice", "alice-token", "src/main.py")
        self.assertEqual(result["content"], "print('hi')\n")
        self.assertIn(f"/repos/student-alice/{self.repository_name}/contents/src/main.py?ref=main", get.await_args.args[0])

    async def test_invalid_path_is_rejected_before_database_or_github_access(self):
        with patch("services.github_service.get_supabase_client") as db, patch(
            "services.github_service.httpx.AsyncClient.get", AsyncMock()
        ) as get:
            for path in ("../secret", "src/../../secret", "C:/secret", ".env", "src\\file.py"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    await get_student_project_file("internsim-alice", "alice-token", path)
        db.assert_not_called()
        get.assert_not_awaited()

    async def test_missing_file_and_directory_are_reported_safely(self):
        for status, payload, expected in (
            (404, None, GitHubStudentProjectFileNotFoundError),
            (200, [{"type": "file", "name": "nested.py"}], GitHubStudentProjectPathIsDirectoryError),
        ):
            with self.subTest(status=status), self.with_database(), patch(
                "services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=self.file_responses(self.response(status, payload)))
            ):
                with self.assertRaises(expected):
                    await get_student_project_file("internsim-alice", "alice-token", "src")

    async def test_binary_and_oversized_files_are_rejected(self):
        import base64 as _base64
        scenarios = (
            ({"type": "file", "size": 2, "encoding": "base64", "content": _base64.b64encode(b"\0x").decode()}, GitHubStudentProjectBinaryFileError),
            ({"type": "file", "size": 1_000_001, "encoding": "base64", "content": "eA=="}, GitHubStudentProjectFileTooLargeError),
        )
        for payload, expected in scenarios:
            with self.subTest(expected=expected.__name__), self.with_database(), patch(
                "services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=self.file_responses(self.response(200, payload)))
            ):
                with self.assertRaises(expected):
                    await get_student_project_file("internsim-alice", "alice-token", "src/data.txt")

    async def test_truncated_tree_and_github_api_failure_are_safe(self):
        truncated_responses = self.github_responses(self.response(200, {"tree": [], "truncated": True}))
        with self.with_database(), patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=truncated_responses)):
            with self.assertRaises(GitHubStudentProjectListingTooLargeError):
                await list_student_project_files("internsim-alice", "alice-token")

        failed = self.github_responses(self.response(403, {"message": "sensitive upstream detail"}, {"x-ratelimit-remaining": "0"}))
        with self.with_database(), patch("services.github_service.httpx.AsyncClient.get", AsyncMock(side_effect=failed)):
            with self.assertRaises(GitHubForkRateLimitError):
                await list_student_project_files("internsim-alice", "alice-token")

    async def test_file_routes_require_authentication_and_bind_user_token(self):
        from fastapi import HTTPException
        from routers.github import get_student_project_files, get_student_project_file_content

        for endpoint, kwargs in ((get_student_project_files, {}), (get_student_project_file_content, {"path": "main.py"})):
            with self.subTest(endpoint=endpoint.__name__), self.assertRaises(HTTPException) as ctx:
                await endpoint(authenticated_user_id=None, **kwargs)
            self.assertEqual(ctx.exception.status_code, 401)

        with patch("routers.github._get_authenticated_github_token", AsyncMock(return_value="alice-token")) as token, \
             patch("routers.github.list_student_project_files", AsyncMock(return_value={"repository": "alice/repo"})) as listing:
            await get_student_project_files(path="src", page=1, page_size=100, authenticated_user_id="internsim-alice")
        token.assert_awaited_once_with("internsim-alice")
        listing.assert_awaited_once_with("internsim-alice", "alice-token", path="src", page=1, page_size=100)

    async def test_repository_run_revalidates_mapping_and_executes_submitted_draft_buffers(self):
        from routers.github import StudentProjectRunRequest, run_student_project_draft
        from models import CodeRunResult
        draft_files = {"app.py": "print('draft app')", "src/helper.py": "VALUE = 'draft helper'"}
        request = StudentProjectRunRequest(
            language="python", code=draft_files["app.py"], files=draft_files, stdin=""
        )
        with patch("routers.github._get_authenticated_github_token", AsyncMock(return_value="alice-token")) as token, \
             patch("routers.github.verify_student_project_repository_access", AsyncMock(return_value=self.mapping)) as verify, \
             patch("routers.github.run_code_preview_with_options", AsyncMock(return_value=CodeRunResult(
                 stdout="draft app", stderr="", exit_code=0, timed_out=False, error=None
             ))) as run:
            result = await run_student_project_draft(request, authenticated_user_id="internsim-alice")

        token.assert_awaited_once_with("internsim-alice")
        verify.assert_awaited_once_with("internsim-alice", "alice-token")
        run_request = run.await_args.args[0]
        self.assertEqual(run_request.code, "print('draft app')")
        self.assertEqual(run_request.files, draft_files)
        self.assertFalse(run.await_args.kwargs["allow_local_fallback"])
        self.assertEqual(result.stdout, "draft app")

    async def test_repository_run_rejects_unsafe_file_paths_before_token_lookup(self):
        from fastapi import HTTPException
        from routers.github import StudentProjectRunRequest, run_student_project_draft
        request = StudentProjectRunRequest(language="python", code="pass", files={"../outside.py": "pass"})
        with patch("routers.github._get_authenticated_github_token", AsyncMock()) as token:
            with self.assertRaises(HTTPException) as ctx:
                await run_student_project_draft(request, authenticated_user_id="internsim-alice")
        self.assertEqual(ctx.exception.status_code, 400)
        token.assert_not_awaited()

    async def test_repository_run_rejects_unauthenticated_requests(self):
        from fastapi import HTTPException
        from routers.github import StudentProjectRunRequest, run_student_project_draft
        request = StudentProjectRunRequest(language="python", code="pass", files={"main.py": "pass"})
        with self.assertRaises(HTTPException) as ctx:
            await run_student_project_draft(request, authenticated_user_id=None)
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_repository_run_never_uses_local_python_subprocess_fallback(self):
        from services.piston_service import execute_code
        with patch("services.piston_service.httpx.AsyncClient.post", AsyncMock(side_effect=TimeoutError("offline"))), \
             patch("services.piston_service.subprocess.run") as local_run:
            result = await execute_code(
                "python", "3.10.0", "print('draft')", files=[{"name": "main.py", "content": "print('draft')"}],
                allow_local_fallback=False,
            )
        local_run.assert_not_called()
        self.assertEqual(result["run"]["code"], -1)
        self.assertIn("local execution fallback is disabled", result["run"]["stderr"])

if __name__ == "__main__":
    unittest.main()
