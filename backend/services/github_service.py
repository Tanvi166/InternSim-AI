"""
GitHub Integration Service for InternSim AI.
Handles OAuth URL generation, state validation, code exchange,
user profile fetching, authorized repository listing, and upstream revocation.
"""

import os
import re
import secrets
import logging
import base64
import binascii
import httpx
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from urllib.parse import quote, urlparse

from services.file_service import is_safe_relative_path
from services.encryption_service import encrypt_token, decrypt_token
from database import get_supabase_client

class OAuthStateStoreError(RuntimeError):
    """Raised when the shared OAuth state store cannot safely serve a request."""


class GitHubRepositoryAccessError(PermissionError):
    """The connected GitHub account cannot access the requested repository."""


class GitHubAuthenticationError(PermissionError):
    """The stored GitHub credential is no longer accepted by GitHub."""


class GitHubBranchConflictError(RuntimeError):
    """GitHub rejected branch creation because the reference conflicts."""


class GitHubBranchCreationError(RuntimeError):
    """A safe, non-sensitive GitHub API failure while creating a branch."""


class GitHubRateLimitError(TimeoutError):
    """GitHub rate-limited a branch creation request."""


class GitHubForkError(RuntimeError):
    """A safe GitHub API or persistence error while managing a starter fork."""


class GitHubForkConflictError(GitHubForkError):
    """A same-name repository exists but is not the expected student fork."""


class GitHubForkNotFoundError(GitHubForkError):
    """The authenticated user has not created a mapped starter fork."""


class GitHubStudentProjectStoreError(GitHubForkError):
    """The durable student-project mapping store is unavailable."""


class GitHubStudentProjectPendingError(GitHubForkError):
    """The student's repository fork is not ready for file browsing."""


class GitHubStudentProjectFileNotFoundError(GitHubForkError):
    """A requested repository folder or file does not exist."""


class GitHubStudentProjectPathIsDirectoryError(GitHubForkError):
    """A file-content request targeted a directory."""


class GitHubStudentProjectFileTooLargeError(GitHubForkError):
    """A repository file exceeds the read-only browser's size limit."""


class GitHubStudentProjectBinaryFileError(GitHubForkError):
    """A repository file is binary or is not valid UTF-8 text."""


class GitHubStudentProjectListingTooLargeError(GitHubForkError):
    """GitHub could not return a complete bounded tree listing."""


class GitHubForkRateLimitError(GitHubForkError):
    """GitHub rate-limited a fork operation or readiness check."""


# The starter source is fixed in trusted server code. No request parameter can
# redirect the fork operation to an arbitrary repository.
STARTER_REPOSITORY_OWNER = "Tanvi166"
STARTER_REPOSITORY_NAME = "trendhive"
STUDENT_PROJECT_TABLE = "github_student_projects"
STUDENT_PROJECT_FORK_REQUEST_TABLE = "github_student_project_fork_requests"
MAX_STUDENT_PROJECT_FILE_BYTES = 1_000_000
MAX_STUDENT_PROJECT_TREE_ENTRIES = 10_000
MAX_STUDENT_PROJECT_PAGE_SIZE = 100
logger = logging.getLogger(__name__)

