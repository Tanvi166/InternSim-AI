import unittest
from fastapi import HTTPException
from unittest.mock import patch

from routers.projects import get_user_project, list_user_projects


class _Query:
    def __init__(self, database, table):
        self.database = database
        self.table_name = table
        self.filters = {}

    def select(self, *_args):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def in_(self, column, values):
        self.filters[column] = values
        return self

    def gte(self, column, value):
        self.filters[f"{column}_gte"] = value
        return self

    def execute(self):
        rows = self.database.rows[self.table_name]
        if self.table_name == "projects":
            rows = [row for row in rows if all(row.get(key) == value for key, value in self.filters.items())]
        elif self.table_name == "tasks":
            rows = [row for row in rows if row["project_id"] == self.filters.get("project_id")]
        elif self.table_name == "submissions":
            rows = [
                row for row in rows
                if row["user_id"] == self.filters.get("user_id")
                and row["task_id"] in self.filters.get("task_id", [])
                and row["correctness_score"] >= self.filters.get("correctness_score_gte", 0)
            ]
        return type("Result", (), {"data": rows})()


class _Database:
    def __init__(self):
        self.rows = {
            "projects": [
                {"project_id": "owned-project", "user_id": "user-a", "title": "My project", "description": "A test project", "persona": "Enterprise SaaS", "language": "python", "status": "active", "target_tickets": 2, "created_at": "2026-01-01T00:00:00Z", "completed_at": None},
                {"project_id": "other-project", "user_id": "user-b", "title": "Private project", "description": "Other user's project", "persona": "AI Startup", "language": "python", "status": "active", "target_tickets": 2, "created_at": "2026-01-02T00:00:00Z", "completed_at": None},
            ],
            "tasks": [
                {"task_id": "passed-task", "project_id": "owned-project"},
                {"task_id": "other-task", "project_id": "other-project"},
            ],
            "submissions": [
                {"task_id": "passed-task", "user_id": "user-a", "correctness_score": 40},
                {"task_id": "other-task", "user_id": "user-b", "correctness_score": 60},
            ],
        }

    def table(self, name):
        return _Query(self, name)


class ProjectListApiTests(unittest.TestCase):
    def test_project_list_requires_authentication(self):
        with self.assertRaises(HTTPException) as error:
            list_user_projects(None)
        self.assertEqual(error.exception.status_code, 401)

    def test_project_list_is_user_scoped_and_includes_progress(self):
        with patch("routers.projects.get_supabase_client", return_value=_Database()):
            projects = list_user_projects("user-a")

        self.assertEqual([project.project_id for project in projects], ["owned-project"])
        self.assertEqual(projects[0].completed_tickets_count, 1)

    def test_project_detail_requires_authentication_and_hides_other_users_projects(self):
        with self.assertRaises(HTTPException) as error:
            get_user_project("owned-project", None)
        self.assertEqual(error.exception.status_code, 401)

        with patch("routers.projects.get_supabase_client", return_value=_Database()):
            with self.assertRaises(HTTPException) as error:
                get_user_project("other-project", "user-a")
        self.assertEqual(error.exception.status_code, 404)

    def test_project_detail_returns_only_owner_scoped_project_and_progress(self):
        with patch("routers.projects.get_supabase_client", return_value=_Database()):
            project = get_user_project("owned-project", "user-a")

        self.assertEqual(project.project_id, "owned-project")
        self.assertEqual(project.completed_tickets_count, 1)


if __name__ == "__main__":
    unittest.main()
