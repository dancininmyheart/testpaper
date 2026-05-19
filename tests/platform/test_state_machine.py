from __future__ import annotations

import pytest

from backend.domain.models import PaperProjectStatus
from backend.domain.state_machine import (
    InvalidProjectTransition,
    _ALLOWED,
    validate_transition,
)


def test_each_allowed_transition_passes():
    for from_enum, to_set in _ALLOWED.items():
        for to_enum in to_set:
            validate_transition(from_enum.value, to_enum.value)


def test_draft_to_analyzing_raises():
    with pytest.raises(InvalidProjectTransition):
        validate_transition(
            PaperProjectStatus.DRAFT.value,
            PaperProjectStatus.ANALYZING.value,
        )


def test_completed_is_terminal():
    assert _ALLOWED[PaperProjectStatus.COMPLETED] == frozenset()
    with pytest.raises(InvalidProjectTransition):
        validate_transition(
            PaperProjectStatus.COMPLETED.value,
            PaperProjectStatus.DRAFT.value,
        )


def test_unknown_status_raises():
    with pytest.raises(InvalidProjectTransition):
        validate_transition("not_a_status", PaperProjectStatus.DRAFT.value)
    with pytest.raises(InvalidProjectTransition):
        validate_transition(PaperProjectStatus.DRAFT.value, "not_a_status")


def test_self_transition_raises():
    with pytest.raises(InvalidProjectTransition):
        validate_transition(
            PaperProjectStatus.READY.value,
            PaperProjectStatus.READY.value,
        )


def test_error_to_draft_allowed_for_manual_recovery():
    validate_transition(
        PaperProjectStatus.ERROR.value,
        PaperProjectStatus.DRAFT.value,
    )


def test_review_questions_cannot_jump_to_completed():
    with pytest.raises(InvalidProjectTransition):
        validate_transition(
            PaperProjectStatus.REVIEW_QUESTIONS.value,
            PaperProjectStatus.COMPLETED.value,
        )


def test_review_questions_can_move_to_reference_answer_review():
    validate_transition(
        PaperProjectStatus.REVIEW_QUESTIONS.value,
        PaperProjectStatus.REVIEW_ANSWERS.value,
    )


def test_review_answers_can_regenerate_reference_answers():
    validate_transition(
        PaperProjectStatus.REVIEW_ANSWERS.value,
        PaperProjectStatus.GENERATING_ANSWERS.value,
    )


def test_invalid_transition_carries_from_and_to():
    try:
        validate_transition("draft", "analyzing")
    except InvalidProjectTransition as exc:
        assert exc.from_status == "draft"
        assert exc.to_status == "analyzing"
    else:
        raise AssertionError("expected InvalidProjectTransition")
