from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, List
from datetime import datetime, timezone
from models import ProjectResponse, ProjectCreateRequest
from database import get_supabase_client
from services.auth_service import get_authenticated_user_id

router = APIRouter()

PROJECT_BLUEPRINTS = {
    "Fintech Startup": {
        "title": "Payment Ledger & Webhook Settlement Engine",
        "description": "High-throughput double-entry financial ledger, idempotent webhook processor, and fraud detection heuristics."
    },
    "Enterprise SaaS": {
        "title": "Multi-Tenant RBAC & Provisioning Core",
        "description": "Enterprise directory sync, hierarchical role-based access control, tenant subdomain router, and rate limiter."
    },
    "AI Startup": {
        "title": "LLM Inference Routing & Guardrails Pipeline",
        "description": "Streaming model gateway, dynamic prompt caching, content guardrails AST evaluator, and token usage aggregator."
    }
}

def get_project_completed_tasks_count(supabase, project_id: str, user_id: str) -> int:
    """
    Computes completed tickets count by strictly counting DISTINCT tasks belonging to this project
    that the authenticated user has passed (correctness_score >= 40).
    Never counts submissions from other projects or users.
    """
    tasks_res = supabase.table("tasks").select("task_id").eq("project_id", project_id).execute()
    if not tasks_res.data:
        return 0
    
    task_ids = [t["task_id"] for t in tasks_res.data]
    
    sub_res = (
        supabase.table("submissions")
        .select("task_id")
        .eq("user_id", user_id)
        .in_("task_id", task_ids)
        .gte("correctness_score", 40)
        .execute()
    )
    
    if not sub_res.data:
        return 0
        
    unique_passed_task_ids = set(s["task_id"] for s in sub_res.data)
    return len(unique_passed_task_ids)

@router.get("/active", response_model=Optional[ProjectResponse])
def get_active_project(
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id)
):
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required to view active project.")

    supabase = get_supabase_client()
    
    # 1. Look for existing active project for this user
    proj_res = (
        supabase.table("projects")
        .select("*")
        .eq("user_id", authenticated_user_id)
        .eq("status", "active")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    
    if proj_res.data and len(proj_res.data) > 0:
        proj = proj_res.data[0]
        completed_count = get_project_completed_tasks_count(supabase, proj["project_id"], authenticated_user_id)
        
        # Check if project has reached its target and should be automatically completed
        if completed_count >= proj.get("target_tickets", 4) and proj["status"] == "active":
            now_iso = datetime.now(timezone.utc).isoformat()
            upd_res = (
                supabase.table("projects")
                .update({"status": "completed", "completed_at": now_iso})
                .eq("project_id", proj["project_id"])
                .execute()
            )
            if upd_res.data:
                proj = upd_res.data[0]

        return ProjectResponse(
            project_id=proj["project_id"],
            user_id=proj["user_id"],
            title=proj["title"],
            description=proj["description"],
            persona=proj["persona"],
            language=proj["language"],
            status=proj["status"],
            target_tickets=proj["target_tickets"],
            completed_tickets_count=completed_count,
            created_at=proj["created_at"],
            completed_at=proj.get("completed_at")
        )

    # 2. If no active project, look up user profile to auto-provision initial project
    profile_res = supabase.table("profiles").select("*").eq("id", authenticated_user_id).single().execute()
    chosen_persona = profile_res.data.get("chosen_persona", "Enterprise SaaS") if profile_res.data else "Enterprise SaaS"
    
    blueprint = PROJECT_BLUEPRINTS.get(chosen_persona, PROJECT_BLUEPRINTS["Enterprise SaaS"])
    
    new_project_data = {
        "user_id": authenticated_user_id,
        "title": blueprint["title"],
        "description": blueprint["description"],
        "persona": chosen_persona,
        "language": "python",
        "status": "active",
        "target_tickets": 4
    }
    
    try:
        ins_res = supabase.table("projects").insert(new_project_data).execute()
        if not ins_res.data:
            raise HTTPException(status_code=500, detail="Failed to initialize active project")
            
        proj = ins_res.data[0]
        return ProjectResponse(
            project_id=proj["project_id"],
            user_id=proj["user_id"],
            title=proj["title"],
            description=proj["description"],
            persona=proj["persona"],
            language=proj["language"],
            status=proj["status"],
            target_tickets=proj["target_tickets"],
            completed_tickets_count=0,
            created_at=proj["created_at"],
            completed_at=None
        )
    except Exception as e:
        # If unique index conflict occurred from concurrent requests, fetch the winner
        winner = (
            supabase.table("projects")
            .select("*")
            .eq("user_id", authenticated_user_id)
            .eq("status", "active")
            .limit(1)
            .execute()
        )
        if winner.data and len(winner.data) > 0:
            proj = winner.data[0]
            completed_count = get_project_completed_tasks_count(supabase, proj["project_id"], authenticated_user_id)
            return ProjectResponse(
                project_id=proj["project_id"],
                user_id=proj["user_id"],
                title=proj["title"],
                description=proj["description"],
                persona=proj["persona"],
                language=proj["language"],
                status=proj["status"],
                target_tickets=proj["target_tickets"],
                completed_tickets_count=completed_count,
                created_at=proj["created_at"],
                completed_at=proj.get("completed_at")
            )
        raise HTTPException(status_code=500, detail=f"Database error initializing project: {str(e)}")

@router.post("/new", response_model=ProjectResponse)
def start_new_project(
    request: ProjectCreateRequest,
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id)
):
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required to start a project.")

    supabase = get_supabase_client()

    # 1. Inspect existing active project
    existing_active = (
        supabase.table("projects")
        .select("*")
        .eq("user_id", authenticated_user_id)
        .eq("status", "active")
        .limit(1)
        .execute()
    )

    if existing_active.data and len(existing_active.data) > 0:
        current_proj = existing_active.data[0]
        completed_count = get_project_completed_tasks_count(supabase, current_proj["project_id"], authenticated_user_id)
        is_completed = completed_count >= current_proj.get("target_tickets", 4)

        if is_completed:
            # Mark completed with timestamp
            supabase.table("projects").update({
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat()
            }).eq("project_id", current_proj["project_id"]).execute()
        else:
            # Project is incomplete: must explicitly require confirmation to abandon
            if not request.abandon_current:
                raise HTTPException(
                    status_code=400,
                    detail="Active project is incomplete. Pass 'abandon_current: true' to abandon it and start a new project."
                )
            # Mark abandoned (NOT completed)
            supabase.table("projects").update({
                "status": "abandoned"
            }).eq("project_id", current_proj["project_id"]).execute()

    # 2. Determine blueprint for new project
    blueprint = PROJECT_BLUEPRINTS.get(request.persona, PROJECT_BLUEPRINTS["Enterprise SaaS"])
    
    new_project_data = {
        "user_id": authenticated_user_id,
        "title": blueprint["title"],
        "description": blueprint["description"],
        "persona": request.persona,
        "language": request.language,
        "status": "active",
        "target_tickets": request.target_tickets
    }

    ins_res = supabase.table("projects").insert(new_project_data).execute()
    if not ins_res.data:
        raise HTTPException(status_code=500, detail="Failed to create new project.")

    proj = ins_res.data[0]
    return ProjectResponse(
        project_id=proj["project_id"],
        user_id=proj["user_id"],
        title=proj["title"],
        description=proj["description"],
        persona=proj["persona"],
        language=proj["language"],
        status=proj["status"],
        target_tickets=proj["target_tickets"],
        completed_tickets_count=0,
        created_at=proj["created_at"],
        completed_at=None
    )
