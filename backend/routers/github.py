"""
GitHub Router for InternSim AI.
Implements secure OAuth flow, state verification, connection status,
authorized repository listing, and account disconnection with upstream revocation.
"""

from fastapi import APIRouter, HTTPException, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import logging
import asyncio
import os
import re
import urllib.parse
import httpx

from services.auth_service import get_authenticated_user_id
from models import CodeRunRequest, CodeRunResult
from services.github_service import (
    OAuthStateStoreError,
    generate_oauth_authorization_url,
    validate_oauth_state,
    exchange_code_for_token,
    fetch_github_user_profile,
    list_authorized_repositories,
    create_github_feature_branch,
    GitHubAuthenticationError,
    GitHubRepositoryAccessError,
    GitHubBranchConflictError,
    GitHubBranchCreationError,
    GitHubRateLimitError,
    GitHubForkError,
    GitHubForkConflictError,
    GitHubForkNotFoundError,
    GitHubForkRateLimitError,
    GitHubStudentProjectStoreError,
    GitHubStudentProjectPendingError,
    GitHubStudentProjectFileNotFoundError,
    GitHubStudentProjectPathIsDirectoryError,
    GitHubStudentProjectFileTooLargeError,
    GitHubStudentProjectBinaryFileError,
    GitHubStudentProjectListingTooLargeError,
    create_or_get_student_starter_fork,
    get_student_starter_fork_status,
    list_student_project_files,
    get_student_project_file,
    verify_student_project_repository_access,
    save_github_integration,
    get_github_integration,
    delete_github_integration,
)
from services.encryption_service import decrypt_token
from services.file_service import validate_and_normalize_files
from services import project_runtime_service
from routers.evaluations import run_code_preview_with_options

router = APIRouter()
logger = logging.getLogger(__name__)

class GitHubExchangeRequest(BaseModel):
    code: str
    state: str
    redirect_uri: Optional[str] = None

class GitHubStatusResponse(BaseModel):
    connected: bool
    github_username: Optional[str] = None
    avatar_url: Optional[str] = None
    scope: Optional[str] = None
    connected_at: Optional[str] = None

class RepositoryItem(BaseModel):
    id: int
    name: str
    full_name: str
    owner: str
    private: bool
    default_branch: str
    html_url: str
    description: Optional[str] = None

class CreateFeatureBranchRequest(BaseModel):
    owner: str = Field(max_length=39)
    repository: str = Field(max_length=100)
    branch_name: str = Field(max_length=120)

class CreateFeatureBranchResponse(BaseModel):
    branch_name: str
    base_branch: str

class StudentForkResponse(BaseModel):
    owner: str
    name: str
    full_name: str
    url: str
    status: str

class StudentProjectFileItem(BaseModel):
    name: str
    path: str
    type: str
    size: Optional[int] = None

class StudentProjectFilesResponse(BaseModel):
    repository_id: int
    repository: str
    path: str
    page: int
    page_size: int
    total: int
    has_more: bool
    next_page: Optional[int] = None
    items: List[StudentProjectFileItem]

class StudentProjectFileResponse(BaseModel):
    repository_id: int
    repository: str
    path: str
    size: int
    content: str

class StudentProjectRunRequest(BaseModel):
    language: str = Field(max_length=20)
    code: str = Field(max_length=1_000_000)
    files: Dict[str, str]
    stdin: Optional[str] = Field(default="", max_length=10_000)

class StudentProjectRuntimeRequest(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=100)
    files: Dict[str, str]
    working_directory: str = Field(default="", max_length=512)

class StudentProjectRuntimeAction(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=100)

class DisconnectResponse(BaseModel):
    message: str
    local_deleted: bool
    upstream_revoked: bool


async def _get_authenticated_github_token(user_id: str) -> str:
    """Load and decrypt only the integration owned by the authenticated user."""
    try:
        integration = await get_github_integration(user_id)
    except Exception as exc:
        logger.error("GitHub integration lookup failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="GitHub connection is temporarily unavailable.") from None
    if not integration or not integration.get("encrypted_access_token"):
        raise HTTPException(status_code=400, detail="GitHub account is not connected.")
    try:
        return decrypt_token(integration["encrypted_access_token"])
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Stored GitHub credentials could not be decrypted. Please reconnect your account.",
        ) from None

@router.get("/auth-url")
async def get_github_auth_url(
    redirect_uri: Optional[str] = None,
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id)
):
    """
    Returns the GitHub authorization URL with a cryptographically secure CSRF state
    bound to the authenticated user's session.
    """
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required to connect GitHub.")

    try:
        url_data = await generate_oauth_authorization_url(authenticated_user_id, redirect_uri)
        return url_data
    except OAuthStateStoreError:
        raise HTTPException(status_code=503, detail="OAuth state storage is temporarily unavailable.")
    except Exception as exc:
        logger.error("GitHub authorization URL setup failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not start GitHub connection. Please try again later.") from None

