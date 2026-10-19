import httpx
import sys
import subprocess
from typing import List, Dict, Any

PISTON_API_URL = "https://emkc.org/api/v2/piston"

async def get_runtimes():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{PISTON_API_URL}/runtimes")
            return response.json()
    except Exception as e:
        print(f"[PISTON RUNTIMES ERROR]: {e}")
        return []

async def execute_code(language: str, version: str, code: str, run_args: List[str] = None, stdin: str = "") -> Dict[str, Any]:
    """
    Executes code using Piston API, with fallback to local Python subprocess execution if Piston is unreachable.
    """
    payload = {
        "language": language,
        "version": version,
        "files": [
            {
                "name": f"main.{language}",
                "content": code
            }
        ],
        "args": run_args or [],
        "stdin": stdin,
        "compile_timeout": 5000,
        "run_timeout": 3000,
        "compile_memory_limit": -1,
        "run_memory_limit": -1
    }
    
    # 1. Attempt Remote Piston API Call (Fast 3-second timeout)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(f"{PISTON_API_URL}/execute", json=payload)
            if response.status_code == 200:
                res_data = response.json()
                if "run" in res_data and (res_data["run"].get("stdout") or res_data["run"].get("stderr")):
                    return res_data
    except Exception as e:
        print(f"[PISTON API UNREACHABLE/TIMEOUT]: {e}. Using local execution fallback...")

    # 2. Local Fallback Execution for Python
    if language.lower() in ["python", "py"]:
        try:
            res = subprocess.run(
                [sys.executable, "-c", code],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=5
            )
            return {
                "run": {
                    "stdout": res.stdout,
                    "stderr": res.stderr,
                    "code": res.returncode
                }
            }
        except Exception as local_err:
            print(f"[LOCAL EXECUTION ERROR]: {local_err}")
            return {"run": {"stdout": "", "stderr": f"Local execution error: {local_err}"}}

    return {"run": {"stdout": "", "stderr": "Execution endpoint unreachable"}}


