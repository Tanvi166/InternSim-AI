from pydantic import BaseModel
from typing import List, Optional, Any, Dict

class UserProfile(BaseModel):
    user_id: str
    skill_level: str  # Beginner, Intermediate
    current_difficulty_tier: int
    chosen_persona: str

class TaskGenerateRequest(BaseModel):
    skill_level: str
    persona: str
    difficulty_level: int
    task_type: str
    language: str
    project_id: Optional[str] = None
    include_continuity: bool = True

class TestCase(BaseModel):
    input: str
    expected_output: str
    hidden: bool = False

class Task(BaseModel):
    task_id: Optional[str] = None
    project_id: Optional[str] = None
    title: str
    description: str
    task_type: str # bug-fix, feature-dev
    difficulty_level: int
    persona: str
    language: str # python, javascript
    starter_code: str
    test_cases: List[TestCase]

class TaskResponse(BaseModel):
    task_id: str
    project_id: Optional[str] = None
    title: str
    description: str
    task_type: str
    difficulty_level: int
    persona: str
    language: str
    starter_code: str
    files: Optional[Dict[str, str]] = None
    target_files: Optional[List[str]] = None
    # Notice: test_cases are excluded as per user requirements

class ProjectResponse(BaseModel):
    project_id: str
    user_id: str
    title: str
    description: str
    persona: str
    language: str
    status: str # active, completed, abandoned
    target_tickets: int
    completed_tickets_count: int
    created_at: str
    completed_at: Optional[str] = None

class ProjectCreateRequest(BaseModel):
    persona: str
    language: str = "python"
    target_tickets: int = 4
    abandon_current: bool = False # Must be explicitly true to abandon an incomplete active project

class CodeSubmission(BaseModel):
    task_id: str
    user_id: str
    submitted_code: str
    language: str
    files: Optional[Dict[str, str]] = None

class QualityFeedback(BaseModel):
    readability: int
    structure: int
    edge_cases: int
    naming: int
    comments: str

class SubmissionResult(BaseModel):
    submission_id: Optional[str] = None
    correctness_score: int
    quality_score: int
    total_score: int
    feedback: QualityFeedback

class CodeRunRequest(BaseModel):
    language: str
    code: str
    stdin: Optional[str] = ""
    files: Optional[Dict[str, str]] = None

class CodeRunResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: Optional[int] = 0
    timed_out: bool = False
    error: Optional[str] = None

class SampleTestsRequest(BaseModel):
    task_id: str
    code: str
    language: str
    files: Optional[Dict[str, str]] = None

class SampleTestResult(BaseModel):
    index: int
    input: str
    expected_output: str
    actual_output: str
    passed: bool
    stderr: Optional[str] = ""
    error: Optional[str] = None

class SampleTestsResponse(BaseModel):
    total_samples: int
    passed_samples: int
    results: List[SampleTestResult]
    raw_error: Optional[str] = None
