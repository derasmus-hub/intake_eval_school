from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class LessonContent(BaseModel):
    objective: str = ""
    polish_explanation: str = ""
    exercises: list[dict] = []
    conversation_prompts: list[str] = []
    win_activity: str = ""
    difficulty: str = ""


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
