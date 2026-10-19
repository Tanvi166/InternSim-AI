from fastapi import APIRouter, HTTPException
from models import (
    CodeSubmission,
    SubmissionResult,
    QualityFeedback,
    CodeRunRequest,
    CodeRunResult,
    SampleTestsRequest,
    SampleTestsResponse,
    SampleTestResult,
)
from database import get_supabase_client
from services.piston_service import execute_code
from services.llm_service import generate_ai_response
from typing import Any, List
import json

router = APIRouter()

def normalize_val(val: Any) -> str:
    if val is None:
        return "None"
    s = str(val).strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        inner = s[1:-1].strip()
        if not (inner.startswith("{") and inner.endswith("}")) and not (inner.startswith("[") and inner.endswith("]")):
            s = inner
    return s

def compare_results(actual_val: Any, expected_val: Any) -> bool:
    """
    Robust semantic comparison supporting primitives, dicts, lists, booleans, and numbers.
    """
    norm_act = normalize_val(actual_val)
    norm_exp = normalize_val(expected_val)
    
    # Exact or case-insensitive string match
    if norm_act == norm_exp or norm_act.lower() == norm_exp.lower():
        return True

    # Numeric equivalence (e.g. 63.0 vs 63)
    try:
        f_act = float(norm_act)
        f_exp = float(norm_exp)
        if abs(f_act - f_exp) < 1e-6:
            return True
    except (ValueError, TypeError):
        pass

    # Structured Python / JSON comparison
    import ast
    def parse_struct(v_str):
        if not v_str:
            return None
        try:
            return json.loads(v_str)
        except Exception:
            try:
                return ast.literal_eval(v_str)
            except Exception:
                return None

    s_act = parse_struct(norm_act)
    s_exp = parse_struct(norm_exp)

    if s_act is not None and s_exp is not None:
        return s_act == s_exp

    return False

def build_harness_code(language: str, submitted_code: str, tc_input: str) -> str:
    lang = language.lower()
    if lang == "python":
        harness_stub = """
__SUBMITTED_CODE__

# --- AUTOMATED TEST HARNESS ---
import json, sys, inspect, io

# Alias starter_code module if tests import from starter_code
sys.modules['starter_code'] = sys.modules['__main__']

def _run_test_harness():
    raw_in = __TC_INPUT_REPR__
    
    # Check if raw_in is a full script with prints/imports
    s_trimmed = raw_in.strip()
    if "\\n" in s_trimmed or s_trimmed.startswith("from ") or s_trimmed.startswith("import ") or "print(" in s_trimmed:
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()
        try:
            exec(compile(raw_in, '<test_script>', 'exec'), globals(), globals())
            captured = buffer.getvalue().strip()
            sys.stdout = old_stdout
            if captured:
                print(captured)
            return
        except Exception as e:
            sys.stdout = old_stdout
            print(f"ERROR: {e}", file=sys.stderr)
            return

    # Check if raw_in is an assignment e.g. "url = '...'"
    if s_trimmed.startswith("url =") or s_trimmed.startswith("url="):
        # Extract rhs
        rhs = s_trimmed.split("=", 1)[1].strip()
        if "(" in rhs and rhs.endswith(")"):
            rhs = rhs[:rhs.rfind("(")].strip()
        try:
            import ast
            raw_in = ast.literal_eval(rhs)
        except Exception:
            if (rhs.startswith("'") and rhs.endswith("'")) or (rhs.startswith('"') and rhs.endswith('"')):
                raw_in = rhs[1:-1].strip()
            else:
                raw_in = rhs

    # Check if raw_in is a function call expression e.g. fn(...)
    try:
        import ast
        tree = ast.parse(raw_in, mode='eval')
        if isinstance(tree.body, ast.Call):
            res = eval(compile(tree, '<test_call>', 'eval'), globals(), globals())
            if isinstance(res, (dict, list)):
                print(json.dumps(res))
            else:
                print(str(res))
            return
    except Exception:
        pass

    # Fallback to finding user function
    user_funcs = [
        obj for name, obj in list(globals().items())
        if inspect.isfunction(obj) and not name.startswith("_")
    ]

    # If no free function, check classes with route / route_request / handle_request / resolve
    if not user_funcs:
        for name, obj in list(globals().items()):
            if inspect.isclass(obj) and not name.startswith("_"):
                try:
                    inst = obj()
                    for m_name in ["route", "route_request", "handle_request", "resolve"]:
                        if hasattr(inst, m_name):
                            user_funcs.append(getattr(inst, m_name))
                            break
                except Exception:
                    pass

    if not user_funcs:
        return

    fn = user_funcs[-1]
    
    # Attempt argument parsing
    try:
        val = json.loads(raw_in)
        if isinstance(val, list):
            res = fn(*val)
        elif isinstance(val, dict):
            res = fn(**val)
        else:
            res = fn(val)
    except Exception:
        try:
            res = fn(raw_in)
        except Exception:
            try:
                parts = [p.strip() for p in raw_in.split(",")]
                res = fn(*parts)
            except Exception:
                try:
                    res = fn()
                except Exception:
                    res = None

    if isinstance(res, (dict, list)):
        print(json.dumps(res))
    else:
        print(str(res))

if __name__ == "__main__":
    _run_test_harness()
"""
        return harness_stub.replace("__SUBMITTED_CODE__", submitted_code).replace("__TC_INPUT_REPR__", repr(tc_input))
    elif lang in ["javascript", "js", "typescript", "ts"]:
        harness_stub = """
__SUBMITTED_CODE__

// --- AUTOMATED TEST HARNESS ---
(function() {
  const rawIn = __TC_INPUT_REPR__;
  let funcs = [];
  try {
    for (let key in this) {
      if (typeof this[key] === 'function' && !key.startsWith('_')) funcs.push(this[key]);
    }
  } catch(e) {}
  
  if (funcs.length > 0) {
    const fn = funcs[funcs.length - 1];
    let arg;
    try { arg = JSON.parse(rawIn); } catch(e) { arg = rawIn; }
    let res;
    if (Array.isArray(arg)) res = fn(...arg);
    else res = fn(arg);
    if (typeof res === 'object' && res !== null) {
      console.log(JSON.stringify(res));
    } else {
      console.log(String(res));
    }
  }
})();
"""
        return harness_stub.replace("__SUBMITTED_CODE__", submitted_code).replace("__TC_INPUT_REPR__", json.dumps(tc_input))
    return submitted_code

