from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol


class AnalysisStage(Protocol):
    """Protocol for pipeline analysis stages."""

    def __call__(self, ctx: PipelineContext) -> StageResult:
        ...


@dataclass
class StageResult:
    status: str  # succeeded | partial | failed | skipped
    output: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    elapsed_ms: float = 0.0


@dataclass
class PipelineContext:
    """Context object passed through pipeline stages.

    Carries the shared state that stages read from and write to.
    Individual stages receive this context and update its fields.
    """

    job_id: str = ""
    student_id: str = ""
    input_mode: str = ""

    # Input data
    paper_urls: List[str] = field(default_factory=list)
    answer_urls: List[str] = field(default_factory=list)
    answer_key_urls: List[str] = field(default_factory=list)
    answer_key_source: str = ""
    pre_split_questions: List[Dict[str, Any]] = field(default_factory=list)
    selected_answer_blocks: List[Dict[str, Any]] = field(default_factory=list)

    # Model selection
    vision_profile: str = ""
    text_profile: str = ""

    # Pipeline outputs (populated by stages)
    questions: List[Dict[str, Any]] = field(default_factory=list)
    answers: List[Dict[str, Any]] = field(default_factory=list)
    reference_answers: List[Dict[str, Any]] = field(default_factory=list)
    profile_data: Dict[str, Any] = field(default_factory=dict)
    new_nodes: List[Dict[str, Any]] = field(default_factory=list)
    mapping_report: Dict[str, Any] = field(default_factory=dict)

    # Pipeline metadata
    warnings: List[str] = field(default_factory=list)
    stage_logs: List[Dict[str, Any]] = field(default_factory=list)
    mock_mode: bool = False
