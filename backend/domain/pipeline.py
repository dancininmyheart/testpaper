from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DocumentPage:
    artifact_id: str = ""
    source_file: str = ""
    page_index: int = 0
    data_url: str = ""
    width: int | None = None
    height: int | None = None
    dpi: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Question:
    question_id: str = ""
    question_no: str = ""
    question_type: str = "unknown"
    content: str = ""
    max_score: float | None = None
    page_index: int | None = None
    skill_tags: list[str] = field(default_factory=list)
    confidence: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnswerBlock:
    block_id: str = ""
    page_index: int = 0
    bbox: list[float] = field(default_factory=list)
    block_type: str = "unknown"
    detector: str = ""
    confidence: float | None = None
    image_artifact_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StudentAnswer:
    question_id: str = ""
    answer_block_id: str = ""
    answer_text: str = ""
    steps: list[str] = field(default_factory=list)
    selected_option: str | None = None
    filled_value: str | None = None
    score: float | None = None
    max_score: float | None = None
    recognition_confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReferenceAnswer:
    question_id: str = ""
    answer_text: str = ""
    final_answer: str | None = None
    steps: list[str] = field(default_factory=list)
    source: str = "uploaded"
    confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Judgement:
    question_id: str = ""
    is_correct: bool | None = None
    score: float | None = None
    max_score: float | None = None
    error_type: str | None = None
    reason: str = ""
    suggestion: str = ""
    confidence: float | None = None
    conflict_flags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisPipelineContext:
    job_id: str = ""
    student_id: str = ""
    input_mode: str = ""
    paper_pages: list[DocumentPage] = field(default_factory=list)
    answer_sheet_pages: list[DocumentPage] = field(default_factory=list)
    answer_key_pages: list[DocumentPage] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)
    answer_blocks: list[dict[str, Any]] = field(default_factory=list)
    student_answers: list[dict[str, Any]] = field(default_factory=list)
    reference_answers: list[dict[str, Any]] = field(default_factory=list)
    judgements: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisStageRun:
    stage: str
    status: str
    elapsed_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)
    error_message: str | None = None
    output: dict[str, Any] = field(default_factory=dict)

    def to_log(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "stage": self.stage,
            "status": self.status,
            "elapsed_ms": round(float(self.elapsed_ms), 1),
        }
        if self.warnings:
            entry["warnings"] = list(self.warnings)
        if self.error_message:
            entry["error_message"] = self.error_message
        for key, value in self.output.items():
            if value is not None:
                entry[key] = value
        return entry