_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(\b(?:authorization|access[_ -]?token|refresh[_ -]?token|github[_ -]?token|"
    r"github[_ -]?token[_ -]?encryption[_ -]?key|encryption[_ -]?key|client[_ -]?secret|"
    r"service[_ -]?role[_ -]?key|supabase[_ -]?key|api[_ -]?key|private[_ -]?key|"
    r"password|secret|token)\b\s*[:=]\s*)(?:bearer\s+)?(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_GITHUB_TOKEN_PATTERN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)\b")
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_URL_CREDENTIAL_PATTERN = re.compile(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@")
_URL_SECRET_QUERY_PATTERN = re.compile(r"(?i)([?&](?:token|key|secret|password|apikey)=)[^&\s]+")


def _safe_store_error_message(exc: Exception) -> str:
    """Keep actionable database diagnostics while removing credential-like values."""
    message = getattr(exc, "message", None) or str(exc) or type(exc).__name__
    message = str(message)
    message = _SECRET_ASSIGNMENT_PATTERN.sub(r"\1[REDACTED]", message)
    message = _BEARER_PATTERN.sub("Bearer [REDACTED]", message)
    message = _GITHUB_TOKEN_PATTERN.sub("[REDACTED_GITHUB_TOKEN]", message)
    message = _JWT_PATTERN.sub("[REDACTED_JWT]", message)
    message = _URL_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]@", message)
    message = _URL_SECRET_QUERY_PATTERN.sub(r"\1[REDACTED]", message)
    return message[:600]


def _log_student_project_store_error(operation: str, exc: Exception) -> None:
    root_cause = exc
    while root_cause.__cause__ is not None and root_cause.__cause__ is not root_cause:
        root_cause = root_cause.__cause__
    code = getattr(root_cause, "code", None)
    safe_code = re.sub(r"[^A-Za-z0-9_.-]", "", str(code))[:40] if code is not None else "none"
    logger.error(
        "Student project storage failure operation=%s category=%s code=%s message=%s",
        operation,
        type(root_cause).__name__,
        safe_code,
        _safe_store_error_message(root_cause),
    )


def _log_github_fork_response(
    operation: str,
    response: httpx.Response,
    *,
    reason: Optional[str] = None,
) -> None:
    """Log GitHub status plus sanitized message and a static reason, never headers/body."""
    try:
        payload = response.json()
    except Exception:
        payload = None
    message = payload.get("message") if isinstance(payload, dict) else None
    safe_message = (
        _safe_store_error_message(RuntimeError(message))
        if isinstance(message, str)
        else "no safe message provided"
    )
    logger.error(
        "GitHub starter fork response operation=%s status=%s message=%s reason=%s",
        operation,
        response.status_code,
        safe_message,
        reason or "none",
    )


def _get_student_project_client():
    """Reject database stubs that cannot prove they support Supabase RPC access."""
    client = get_supabase_client()
    if not callable(getattr(client, "rpc", None)):
        raise GitHubStudentProjectStoreError("Supabase client does not expose the required rpc() capability.")
    return client


def _fork_api_error(response: httpx.Response, *, conflict: bool = False) -> None:
    _log_github_fork_response("fork_api_error", response, reason="unexpected GitHub API status")
    if response.status_code == 401:
        raise GitHubAuthenticationError("GitHub credentials are invalid or revoked.")
    if response.status_code == 429:
        raise GitHubForkRateLimitError("GitHub API rate limit exceeded.")
    if response.status_code == 403:
        if response.headers.get("x-ratelimit-remaining") == "0" or response.headers.get("retry-after"):
            raise GitHubForkRateLimitError("GitHub API rate limit exceeded.")
        raise GitHubRepositoryAccessError("GitHub permissions are insufficient for this repository operation.")
    if response.status_code == 404:
        raise GitHubRepositoryAccessError("The connected GitHub account cannot access the required repository.")
    if conflict and response.status_code in (409, 422):
        raise GitHubForkConflictError("A repository conflict prevented the fork operation.")
    raise GitHubForkError("GitHub could not complete the fork operation.")


def _require_fork_scope(user_response: httpx.Response, starter_is_private: bool) -> None:
    scope_header = user_response.headers.get("x-oauth-scopes", "")
    scopes = {scope.strip().casefold() for scope in scope_header.split(",") if scope.strip()}
    permitted = "repo" in scopes if starter_is_private else bool(scopes & {"repo", "public_repo"})
    if not permitted:
        raise GitHubRepositoryAccessError("Reconnect GitHub with repository permissions to create this project copy.")


def _validate_fork_repository(
    data: Any,
    expected_login: str,
    *,
    response: Optional[httpx.Response] = None,
    operation: str = "fork_response_validation",
) -> Dict[str, Any]:
    """Validate GitHub's response identity and source before persisting its metadata."""
    if not isinstance(data, dict):
        if response is not None:
            _log_github_fork_response(operation, response, reason="response body was not a repository object")
        raise GitHubForkError("GitHub returned an invalid fork response.")
    owner_data = data.get("owner")
    owner = owner_data.get("login") if isinstance(owner_data, dict) else None
    name = data.get("name")
    full_name = data.get("full_name")
    repo_id = data.get("id")
    url = data.get("html_url")
    parent_data = data.get("parent")
    parent_full_name = parent_data.get("full_name") if isinstance(parent_data, dict) else None
    parsed_url = urlparse(url) if isinstance(url, str) else None

    if (
        not isinstance(owner, str)
        or owner.casefold() != expected_login.casefold()
        or not isinstance(name, str)
        or not _REPOSITORY_PATTERN.fullmatch(name)
        or not isinstance(full_name, str)
        or full_name.casefold() != f"{owner}/{name}".casefold()
        or isinstance(repo_id, bool)
        or not isinstance(repo_id, int)
        or repo_id <= 0
        or data.get("fork") is not True
        or not isinstance(parent_full_name, str)
        or parent_full_name.casefold() != f"{STARTER_REPOSITORY_OWNER}/{STARTER_REPOSITORY_NAME}".casefold()
        or parsed_url is None
        or parsed_url.scheme != "https"
        or parsed_url.netloc.casefold() != "github.com"
        or parsed_url.path.rstrip("/").casefold() != f"/{owner}/{name}".casefold()
        or parsed_url.query
        or parsed_url.fragment
    ):
        if response is not None:
            _log_github_fork_response(
                operation,
                response,
                reason="owner, repository ID, fork parent, or repository URL failed validation",
            )
        raise GitHubForkError("GitHub returned repository data that did not match the configured starter fork.")

    return {
        "github_repository_id": repo_id,
        "github_owner": owner,
        "github_repository_name": name,
        "github_full_name": full_name,
        "repository_url": url,
    }


def _validate_existing_student_fork(
    data: Any,
    expected_login: str,
    *,
    response: Optional[httpx.Response] = None,
) -> Dict[str, Any]:
    """Accept a pre-existing repository only when it is this user's starter fork."""
    if not isinstance(data, dict) or data.get("fork") is not True:
        if response is not None:
            _log_github_fork_response(
                "existing_fork_validation",
                response,
                reason="existing repository is not marked as a fork",
            )
        raise GitHubForkConflictError("A repository with the starter name exists but is not the expected fork.")
    try:
        return _validate_fork_repository(data, expected_login)
    except GitHubForkError:
        if response is not None:
            _log_github_fork_response(
                "existing_fork_validation",
                response,
                reason="existing repository failed owner, ID, parent, or URL validation",
            )
        raise GitHubForkConflictError(
            "The existing repository does not belong to the authenticated account as a fork of the configured starter."
        ) from None


def _student_starter_fork_name(login: str, github_user_id: int) -> str:
    """Generate a stable per-GitHub-account fork name that avoids the starter name."""
    if isinstance(github_user_id, bool) or not isinstance(github_user_id, int) or github_user_id <= 0:
        raise GitHubAuthenticationError("GitHub did not return a valid authenticated account ID.")
    return f"trendhive-internsim-{login.casefold()}-{github_user_id}"


def _read_student_project_mapping(user_id: str) -> Optional[Dict[str, Any]]:
    try:
        response = (
            _get_student_project_client()
            .table(STUDENT_PROJECT_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("starter_owner", STARTER_REPOSITORY_OWNER)
            .eq("starter_repository", STARTER_REPOSITORY_NAME)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        return rows[0] if rows else None
    except Exception as exc:
        _log_student_project_store_error("select_mapping", exc)
        raise GitHubStudentProjectStoreError("Student project storage is temporarily unavailable.") from exc


def _student_project_response(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "owner": row["github_owner"],
        "name": row["github_repository_name"],
        "full_name": row["github_full_name"],
        "url": row["repository_url"],
        "status": row["status"],
    }


def _validate_student_project_path(path: str, *, allow_root: bool = False) -> str:
    if allow_root and path == "":
        return ""
    if not isinstance(path, str) or path != path.strip() or not is_safe_relative_path(path):
        raise ValueError("Repository path is invalid or not allowed.")
    parts = path.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise ValueError("Repository path is invalid or not allowed.")
    return path


def _student_project_github_headers(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "InternSim-AI-App",
    }


async def _get_verified_student_project_repository(
    client: httpx.AsyncClient,
    user_id: str,
    access_token: str,
) -> tuple[Dict[str, Any], str, Dict[str, str]]:
    """Resolve only the authenticated user's persisted, verified student fork."""
    mapping = _read_student_project_mapping(user_id)
    if not mapping:
        raise GitHubForkNotFoundError("No starter project copy is mapped to this user.")
    if mapping.get("status") != "ready":
        raise GitHubStudentProjectPendingError("The student project copy is still being prepared.")

    headers = _student_project_github_headers(access_token)
    user_response = await client.get("https://api.github.com/user", headers=headers)
    if user_response.status_code != 200:
        _fork_api_error(user_response)
    user_data = user_response.json()
    login = user_data.get("login") if isinstance(user_data, dict) else None
    mapped_owner = mapping.get("github_owner")
    if (
        not isinstance(login, str)
        or not isinstance(mapped_owner, str)
        or login.casefold() != mapped_owner.casefold()
    ):
        raise GitHubRepositoryAccessError("The connected GitHub account does not own the mapped student repository.")

    repo_id = mapping.get("github_repository_id")
    if isinstance(repo_id, bool) or not isinstance(repo_id, (int, str)):
        raise GitHubForkConflictError("The mapped student repository identity is invalid.")
    try:
        repo_id = int(repo_id)
    except (TypeError, ValueError):
        raise GitHubForkConflictError("The mapped student repository identity is invalid.") from None
    if repo_id <= 0:
        raise GitHubForkConflictError("The mapped student repository identity is invalid.")

    repo_response = await client.get(f"https://api.github.com/repositories/{repo_id}", headers=headers)
    if repo_response.status_code != 200:
        _fork_api_error(repo_response)
    repo_data = repo_response.json()
    verified = _validate_fork_repository(
        repo_data,
        login,
        response=repo_response,
        operation="student_project_file_repository_validation",
    )
    if (
        verified["github_repository_id"] != repo_id
        or verified["github_owner"].casefold() != str(mapping.get("github_owner", "")).casefold()
        or verified["github_repository_name"].casefold()
        != str(mapping.get("github_repository_name", "")).casefold()
        or verified["github_full_name"].casefold() != str(mapping.get("github_full_name", "")).casefold()
        or verified["repository_url"].rstrip("/").casefold()
        != str(mapping.get("repository_url", "")).rstrip("/").casefold()
    ):
        raise GitHubForkConflictError("The mapped repository no longer matches the verified student fork.")

    default_branch = repo_data.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        raise GitHubForkError("GitHub did not return a valid default branch for the student repository.")
    return mapping, default_branch, headers


async def verify_student_project_repository_access(user_id: str, access_token: str) -> Dict[str, Any]:
    """Revalidate the authenticated user's mapped fork before workspace execution."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        mapping, _default_branch, _headers = await _get_verified_student_project_repository(
            client, user_id, access_token
        )
    return mapping


async def _get_student_project_tree(
    client: httpx.AsyncClient,
    headers: Dict[str, str],
    owner: str,
    repository: str,
    default_branch: str,
    directory_path: str,
) -> List[Dict[str, Any]]:
    repo_api = (
        f"https://api.github.com/repos/{quote(owner, safe='')}"
        f"/{quote(repository, safe='')}"
    )
    ref_response = await client.get(
        f"{repo_api}/git/ref/heads/{quote(default_branch, safe='/')}", headers=headers
    )
    if ref_response.status_code != 200:
        _fork_api_error(ref_response)
    ref_data = ref_response.json()
    ref_object = ref_data.get("object") if isinstance(ref_data, dict) else None
    commit_sha = ref_object.get("sha") if isinstance(ref_object, dict) else None
    if not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit_sha):
        raise GitHubForkError("GitHub did not return a valid repository commit reference.")

    commit_response = await client.get(f"{repo_api}/git/commits/{quote(commit_sha, safe='')}", headers=headers)
    if commit_response.status_code != 200:
        _fork_api_error(commit_response)
    commit_data = commit_response.json()
    tree_data = commit_data.get("tree") if isinstance(commit_data, dict) else None
    tree_sha = tree_data.get("sha") if isinstance(tree_data, dict) else None
    if not isinstance(tree_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", tree_sha):
        raise GitHubForkError("GitHub did not return a valid repository tree reference.")

    requested_parts = directory_path.split("/") if directory_path else []
    for directory_name in requested_parts:
        tree_response = await client.get(f"{repo_api}/git/trees/{quote(tree_sha, safe='')}", headers=headers)
        if tree_response.status_code == 404:
            raise GitHubStudentProjectFileNotFoundError("The requested repository folder was not found.")
        if tree_response.status_code != 200:
            _fork_api_error(tree_response)
        current_tree = tree_response.json()
        entries = current_tree.get("tree") if isinstance(current_tree, dict) else None
        if not isinstance(current_tree, dict) or current_tree.get("truncated") is True or not isinstance(entries, list):
            raise GitHubStudentProjectListingTooLargeError("This repository folder is too large to list safely.")
        child = next(
            (entry for entry in entries if isinstance(entry, dict)
             and entry.get("path") == directory_name and entry.get("type") == "tree"),
            None,
        )
        if child is None or not isinstance(child.get("sha"), str):
            raise GitHubStudentProjectFileNotFoundError("The requested repository folder was not found.")
        tree_sha = child["sha"]

    tree_response = await client.get(f"{repo_api}/git/trees/{quote(tree_sha, safe='')}", headers=headers)
    if tree_response.status_code == 404:
        raise GitHubStudentProjectFileNotFoundError("The requested repository folder was not found.")
    if tree_response.status_code != 200:
        _fork_api_error(tree_response)
    tree_data = tree_response.json()
    entries = tree_data.get("tree") if isinstance(tree_data, dict) else None
    if not isinstance(tree_data, dict) or tree_data.get("truncated") is True or not isinstance(entries, list):
        raise GitHubStudentProjectListingTooLargeError("This repository folder is too large to list safely.")
    if len(entries) > MAX_STUDENT_PROJECT_TREE_ENTRIES:
        raise GitHubStudentProjectListingTooLargeError("This repository folder is too large to list safely.")
    return entries


async def list_student_project_files(
    user_id: str,
    access_token: str,
    *,
    path: str = "",
    page: int = 1,
    page_size: int = MAX_STUDENT_PROJECT_PAGE_SIZE,
) -> Dict[str, Any]:
    """Return one paginated directory listing from the user's mapped fork."""
    path = _validate_student_project_path(path, allow_root=True)
    if (
        isinstance(page, bool)
        or not isinstance(page, int)
        or page < 1
        or isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= MAX_STUDENT_PROJECT_PAGE_SIZE
    ):
        raise ValueError("Invalid repository file pagination values.")

    async with httpx.AsyncClient(timeout=20.0) as client:
        mapping, default_branch, headers = await _get_verified_student_project_repository(
            client, user_id, access_token
        )
        entries = await _get_student_project_tree(
            client,
            headers,
            mapping["github_owner"],
            mapping["github_repository_name"],
            default_branch,
            path,
        )

    normalized = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") not in {"tree", "blob"}:
            continue
        name = entry.get("path")
        if not isinstance(name, str) or "/" in name:
            continue
        item_path = f"{path}/{name}" if path else name
        if not is_safe_relative_path(item_path):
            continue
        size = entry.get("size") if entry.get("type") == "blob" else None
        normalized.append({
            "name": name,
            "path": item_path,
            "type": "directory" if entry["type"] == "tree" else "file",
            "size": size if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else None,
        })
    normalized.sort(key=lambda item: (item["type"] != "directory", item["name"].casefold()))
    start = (page - 1) * page_size
    page_items = normalized[start:start + page_size]
    has_more = start + page_size < len(normalized)
    return {
        "repository_id": mapping["github_repository_id"],
        "repository": mapping["github_full_name"],
        "path": path,
        "page": page,
        "page_size": page_size,
        "total": len(normalized),
        "has_more": has_more,
        "next_page": page + 1 if has_more else None,
        "items": page_items,
    }


async def get_student_project_file(user_id: str, access_token: str, path: str) -> Dict[str, Any]:
    """Return bounded UTF-8 text from one path in the user's mapped fork."""
    path = _validate_student_project_path(path)
    async with httpx.AsyncClient(timeout=20.0) as client:
        mapping, default_branch, headers = await _get_verified_student_project_repository(
            client, user_id, access_token
        )
        url = (
            f"https://api.github.com/repos/{quote(mapping['github_owner'], safe='')}"
            f"/{quote(mapping['github_repository_name'], safe='')}/contents/{quote(path, safe='/')}"
            f"?ref={quote(default_branch, safe='')}"
        )
        response = await client.get(url, headers=headers)
        if response.status_code == 404:
            raise GitHubStudentProjectFileNotFoundError("The requested repository file was not found.")
        if response.status_code != 200:
            _fork_api_error(response)
        data = response.json()

    # GitHub's Contents API returns an array for a directory request.
    if isinstance(data, list):
        raise GitHubStudentProjectPathIsDirectoryError("Choose a file rather than a folder.")
    if not isinstance(data, dict):
        raise GitHubForkError("GitHub returned invalid repository file data.")
    if data.get("type") == "dir":
        raise GitHubStudentProjectPathIsDirectoryError("Choose a file rather than a folder.")
    if data.get("type") != "file":
        raise GitHubStudentProjectFileNotFoundError("The requested repository file was not found.")
    size = data.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise GitHubForkError("GitHub returned invalid repository file metadata.")
    if size > MAX_STUDENT_PROJECT_FILE_BYTES:
        raise GitHubStudentProjectFileTooLargeError("This file exceeds the 1 MB read-only preview limit.")
    encoded = data.get("content")
    if data.get("encoding") != "base64" or not isinstance(encoded, str):
        raise GitHubStudentProjectBinaryFileError("This file cannot be displayed as text.")
    try:
        raw = base64.b64decode("".join(encoded.split()), validate=True)
    except (ValueError, binascii.Error):
        raise GitHubForkError("GitHub returned invalid repository file content.") from None
    if len(raw) > MAX_STUDENT_PROJECT_FILE_BYTES:
        raise GitHubStudentProjectFileTooLargeError("This file exceeds the 1 MB read-only preview limit.")
    if b"\0" in raw:
        raise GitHubStudentProjectBinaryFileError("This file cannot be displayed as text.")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise GitHubStudentProjectBinaryFileError("This file cannot be displayed as text.") from None
    return {
        "repository_id": mapping["github_repository_id"],
        "repository": mapping["github_full_name"],
        "path": path,
        "size": len(raw),
        "content": content,
    }


def _pending_student_fork_response(login: str, repository_name: str) -> Dict[str, Any]:
    """Describe a pending fork without inventing or persisting repository identity."""
    full_name = f"{login}/{repository_name}"
    return {
        "owner": login,
        "name": repository_name,
        "full_name": full_name,
        "url": f"https://github.com/{full_name}",
        "status": "pending",
    }


def _read_pending_student_fork_request(user_id: str) -> Optional[Dict[str, Any]]:
    try:
        response = (
            _get_student_project_client()
            .table(STUDENT_PROJECT_FORK_REQUEST_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("starter_owner", STARTER_REPOSITORY_OWNER)
            .eq("starter_repository", STARTER_REPOSITORY_NAME)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        return rows[0] if rows else None
    except Exception as exc:
        _log_student_project_store_error("select_pending_fork_request", exc)
        raise GitHubStudentProjectStoreError("Student project storage is temporarily unavailable.") from exc


def _register_pending_student_fork_request(
    user_id: str, github_user_id: int, login: str, repository_name: str
) -> bool:
    """Persist intent before POST; only the request that inserts it may create a fork."""
    values = {
        "user_id": user_id,
        "starter_owner": STARTER_REPOSITORY_OWNER,
        "starter_repository": STARTER_REPOSITORY_NAME,
        "github_user_id": github_user_id,
        "github_owner": login,
        "github_repository_name": repository_name,
    }
    try:
        response = (
            _get_student_project_client()
            .table(STUDENT_PROJECT_FORK_REQUEST_TABLE)
            .insert(values)
            .select("user_id")
            .execute()
        )
        rows = getattr(response, "data", None) or []
        if rows:
            return True
        raise RuntimeError("Pending fork request insert returned no row.")
    except Exception as exc:
        # Concurrent callers race on the table's unique user/starter constraint.
        try:
            existing = _read_pending_student_fork_request(user_id)
        except GitHubStudentProjectStoreError:
            _log_student_project_store_error("insert_pending_fork_request", exc)
            raise
        if existing and all(existing.get(key) == values[key] for key in values):
            return False
        if existing:
            raise GitHubForkConflictError("A different pending starter fork request exists for this account.") from None
        _log_student_project_store_error("insert_pending_fork_request", exc)
        raise GitHubStudentProjectStoreError("Student project storage is temporarily unavailable.") from None


def _delete_pending_student_fork_request(user_id: str) -> None:
    try:
        (
            _get_student_project_client()
            .table(STUDENT_PROJECT_FORK_REQUEST_TABLE)
            .delete()
            .eq("user_id", user_id)
            .eq("starter_owner", STARTER_REPOSITORY_OWNER)
            .eq("starter_repository", STARTER_REPOSITORY_NAME)
            .execute()
        )
    except Exception as exc:
        # A saved mapping takes precedence; a stale intent still prevents duplicate POSTs.
        _log_student_project_store_error("delete_pending_fork_request", exc)


async def _check_student_fork_readiness(
    client: httpx.AsyncClient,
    access_token: str,
    row: Dict[str, Any],
    expected_login: str,
) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "InternSim-AI-App",
    }
    repo_url = f"https://api.github.com/repositories/{int(row['github_repository_id'])}"
    repo_response = await client.get(repo_url, headers=headers)
    if repo_response.status_code == 404:
        return {"status": "pending"}
    if repo_response.status_code != 200:
        _fork_api_error(repo_response)

    verified = _validate_fork_repository(
        repo_response.json(),
        expected_login,
        response=repo_response,
        operation="readiness_repository_validation",
    )
    if verified["github_repository_id"] != row["github_repository_id"]:
        _log_github_fork_response("mapped_repository_identity_conflict", repo_response)
        raise GitHubForkConflictError("The mapped student repository no longer matches the forked repository.")
    branch = repo_response.json().get("default_branch")
    if not isinstance(branch, str) or not branch:
        return {**verified, "status": "pending"}

    fork_path = (
        f"https://api.github.com/repos/{quote(verified['github_owner'], safe='')}"
        f"/{quote(verified['github_repository_name'], safe='')}"
    )
    ref_url = f"{fork_path}/git/ref/heads/{quote(branch, safe='/')}"
    ref_response = await client.get(ref_url, headers=headers)
    if ref_response.status_code == 404:
        return {**verified, "status": "pending"}
    if ref_response.status_code != 200:
        _fork_api_error(ref_response)
    return {**verified, "status": "ready"}


async def _refresh_student_fork(
    user_id: str,
    access_token: str,
    row: Dict[str, Any],
) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "InternSim-AI-App",
        }
        user_response = await client.get("https://api.github.com/user", headers=headers)
        if user_response.status_code != 200:
            _fork_api_error(user_response)
        user_data = user_response.json()
        login = user_data.get("login") if isinstance(user_data, dict) else None
        mapped_owner = row.get("github_owner")
        if not isinstance(login, str) or not isinstance(mapped_owner, str) or login.casefold() != mapped_owner.casefold():
            raise GitHubRepositoryAccessError("This GitHub connection does not own the mapped student repository.")
        readiness = await _check_student_fork_readiness(client, access_token, row, login)
    changes = {key: value for key, value in readiness.items() if key != "status" and row.get(key) != value}
    status = readiness["status"]
    if status != row.get("status") or changes:
        update_data = {**changes, "status": status, "updated_at": datetime.now(timezone.utc).isoformat()}
        try:
            update_result = (
                _get_student_project_client()
                .table(STUDENT_PROJECT_TABLE)
                .update(update_data)
                .eq("id", row["id"])
                .eq("user_id", user_id)
                .select("id")
                .execute()
            )
            updated_rows = getattr(update_result, "data", None) or []
            if not any(item.get("id") == row["id"] for item in updated_rows if isinstance(item, dict)):
                raise RuntimeError("Student project mapping was not updated.")
        except Exception as exc:
            _log_student_project_store_error("update_mapping", exc)
            raise GitHubStudentProjectStoreError("Student project status could not be saved.") from exc
        row = {**row, **update_data}
    return _student_project_response(row)


async def create_or_get_student_starter_fork(user_id: str, access_token: str) -> Dict[str, Any]:
    """Idempotently create or return the authenticated user's fork of the fixed starter."""
    existing_mapping = _read_student_project_mapping(user_id)
    if existing_mapping:
        return await _refresh_student_fork(user_id, access_token, existing_mapping)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "InternSim-AI-App",
    }
    starter_url = (
        f"https://api.github.com/repos/{quote(STARTER_REPOSITORY_OWNER, safe='')}"
        f"/{quote(STARTER_REPOSITORY_NAME, safe='')}"
    )
    async with httpx.AsyncClient(timeout=20.0) as client:
        user_response = await client.get("https://api.github.com/user", headers=headers)
        if user_response.status_code != 200:
            _fork_api_error(user_response)
        user_data = user_response.json()
        login = user_data.get("login") if isinstance(user_data, dict) else None
        if not isinstance(login, str) or not _OWNER_PATTERN.fullmatch(login):
            raise GitHubAuthenticationError("GitHub did not return a valid authenticated account.")
        github_user_id = user_data.get("id")
        student_repository_name = _student_starter_fork_name(login, github_user_id)

        starter_response = await client.get(starter_url, headers=headers)
        if starter_response.status_code != 200:
            _fork_api_error(starter_response)
        starter_data = starter_response.json()
        starter_full_name = starter_data.get("full_name") if isinstance(starter_data, dict) else None
        if not isinstance(starter_full_name, str) or starter_full_name.casefold() != (
            f"{STARTER_REPOSITORY_OWNER}/{STARTER_REPOSITORY_NAME}".casefold()
        ):
            _log_github_fork_response(
                "starter_repository_validation",
                starter_response,
                reason="starter full_name did not match configured source",
            )
            raise GitHubForkError("The configured starter repository could not be verified.")
        if not isinstance(starter_data.get("private"), bool):
            _log_github_fork_response(
                "starter_repository_validation",
                starter_response,
                reason="starter private flag was missing or invalid",
            )
            raise GitHubForkError("GitHub did not provide valid starter repository permissions data.")
        _require_fork_scope(user_response, starter_data["private"])

        # Use a stable account-specific fork name, so an unrelated repository
        # named "trendhive" in the student's account cannot block the copy.
        student_repo_url = (
            f"https://api.github.com/repos/{quote(login, safe='')}"
            f"/{quote(student_repository_name, safe='')}"
        )
        student_repo_response = await client.get(student_repo_url, headers=headers)
        repository_data = None
        if student_repo_response.status_code == 200:
            try:
                repository_data = _validate_existing_student_fork(
                    student_repo_response.json(), login, response=student_repo_response
                )
            except GitHubForkConflictError:
                _log_github_fork_response("existing_repository_conflict", student_repo_response)
                raise
        elif student_repo_response.status_code == 404:
            # A legacy default-named fork may already exist from an earlier
            # version. Recover it only after validating owner and upstream.
            legacy_repo_url = (
                f"https://api.github.com/repos/{quote(login, safe='')}"
                f"/{quote(STARTER_REPOSITORY_NAME, safe='')}"
            )
            legacy_response = await client.get(legacy_repo_url, headers=headers)
            if legacy_response.status_code == 200:
                try:
                    repository_data = _validate_existing_student_fork(
                        legacy_response.json(), login, response=legacy_response
                    )
                except GitHubForkConflictError:
                    # The old default name is occupied by an unrelated repo.
                    # Leave it untouched and continue with the unique fork name.
                    repository_data = None
            elif legacy_response.status_code != 404:
                _fork_api_error(legacy_response)

            if repository_data is None:
                pending_request = _read_pending_student_fork_request(user_id)
                if pending_request:
                    if (
                        pending_request.get("github_user_id") != github_user_id
                        or str(pending_request.get("github_owner", "")).casefold() != login.casefold()
                        or pending_request.get("github_repository_name") != student_repository_name
                    ):
                        raise GitHubForkConflictError("A pending starter fork request does not match this GitHub account.")
                    # A prior POST may still be processing. Continue checking by
                    # deterministic repository name, but never submit another POST.
                    return _pending_student_fork_response(login, student_repository_name)

                may_create = _register_pending_student_fork_request(
                    user_id, github_user_id, login, student_repository_name
                )
                if not may_create:
                    return _pending_student_fork_response(login, student_repository_name)

                fork_response = await client.post(
                    f"{starter_url}/forks",
                    headers=headers,
                    json={"name": student_repository_name},
                )
                if fork_response.status_code not in (201, 202):
                    if fork_response.status_code in (409, 422):
                        _log_github_fork_response("create_fork", fork_response)
                        # A concurrent request may have created our deterministic name.
                        recovered = await client.get(student_repo_url, headers=headers)
                        if recovered.status_code == 200:
                            repository_data = _validate_existing_student_fork(
                                recovered.json(), login, response=recovered
                            )
                        else:
                            if recovered.status_code == 404:
                                _log_github_fork_response(
                                    "lookup_after_create_conflict",
                                    recovered,
                                    reason="deterministic destination was not visible after create conflict",
                                )
                                raise GitHubForkConflictError("A repository conflict prevented the fork operation.")
                            _fork_api_error(recovered)
                    else:
                        _fork_api_error(fork_response, conflict=True)
                else:
                    if fork_response.status_code == 202:
                        # GitHub accepted asynchronous fork creation. Do not trust
                        # the partial response body as repository identity.
                        resolved = await client.get(student_repo_url, headers=headers)
                        if resolved.status_code == 404:
                            return _pending_student_fork_response(login, student_repository_name)
                        if resolved.status_code != 200:
                            _fork_api_error(resolved)
                        repository_data = _validate_existing_student_fork(
                            resolved.json(), login, response=resolved
                        )
                    else:
                        repository_data = _validate_fork_repository(
                            fork_response.json(),
                            login,
                            response=fork_response,
                            operation="fork_create_response_validation",
                        )
        else:
            _fork_api_error(student_repo_response)

        provisional = {
            **repository_data,
            "default_branch": "",
            "status": "pending",
        }
        readiness = await _check_student_fork_readiness(client, access_token, provisional, login)
        if readiness.get("github_repository_id") == repository_data["github_repository_id"]:
            repository_data.update({key: value for key, value in readiness.items() if key != "status"})
        status = readiness["status"]

    mapping = {
        "user_id": user_id,
        "starter_owner": STARTER_REPOSITORY_OWNER,
        "starter_repository": STARTER_REPOSITORY_NAME,
        **repository_data,
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        insert_result = (
            _get_student_project_client()
            .table(STUDENT_PROJECT_TABLE)
            .insert(mapping)
            .select("*")
            .execute()
        )
        rows = getattr(insert_result, "data", None) or []
        if rows:
            _delete_pending_student_fork_request(user_id)
            return _student_project_response(rows[0])
    except Exception as exc:
        # A concurrent request may have won the unique mapping race. Return only
        # that same fork; never replace an existing mapping or repository.
        try:
            raced_mapping = _read_student_project_mapping(user_id)
        except GitHubStudentProjectStoreError:
            # Keep the insert failure visible if the diagnostic race check also
            # fails; the read path logs its own underlying database failure.
            _log_student_project_store_error("insert_mapping", exc)
            raise
        if raced_mapping and raced_mapping.get("github_repository_id") == repository_data["github_repository_id"]:
            _delete_pending_student_fork_request(user_id)
            return await _refresh_student_fork(user_id, access_token, raced_mapping)
        _log_student_project_store_error("insert_mapping", exc)
        raise GitHubStudentProjectStoreError("Student project mapping could not be saved.") from None

    raced_mapping = _read_student_project_mapping(user_id)
    if raced_mapping and raced_mapping.get("github_repository_id") == repository_data["github_repository_id"]:
        _delete_pending_student_fork_request(user_id)
        return await _refresh_student_fork(user_id, access_token, raced_mapping)
    exc = RuntimeError("Student project mapping insert returned no row and no concurrent mapping was found.")
    _log_student_project_store_error("insert_mapping", exc)
    raise GitHubStudentProjectStoreError("Student project mapping could not be saved.") from None


async def get_student_starter_fork_status(user_id: str, access_token: str) -> Dict[str, Any]:
    row = _read_student_project_mapping(user_id)
    if not row:
        pending_request = _read_pending_student_fork_request(user_id)
        if pending_request:
            return await create_or_get_student_starter_fork(user_id, access_token)
        raise GitHubForkNotFoundError("No starter fork has been created for this account.")
    return await _refresh_student_fork(user_id, access_token, row)


_OWNER_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
_REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,100}\Z")
_BRANCH_PATTERN = re.compile(r"feature/[A-Za-z0-9._/-]+\Z")


def validate_feature_branch_inputs(owner: str, repository: str, branch_name: str) -> None:
    """Reject unsafe path components and malformed Git refs before making API calls."""
    if not isinstance(owner, str) or not _OWNER_PATTERN.fullmatch(owner):
        raise ValueError("Invalid GitHub repository owner.")
    if (
        not isinstance(repository, str)
        or not _REPOSITORY_PATTERN.fullmatch(repository)
        or repository in {".", ".."}
    ):
        raise ValueError("Invalid GitHub repository name.")
    if (
        not isinstance(branch_name, str)
        or len(branch_name) > 120
        or not _BRANCH_PATTERN.fullmatch(branch_name)
        or ".." in branch_name
        or "//" in branch_name
    ):
        raise ValueError("Branch name must be a valid feature/<name> Git branch.")

    components = branch_name.split("/")
    if any(
        not component
        or component.startswith(".")
        or component.endswith(".")
        or component.lower().endswith(".lock")
        for component in components
    ):
        raise ValueError("Branch name must be a valid feature/<name> Git branch.")


def _raise_branch_api_error(response: httpx.Response, *, creating: bool = False) -> None:
    """Map GitHub status codes without including upstream response content."""
    if response.status_code == 401:
        raise GitHubAuthenticationError("GitHub credentials are invalid or revoked.")
    if response.status_code == 403:
        if response.headers.get("x-ratelimit-remaining") == "0":
            raise GitHubRateLimitError("GitHub API rate limit exceeded.")
        raise GitHubRepositoryAccessError("The connected GitHub account cannot access this repository.")
    if response.status_code == 404:
        # Avoid revealing whether a private repository exists to this user.
        raise GitHubRepositoryAccessError("The connected GitHub account cannot access this repository.")
    if creating and response.status_code in (409, 422):
        raise GitHubBranchConflictError("The branch already exists or conflicts with an existing Git ref.")
    raise GitHubBranchCreationError("GitHub could not complete the branch request.")


async def create_github_feature_branch(
    access_token: str,
    owner: str,
    repository: str,
    branch_name: str,
) -> Dict[str, str]:
    """Create a feature branch at the connected repository's current default-branch tip."""
    validate_feature_branch_inputs(owner, repository, branch_name)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "InternSim-AI-App",
    }
    repo_path = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repository, safe='')}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        repo_response = await client.get(repo_path, headers=headers)
        if repo_response.status_code != 200:
            _raise_branch_api_error(repo_response)

        repo_data = repo_response.json()
        default_branch = repo_data.get("default_branch") if isinstance(repo_data, dict) else None
        if not isinstance(default_branch, str) or not default_branch:
            raise GitHubBranchCreationError("GitHub did not provide a valid default branch.")

        ref = f"refs/heads/{branch_name}"
        if ref == f"refs/heads/{default_branch}":
            raise ValueError("A feature branch cannot replace the repository default branch.")

        encoded_default_branch = quote(default_branch, safe="/")
        ref_url = f"{repo_path}/git/ref/heads/{encoded_default_branch}"
        ref_response = await client.get(ref_url, headers=headers)
        if ref_response.status_code != 200:
            _raise_branch_api_error(ref_response)
        ref_data = ref_response.json()
        commit = ref_data.get("object") if isinstance(ref_data, dict) else None
        sha = commit.get("sha") if isinstance(commit, dict) else None
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
            raise GitHubBranchCreationError("GitHub returned an invalid default-branch commit reference.")

        create_response = await client.post(
            f"{repo_path}/git/refs",
            headers=headers,
            json={"ref": ref, "sha": sha},
        )
        if create_response.status_code != 201:
            _raise_branch_api_error(create_response, creating=True)

    return {"branch_name": branch_name, "base_branch": default_branch}