def build_batch_harness_code(language: str, submitted_code: str, tc_inputs: list) -> str:
    lang = language.lower()
    if lang == "python":
        harness_stub = """
__SUBMITTED_CODE__

# --- AUTOMATED BATCH TEST HARNESS ---
import json, sys, inspect, io

# Alias starter_code module if tests import from starter_code
sys.modules['starter_code'] = sys.modules['__main__']

def _run_batch_test_harness():
    raw_inputs = __TC_INPUTS_JSON__
    user_funcs = [
        obj for name, obj in list(globals().items())
        if inspect.isfunction(obj) and not name.startswith("_")
    ]

    # If no free function, check classes with route / route_request / handle_request
    if not user_funcs:
        for name, obj in list(globals().items()):
            if inspect.isclass(obj) and not name.startswith("_"):
                try:
                    inst = obj()
                    for m_name in ["route", "route_request", "handle_request", "resolve"]:
                        if hasattr(inst, m_name):
                            user_funcs.append(getattr(inst, m_name))
                            break
                except Exception:
                    pass

    fn = user_funcs[-1] if user_funcs else None
    results = []

    for raw_in in raw_inputs:
        s_trimmed = raw_in.strip()
        res = None

        # Check if raw_in is a full multi-line script with print or imports
        if "\\n" in s_trimmed or s_trimmed.startswith("from ") or s_trimmed.startswith("import ") or "print(" in s_trimmed:
            old_stdout = sys.stdout
            sys.stdout = buffer = io.StringIO()
            try:
                exec(compile(raw_in, '<test_script>', 'exec'), globals(), globals())
                captured = buffer.getvalue().strip()
                sys.stdout = old_stdout
                results.append(captured)
                continue
            except Exception as e:
                sys.stdout = old_stdout
                results.append(f"ERROR: {e}")
                continue

        # Check assignment e.g. "url = '...'"
        cur_input = raw_in
        if s_trimmed.startswith("url =") or s_trimmed.startswith("url="):
            rhs = s_trimmed.split("=", 1)[1].strip()
            if "(" in rhs and rhs.endswith(")"):
                rhs = rhs[:rhs.rfind("(")].strip()
            try:
                import ast
                cur_input = ast.literal_eval(rhs)
            except Exception:
                if (rhs.startswith("'") and rhs.endswith("'")) or (rhs.startswith('"') and rhs.endswith('"')):
                    cur_input = rhs[1:-1].strip()
                else:
                    cur_input = rhs

        # Check function call expression e.g. fn(...)
        evaluated = False
        try:
            import ast
            tree = ast.parse(str(cur_input), mode='eval')
            if isinstance(tree.body, ast.Call):
                res = eval(compile(tree, '<test_call>', 'eval'), globals(), globals())
                evaluated = True
        except Exception:
            pass

        if not evaluated and fn is not None:
            try:
                val = json.loads(str(cur_input))
                if isinstance(val, list):
                    res = fn(*val)
                elif isinstance(val, dict):
                    res = fn(**val)
                else:
                    res = fn(val)
            except Exception:
                try:
                    res = fn(cur_input)
                except Exception:
                    try:
                        parts = [p.strip() for p in str(cur_input).split(",")]
                        res = fn(*parts)
                    except Exception:
                        try:
                            res = fn()
                        except Exception:
                            res = None

        if isinstance(res, (dict, list)):
            out_str = json.dumps(res)
        else:
            out_str = str(res)
            
        results.append(out_str)

    print("__BATCH_RESULTS_START__")
    print(json.dumps(results))
    print("__BATCH_RESULTS_END__")

if __name__ == "__main__":
    _run_batch_test_harness()
"""
        return harness_stub.replace("__SUBMITTED_CODE__", submitted_code).replace("__TC_INPUTS_JSON__", json.dumps(tc_inputs))
    elif lang in ["javascript", "js", "typescript", "ts"]:
        harness_stub = """
__SUBMITTED_CODE__

// --- AUTOMATED BATCH TEST HARNESS ---
(function() {
  const rawInputs = __TC_INPUTS_JSON__;
  let funcs = [];
  try {
    for (let key in this) {
      if (typeof this[key] === 'function' && !key.startsWith('_')) funcs.push(this[key]);
    }
  } catch(e) {}
  
  if (funcs.length > 0) {
    const fn = funcs[funcs.length - 1];
    let results = [];
    for (let i = 0; i < rawInputs.length; i++) {
      const rawIn = rawInputs[i];
      let arg;
      try { arg = JSON.parse(rawIn); } catch(e) { arg = rawIn; }
      let res;
      try {
        if (Array.isArray(arg)) res = fn(...arg);
        else res = fn(arg);
      } catch(e) {
        res = undefined;
      }
      results.push(res !== undefined ? (typeof res === 'object' ? JSON.stringify(res) : String(res)) : "");
    }
    console.log("__BATCH_RESULTS_START__");
    console.log(JSON.stringify(results));
    console.log("__BATCH_RESULTS_END__");
  }
})();
"""
        return harness_stub.replace("__SUBMITTED_CODE__", submitted_code).replace("__TC_INPUTS_JSON__", json.dumps(tc_inputs))
    return submitted_code

