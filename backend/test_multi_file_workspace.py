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
                    t.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{
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
                    t.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{
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

if __name__ == "__main__":
    unittest.main()