def _get_oauth_state_client():
    """Return a Supabase client with the RPC capability required for durable state."""
    client = get_supabase_client()
    if not callable(getattr(client, "rpc", None)):
        # The current database.py test stub only offers process-local table storage.
        raise OAuthStateStoreError("OAuth state storage is unavailable.")
    return client

async def generate_oauth_authorization_url(user_id: str, redirect_uri: Optional[str] = None) -> Dict[str, str]:
    """
    Generates a secure GitHub OAuth authorization URL with a cryptographically random state token.
    Binds state strictly to the authenticated user_id to prevent CSRF and account linking attacks.
    Saves state with TTL in the shared public.oauth_states table.
    """
    client_id = os.environ.get("GITHUB_CLIENT_ID")
    if not client_id:
        raise ValueError("GITHUB_CLIENT_ID is not configured in backend environment")

    # Cryptographically secure random 32-byte token
    state = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=15)

    try:
        supabase = _get_oauth_state_client()
        supabase.table("oauth_states").insert({
            "state": state,
            "user_id": user_id,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat()
        }).execute()
    except Exception as exc:
        raise OAuthStateStoreError("OAuth state storage is unavailable.") from exc

    # Scopes: repo (grants repository access for assignments).
    scope = "repo read:user"

    auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={client_id}"
        f"&scope={scope}"
        f"&state={state}"
    )
    if redirect_uri:
        auth_url += f"&redirect_uri={redirect_uri}"

    return {
        "authorization_url": auth_url,
        "state": state
    }