@router.post("/submit", response_model=SubmissionResult)
async def submit_code(submission: CodeSubmission):
    supabase = get_supabase_client()
    
    # 1. Fetch Task
    task_res = supabase.table("tasks").select("*").eq("task_id", submission.task_id).execute()
    if not task_res.data:
        raise HTTPException(status_code=404, detail="Task not found")
        
    task = task_res.data[0]
    test_cases = task["test_cases"]
    
    # 2. Correctness Evaluation (Piston)
    passed_tests = 0
    total_tests = len(test_cases)
    
    version = "3.10.0" if submission.language.lower() == "python" else "18.15.0"
    
    # Try batch execution first to support stateful test sequences in a single process
    batch_success = False
    tc_inputs = [tc.get("input", "") for tc in test_cases]
    batch_harness = build_batch_harness_code(submission.language, submission.submitted_code, tc_inputs)
    
    try:
        piston_batch_res = await execute_code(submission.language, version, batch_harness)
        run_data = piston_batch_res.get("run", {})
        stdout = run_data.get("stdout", "")
        stderr = run_data.get("stderr", "")

        if "__BATCH_RESULTS_START__" in stdout and "__BATCH_RESULTS_END__" in stdout:
            batch_payload = stdout.split("__BATCH_RESULTS_START__")[1].split("__BATCH_RESULTS_END__")[0].strip()
            batch_results = json.loads(batch_payload)
            if isinstance(batch_results, list) and len(batch_results) == total_tests:
                for idx, tc in enumerate(test_cases):
                    tc_in = tc.get("input", "")
                    expected = tc.get("expected_output", "")
                    actual_out = batch_results[idx]

                    is_pass = compare_results(actual_out, expected)
                    if is_pass:
                        passed_tests += 1

                    print(f"[TEST {idx+1}/{total_tests}] Input: {repr(tc_in)} | Expected: {repr(expected)} | Actual: {repr(actual_out)} | Pass: {is_pass}")
                batch_success = True
        if stderr and not batch_success:
            print(f"[BATCH HARNESS STDERR]: {stderr}")
    except Exception as e:
        print(f"[BATCH HARNESS ERROR]: {e}. Falling back to isolated test runner...")

    # Fallback to isolated test runner if batch harness fails or is incomplete
    if not batch_success:
        passed_tests = 0
        for idx, tc in enumerate(test_cases):
            tc_in = tc.get("input", "")
            expected = tc.get("expected_output", "")
            harness_code = build_harness_code(submission.language, submission.submitted_code, tc_in)
            piston_res = await execute_code(submission.language, version, harness_code, stdin=tc_in)
            
            run_data = piston_res.get("run", {})
            stdout = run_data.get("stdout", "").strip()
            stderr = run_data.get("stderr", "").strip()

            is_pass = compare_results(stdout, expected)
            if is_pass:
                passed_tests += 1

            print(f"[TEST {idx+1}/{total_tests}] Input: {repr(tc_in)} | Expected: {repr(expected)} | Actual: {repr(stdout)} | Pass: {is_pass}")
            if stderr:
                print(f"[TEST {idx+1} STDERR]: {stderr}")
            
    correctness_score = int((passed_tests / total_tests) * 60) if total_tests > 0 else 60
    
    # 3. Quality Evaluation (LLM)
    prompt = f"""
    Evaluate the following {submission.language} code for code quality on a scale of 1-5 for each metric.
    
    Task Description: {task['description']}
    
    Submitted Code:
    ```
    {submission.submitted_code}
    ```
    
    Metrics:
    - readability (1-5)
    - structure (1-5)
    - edge_cases (1-5)
    - naming (1-5)
    - comments (Brief feedback explaining the scores and how to improve)
    """
    
    try:
        quality_feedback: QualityFeedback = generate_ai_response(prompt, QualityFeedback)
        # Calculate quality out of 40 (each metric is out of 5, total max is 20)
        quality_total = quality_feedback.readability + quality_feedback.structure + quality_feedback.edge_cases + quality_feedback.naming
        quality_score = int((quality_total / 20) * 40)
    except Exception as e:
        print(f"[QUALITY EVALUATION ERROR]: {e}")
        import traceback
        traceback.print_exc()
        quality_feedback = QualityFeedback(readability=3, structure=3, edge_cases=3, naming=3, comments="Automated review failed.")
        quality_score = 24 # 60% of 40
        
    total_score = correctness_score + quality_score
    
    # 4. Save Submission
    submission_data = {
        "task_id": submission.task_id,
        "user_id": submission.user_id,
        "submitted_code": submission.submitted_code,
        "language": submission.language,
        "correctness_score": correctness_score,
        "quality_score": quality_score,
        "total_score": total_score,
        "feedback": quality_feedback.model_dump()
    }
    
    sub_res = supabase.table("submissions").insert(submission_data).execute()
    
    if not sub_res.data:
        raise HTTPException(status_code=500, detail="Failed to save submission")
        
    saved_sub = sub_res.data[0]
    
    # 5. Adaptive Difficulty logic (Check last N tasks)
    # E.g. get average of last 3
    history_res = supabase.table("submissions").select("total_score").eq("user_id", submission.user_id).order("created_at", desc=True).limit(3).execute()
    if history_res.data and len(history_res.data) == 3:
        avg_score = sum(h["total_score"] for h in history_res.data) / 3
        if avg_score >= 75:
            # Upgrade difficulty tier
            profile_res = supabase.table("profiles").select("current_difficulty_tier").eq("id", submission.user_id).single().execute()
            if profile_res.data:
                current_tier = profile_res.data["current_difficulty_tier"]
                supabase.table("profiles").update({"current_difficulty_tier": current_tier + 1}).eq("id", submission.user_id).execute()
    
    return SubmissionResult(
        submission_id=saved_sub["submission_id"],
        correctness_score=correctness_score,
        quality_score=quality_score,
        total_score=total_score,
        feedback=quality_feedback
    )

