import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from main import app
from models import Task, TaskGenerateRequest, TestCase

client = TestClient(app)

class TestProjectBasedTicketManagement(unittest.TestCase):

    def test_unauthenticated_request_generates_standalone_task(self):
        """When no Authorization header is provided, task generation proceeds standalone."""
        mock_task = Task(
            title="Standalone Ticket",
            description="Build a standalone utility.",
            task_type="feature-dev",
            difficulty_level=1,
            persona="Enterprise SaaS",
            language="python",
            starter_code="def standalone(): pass",
            test_cases=[TestCase(input="1", expected_output="1", hidden=False)]
        )

        with patch("routers.tasks.generate_ai_response", return_value=mock_task) as mock_llm, \
             patch("routers.tasks.get_supabase_client") as mock_supabase:
            
            mock_db = MagicMock()
            mock_supabase.return_value = mock_db
            mock_db.table.return_value.insert.return_value.execute.return_value.data = [{
                "task_id": "mock-task-id-1",
                "project_id": None,
                "title": mock_task.title,
                "description": mock_task.description,
                "task_type": mock_task.task_type,
                "difficulty_level": mock_task.difficulty_level,
                "persona": mock_task.persona,
                "language": mock_task.language,
                "starter_code": mock_task.starter_code
            }]

            response = client.post("/api/tasks/generate", json={
                "skill_level": "Beginner",
                "persona": "Enterprise SaaS",
                "difficulty_level": 1,
                "task_type": "feature-dev",
                "language": "python",
                "include_continuity": True
            })

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["task_id"], "mock-task-id-1")
            
            prompt_called = mock_llm.call_args[0][0]
            self.assertNotIn("CONTEXT FROM PREVIOUS COMPLETED TICKET", prompt_called)

    def test_project_ownership_verification_rejects_unowned_project(self):
        """When user attempts to generate a ticket for a project they do NOT own, return 403 Forbidden."""
        with patch("services.auth_service.get_supabase_client") as mock_auth_sb, \
             patch("routers.tasks.get_supabase_client") as mock_tasks_sb:
            
            user_res = MagicMock()
            user_res.user.id = "user-alice-123"
            mock_auth_sb.return_value.auth.get_user.return_value = user_res

            mock_db = MagicMock()
            mock_tasks_sb.return_value = mock_db
            # Project belongs to Bob
            mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{
                "project_id": "project-bob-456",
                "user_id": "user-bob-999",
                "title": "Bob's Project",
                "description": "Bob's private domain."
            }]

            headers = {"Authorization": "Bearer valid-jwt-token"}
            response = client.post("/api/tasks/generate", json={
                "skill_level": "Beginner",
                "persona": "Enterprise SaaS",
                "difficulty_level": 1,
                "task_type": "feature-dev",
                "language": "python",
                "project_id": "project-bob-456",
                "include_continuity": True
            }, headers=headers)

            self.assertEqual(response.status_code, 403)
            self.assertIn("Access denied: You do not own this project", response.json()["detail"])

    def test_same_project_continuity_passes_previous_code(self):
        """Tickets belonging to the same project inherit previous passed submission in that project."""
        mock_task = Task(
            title="Follow-up Ticket",
            description="Extend project auth module.",
            task_type="feature-dev",
            difficulty_level=2,
            persona="Enterprise SaaS",
            language="python",
            starter_code="def base_auth(): pass\ndef new_oauth(): pass",
            test_cases=[TestCase(input="test", expected_output="test", hidden=False)]
        )

        with patch("services.auth_service.get_supabase_client") as mock_auth_sb, \
             patch("routers.tasks.generate_ai_response", return_value=mock_task) as mock_llm, \
             patch("routers.tasks.get_supabase_client") as mock_tasks_sb:
            
            user_res = MagicMock()
            user_res.user.id = "user-alice-123"
            mock_auth_sb.return_value.auth.get_user.return_value = user_res

            mock_db = MagicMock()
            mock_tasks_sb.return_value = mock_db

            def table_mock(name):
                t = MagicMock()
                if name == "projects":
                    t.select.return_value.eq.return_value.execute.return_value.data = [{
                        "project_id": "project-alpha",
                        "user_id": "user-alice-123",
                        "title": "Alpha Platform Project",
                        "description": "Multi-tenant auth core."
                    }]
                elif name == "tasks":
                    t.select.return_value.eq.return_value.execute.return_value.data = [
                        {"task_id": "task-alpha-1"}
                    ]
                    t.insert.return_value.execute.return_value.data = [{
                        "task_id": "task-alpha-2",
                        "project_id": "project-alpha",
                        "title": mock_task.title,
                        "description": mock_task.description,
                        "task_type": mock_task.task_type,
                        "difficulty_level": mock_task.difficulty_level,
                        "persona": mock_task.persona,
                        "language": mock_task.language,
                        "starter_code": mock_task.starter_code
                    }]
                elif name == "submissions":
                    t.select.return_value.eq.return_value.in_.return_value.eq.return_value.gte.return_value.order.return_value.limit.return_value.execute.return_value.data = [{
                        "submitted_code": "def base_auth(): return True",
                        "language": "python",
                        "tasks": {
                            "title": "Base Auth Model",
                            "description": "Created base auth."
                        }
                    }]
                return t

            mock_db.table.side_effect = table_mock

            headers = {"Authorization": "Bearer valid-jwt-token"}
            response = client.post("/api/tasks/generate", json={
                "skill_level": "Intermediate",
                "persona": "Enterprise SaaS",
                "difficulty_level": 2,
                "task_type": "feature-dev",
                "language": "python",
                "project_id": "project-alpha",
                "include_continuity": True
            }, headers=headers)

            self.assertEqual(response.status_code, 200)
            prompt_called = mock_llm.call_args[0][0]
            self.assertIn("CONTEXT FROM PREVIOUS COMPLETED TICKET", prompt_called)
            self.assertIn("Alpha Platform Project", prompt_called)
            self.assertIn("def base_auth(): return True", prompt_called)

    def test_first_ticket_of_new_project_starts_clean_without_leakage(self):
        """Ticket 1 of a new project (no prior tasks/submissions in that project) does not inherit code from older projects."""
        mock_task = Task(
            title="Clean New Architecture",
            description="Start brand new clean module.",
            task_type="feature-dev",
            difficulty_level=1,
            persona="Enterprise SaaS",
            language="python",
            starter_code="def new_module(): pass",
            test_cases=[TestCase(input="1", expected_output="1", hidden=False)]
        )

        with patch("services.auth_service.get_supabase_client") as mock_auth_sb, \
             patch("routers.tasks.generate_ai_response", return_value=mock_task) as mock_llm, \
             patch("routers.tasks.get_supabase_client") as mock_tasks_sb:
            
            user_res = MagicMock()
            user_res.user.id = "user-alice-123"
            mock_auth_sb.return_value.auth.get_user.return_value = user_res

            mock_db = MagicMock()
            mock_tasks_sb.return_value = mock_db

            def table_mock(name):
                t = MagicMock()
                if name == "projects":
                    t.select.return_value.eq.return_value.execute.return_value.data = [{
                        "project_id": "project-beta",
                        "user_id": "user-alice-123",
                        "title": "Beta Clean Project",
                        "description": "Brand new billing pipeline."
                    }]
                elif name == "tasks":
                    # Project Beta has no tasks yet
                    t.select.return_value.eq.return_value.execute.return_value.data = []
                    t.insert.return_value.execute.return_value.data = [{
                        "task_id": "task-beta-1",
                        "project_id": "project-beta",
                        "title": mock_task.title,
                        "description": mock_task.description,
                        "task_type": mock_task.task_type,
                        "difficulty_level": mock_task.difficulty_level,
                        "persona": mock_task.persona,
                        "language": mock_task.language,
                        "starter_code": mock_task.starter_code
                    }]
                return t

            mock_db.table.side_effect = table_mock

            headers = {"Authorization": "Bearer valid-jwt-token"}
            response = client.post("/api/tasks/generate", json={
                "skill_level": "Beginner",
                "persona": "Enterprise SaaS",
                "difficulty_level": 1,
                "task_type": "feature-dev",
                "language": "python",
                "project_id": "project-beta",
                "include_continuity": True
            }, headers=headers)

            self.assertEqual(response.status_code, 200)
            prompt_called = mock_llm.call_args[0][0]
            # No continuity prompt attached because project-beta is clean
            self.assertNotIn("CONTEXT FROM PREVIOUS COMPLETED TICKET", prompt_called)

    def test_continuity_filters_out_different_language_within_same_project(self):
        """Even inside the same project, if user requests javascript when previous submission was python, continuity is skipped."""
        mock_task = Task(
            title="Frontend Component Task",
            description="Write javascript logic.",
            task_type="feature-dev",
            difficulty_level=1,
            persona="Enterprise SaaS",
            language="javascript",
            starter_code="function clean() {}",
            test_cases=[TestCase(input="1", expected_output="1", hidden=False)]
        )

        with patch("services.auth_service.get_supabase_client") as mock_auth_sb, \
             patch("routers.tasks.generate_ai_response", return_value=mock_task) as mock_llm, \
             patch("routers.tasks.get_supabase_client") as mock_tasks_sb:
            
            user_res = MagicMock()
            user_res.user.id = "user-alice-123"
            mock_auth_sb.return_value.auth.get_user.return_value = user_res

            mock_db = MagicMock()
            mock_tasks_sb.return_value = mock_db

            def table_mock(name):
                t = MagicMock()
                if name == "projects":
                    t.select.return_value.eq.return_value.execute.return_value.data = [{
                        "project_id": "project-gamma",
                        "user_id": "user-alice-123",
                        "title": "Gamma Project",
                        "description": "Full stack project."
                    }]
                elif name == "tasks":
                    t.select.return_value.eq.return_value.execute.return_value.data = [{"task_id": "task-gamma-1"}]
                    t.insert.return_value.execute.return_value.data = [{
                        "task_id": "task-gamma-2",
                        "project_id": "project-gamma",
                        "title": mock_task.title,
                        "description": mock_task.description,
                        "task_type": mock_task.task_type,
                        "difficulty_level": mock_task.difficulty_level,
                        "persona": mock_task.persona,
                        "language": mock_task.language,
                        "starter_code": mock_task.starter_code
                    }]
                elif name == "submissions":
                    # Filter .eq("language", "javascript") returns empty because previous was python
                    t.select.return_value.eq.return_value.in_.return_value.eq.return_value.gte.return_value.order.return_value.limit.return_value.execute.return_value.data = []
                return t

            mock_db.table.side_effect = table_mock

            headers = {"Authorization": "Bearer valid-jwt-token"}
            response = client.post("/api/tasks/generate", json={
                "skill_level": "Beginner",
                "persona": "Enterprise SaaS",
                "difficulty_level": 1,
                "task_type": "feature-dev",
                "language": "javascript",
                "project_id": "project-gamma",
                "include_continuity": True
            }, headers=headers)

            self.assertEqual(response.status_code, 200)
            prompt_called = mock_llm.call_args[0][0]
            self.assertNotIn("CONTEXT FROM PREVIOUS COMPLETED TICKET", prompt_called)

    def test_start_new_project_requires_explicit_abandonment_for_incomplete_project(self):
        """Attempting to start a new project while current project is incomplete returns 400 unless abandon_current=True."""
        with patch("services.auth_service.get_supabase_client") as mock_auth_sb, \
             patch("routers.projects.get_supabase_client") as mock_projects_sb:
            
            user_res = MagicMock()
            user_res.user.id = "user-alice-123"
            mock_auth_sb.return_value.auth.get_user.return_value = user_res

            mock_db = MagicMock()
            mock_projects_sb.return_value = mock_db

            # Active project has target_tickets = 4, but only 1 task completed
            def table_mock(name):
                t = MagicMock()
                if name == "projects":
                    t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{
                        "project_id": "proj-incomplete",
                        "user_id": "user-alice-123",
                        "title": "Incomplete Project",
                        "target_tickets": 4,
                        "status": "active"
                    }]
                elif name == "tasks":
                    t.select.return_value.eq.return_value.execute.return_value.data = [{"task_id": "t1"}]
                elif name == "submissions":
                    t.select.return_value.eq.return_value.in_.return_value.gte.return_value.execute.return_value.data = [{"task_id": "t1"}]
                return t

            mock_db.table.side_effect = table_mock

            headers = {"Authorization": "Bearer valid-jwt-token"}
            
            # 1. Without abandon_current=True -> 400 Bad Request
            res_fail = client.post("/api/projects/new", json={
                "persona": "Enterprise SaaS",
                "language": "python",
                "target_tickets": 4,
                "abandon_current": False
            }, headers=headers)

            self.assertEqual(res_fail.status_code, 400)
            self.assertIn("Active project is incomplete", res_fail.json()["detail"])

            # 2. With abandon_current=True -> Success, marks previous as abandoned
            def table_mock_success(name):
                t = MagicMock()
                if name == "projects":
                    t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{
                        "project_id": "proj-incomplete",
                        "user_id": "user-alice-123",
                        "title": "Incomplete Project",
                        "target_tickets": 4,
                        "status": "active"
                    }]
                    t.update.return_value.eq.return_value.execute.return_value.data = [{"status": "abandoned"}]
                    t.insert.return_value.execute.return_value.data = [{
                        "project_id": "proj-new-active",
                        "user_id": "user-alice-123",
                        "title": "Multi-Tenant RBAC & Provisioning Core",
                        "description": "New project description.",
                        "persona": "Enterprise SaaS",
                        "language": "python",
                        "status": "active",
                        "target_tickets": 4,
                        "created_at": "2026-10-19T03:00:00Z"
                    }]
                elif name == "tasks":
                    t.select.return_value.eq.return_value.execute.return_value.data = [{"task_id": "t1"}]
                elif name == "submissions":
                    t.select.return_value.eq.return_value.in_.return_value.gte.return_value.execute.return_value.data = [{"task_id": "t1"}]
                return t

            mock_db.table.side_effect = table_mock_success

            res_success = client.post("/api/projects/new", json={
                "persona": "Enterprise SaaS",
                "language": "python",
                "target_tickets": 4,
                "abandon_current": True
            }, headers=headers)

            self.assertEqual(res_success.status_code, 200)
            self.assertEqual(res_success.json()["project_id"], "proj-new-active")

    def test_distinct_passed_tickets_counting_prevents_double_counting(self):
        """Submitting 5 times for ticket 't1' only counts as 1 distinct completed ticket towards target_tickets."""
        from routers.projects import get_project_completed_tasks_count

        mock_db = MagicMock()
        # Project has 2 tasks
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"task_id": "t1"},
            {"task_id": "t2"}
        ]
        
        # User submitted 5 times for 't1' (all passed) and 0 times for 't2'
        mock_db.table.return_value.select.return_value.eq.return_value.in_.return_value.gte.return_value.execute.return_value.data = [
            {"task_id": "t1"},
            {"task_id": "t1"},
            {"task_id": "t1"},
            {"task_id": "t1"},
            {"task_id": "t1"}
        ]

        count = get_project_completed_tasks_count(mock_db, "proj-123", "user-alice-123")
        # Must strictly be 1, NOT 5
        self.assertEqual(count, 1)

    def test_project_auto_completes_when_target_reached(self):
        """When completed_count reaches target_tickets, GET /api/projects/active sets status to 'completed'."""
        with patch("services.auth_service.get_supabase_client") as mock_auth_sb, \
             patch("routers.projects.get_supabase_client") as mock_projects_sb:
            
            user_res = MagicMock()
            user_res.user.id = "user-alice-123"
            mock_auth_sb.return_value.auth.get_user.return_value = user_res

            mock_db = MagicMock()
            mock_projects_sb.return_value = mock_db

            def table_mock(name):
                t = MagicMock()
                if name == "projects":
                    t.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [{
                        "project_id": "proj-reach-target",
                        "user_id": "user-alice-123",
                        "title": "Target Reached Project",
                        "description": "Full target completed.",
                        "persona": "Enterprise SaaS",
                        "language": "python",
                        "status": "active",
                        "target_tickets": 4,
                        "created_at": "2026-10-19T03:00:00Z"
                    }]
                    t.update.return_value.eq.return_value.execute.return_value.data = [{
                        "project_id": "proj-reach-target",
                        "user_id": "user-alice-123",
                        "title": "Target Reached Project",
                        "description": "Full target completed.",
                        "persona": "Enterprise SaaS",
                        "language": "python",
                        "status": "completed",
                        "target_tickets": 4,
                        "created_at": "2026-10-19T03:00:00Z",
                        "completed_at": "2026-10-19T03:20:00Z"
                    }]
                elif name == "tasks":
                    t.select.return_value.eq.return_value.execute.return_value.data = [
                        {"task_id": "t1"}, {"task_id": "t2"}, {"task_id": "t3"}, {"task_id": "t4"}
                    ]
                elif name == "submissions":
                    t.select.return_value.eq.return_value.in_.return_value.gte.return_value.execute.return_value.data = [
                        {"task_id": "t1"}, {"task_id": "t2"}, {"task_id": "t3"}, {"task_id": "t4"}
                    ]
                return t

            mock_db.table.side_effect = table_mock

            headers = {"Authorization": "Bearer valid-jwt-token"}
            res = client.get("/api/projects/active", headers=headers)

            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "completed")
            self.assertEqual(data["completed_tickets_count"], 4)
            self.assertIsNotNone(data["completed_at"])

if __name__ == "__main__":
    unittest.main()
