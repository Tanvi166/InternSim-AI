import unittest
from fastapi.testclient import TestClient
from main import app
from database import get_supabase_client

class TestDevWorkflow(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.sb = get_supabase_client()
        # Find a task with visible test cases
        task_res = self.sb.table("tasks").select("*").ilike("title", "%Email Validation%").limit(1).execute()
        self.task = task_res.data[0] if task_res.data else None

    def test_run_code_preview_success(self):
        code = 'print("Hello Debugger!")'
        res = self.client.post("/api/evaluations/run", json={
            "language": "python",
            "code": code,
            "stdin": ""
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("Hello Debugger!", data["stdout"])
        self.assertEqual(data["exit_code"], 0)
        self.assertIsNone(data["error"])

    def test_run_code_preview_syntax_error(self):
        code = 'def broken('
        res = self.client.post("/api/evaluations/run", json={
            "language": "python",
            "code": code,
            "stdin": ""
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["exit_code"] != 0 or len(data["stderr"]) > 0)
        self.assertIn("SyntaxError", data["stderr"])

    def test_run_code_pure_function_definition(self):
        # A pure function definition produces exit code 0 and empty stdout without error
        code = '''
def calculate_tax(amount: float) -> float:
    return amount * 0.15
'''
        res = self.client.post("/api/evaluations/run", json={
            "language": "python",
            "code": code,
            "stdin": ""
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["exit_code"], 0)
        self.assertEqual(data["stdout"].strip(), "")
        self.assertIsNone(data["error"])

    def test_run_code_with_stdin(self):
        code = '''
import sys
line = sys.stdin.read().strip()
print(f"ECHO: {line}")
'''
        res = self.client.post("/api/evaluations/run", json={
            "language": "python",
            "code": code,
            "stdin": "InternSim Test Input"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["exit_code"], 0)
        self.assertIn("ECHO: InternSim Test Input", data["stdout"])

    def test_run_code_runtime_exception(self):
        code = '''
x = 10 / 0
'''
        res = self.client.post("/api/evaluations/run", json={
            "language": "python",
            "code": code,
            "stdin": ""
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["exit_code"] != 0 or len(data["stderr"]) > 0)
        self.assertIn("ZeroDivisionError", data["stderr"])

    def test_run_sample_tests_with_none_return_values(self):
        # Test against 'Fix Tenant Subdomain Router Bug' where starter code returns None for unknown/invalid
        task_res = self.sb.table("tasks").select("*").eq("title", "Fix Tenant Subdomain Router Bug").limit(1).execute()
        if not task_res.data:
            self.skipTest("Fix Tenant Subdomain Router Bug task not found")

        task = task_res.data[0]
        starter_code = task.get("starter_code")

        res = self.client.post("/api/evaluations/test-samples", json={
            "task_id": task["task_id"],
            "code": starter_code,
            "language": "python"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # In starter code, acme and beta pass (2), unknown and invalid return None and match expected None (2)
        # ACME fails case-sensitivity. So 4/5 sample tests pass!
        self.assertEqual(data["total_samples"], 5)
        self.assertEqual(data["passed_samples"], 4)

        # Confirm actual_output for unknown is captured as 'None', matching expected 'None'
        unknown_test = next(r for r in data["results"] if "unknown" in r["input"])
        self.assertEqual(unknown_test["actual_output"], "None")
        self.assertEqual(unknown_test["expected_output"], "None")
        self.assertTrue(unknown_test["passed"])

if __name__ == "__main__":
    unittest.main()