@router.post("/run", response_model=CodeRunResult)
async def run_code_preview(req: CodeRunRequest):
    """
    Executes submitted code directly in Piston/local sandbox with custom stdin.
    Does NOT create a submission or change user scores.
    """
    lang = req.language.lower()
    version = "3.10.0" if lang == "python" else "18.15.0"

    try:
        piston_res = await execute_code(lang, version, req.code, stdin=req.stdin or "")
        run_data = piston_res.get("run", {})
        stdout = run_data.get("stdout", "")
        stderr = run_data.get("stderr", "")
        code = run_data.get("code", 0)

        timed_out = "timeout" in stderr.lower() or "timed out" in stderr.lower()

        return CodeRunResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=code,
            timed_out=timed_out,
            error=None if code == 0 and not timed_out else (stderr or "Execution failed")
        )
    except Exception as e:
        return CodeRunResult(
            stdout="",
            stderr=str(e),
            exit_code=-1,
            timed_out=False,
            error=str(e)
        )

@router.post("/test-samples", response_model=SampleTestsResponse)
async def run_sample_tests(req: SampleTestsRequest):
    """
    Runs code against only VISIBLE test cases for the specified task.
    Hidden test cases remain strictly private and are NEVER evaluated or leaked here.
    Does NOT affect user score or persist submissions.
    """
    supabase = get_supabase_client()
    task_res = supabase.table("tasks").select("*").eq("task_id", req.task_id).execute()
    if not task_res.data:
        raise HTTPException(status_code=404, detail="Task not found")

    task = task_res.data[0]
    all_test_cases = task.get("test_cases", [])

    # Filter strictly to visible (non-hidden) test cases
    visible_tests = [tc for tc in all_test_cases if not tc.get("hidden", False)]
    if not visible_tests:
        # If no explicit hidden flag is set, take the first 2 as sample tests, keeping remainder hidden
        visible_tests = all_test_cases[:2] if len(all_test_cases) > 2 else all_test_cases

    lang = req.language.lower()
    version = "3.10.0" if lang == "python" else "18.15.0"
    total_samples = len(visible_tests)

    tc_inputs = [tc.get("input", "") for tc in visible_tests]
    batch_harness = build_batch_harness_code(lang, req.code, tc_inputs)

    results: List[SampleTestResult] = []
    passed_samples = 0
    batch_success = False
    raw_error = None

    try:
        piston_batch_res = await execute_code(lang, version, batch_harness)
        run_data = piston_batch_res.get("run", {})
        stdout = run_data.get("stdout", "")
        stderr = run_data.get("stderr", "")

        if "__BATCH_RESULTS_START__" in stdout and "__BATCH_RESULTS_END__" in stdout:
            batch_payload = stdout.split("__BATCH_RESULTS_START__")[1].split("__BATCH_RESULTS_END__")[0].strip()
            batch_results = json.loads(batch_payload)
            if isinstance(batch_results, list) and len(batch_results) == total_samples:
                for idx, tc in enumerate(visible_tests):
                    tc_in = tc.get("input", "")
                    expected = tc.get("expected_output", "")
                    actual_out = batch_results[idx]

                    is_pass = compare_results(actual_out, expected)
                    if is_pass:
                        passed_samples += 1

                    results.append(SampleTestResult(
                        index=idx,
                        input=tc_in,
                        expected_output=expected,
                        actual_output=actual_out,
                        passed=is_pass,
                        stderr=stderr if not is_pass else "",
                        error=actual_out if actual_out.startswith("ERROR:") else None
                    ))
                batch_success = True
        if stderr and not batch_success:
            raw_error = stderr
    except Exception as e:
        raw_error = str(e)

    # Fallback to isolated execution per sample test if batching fails
    if not batch_success:
        results = []
        passed_samples = 0
        for idx, tc in enumerate(visible_tests):
            tc_in = tc.get("input", "")
            expected = tc.get("expected_output", "")
            harness_code = build_harness_code(lang, req.code, tc_in)
            piston_res = await execute_code(lang, version, harness_code, stdin=tc_in)

            run_data = piston_res.get("run", {})
            stdout = run_data.get("stdout", "").strip()
            stderr = run_data.get("stderr", "").strip()

            is_pass = compare_results(stdout, expected)
            if is_pass:
                passed_samples += 1

            results.append(SampleTestResult(
                index=idx,
                input=tc_in,
                expected_output=expected,
                actual_output=stdout,
                passed=is_pass,
                stderr=stderr,
                error=stderr if stderr and not is_pass else None
            ))

    return SampleTestsResponse(
        total_samples=total_samples,
        passed_samples=passed_samples,
        results=results,
        raw_error=raw_error
    )

