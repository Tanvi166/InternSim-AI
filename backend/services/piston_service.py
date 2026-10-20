import httpx
import sys
import subprocess
from typing import List, Dict, Any, Optional

PISTON_API_URL = "https://emkc.org/api/v2/piston"

async def get_runtimes():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{PISTON_API_URL}/runtimes")
            return response.json()
    except Exception as e:
        print(f"[PISTON RUNTIMES ERROR]: {e}")
        return []

async def execute_code(
    language: str, 
    version: str, 
    code: str, 
    run_args: List[str] = None, 
    stdin: str = "",
    files: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """
    Executes code using Piston API, with fallback to local Python subprocess execution if Piston is unreachable.
    Supports both single-file and multi-file project buffers.
    """
    # Build files array for Piston
    main_ext = "py" if language.lower() in ["python", "py"] else ("js" if language.lower() in ["javascript", "js"] else language)
    piston_files = []
    
    if files and len(files) > 0:
        # If files list provided, ensure primary entry is the first file
        piston_files = [f for f in files]
        # If first file content doesn't match harness code, replace/prepend entrypoint
        if piston_files[0].get("content") != code:
            piston_files[0]["content"] = code
    else:
        piston_files = [{"name": f"main.{main_ext}", "content": code}]

    payload = {
        "language": language,
        "version": version,
        "files": piston_files,
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
        import tempfile
        import os
        # If single-file without external dependencies, use direct python -c
        if len(piston_files) == 1:
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

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                entry_name = piston_files[0].get("name", "main.py")
                entry_file_path = os.path.join(tmpdir, entry_name)
                for f in piston_files:
                    fname = f.get("name", "main.py")
                    fpath = os.path.join(tmpdir, fname)
                    os.makedirs(os.path.dirname(fpath), exist_ok=True)
                    with open(fpath, "w", encoding="utf-8") as wf:
                        wf.write(f.get("content", ""))

                # Execute entry file inside the temporary directory so local imports resolve
                res = subprocess.run(
                    [sys.executable, entry_file_path],
                    input=stdin,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=tmpdir
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


