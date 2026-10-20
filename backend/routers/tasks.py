from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any, Optional
from models import TaskResponse, Task, TaskGenerateRequest
from database import get_supabase_client
from services.llm_service import generate_ai_response
from services.auth_service import get_authenticated_user_id

router = APIRouter()

@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: str,
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id)
):
    supabase = get_supabase_client()
    response = supabase.table("tasks").select("*").eq("task_id", task_id).execute()
    
    if not response.data:
        raise HTTPException(status_code=404, detail="Task not found")
        
    task_data = response.data[0]

    # If the task belongs to a project, prevent users who do not own the project from accessing it
    if task_data.get("project_id") and authenticated_user_id:
        proj_res = supabase.table("projects").select("user_id").eq("project_id", task_data["project_id"]).execute()
        if proj_res.data and proj_res.data[0]["user_id"] != authenticated_user_id:
            raise HTTPException(status_code=403, detail="Access denied: You do not own the project associated with this ticket.")
    
    # Do not expose test cases to the frontend
    return TaskResponse(
        task_id=task_data["task_id"],
        project_id=task_data.get("project_id"),
        title=task_data["title"],
        description=task_data["description"],
        task_type=task_data["task_type"],
        difficulty_level=task_data["difficulty_level"],
        persona=task_data["persona"],
        language=task_data["language"],
        starter_code=task_data["starter_code"]
    )

@router.get("", response_model=List[TaskResponse])
def list_tasks_for_project(
    project_id: str,
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id)
):
    """
    Lists engineering assignment tickets belonging to a project.
    Strictly verifies user ownership of the project before returning tasks.
    """
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required to view project assignments.")

    supabase = get_supabase_client()
    proj_res = supabase.table("projects").select("user_id").eq("project_id", project_id).execute()
    if not proj_res.data:
        raise HTTPException(status_code=404, detail="Project not found.")

    if proj_res.data[0]["user_id"] != authenticated_user_id:
        raise HTTPException(status_code=403, detail="Access denied: You do not own this project.")

    tasks_res = (
        supabase.table("tasks")
        .select("*")
        .eq("project_id", project_id)
        .order("created_at", desc=False)
        .execute()
    )

    return [
        TaskResponse(
            task_id=t["task_id"],
            project_id=t.get("project_id"),
            title=t["title"],
            description=t["description"],
            task_type=t["task_type"],
            difficulty_level=t["difficulty_level"],
            persona=t["persona"],
            language=t["language"],
            starter_code=t["starter_code"]
        )
        for t in (tasks_res.data or [])
    ]

