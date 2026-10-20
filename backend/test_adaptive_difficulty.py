import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from main import app
from models import Task, TestCase
from services.difficulty_service import (
    get_distinct_eligible_submissions,
    calculate_rolling_difficulty_decision,
    evaluate_and_update_user_difficulty,
    PROMOTION_THRESHOLD,
    DEMOTION_THRESHOLD,
    MIN_DIFFICULTY_TIER,
    MAX_DIFFICULTY_TIER,
    ROLLING_WINDOW_SIZE
)

client = TestClient(app)

class TestAdaptiveDifficultyEngine(unittest.TestCase):

    def test_distinct_eligible_submissions_deduplicates_retries(self):
        """Verify that multiple submissions of the same ticket only retain the latest attempt, and failures (< 40) are excluded."""
        subs = [
            {"task_id": "task-A", "correctness_score": 60, "total_score": 90, "created_at": "2026-10-20T10:00:00Z"},
            {"task_id": "task-A", "correctness_score": 20, "total_score": 45, "created_at": "2026-10-20T09:00:00Z"},
            {"task_id": "task-B", "correctness_score": 30, "total_score": 50, "created_at": "2026-10-20T08:00:00Z"}, # Failed, excluded
            {"task_id": "task-C", "correctness_score": 50, "total_score": 80, "created_at": "2026-10-20T07:00:00Z"},
        ]

        distinct = get_distinct_eligible_submissions(subs)
        self.assertEqual(len(distinct), 2)
        # Should contain task-A (the latest 90 score, not 45) and task-C
        self.assertEqual(distinct[0]["task_id"], "task-A")
        self.assertEqual(distinct[0]["total_score"], 90)
        self.assertEqual(distinct[1]["task_id"], "task-C")
        self.assertEqual(distinct[1]["total_score"], 80)

    def test_insufficient_data_when_fewer_than_three_distinct_tickets(self):
        """When user has fewer than 3 distinct eligible tickets, tier remains unchanged with 'insufficient_data'."""
        subs = [
            {"task_id": "task-1", "correctness_score": 60, "total_score": 95},
            {"task_id": "task-2", "correctness_score": 60, "total_score": 90},
        ]
        new_tier, rolling_avg, action, rationale = calculate_rolling_difficulty_decision(1, subs)
        self.assertEqual(new_tier, 1)
        self.assertIsNone(rolling_avg)
        self.assertEqual(action, "insufficient_data")
        self.assertIn("Need 3 distinct completed tickets", rationale)

    def test_promotion_at_or_above_threshold(self):
        """When rolling average of 3 distinct tickets reaches 75/100, promote tier."""
        subs = [
            {"task_id": "t3", "correctness_score": 60, "total_score": 80},
            {"task_id": "t2", "correctness_score": 50, "total_score": 75},
            {"task_id": "t1", "correctness_score": 50, "total_score": 70}, # Avg = 75.0
        ]
        new_tier, rolling_avg, action, rationale = calculate_rolling_difficulty_decision(2, subs)
        self.assertEqual(rolling_avg, 75.0)
        self.assertEqual(new_tier, 3)
        self.assertEqual(action, "promoted")

    def test_max_difficulty_tier_cap(self):
        """When rolling average is >= 75/100 but user is already at MAX tier (5), do not exceed 5."""
        subs = [
            {"task_id": "t3", "correctness_score": 60, "total_score": 90},
            {"task_id": "t2", "correctness_score": 60, "total_score": 95},
            {"task_id": "t1", "correctness_score": 60, "total_score": 90},
        ]
        new_tier, rolling_avg, action, rationale = calculate_rolling_difficulty_decision(5, subs)
        self.assertEqual(new_tier, 5)
        self.assertEqual(action, "unchanged")
        self.assertIn("already at maximum Tier 5", rationale)

    def test_demotion_policy_for_low_scores(self):
        """When rolling average drops below 50.0/100, demote tier."""
        subs = [
            {"task_id": "t3", "correctness_score": 40, "total_score": 45},
            {"task_id": "t2", "correctness_score": 40, "total_score": 48},
            {"task_id": "t1", "correctness_score": 40, "total_score": 45}, # Avg = 46.0
        ]
        new_tier, rolling_avg, action, rationale = calculate_rolling_difficulty_decision(3, subs)
        self.assertAlmostEqual(rolling_avg, 46.0)
        self.assertEqual(new_tier, 2)
        self.assertEqual(action, "demoted")

    def test_min_difficulty_tier_floor(self):
        """When rolling average is < 50.0/100 but user is already at MIN tier (1), do not drop below 1."""
        subs = [
            {"task_id": "t3", "correctness_score": 40, "total_score": 42},
            {"task_id": "t2", "correctness_score": 40, "total_score": 45},
            {"task_id": "t1", "correctness_score": 40, "total_score": 40},
        ]
        new_tier, rolling_avg, action, rationale = calculate_rolling_difficulty_decision(1, subs)
        self.assertEqual(new_tier, 1)
        self.assertEqual(action, "unchanged")
        self.assertIn("already at base Tier 1", rationale)

    def test_stability_buffer_prevents_oscillation(self):
        """Rolling average between 50.0 and 74.9 leaves tier unchanged."""
        subs = [
            {"task_id": "t3", "correctness_score": 45, "total_score": 65},
            {"task_id": "t2", "correctness_score": 50, "total_score": 70},
            {"task_id": "t1", "correctness_score": 40, "total_score": 60}, # Avg = 65.0
        ]
        new_tier, rolling_avg, action, rationale = calculate_rolling_difficulty_decision(2, subs)
        self.assertEqual(rolling_avg, 65.0)
        self.assertEqual(new_tier, 2)
        self.assertEqual(action, "unchanged")
        self.assertIn("stable within 50.0-75.0 range", rationale)

    def test_task_generator_applies_users_profile_difficulty_tier(self):
        """When generating a new ticket, backend synchronizes difficulty with user's authenticated profile tier."""
        mock_task = Task(
            title="Adapted Ticket",
            description="Tier 3 difficulty problem",
            task_type="feature-dev",
            difficulty_level=3,
            persona="Enterprise SaaS",
            language="python",
            starter_code="def solve(): pass",
            test_cases=[TestCase(input="1", expected_output="1", hidden=False)]
        )

        with patch("services.auth_service.get_supabase_client") as mock_auth_sb, \
             patch("routers.tasks.get_supabase_client") as mock_tasks_sb, \
             patch("routers.tasks.generate_ai_response", return_value=mock_task) as mock_llm:

            mock_auth = MagicMock()
            mock_auth_sb.return_value = mock_auth
            mock_auth.auth.get_user.return_value.user.id = "user-alice-123"

            mock_db = MagicMock()
            mock_tasks_sb.return_value = mock_db

            def table_mock(name):
                t = MagicMock()
                if name == "profiles":
                    # User's profile has been promoted to Tier 3
                    t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
                        "current_difficulty_tier": 3
                    }
                elif name == "projects":
                    t.select.return_value.eq.return_value.execute.return_value.data = [{
                        "user_id": "user-alice-123",
                        "title": "Core Project",
                        "description": "Project Desc"
                    }]
                elif name == "tasks":
                    t.select.return_value.eq.return_value.execute.return_value.data = []
                    t.insert.return_value.execute.return_value.data = [{
                        "task_id": "t-adapted-1",
                        "project_id": "proj-1",
                        "title": mock_task.title,
                        "description": mock_task.description,
                        "task_type": mock_task.task_type,
                        "difficulty_level": 3,
                        "persona": mock_task.persona,
                        "language": mock_task.language,
                        "starter_code": mock_task.starter_code
                    }]
                return t

            mock_db.table.side_effect = table_mock

            headers = {"Authorization": "Bearer alice-token"}
            res = client.post("/api/tasks/generate", json={
                "skill_level": "Beginner",
                "persona": "Enterprise SaaS",
                "difficulty_level": 1, # Stale request payload tier
                "task_type": "feature-dev",
                "language": "python",
                "project_id": "proj-1",
                "include_continuity": False
            }, headers=headers)

            self.assertEqual(res.status_code, 200)
            data = res.json()
            # Must be synchronized to user's updated profile tier (3)
            self.assertEqual(data["difficulty_level"], 3)
            
            prompt_called = mock_llm.call_args[0][0]
            self.assertIn("Difficulty tier: 3", prompt_called)

if __name__ == "__main__":
    unittest.main()
