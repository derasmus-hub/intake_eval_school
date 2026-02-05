from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class WarmUp(BaseModel):
    description: str = ""
    activity: str = ""
    duration_minutes: int = 5
    materials: Optional[list[str]] = None


class Presentation(BaseModel):
    topic: str = ""
    explanation: str = ""
    polish_explanation: str = ""
    examples: list[str] = []
    visual_aid: Optional[str] = None


class ControlledPractice(BaseModel):
    exercises: list[dict] = []
    instructions: str = ""
    instructions_pl: Optional[str] = None


class FreePractice(BaseModel):
    activity: str = ""
    description: str = ""
    prompts: list[str] = []
    success_criteria: Optional[str] = None


class WrapUp(BaseModel):
    summary: str = ""
    homework: Optional[str] = None
    next_preview: Optional[str] = None
    win_activity: str = ""


class LessonContent(BaseModel):
    objective: str = ""
    polish_explanation: str = ""
    exercises: list[dict] = []
    conversation_prompts: list[str] = []
    win_activity: str = ""
    difficulty: str = ""
    # 5-phase structure (Optional — old lessons won't have these)
    warm_up: Optional[WarmUp] = None
    presentation: Optional[Presentation] = None
    controlled_practice: Optional[ControlledPractice] = None
    free_practice: Optional[FreePractice] = None
    wrap_up: Optional[WrapUp] = None


class LessonResponse(BaseModel):
    id: int
    student_id: int
    session_number: int
    objective: Optional[str] = None
    content: Optional[LessonContent] = None
    difficulty: Optional[str] = None
    status: str = "generated"
    created_at: Optional[str] = None


class ProgressEntry(BaseModel):
    lesson_id: int
    student_id: int
    score: float
    notes: Optional[str] = None
    areas_improved: list[str] = []
    areas_struggling: list[str] = []


class ProgressResponse(BaseModel):
    id: int
    student_id: int
    lesson_id: int
    score: float
    notes: Optional[str] = None
    areas_improved: list[str] = []
    areas_struggling: list[str] = []
    completed_at: Optional[str] = None


class ProgressSummary(BaseModel):
    student_id: int
    total_lessons: int = 0
    average_score: float = 0.0
    entries: list[ProgressResponse] = []
    skill_averages: dict[str, float] = {}
