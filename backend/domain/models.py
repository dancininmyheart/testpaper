from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class UserRole(StrEnum):
    ADMIN = "admin"
    TEACHER = "teacher"


class PaperProjectStatus(StrEnum):
    DRAFT = "draft"
    EXTRACTING = "extracting"
    REVIEW_QUESTIONS = "review_questions"
    READY = "ready"
    GENERATING_ANSWERS = "generating_answers"
    REVIEW_ANSWERS = "review_answers"
    RECOGNIZING = "recognizing"
    REVIEW_RECOGNITION = "review_recognition"
    ANALYZING = "analyzing"
    REVIEW_SCORES = "review_scores"
    PROFILING = "profiling"
    COMPLETED = "completed"
    ERROR = "error"