@router.post("/exchange-code", response_model=GitHubStatusResponse)
async def exchange_github_code(
    payload: GitHubExchangeRequest,
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id)
):
    """
    Validates CSRF state and exchanges the authorization code for an access token.
    Token is encrypted at rest and stored. Returns connection status without token.
    """
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required to link GitHub account.")

    # 1. Validate CSRF state and verify it was generated for this specific user
    try:
        is_valid_state = await validate_oauth_state(payload.state, authenticated_user_id)
    except OAuthStateStoreError:
        raise HTTPException(status_code=503, detail="OAuth state validation is temporarily unavailable.")
    if not is_valid_state:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state parameter. Possible CSRF or expired session."
        )

    # 2. Exchange code for access token via backend-to-GitHub call
    try:
        token_data = await exchange_code_for_token(payload.code, payload.redirect_uri)
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="Failed to retrieve access token from GitHub.")

        # 3. Fetch GitHub profile to verify identity
        github_profile = await fetch_github_user_profile(access_token)

        # 4. Encrypt and save integration in database (checking account uniqueness)
        try:
            saved = await save_github_integration(
                user_id=authenticated_user_id,
                access_token=access_token,
                github_user=github_profile,
                scope=token_data.get("scope")
            )
        except ValueError as dup_err:
            raise HTTPException(status_code=409, detail=str(dup_err))

        return GitHubStatusResponse(
            connected=True,
            github_username=github_profile.get("login"),
            avatar_url=github_profile.get("avatar_url"),
            scope=token_data.get("scope"),
            connected_at=saved.get("created_at") or saved.get("updated_at")
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("GitHub connection failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="GitHub connection failed. Please try again.") from None

@router.get("/status", response_model=GitHubStatusResponse)
async def get_github_status(
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id)
):
    """
    Returns current GitHub connection status for the authenticated user.
    Never exposes encrypted or plaintext tokens.
    """
    if not authenticated_user_id:
        return GitHubStatusResponse(connected=False)

    integration = await get_github_integration(authenticated_user_id)
    if not integration:
        return GitHubStatusResponse(connected=False)

    return GitHubStatusResponse(
        connected=True,
        github_username=integration.get("github_username"),
        avatar_url=integration.get("avatar_url"),
        scope=integration.get("token_scope"),
        connected_at=integration.get("created_at") or integration.get("updated_at")
    )

@router.get("/repositories", response_model=List[RepositoryItem])
async def get_github_repositories(
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id)
):
    """
    Lists repositories authorized for the user's connected GitHub token with pagination.
    Decryption happens strictly in-memory during this call.
    """
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")

    access_token = await _get_authenticated_github_token(authenticated_user_id)

    try:
        repos = await list_authorized_repositories(access_token, max_repos=100)
        return repos
    except PermissionError as pe:
        raise HTTPException(status_code=401, detail=str(pe))
    except TimeoutError as te:
        raise HTTPException(status_code=429, detail=str(te))
    except Exception as exc:
        logger.error("GitHub repository request failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not load repositories. Please try again later.") from None

@router.post("/repositories/branches", response_model=CreateFeatureBranchResponse)
async def create_github_repository_branch(
    payload: CreateFeatureBranchRequest,
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id),
):
    """Create a feature branch using only the authenticated user's linked GitHub token."""
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")

    access_token = await _get_authenticated_github_token(authenticated_user_id)

    try:
        return await create_github_feature_branch(
            access_token,
            payload.owner,
            payload.repository,
            payload.branch_name,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="Provide a valid feature branch name and repository.") from None
    except GitHubBranchConflictError:
        raise HTTPException(status_code=409, detail="That branch already exists or conflicts with an existing Git ref.") from None
    except GitHubAuthenticationError:
        raise HTTPException(status_code=401, detail="GitHub credentials are no longer valid. Please reconnect your account.") from None
    except GitHubRepositoryAccessError:
        raise HTTPException(status_code=403, detail="The connected GitHub account cannot access this repository.") from None
    except GitHubRateLimitError:
        raise HTTPException(status_code=429, detail="GitHub rate limit reached. Please try again later.") from None
    except GitHubBranchCreationError:
        logger.warning("GitHub branch request failed safely for user %s", authenticated_user_id)
        raise HTTPException(status_code=502, detail="GitHub could not create the branch. Please try again later.") from None
    except Exception as exc:
        logger.error("GitHub branch creation failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not create the branch. Please try again later.") from None