@router.post("/generate", response_model=TaskResponse)
def generate_new_task(
    request: TaskGenerateRequest,
    authenticated_user_id: Optional[str] = Depends(get_authenticated_user_id)
):
    supabase = get_supabase_client()
    prior_context_prompt = ""
    project_title = ""
    project_desc = ""

    # Validate project ownership if project_id is provided
    if request.project_id:
        if not authenticated_user_id:
            raise HTTPException(status_code=401, detail="Authentication required to assign tickets to a project.")
            
        proj_res = supabase.table("projects").select("*").eq("project_id", request.project_id).execute()
        if not proj_res.data:
            raise HTTPException(status_code=404, detail="Project not found.")
            
        proj_data = proj_res.data[0]
        if proj_data["user_id"] != authenticated_user_id:
            raise HTTPException(status_code=403, detail="Access denied: You do not own this project.")
            
        project_title = proj_data.get("title", "")
        project_desc = proj_data.get("description", "")

    # Synchronize difficulty_level with authenticated user's profile if available
    effective_difficulty = request.difficulty_level
    if authenticated_user_id:
        try:
            profile_res = supabase.table("profiles").select("current_difficulty_tier").eq("id", authenticated_user_id).single().execute()
            if isinstance(profile_res.data, dict) and profile_res.data.get("current_difficulty_tier") is not None:
                tier_val = profile_res.data["current_difficulty_tier"]
                if isinstance(tier_val, int):
                    effective_difficulty = tier_val
        except Exception as pe:
            print(f"[PROFILE DIFFICULTY LOOKUP WARNING]: {pe}")

    # Check for previous successful submission strictly within the same project
    if authenticated_user_id and request.include_continuity and request.project_id:
        try:
            # 1. Fetch task IDs belonging to this project
            proj_tasks_res = supabase.table("tasks").select("task_id").eq("project_id", request.project_id).execute()
            proj_task_ids = [t["task_id"] for t in proj_tasks_res.data] if proj_tasks_res.data else []

            if proj_task_ids:
                # Passing criteria in evaluations pipeline: correctness_score >= 40 (out of 60)
                sub_res = (
                    supabase.table("submissions")
                    .select("submitted_code, language, tasks(title, description)")
                    .eq("user_id", authenticated_user_id)
                    .in_("task_id", proj_task_ids)
                    .eq("language", request.language.lower())
                    .gte("correctness_score", 40)
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )

                if sub_res.data and len(sub_res.data) > 0:
                    prior_sub = sub_res.data[0]
                    raw_code = (prior_sub.get("submitted_code") or "").strip()
                    # Bound code snippet to maximum 800 characters to prevent prompt bloat
                    bounded_code = raw_code[:800]
                    if len(raw_code) > 800:
                        bounded_code += "\n# ... (truncated for brevity)"

                    prior_task = prior_sub.get("tasks") or {}
                    prior_title = (prior_task.get("title") or "Previous Ticket").strip()
                    raw_desc = (prior_task.get("description") or "").strip()
                    prior_desc_summary = raw_desc[:250] + ("..." if len(raw_desc) > 250 else "")

                    prior_context_prompt = f"""
    CONTEXT FROM PREVIOUS COMPLETED TICKET (Project Code Continuity):
    This ticket is part of Project: "{project_title}".
    The engineer previously completed ticket: "{prior_title}"
    Previous ticket summary: {prior_desc_summary}
    Their working implementation code:
    ```{request.language}
    {bounded_code}
    ```
    INSTRUCTIONS FOR CONTINUITY:
    - This is a follow-up ticket in the same project codebase.
    - If task_type is 'feature-dev': Ask the engineer to implement a new method, add a new related feature, or extend the existing module. The 'starter_code' should contain the working base code or importable stubs from earlier so they can continue building upon it.
    - If task_type is 'bug-fix': Provide a broken extension or integration with the earlier module and test cases that verify both the fix and existing behavior.
    - Ensure function/class naming stays consistent with the previous module.
    """
        except Exception as e:
            # Gracefully log and fall back to standalone ticket generation
            print(f"[PROJECT CONTINUITY CONTEXT LOOKUP WARNING]: {e}")

    prompt = f"""
    Generate a {request.task_type} programming task in {request.language}.
    Target skill level: {request.skill_level} (Difficulty tier: {effective_difficulty}).
    Company Persona: {request.persona}.
    {f'Project Focus: {project_title} - {project_desc}' if project_title else ''}
    {prior_context_prompt}
    If task_type is 'bug-fix': Provide a broken code snippet with logical or syntactic errors and failing test cases.
    If task_type is 'feature-dev': Provide a requirement description and mostly empty starter code (or continuing the base code if continuity context is provided).
    
    Test cases requirements:
    - 'input' should be either:
      1) A direct function call expression matching starter_code signature (e.g. "is_valid_email('test@example.com')", "calculate_total([10, 20])"), OR
      2) Plain arguments/JSON matching starter_code parameters.
    - 'expected_output' must be the exact expected return value formatted as a string (e.g. "True", "False", "63.0", "['read', 'write']").
    - Do not invent non-existent imports or wrapper statements in test case inputs.
    - Test cases must have 'input' and 'expected_output' as strings.
    Return only valid JSON matching the schema.
    """
    
    try:
        generated_task: Task = generate_ai_response(prompt, Task)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    # Ensure generated data aligns with the request
    generated_task.task_type = request.task_type
    generated_task.difficulty_level = effective_difficulty
    generated_task.persona = request.persona
    generated_task.language = request.language
    generated_task.project_id = request.project_id
    
    supabase = get_supabase_client()
    
    # Insert task into database
    insert_data = generated_task.model_dump(exclude={'task_id'})  # task_id is generated by DB
    # Fix test_cases serialization for Supabase
    insert_data['test_cases'] = [
        tc.model_dump() if hasattr(tc, 'model_dump') else tc
        for tc in insert_data.get('test_cases', [])
    ]
    
    db_response = supabase.table("tasks").insert(insert_data).execute()
    
    if not db_response.data:
        raise HTTPException(status_code=500, detail="Failed to save generated task to database")
        
    saved_task = db_response.data[0]
    
    return TaskResponse(
        task_id=saved_task["task_id"],
        project_id=saved_task.get("project_id"),
        title=saved_task["title"],
        description=saved_task["description"],
        task_type=saved_task["task_type"],
        difficulty_level=saved_task["difficulty_level"],
        persona=saved_task["persona"],
        language=saved_task["language"],
        starter_code=saved_task["starter_code"]
    )
