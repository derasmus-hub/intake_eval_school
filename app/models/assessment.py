from pydantic import BaseModel
from typing import Optional
from enum import Enum


class Bracket(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class QuestionType(str, Enum):
    PLACEMENT = "placement"
    GRAMMAR_MCQ = "grammar_mcq"
    VOCABULARY_FILL = "vocabulary_fill"
    READING_COMPREHENSION = "reading_comprehension"


class PlacementQuestion(BaseModel):
    id: int
    sentence: str
    is_correct: bool
    difficulty: int  # 1-5
    explanation: str


class DiagnosticQuestion(BaseModel):
    id: str  # e.g. "grammar_1", "vocab_2"
    type: QuestionType
    bracket: Bracket
    question: str
    options: Optional[list[str]] = None  # for MCQ
    correct_answer: str
    passage: Optional[str] = None  # for reading comprehension
    skill: str  # "grammar", "vocabulary", "reading"
    topic: str  # e.g. "articles", "present_perfect"


class PlacementAnswer(BaseModel):
    question_id: int
    answer: bool  # student says correct or incorrect


class DiagnosticAnswer(BaseModel):
    question_id: str
    answer: str


class StartAssessmentRequest(BaseModel):
    student_id: int


class PlacementSubmission(BaseModel):
    student_id: int
    assessment_id: int
    answers: list[PlacementAnswer]


class DiagnosticSubmission(BaseModel):
    student_id: int
    assessment_id: int
    answers: list[DiagnosticAnswer]


class PlacementResult(BaseModel):
    bracket: Bracket
    score: int  # number correct out of 5
    detail: str  # explanation of bracket assignment


class SubSkillScore(BaseModel):
    skill: str
    score: float
    level: str
    details: str


class AssessmentResultResponse(BaseModel):
    id: int
    student_id: int
    stage: str
    bracket: Optional[str] = None
    determined_level: Optional[str] = None
    confidence_score: Optional[float] = None
    sub_skill_breakdown: Optional[list[SubSkillScore]] = None
    weak_areas: Optional[list[str]] = None
    ai_analysis: Optional[dict] = None
    status: str
    created_at: Optional[str] = None