def _map_student_fork_error(exc: Exception) -> HTTPException:
    if isinstance(exc, GitHubStudentProjectStoreError):
        return HTTPException(status_code=503, detail="Student project storage is temporarily unavailable.")
    if isinstance(exc, GitHubForkNotFoundError):
        return HTTPException(status_code=404, detail="No starter project copy was found for this account.")
    if isinstance(exc, GitHubForkConflictError):
        return HTTPException(status_code=409, detail="GitHub reports a repository conflict. Check whether your fork already exists and retry.")
    if isinstance(exc, GitHubForkRateLimitError):
        return HTTPException(status_code=429, detail="GitHub rate limit reached. Please try again later.")
    if isinstance(exc, GitHubAuthenticationError):
        return HTTPException(status_code=401, detail="GitHub credentials are no longer valid. Please reconnect your account.")
    if isinstance(exc, GitHubRepositoryAccessError):
        return HTTPException(status_code=403, detail="The connected GitHub account lacks access needed to fork this starter.")
    if isinstance(exc, GitHubForkError):
        return HTTPException(status_code=502, detail="GitHub could not complete the starter fork request. Please try again.")
    return HTTPException(status_code=502, detail="Could not complete the starter fork request. Please try again.")


def _map_student_project_file_error(exc: Exception) -> HTTPException:
    if isinstance(exc, GitHubStudentProjectStoreError):
        return HTTPException(status_code=503, detail="Student project storage is temporarily unavailable.")
    if isinstance(exc, GitHubForkNotFoundError):
        return HTTPException(status_code=404, detail="No verified student project copy was found for this account.")
    if isinstance(exc, GitHubStudentProjectPendingError):
        return HTTPException(status_code=409, detail="Your project copy is still being prepared. Try again shortly.")
    if isinstance(exc, GitHubStudentProjectFileNotFoundError):
        return HTTPException(status_code=404, detail="The requested repository path was not found.")
    if isinstance(exc, GitHubStudentProjectPathIsDirectoryError):
        return HTTPException(status_code=400, detail="Choose a file rather than a folder.")
    if isinstance(exc, GitHubStudentProjectFileTooLargeError):
        return HTTPException(status_code=413, detail="This file exceeds the 1 MB preview limit.")
    if isinstance(exc, GitHubStudentProjectListingTooLargeError):
        return HTTPException(status_code=413, detail="This repository folder is too large to list safely.")
    if isinstance(exc, GitHubStudentProjectBinaryFileError):
        return HTTPException(status_code=415, detail="This file is binary or is not supported for text preview.")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail="Repository path or pagination values are invalid.")
    if isinstance(exc, GitHubForkRateLimitError):
        return HTTPException(status_code=429, detail="GitHub rate limit reached. Please try again later.")
    if isinstance(exc, GitHubAuthenticationError):
        return HTTPException(status_code=401, detail="GitHub credentials are no longer valid. Please reconnect your account.")
    if isinstance(exc, GitHubRepositoryAccessError):
        return HTTPException(status_code=403, detail="The connected GitHub account cannot access this project copy.")
    if isinstance(exc, GitHubForkError):
        return HTTPException(status_code=502, detail="GitHub could not load the project files. Please try again.")
    return HTTPException(status_code=502, detail="Could not load project files. Please try again.")


@router.post("/starter-project/fork", response_model=StudentForkResponse)
async def create_student_starter_fork(
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id),
):
    """Create or return the current user's copy of the server-configured starter repository."""
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    access_token = await _get_authenticated_github_token(authenticated_user_id)
    try:
        return await create_or_get_student_starter_fork(authenticated_user_id, access_token)
    except Exception as exc:
        logger.error("Starter fork request failed (%s)", type(exc).__name__)
        raise _map_student_fork_error(exc) from None


@router.get("/starter-project/fork", response_model=StudentForkResponse)
async def get_student_starter_fork(
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id),
):
    """Refresh and return only the authenticated user's persisted starter-fork status."""
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    access_token = await _get_authenticated_github_token(authenticated_user_id)
    try:
        return await get_student_starter_fork_status(authenticated_user_id, access_token)
    except Exception as exc:
        logger.error("Starter fork status check failed (%s)", type(exc).__name__)
        raise _map_student_fork_error(exc) from None