async def validate_oauth_state(state: str, expected_user_id: str) -> bool:
    """
    Validates that the provided state exists, has not expired, and belongs to expected_user_id.
    Atomically validates owner and expiry and consumes the state through PostgreSQL.
    """
    if not state or not expected_user_id:
        return False

    try:
        supabase = _get_oauth_state_client()
        result = supabase.rpc("consume_github_oauth_state", {
            "p_state": state,
            "p_user_id": expected_user_id,
        }).execute()
        data = result.data
        if isinstance(data, bool):
            return data
        if isinstance(data, list) and len(data) == 1:
            value = data[0]
            if isinstance(value, bool):
                return value
            if isinstance(value, dict):
                return value.get("consumed") is True
        raise OAuthStateStoreError("OAuth state validation returned an invalid response.")
    except OAuthStateStoreError:
        raise
    except Exception as exc:
        raise OAuthStateStoreError("OAuth state validation is unavailable.") from exc

async def exchange_code_for_token(code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
    """
    Exchanges the GitHub OAuth authorization code for an access token via server-to-server call.
    """
    client_id = os.environ.get("GITHUB_CLIENT_ID")
    client_secret = os.environ.get("GITHUB_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError("GitHub OAuth credentials not configured (GITHUB_CLIENT_ID or GITHUB_CLIENT_SECRET)")

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
    }
    if redirect_uri:
        payload["redirect_uri"] = redirect_uri

    headers = {"Accept": "application/json"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post("https://github.com/login/oauth/access_token", data=payload, headers=headers)
        if res.status_code != 200:
            raise ValueError(f"GitHub token exchange returned status {res.status_code}")

        data = res.json()
        if "error" in data:
            raise ValueError(f"GitHub token exchange error: {data.get('error_description') or data['error']}")

        return data

async def fetch_github_user_profile(access_token: str) -> Dict[str, Any]:
    """
    Fetches the authenticated GitHub user profile.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "InternSim-AI-App"
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.get("https://api.github.com/user", headers=headers)
        if res.status_code != 200:
            raise ValueError(f"Failed to fetch GitHub profile: status {res.status_code}")
        return res.json()

async def list_authorized_repositories(access_token: str, max_repos: int = 100) -> List[Dict[str, Any]]:
    """
    Lists repositories accessible to this token with pagination support (up to max_repos).
    Handles rate limiting and permissions.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "InternSim-AI-App"
    }
    sanitized_repos: List[Dict[str, Any]] = []
    page = 1
    per_page = 50

    async with httpx.AsyncClient(timeout=15.0) as client:
        while len(sanitized_repos) < max_repos:
            url = f"https://api.github.com/user/repos?sort=updated&per_page={per_page}&page={page}"
            res = await client.get(url, headers=headers)

            if res.status_code == 401:
                raise PermissionError("GitHub credentials are invalid or have been revoked. Please reconnect your account.")
            elif res.status_code == 403:
                rate_limit = res.headers.get("x-ratelimit-remaining")
                if rate_limit == "0":
                    raise TimeoutError("GitHub API rate limit exceeded. Please wait a few minutes before retrying.")
                raise PermissionError("Access forbidden: insufficient permissions to list repositories.")
            elif res.status_code != 200:
                raise ValueError(f"GitHub API returned unexpected status {res.status_code}")

            repos = res.json()
            if not repos or not isinstance(repos, list):
                break

            for r in repos:
                sanitized_repos.append({
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "full_name": r.get("full_name"),
                    "owner": r.get("owner", {}).get("login"),
                    "private": r.get("private", False),
                    "default_branch": r.get("default_branch", "main"),
                    "html_url": r.get("html_url"),
                    "description": r.get("description"),
                    "permissions": r.get("permissions", {})
                })
                if len(sanitized_repos) >= max_repos:
                    break

            if len(repos) < per_page:
                break
            page += 1

    return sanitized_repos

async def revoke_github_app_grant(access_token: str) -> bool:
    """
    Attempts upstream token revocation with GitHub's authorization API:
    DELETE https://api.github.com/applications/{client_id}/grant
    Returns True if successfully revoked or already non-existent, False on upstream failure.
    Never logs secret credentials or tokens.
    """
    client_id = os.environ.get("GITHUB_CLIENT_ID")
    client_secret = os.environ.get("GITHUB_CLIENT_SECRET")
    if not client_id or not client_secret:
        return False

    url = f"https://api.github.com/applications/{client_id}/grant"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "InternSim-AI-App"
    }
    payload = {"access_token": access_token}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.request(
                "DELETE",
                url,
                auth=(client_id, client_secret),
                json=payload,
                headers=headers
            )
            # Status 204 No Content indicates successful grant revocation
            # Status 404 indicates grant was already revoked
            return res.status_code in [204, 404]
    except Exception:
        return False

