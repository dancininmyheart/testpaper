from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QuestionItem(BaseModel):
    question_id: str = Field(default="")
    question_no: str = Field(default="")
    question_type: str = Field(default="unknown")
    content: str = Field(default="")
    max_score: float | None = None
    page_index: int | None = None
    skill_tags: list[str] = Field(default_factory=list)
    confidence: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ExtractedQuestionSet(BaseModel):
    questions: list[QuestionItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StudentAnswerItem(BaseModel):
    question_id: str = Field(default="")
    answer_text: str = Field(default="")
    steps: list[str] = Field(default_factory=list)
    selected_option: str | None = None
    filled_value: str | None = None
    score: float | None = None
    max_score: float | None = None
    confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class RecognizedStudentAnswers(BaseModel):
    answers: list[StudentAnswerItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ReferenceAnswerItem(BaseModel):
    question_id: str = Field(default="")
    analysis: str = Field(default="")
    answer_text: str = Field(default="")
    final_answer: str | None = None
    steps: list[str] = Field(default_factory=list)
    source: str = Field(default="uploaded")
    confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class ReferenceAnswerSet(BaseModel):
    reference_answers: list[ReferenceAnswerItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class JudgementItem(BaseModel):
    question_id: str = Field(default="")
    is_correct: bool | None = None
    score: float | None = None
    max_score: float | None = None
    error_type: str | None = None
    reason: str = Field(default="")
    suggestion: str = Field(default="")
    confidence: float | None = None
    conflict_flags: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class JudgementSet(BaseModel):
    judgements: list[JudgementItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StudentProfileDraft(BaseModel):
    student_id: str = Field(default="")
    summary: str = Field(default="")
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    literacy: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class PaperProjectDraft(BaseModel):
    project_id: str = ""
    title: str = ""
    subject: str = ""
    grade: str = ""
    status: str = "draft"
    student_count: int = 0
    paper_page_count: int = 0
    answer_key_source: str = ""
    error_message: str | None = None
    question_count: int = 0
    reference_answer_count: int = 0
    created_by: int = 0
    created_at: str = ""
    updated_at: str = ""


class PaperQuestionItem(BaseModel):
    question_id: str = ""
    question_no: str = ""
    question_type: str = "unknown"
    content: str = ""
    max_score: float | None = None
    page_index: int | None = None
    skill_tags: list[str] = Field(default_factory=list)
    confidence: float | None = None
    sort_order: int = 0
    parent_question_id: str | None = None


class PaperProjectSnapshot(BaseModel):
    """Complete snapshot of a ready paper project for use in student pipelines."""
    project_id: str = ""
    title: str = ""
    subject: str = ""
    grade: str = ""
    questions: list[QuestionItem] = Field(default_factory=list)
    reference_answers: list[ReferenceAnswerItem] = Field(default_factory=list)
    skill_alias_map: dict[str, str] = Field(default_factory=dict)
    new_knowledge_points: list[dict[str, Any]] = Field(default_factory=list)


# ============================================================
# API 统一请求/响应 Schema
# ============================================================

class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class UserInfo(BaseModel):
    id: int
    username: str
    role: str


class LoginResponse(BaseModel):
    token: str
    expires_at: str
    user: UserInfo


class CreateProjectRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    subject: str = ""
    grade: str = ""


class ProjectData(BaseModel):
    project_id: str
    title: str
    subject: str
    grade: str
    status: str
    student_count: int = 0
    paper_page_count: int = 0
    answer_key_source: str = ""
    error_message: str | None = None
    question_count: int = 0
    reference_answer_count: int = 0
    created_by: int = 0
    created_at: str = ""
    updated_at: str = ""


class CreateJobRequest(BaseModel):
    student_id: str = Field(min_length=1)
    input_mode: str = Field(min_length=1)
    vision_profile: str | None = None
    text_profile: str | None = None
    pre_split_questions: list[dict[str, Any]] = Field(default_factory=list)
    selected_answer_blocks: list[dict[str, Any]] = Field(default_factory=list)


class JobData(BaseModel):
    job_id: str
    student_id: str
    input_mode: str
    status: str
    attempt_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    error_message: str | None = None


class IngestMasteryRequest(BaseModel):
    records: list[dict[str, Any]]


class SkillMasteryData(BaseModel):
    skill_id: str
    mastery: float = 0.0
    level: str = ""
    uncertainty: float | None = None


class MasteryData(BaseModel):
    student_id: str = ""
    skills: list[SkillMasteryData] = Field(default_factory=list)
    skill_count: int = 0
    weak_count: int = 0
    average_mastery: float = 0.0


class GroupSkillRisk(BaseModel):
    skill_id: str
    total_count: int = 0
    avg_score_ratio: float = 0.0
    top_error_type: str = ""
    risk_level: str = "low"


class GroupExamSummary(BaseModel):
    paper_id: str = ""
    problem_count: int = 0
    skill_count: int = 0
    skills: list[GroupSkillRisk] = Field(default_factory=list)
