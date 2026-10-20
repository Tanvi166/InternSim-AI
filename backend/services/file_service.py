"""
Path validation and multi-file adapter utilities for InternSim AI.
Ensures safe relative paths, rejects directory traversal, and prepares
multi-file payloads for sandbox execution and persistence.
"""

import re
from typing import Dict, List, Optional, Tuple

SAFE_FILENAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.\/]+$")
DISALLOWED_SUBSTRINGS = ["..", "\\", ":", "\0", "*", "?", '"', "<", ">", "|"]

def is_safe_relative_path(path: str) -> bool:
    """
    Validates that a file path is a clean, safe relative path:
    - Must not be empty.
    - Must not start with / or ./ or ../
    - Must not contain Windows backslashes or traversal sequences.
    - Must not reference hidden sensitive files (e.g. .env, .git).
    """
    if not path or not isinstance(path, str):
        return False
    
    clean_path = path.strip()
    if not clean_path:
        return False

    if clean_path.startswith("/") or clean_path.startswith("./") or clean_path.startswith("../"):
        return False

    for dis in DISALLOWED_SUBSTRINGS:
        if dis in clean_path:
            return False

    # Prevent hidden files
    parts = clean_path.split("/")
    for part in parts:
        if part.startswith(".") and part != ".":
            return False

    return bool(SAFE_FILENAME_REGEX.match(clean_path))

def validate_and_normalize_files(
    primary_code: str,
    language: str,
    files: Optional[Dict[str, str]] = None
) -> Tuple[str, List[Dict[str, str]]]:
    """
    Validates all files in a multi-file buffer.
    Returns:
        (entry_filename, piston_files_list)
    """
    ext = "py" if language.lower() in ["python", "py"] else ("js" if language.lower() in ["javascript", "js"] else language)
    entry_filename = f"solution.{ext}"

    piston_files: List[Dict[str, str]] = []

    if files:
        for fname, content in files.items():
            if not is_safe_relative_path(fname):
                raise ValueError(f"Invalid or unsafe file path: '{fname}'")
            piston_files.append({"name": fname, "content": content or ""})

        # Ensure entry_filename is present
        found_entry = False
        for f in piston_files:
            if f["name"] in [entry_filename, f"main.{ext}"]:
                found_entry = True
                # Update with primary_code if provided
                if primary_code:
                    f["content"] = primary_code
                break
        if not found_entry:
            piston_files.insert(0, {"name": entry_filename, "content": primary_code or ""})
    else:
        piston_files = [{"name": entry_filename, "content": primary_code or ""}]

    return entry_filename, piston_files