async def save_github_integration(
    user_id: str,
    access_token: str,
    github_user: Dict[str, Any],
    scope: Optional[str] = None
) -> Dict[str, Any]:
    """
    Encrypts access token and stores integration row in Supabase via service role.
    Guards against linking a GitHub account that is already claimed by another user.
    """
    github_user_id_str = str(github_user["id"])
    supabase = get_supabase_client()

    # Verify if this github_user_id is already linked to another distinct user
    dup_res = (
        supabase.table("github_integrations")
        .select("user_id")
        .eq("github_user_id", github_user_id_str)
        .execute()
    )
    if dup_res.data:
        existing_owner = dup_res.data[0]["user_id"]
        if str(existing_owner) != str(user_id):
            raise ValueError("This GitHub account is already linked to another InternSim profile.")

    encrypted_token = encrypt_token(access_token)
    integration_data = {
        "user_id": user_id,
        "github_user_id": github_user_id_str,
        "github_username": github_user["login"],
        "avatar_url": github_user.get("avatar_url"),
        "encrypted_access_token": encrypted_token,
        "token_scope": scope or "",
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    # Upsert into github_integrations
    res = supabase.table("github_integrations").select("id").eq("user_id", user_id).execute()
    if res.data:
        update_res = supabase.table("github_integrations").update(integration_data).eq("user_id", user_id).execute()
        return update_res.data[0] if update_res.data else integration_data
    else:
        insert_res = supabase.table("github_integrations").insert(integration_data).execute()
        return insert_res.data[0] if insert_res.data else integration_data

async def get_github_integration(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves the user's GitHub integration metadata. Decrypted token is ONLY returned
    internally for backend API execution, never exposed to user/API response.
    """
    supabase = get_supabase_client()
    res = supabase.table("github_integrations").select("*").eq("user_id", user_id).execute()
    if not res.data:
        return None
    return res.data[0]

async def delete_github_integration(user_id: str) -> Dict[str, Any]:
    """
    Attempts upstream OAuth grant revocation before deleting local integration record.
    Returns audit status: {'local_deleted': bool, 'upstream_revoked': bool}
    """
    supabase = get_supabase_client()
    integration = await get_github_integration(user_id)
    upstream_revoked = False

    if integration and integration.get("encrypted_access_token"):
        try:
            token = decrypt_token(integration["encrypted_access_token"])
            upstream_revoked = await revoke_github_app_grant(token)
        except Exception:
            upstream_revoked = False

    # Return only the owner column so deletion success can be verified without
    # loading or logging the encrypted credential.
    delete_result = (
        supabase.table("github_integrations")
        .delete()
        .eq("user_id", user_id)
        .select("user_id")
        .execute()
    )
    deleted_rows = getattr(delete_result, "data", None) or []
    local_deleted = any(
        isinstance(row, dict) and str(row.get("user_id")) == str(user_id)
        for row in deleted_rows
    )

    return {
        "local_deleted": local_deleted,
        "upstream_revoked": upstream_revoked
    }