@router.get("/student-project/files", response_model=StudentProjectFilesResponse)
async def get_student_project_files(
    path: str = Query("", max_length=1024),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=100),
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id),
):
    """List one folder from the authenticated user's mapped student fork."""
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    access_token = await _get_authenticated_github_token(authenticated_user_id)
    try:
        return await list_student_project_files(
            authenticated_user_id,
            access_token,
            path=path,
            page=page,
            page_size=page_size,
        )
    except Exception as exc:
        logger.error("Student project file listing failed (%s)", type(exc).__name__)
        raise _map_student_project_file_error(exc) from None


@router.get("/student-project/file", response_model=StudentProjectFileResponse)
async def get_student_project_file_content(
    path: str = Query(..., min_length=1, max_length=1024),
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id),
):
    """Read one bounded text file from the authenticated user's mapped student fork."""
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    access_token = await _get_authenticated_github_token(authenticated_user_id)
    try:
        return await get_student_project_file(authenticated_user_id, access_token, path)
    except Exception as exc:
        logger.error("Student project file retrieval failed (%s)", type(exc).__name__)
        raise _map_student_project_file_error(exc) from None


@router.post("/student-project/run", response_model=CodeRunResult)
async def run_student_project_draft(
    request: StudentProjectRunRequest,
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id),
):
    """Run only validated local draft buffers after rechecking mapped repo ownership."""
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    language = request.language.casefold()
    if language not in {"python", "py", "javascript", "js"}:
        raise HTTPException(status_code=422, detail="Only Python and JavaScript draft execution is supported.")
    if (
        len(request.files) > 200
        or any(len(path) > 1024 for path in request.files)
        or sum(len(path) + len(content) for path, content in request.files.items()) > 10_010_000
    ):
        raise HTTPException(status_code=413, detail="The draft workspace exceeds the execution size limit.")
    try:
        validate_and_normalize_files(request.code, language, request.files)
    except ValueError:
        raise HTTPException(status_code=400, detail="The draft contains an invalid or unsupported file path.") from None

    access_token = await _get_authenticated_github_token(authenticated_user_id)
    try:
        await verify_student_project_repository_access(authenticated_user_id, access_token)
        return await run_code_preview_with_options(CodeRunRequest(
            language=language,
            code=request.code,
            stdin=request.stdin or "",
            files=request.files,
        ), allow_local_fallback=False)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Student project draft execution failed (%s)", type(exc).__name__)
        raise _map_student_project_file_error(exc) from None


async def _authorize_project_runtime(user_id: str) -> None:
    token = await _get_authenticated_github_token(user_id)
    try:
        await verify_student_project_repository_access(user_id, token)
    except Exception as exc:
        raise _map_student_project_file_error(exc) from None


@router.post("/student-project/runtime/start")
async def start_student_project_runtime(
    request: StudentProjectRuntimeRequest,
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id),
):
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    await _authorize_project_runtime(authenticated_user_id)
    try:
        return await __import__("asyncio").to_thread(
            project_runtime_service.start_project, authenticated_user_id,
            request.workspace_id, request.files, request.working_directory,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except project_runtime_service.RuntimeErrorBase as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.post("/student-project/runtime/status")
async def student_project_runtime_status(
    request: StudentProjectRuntimeAction,
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id),
):
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    await _authorize_project_runtime(authenticated_user_id)
    try:
        return await __import__("asyncio").to_thread(project_runtime_service.get_status, authenticated_user_id, request.workspace_id)
    except project_runtime_service.RuntimeErrorBase as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.post("/student-project/runtime/logs")
async def student_project_runtime_logs(
    request: StudentProjectRuntimeAction,
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id),
):
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    await _authorize_project_runtime(authenticated_user_id)
    try:
        return await __import__("asyncio").to_thread(project_runtime_service.get_logs, authenticated_user_id, request.workspace_id)
    except project_runtime_service.RuntimeErrorBase as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.post("/student-project/runtime/stop")
async def stop_student_project_runtime(
    request: StudentProjectRuntimeAction,
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id),
):
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    await _authorize_project_runtime(authenticated_user_id)
    try:
        return await __import__("asyncio").to_thread(project_runtime_service.stop_project, authenticated_user_id, request.workspace_id)
    except project_runtime_service.RuntimeErrorBase as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.post("/student-project/runtime/preview")
