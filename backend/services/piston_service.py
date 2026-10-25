import httpx
import sys
import subprocess
import logging
import os
from typing import List, Dict, Any, Optional

PISTON_API_URL = os.getenv("PISTON_API_URL", "https://emkc.org/api/v2/piston").rstrip("/")
logger = logging.getLogger(__name__)

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
    files: Optional[List[Dict[str, str]]] = None,
    allow_local_fallback: bool = True,
) -> Dict[str, Any]:
    """
    Executes code using Piston API, optionally falling back to local Python subprocess execution.
    Repository workspace calls disable that fallback so draft code never executes on the backend host.
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
    response = None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(f"{PISTON_API_URL}/execute", json=payload)
    except httpx.TimeoutException as exc:
        logger.warning("Piston execution unavailable category=timeout error_type=%s", type(exc).__name__)
    except httpx.ConnectError as exc:
        logger.warning("Piston execution unavailable category=connection_error error_type=%s", type(exc).__name__)
    except httpx.RequestError as exc:
        logger.warning("Piston execution unavailable category=request_error error_type=%s", type(exc).__name__)
    except Exception as exc:
        # Log only the exception class. Exception text may contain request details.
        logger.error("Piston execution unavailable category=client_error error_type=%s", type(exc).__name__)

    if response is not None:
        if response.status_code != 200:
            logger.warning(
                "Piston execution unavailable category=http_status status=%d",
                response.status_code,
            )
        else:
            try:
                res_data = response.json()
            except (ValueError, TypeError):
                logger.warning("Piston execution unavailable category=invalid_json status=200")
            else:
                run_data = res_data.get("run") if isinstance(res_data, dict) else None
                if not isinstance(run_data, dict):
                    logger.warning("Piston execution unavailable category=invalid_response status=200")
                elif (
                    not allow_local_fallback
                    or run_data.get("stdout")
                    or run_data.get("stderr")
                ):
                    return res_data

    if not allow_local_fallback:
        return {
            "run": {
                "stdout": "",
                "stderr": "Remote sandbox is unavailable; local execution fallback is disabled.",
                "code": -1,
            }
        }

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


