from __future__ import annotations

from backend.domain.models import PaperProjectStatus


class InvalidProjectTransition(Exception):
    """Raised when a paper project status transition is not allowed by the state machine."""

    def __init__(self, from_status: str, to_status: str):
        super().__init__(
            f"invalid paper project transition: {from_status} -> {to_status}"
        )
        self.from_status = from_status
        self.to_status = to_status


_ALLOWED: dict[PaperProjectStatus, frozenset[PaperProjectStatus]] = {
    PaperProjectStatus.DRAFT: frozenset({
        PaperProjectStatus.EXTRACTING,
        PaperProjectStatus.ERROR,
    }),
    PaperProjectStatus.EXTRACTING: frozenset({
        PaperProjectStatus.REVIEW_QUESTIONS,
        PaperProjectStatus.ERROR,
    }),
    PaperProjectStatus.REVIEW_QUESTIONS: frozenset({
        PaperProjectStatus.REVIEW_ANSWERS,
        PaperProjectStatus.READY,
        PaperProjectStatus.ERROR,
    }),
    PaperProjectStatus.READY: frozenset({
        PaperProjectStatus.GENERATING_ANSWERS,
        PaperProjectStatus.RECOGNIZING,
        PaperProjectStatus.ERROR,
    }),
    PaperProjectStatus.GENERATING_ANSWERS: frozenset({
        PaperProjectStatus.REVIEW_ANSWERS,
        PaperProjectStatus.READY,
        PaperProjectStatus.ERROR,
    }),
    PaperProjectStatus.REVIEW_ANSWERS: frozenset({
        PaperProjectStatus.GENERATING_ANSWERS,
        PaperProjectStatus.READY,
        PaperProjectStatus.ERROR,
    }),
    PaperProjectStatus.RECOGNIZING: frozenset({
        PaperProjectStatus.REVIEW_RECOGNITION,
        PaperProjectStatus.REVIEW_SCORES,
        PaperProjectStatus.READY,
        PaperProjectStatus.ERROR,
    }),
    PaperProjectStatus.REVIEW_RECOGNITION: frozenset({
        PaperProjectStatus.REVIEW_SCORES,
        PaperProjectStatus.ERROR,
    }),
    PaperProjectStatus.ANALYZING: frozenset({
        PaperProjectStatus.REVIEW_SCORES,
        PaperProjectStatus.ERROR,
    }),
    PaperProjectStatus.REVIEW_SCORES: frozenset({
        PaperProjectStatus.COMPLETED,
        PaperProjectStatus.PROFILING,
        PaperProjectStatus.ERROR,
    }),
    PaperProjectStatus.PROFILING: frozenset({
        PaperProjectStatus.COMPLETED,
        PaperProjectStatus.ERROR,
    }),
    PaperProjectStatus.COMPLETED: frozenset(),
    PaperProjectStatus.ERROR: frozenset({
        PaperProjectStatus.DRAFT,
    }),
}


def validate_transition(from_status: str, to_status: str) -> None:
    """Raise InvalidProjectTransition if the transition is not allowed."""
    try:
        from_enum = PaperProjectStatus(from_status)
        to_enum = PaperProjectStatus(to_status)
    except ValueError as exc:
        raise InvalidProjectTransition(from_status, to_status) from exc
    if to_enum not in _ALLOWED[from_enum]:
        raise InvalidProjectTransition(from_status, to_status)
