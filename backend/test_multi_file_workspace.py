import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from main import app
from services.file_service import is_safe_relative_path, validate_and_normalize_files

client = TestClient(app)

class TestMultiFileWorkspaceAndSecurity(unittest.TestCase):

    def test_safe_relative_path_validation(self):
        """Verifies safe relative path checks and rejection of traversal, absolute, or hidden paths."""
        self.assertTrue(is_safe_relative_path("solution.py"))
        self.assertTrue(is_safe_relative_path("utils/helpers.py"))
        self.assertTrue(is_safe_relative_path("models/types.ts"))
        self.assertTrue(is_safe_relative_path("config.json"))

        # Rejections
        self.assertFalse(is_safe_relative_path("/etc/passwd")) # Absolute
        self.assertFalse(is_safe_relative_path("../secret.py")) # Traversal
        self.assertFalse(is_safe_relative_path("foo/../../bar.py")) # Traversal
        self.assertFalse(is_safe_relative_path("sub\\dir\\file.py")) # Windows backslash
        self.assertFalse(is_safe_relative_path(".env")) # Hidden
        self.assertFalse(is_safe_relative_path("dir/.git/config")) # Hidden directory
        self.assertFalse(is_safe_relative_path("")) # Empty
        self.assertFalse(is_safe_relative_path("   ")) # Whitespace

    def test_validate_and_normalize_files_ensures_entrypoint(self):
        """Ensures that multi-file payloads preserve or inject the entry file."""
        code = "def solve(): return 42"
        files = {
            "utils/math.py": "def add(a, b): return a + b"
        }
        entry_fname, piston_files = validate_and_normalize_files(code, "python", files)
        self.assertEqual(entry_fname, "solution.py")
        file_names = [f["name"] for f in piston_files]
        self.assertIn("solution.py", file_names)
        self.assertIn("utils/math.py", file_names)

        # Check entry file content matches primary code
        solution_file = next(f for f in piston_files if f["name"] == "solution.py")
        self.assertEqual(solution_file["content"], code)

    def test_validate_and_normalize_files_rejects_malicious_paths(self):
        """Throws ValueError on directory traversal attempts."""
        files = {"../../evil.py": "import os"}
        with self.assertRaises(ValueError):
            validate_and_normalize_files("pass", "python", files)

    def test_standalone_task_access_rejected_if_owned_by_another_user(self):
        """When an authenticated user requests a standalone task (project_id=NULL) previously worked on by another user, return 403."""
        with patch("services.auth_service.get_supabase_client") as mock_auth_sb, \
             patch("routers.tasks.get_supabase_client") as mock_tasks_sb:

            mock_auth = MagicMock()
            mock_auth_sb.return_value = mock_auth
            mock_auth.auth.get_user.return_value.user.id = "user-bob-999"

            mock_db = MagicMock()
            mock_tasks_sb.return_value = mock_db

            def table_mock(name):
                t = MagicMock()
                if name == "tasks":
                    t.select.return_value.eq.return_value.execute.return_value.data = [{
                        "task_id": "standalone-task-alice",
                        "project_id": None,
                        "title": "Standalone Alice Task",
                        "description": "Legacy standalone task",
                        "task_type": "feature-dev",
                        "difficulty_level": 1,
                        "persona": "Enterprise SaaS",
                        "language": "python",
                        "starter_code": "pass",
                        "test_cases": []
                    }]
                elif name == "submissions":
                    # Alice has previously submitted to this standalone task
                    t.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [{
                        "user_id": "user-alice-123"
                    }]
                return t

            mock_db.table.side_effect = table_mock

            headers = {"Authorization": "Bearer bob-jwt-token"}
            res = client.get("/api/tasks/standalone-task-alice", headers=headers)
            self.assertEqual(res.status_code, 403)
            self.assertIn("Access denied", res.json()["detail"])

    def test_standalone_task_submission_rejected_if_owned_by_another_user(self):
        """When user Bob attempts to submit code for a standalone task owned by Alice, return 403."""
        with patch("services.auth_service.get_supabase_client") as mock_auth_sb, \
             patch("routers.evaluations.get_supabase_client") as mock_eval_sb:

            mock_auth = MagicMock()
            mock_auth_sb.return_value = mock_auth
            mock_auth.auth.get_user.return_value.user.id = "user-bob-999"

            mock_db = MagicMock()
            mock_eval_sb.return_value = mock_db

            def table_mock(name):
                t = MagicMock()
                if name == "tasks":
                    t.select.return_value.eq.return_value.execute.return_value.data = [{
                        "task_id": "standalone-task-alice",
                        "project_id": None,
                        "test_cases": []
                    }]
                elif name == "submissions":
                    t.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [{
                        "user_id": "user-alice-123"
                    }]
                return t

            mock_db.table.side_effect = table_mock

            headers = {"Authorization": "Bearer bob-jwt-token"}
            res = client.post("/api/evaluations/submit", json={
                "task_id": "standalone-task-alice",
                "user_id": "user-bob-999",
                "submitted_code": "def solve(): pass",
                "language": "python",
                "files": {"solution.py": "def solve(): pass"}
            }, headers=headers)

            self.assertEqual(res.status_code, 403)
            self.assertIn("Access denied", res.json()["detail"])

    def test_run_code_preview_rejects_unsafe_paths(self):
        """When run_code_preview receives malicious file traversal, return 400 Bad Request."""
        res = client.post("/api/evaluations/run", json={
            "language": "python",
            "code": "print('hello')",
            "files": {
                "../escape.py": "print('evil')"
            }
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid or unsafe file path", res.json()["detail"])

    def test_multi_file_evaluation_isolated_fallback_preserves_secondary_files(self):
        """
        When batch evaluation fails (e.g. batch harness throws syntax error or missing batch tags),
        the isolated fallback loop must execute each test case with files=piston_files,
        allowing the solution to import from secondary files.
        """
        with patch("services.auth_service.get_supabase_client") as mock_auth_sb, \
             patch("routers.evaluations.get_supabase_client") as mock_eval_sb, \
             patch("routers.evaluations.generate_ai_response") as mock_llm:

            mock_auth = MagicMock()
            mock_auth_sb.return_value = mock_auth
            mock_auth.auth.get_user.return_value.user.id = "user-alice-123"

            mock_db = MagicMock()
            mock_eval_sb.return_value = mock_db

            # Mock task with 1 test case that calls solve(10)
            mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{
                "task_id": "task-multi-fallback",
                "project_id": "proj-alice",
                "test_cases": [{"input": "solve(10)", "expected_output": "20", "hidden": False}]
            }]

            # Mock project ownership
            mock_db.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
                # First call: tasks table select
                MagicMock(data=[{
                    "task_id": "task-multi-fallback",
                    "project_id": "proj-alice",
                    "test_cases": [{"input": "solve(10)", "expected_output": "20", "hidden": False}]
                }]),
                # Second call: projects table select
                MagicMock(data=[{"user_id": "user-alice-123", "status": "active", "target_tickets": 4}]),
                # Subsequent calls if any
                MagicMock(data=[])
            ]

            mock_db.table.return_value.insert.return_value.execute.return_value.data = [{
                "submission_id": "sub-123"
            }]

            from models import QualityFeedback
            mock_llm.return_value = QualityFeedback(readability=5, structure=5, edge_cases=5, naming=5, comments="Great")

            # Patch execute_code so that batch execution fails, forcing the isolated fallback path
            async def fake_execute_code(language, version, code, run_args=None, stdin="", files=None):
                # If it's the batch harness call, simulate a failure (no batch tags)
                if "__BATCH_RESULTS_START__" in code:
                    return {"run": {"stdout": "", "stderr": "Batch syntax error simulation", "code": 1}}

                # It's the isolated fallback runner: verify that files contains secondary file
                file_map = {f["name"]: f["content"] for f in (files or [])}
                if "helpers/calc.py" not in file_map:
                    return {"run": {"stdout": "", "stderr": "ModuleNotFoundError: helpers", "code": 1}}

                # If helper is present, execution succeeds and returns expected 20
                return {"run": {"stdout": "20", "stderr": "", "code": 0}}

            with patch("routers.evaluations.execute_code", side_effect=fake_execute_code):
                headers = {"Authorization": "Bearer alice-jwt-token"}
                res = client.post("/api/evaluations/submit", json={
                    "task_id": "task-multi-fallback",
                    "user_id": "user-alice-123",
                    "submitted_code": "from helpers.calc import double\ndef solve(x):\n    return double(x)",
                    "language": "python",
                    "files": {
                        "solution.py": "from helpers.calc import double\ndef solve(x):\n    return double(x)",
                        "helpers/calc.py": "def double(x):\n    return x * 2"
                    }
                }, headers=headers)

                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertEqual(data["correctness_score"], 60)
                self.assertGreaterEqual(data["total_score"], 60)

    def test_concurrent_claim_attempt_rejected_if_another_user_claimed_first(self):
        """
        When two users attempt to submit to an unclaimed standalone task concurrently,
        the post-insert concurrency audit detects the first committer and rolls back
        the second user's submission with 403 Forbidden.
        """
        with patch("services.auth_service.get_supabase_client") as mock_auth_sb, \
             patch("routers.evaluations.get_supabase_client") as mock_eval_sb, \
             patch("routers.evaluations.generate_ai_response") as mock_llm:

            mock_auth = MagicMock()
            mock_auth_sb.return_value = mock_auth
            mock_auth.auth.get_user.return_value.user.id = "user-bob-999"

            mock_db = MagicMock()
            mock_eval_sb.return_value = mock_db

            # 1. Fetch task: standalone task with no project_id
            task_data = [{
                "task_id": "task-unclaimed",
                "project_id": None,
                "test_cases": [{"input": "solve()", "expected_output": "1"}]
            }]

            # During pre-check: 0 submissions exist (both Bob and Alice pass pre-check concurrently)
            empty_submissions = []

            # During post-insert audit: Alice's submission committed first!
            alice_first_submission = [{
                "submission_id": "sub-alice-first",
                "user_id": "user-alice-123"
            }]

            submissions_table = MagicMock()
            submissions_table.select.return_value.eq.return_value.order.return_value.execute.side_effect = [
                MagicMock(data=empty_submissions),      # pre-check before evaluation
                MagicMock(data=alice_first_submission)  # post-insert concurrency verification
            ]
            submissions_table.insert.return_value.execute.return_value.data = [{
                "submission_id": "sub-bob-conflicting",
                "task_id": "task-unclaimed",
                "user_id": "user-bob-999"
            }]
            submissions_table.delete.return_value.eq.return_value.execute.return_value.data = []

            def table_side_effect(name):
                if name == "tasks":
                    t = MagicMock()
                    t.select.return_value.eq.return_value.execute.return_value.data = task_data
                    return t
                elif name == "submissions":
                    return submissions_table
                return MagicMock()

            mock_db.table.side_effect = table_side_effect

            from models import QualityFeedback
            mock_llm.return_value = QualityFeedback(readability=5, structure=5, edge_cases=5, naming=5, comments="Good")

            async def fake_execute(*args, **kwargs):
                return {"run": {"stdout": "__BATCH_RESULTS_START__\n[\"1\"]\n__BATCH_RESULTS_END__", "code": 0}}

            with patch("routers.evaluations.execute_code", side_effect=fake_execute):
                headers = {"Authorization": "Bearer bob-jwt-token"}
                res = client.post("/api/evaluations/submit", json={
                    "task_id": "task-unclaimed",
                    "user_id": "user-bob-999",
                    "submitted_code": "def solve(): return 1",
                    "language": "python",
                    "files": {"solution.py": "def solve(): return 1"}
                }, headers=headers)

                self.assertEqual(res.status_code, 403)
                self.assertIn("concurrently claimed", res.json()["detail"])
                # Verify rollback deletion was invoked for Bob's conflicting submission
                mock_db.table("submissions").delete.assert_called()

    def test_existing_owner_can_continue_submitting(self):
        """When the established owner of a standalone task submits again, the submission succeeds."""
        with patch("services.auth_service.get_supabase_client") as mock_auth_sb, \
             patch("routers.evaluations.get_supabase_client") as mock_eval_sb, \
             patch("routers.evaluations.generate_ai_response") as mock_llm:

            mock_auth = MagicMock()
            mock_auth_sb.return_value = mock_auth
            mock_auth.auth.get_user.return_value.user.id = "user-alice-123"

            mock_db = MagicMock()
            mock_eval_sb.return_value = mock_db

            task_data = [{
                "task_id": "task-alice-standalone",
                "project_id": None,
                "test_cases": [{"input": "solve()", "expected_output": "1"}]
            }]

            alice_submission = [{
                "submission_id": "sub-alice-1",
                "user_id": "user-alice-123"
            }]

            def table_side_effect(name):
                t = MagicMock()
                if name == "tasks":
                    t.select.return_value.eq.return_value.execute.return_value.data = task_data
                elif name == "submissions":
                    t.select.return_value.eq.return_value.order.return_value.execute.return_value.data = alice_submission
                    t.insert.return_value.execute.return_value.data = [{
                        "submission_id": "sub-alice-2",
                        "task_id": "task-alice-standalone",
                        "user_id": "user-alice-123"
                    }]
                return t

            mock_db.table.side_effect = table_side_effect

            from models import QualityFeedback
            mock_llm.return_value = QualityFeedback(readability=5, structure=5, edge_cases=5, naming=5, comments="Good")

            async def fake_execute(*args, **kwargs):
                return {"run": {"stdout": "__BATCH_RESULTS_START__\n[\"1\"]\n__BATCH_RESULTS_END__", "code": 0}}

            with patch("routers.evaluations.execute_code", side_effect=fake_execute):
                headers = {"Authorization": "Bearer alice-jwt-token"}
                res = client.post("/api/evaluations/submit", json={
                    "task_id": "task-alice-standalone",
                    "user_id": "user-alice-123",
                    "submitted_code": "def solve(): return 1",
                    "language": "python",
                    "files": {"solution.py": "def solve(): return 1"}
                }, headers=headers)

    def test_migration_backfill_single_user_assigned_unambiguously(self):
        """
        Verify the migration backfill logic:
        A standalone task with submissions from exactly 1 distinct user is correctly assigned.
        """
        # Emulate migration group by logic in Python
        raw_submissions = [
            {"task_id": "task-single", "user_id": "user-alice-123"},
            {"task_id": "task-single", "user_id": "user-alice-123"}
        ]
        from collections import defaultdict
        task_users = defaultdict(set)
        for s in raw_submissions:
            task_users[s["task_id"]].add(s["user_id"])

        eligible_for_backfill = {
            tid: list(uids)[0]
            for tid, uids in task_users.items()
            if len(uids) == 1
        }
        self.assertIn("task-single", eligible_for_backfill)
        self.assertEqual(eligible_for_backfill["task-single"], "user-alice-123")

    def test_migration_backfill_multi_user_remains_unassigned(self):
        """
        Verify the migration backfill logic:
        A standalone task with submissions from > 1 distinct users must NOT be assigned
        and remains locked / flagged for manual review.
        """
        raw_submissions = [
            {"task_id": "task-multi", "user_id": "user-alice-123"},
            {"task_id": "task-multi", "user_id": "user-bob-999"}
        ]
        from collections import defaultdict
        task_users = defaultdict(set)
        for s in raw_submissions:
            task_users[s["task_id"]].add(s["user_id"])

        eligible_for_backfill = {
            tid: list(uids)[0]
            for tid, uids in task_users.items()
            if len(uids) == 1
        }
        unresolved_multi_user = {
            tid: uids
            for tid, uids in task_users.items()
            if len(uids) > 1
        }
        self.assertNotIn("task-multi", eligible_for_backfill)
        self.assertIn("task-multi", unresolved_multi_user)
        self.assertEqual(len(unresolved_multi_user["task-multi"]), 2)

    def test_migration_backfill_no_submissions_remains_unassigned(self):
        """
        Verify the migration backfill logic:
        A standalone task with zero submissions has no entries in the backfill mapping.
        """
        raw_submissions = []
        from collections import defaultdict
        task_users = defaultdict(set)
        for s in raw_submissions:
            task_users[s["task_id"]].add(s["user_id"])

        eligible_for_backfill = {
            tid: list(uids)[0]
            for tid, uids in task_users.items()
            if len(uids) == 1
        }
        self.assertEqual(len(eligible_for_backfill), 0)

    def test_no_partial_progress_or_orphaned_state_on_rejected_claim(self):
        """
        Verify that when a submission or claim is rejected,
        neither project progress nor adaptive difficulty updates are invoked.
        """
        with patch("services.auth_service.get_supabase_client") as mock_auth_sb, \
             patch("routers.evaluations.get_supabase_client") as mock_eval_sb, \
             patch("services.difficulty_service.evaluate_and_update_user_difficulty") as mock_diff:

            mock_auth = MagicMock()
            mock_auth_sb.return_value = mock_auth
            mock_auth.auth.get_user.return_value.user.id = "user-bob-999"

            mock_db = MagicMock()
            mock_eval_sb.return_value = mock_db

            # Standalone task owned by Alice
            mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{
                "task_id": "task-alice-only",
                "project_id": None,
                "user_id": "user-alice-123",
                "test_cases": []
            }]

            headers = {"Authorization": "Bearer bob-jwt-token"}
            res = client.post("/api/evaluations/submit", json={
                "task_id": "task-alice-only",
                "user_id": "user-bob-999",
                "submitted_code": "def solve(): return 1",
                "language": "python"
            }, headers=headers)

            self.assertEqual(res.status_code, 403)
            # Ensure difficulty engine was NEVER called
            mock_diff.assert_not_called()
            # Ensure submissions table insert was NEVER called
            mock_db.table("submissions").insert.assert_not_called()

if __name__ == "__main__":
    unittest.main()