async def create_student_project_preview(
    request: StudentProjectRuntimeAction,
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id),
):
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    await _authorize_project_runtime(authenticated_user_id)
    public_base = os.getenv("PROJECT_RUNTIME_PREVIEW_PUBLIC_BASE_URL", "").strip()
    if not public_base:
        raise HTTPException(status_code=503, detail="Configure the authenticated preview proxy public base URL first.")
    try:
        preview = await asyncio.to_thread(
            project_runtime_service.create_preview_session,
            authenticated_user_id, request.workspace_id, public_base,
        )
        response = Response(content=__import__("json").dumps({"preview_url": preview["preview_url"]}), media_type="application/json")
        response.set_cookie(
            _preview_cookie_name(request.workspace_id), preview["cookie_token"],
            max_age=project_runtime_service.TIMEOUT, httponly=True,
            secure=public_base.startswith("https://"), samesite="lax",
            path=f"/api/github/student-project/runtime/preview/{request.workspace_id}/",
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    except project_runtime_service.RuntimeErrorBase as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


def _preview_cookie_name(workspace_id: str) -> str:
    import hashlib
    return "internsim_preview_" + hashlib.sha256(workspace_id.encode()).hexdigest()[:12]


async def _proxy_student_preview(workspace_id: str, path: str, request: Request, head_only: bool = False):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", workspace_id):
        raise HTTPException(status_code=404, detail="Preview not found.")
    decoded = path
    for _ in range(3):
        decoded = urllib.parse.unquote(decoded)
        if "\\" in decoded or "\x00" in decoded or any(part in {".", ".."} for part in decoded.split("/")):
            raise HTTPException(status_code=400, detail="Invalid preview path.")
    if len(request.url.query) > 8192:
        raise HTTPException(status_code=413, detail="Preview query is too large.")
    token = request.cookies.get(_preview_cookie_name(workspace_id))
    if not token:
        raise HTTPException(status_code=401, detail="Preview session is required.")
    body = b"" if head_only else await request.body()
    if len(body) > 2_000_000:
        raise HTTPException(status_code=413, detail="Preview request body is too large.")
    try:
        host, port = await asyncio.to_thread(project_runtime_service.preview_target, workspace_id, token)
        safe_path = urllib.parse.quote(decoded, safe="/-._~!$&'()*+,;=:@")
        upstream_url = f"http://{host}:{port}/{safe_path}"
        headers = {name: request.headers[name] for name in ("accept", "content-type", "range", "if-none-match", "if-modified-since") if name in request.headers}
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            async with client.stream(request.method, upstream_url, params=request.query_params, headers=headers, content=body) as upstream:
                output_headers = {name: upstream.headers[name] for name in ("content-type", "cache-control", "etag", "last-modified", "content-range", "accept-ranges") if name in upstream.headers}
                location = upstream.headers.get("location")
                chunks = bytearray()
                if not head_only:
                    async for chunk in upstream.aiter_bytes():
                        if len(chunks) + len(chunk) > 15_000_000:
                            raise HTTPException(status_code=502, detail="Preview response exceeded the size limit.")
                        chunks.extend(chunk)
                payload = bytes(chunks)
                status_code = upstream.status_code
        if location and location.startswith("/") and not location.startswith("//"):
            output_headers["location"] = f"/api/github/student-project/runtime/preview/{workspace_id}{location}"
        return Response(payload, status_code=status_code, headers=output_headers)
    except HTTPException:
        raise
    except project_runtime_service.RuntimeErrorBase as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from None
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Preview application is not accepting connections.") from None


@router.api_route("/student-project/runtime/preview/{workspace_id}/", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_student_project_preview_root(workspace_id: str, request: Request):
    return await _proxy_student_preview(workspace_id, "", request, request.method == "HEAD")


@router.api_route("/student-project/runtime/preview/{workspace_id}/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_student_project_preview_path(workspace_id: str, path: str, request: Request):
    return await _proxy_student_preview(workspace_id, path, request, request.method == "HEAD")

@router.delete("/disconnect", response_model=DisconnectResponse)
async def disconnect_github(
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id)
):
    """
    Disconnects the user's GitHub account, attempts upstream token revocation,
    and removes local stored credentials.
    """
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")

    try:
        result = await delete_github_integration(authenticated_user_id)
    except Exception as exc:
        logger.error("GitHub disconnect failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not disconnect GitHub. Please try again.") from None
    local_deleted = result.get("local_deleted", False)
    upstream_revoked = result.get("upstream_revoked", False)
    if local_deleted:
        message = "GitHub account disconnected successfully. "
        message += "GitHub access was revoked." if upstream_revoked else (
            "Local credentials were removed, but GitHub access could not be revoked. "
            "Revoke it in GitHub settings."
        )
    else:
        message = "Local GitHub credentials were not removed. "
        message += "GitHub access was revoked." if upstream_revoked else (
            "GitHub access could not be revoked; it may remain active. "
            "Revoke it in GitHub settings."
        )

    return DisconnectResponse(
        message=message,
        local_deleted=local_deleted,
        upstream_revoked=upstream_revoked
    )
