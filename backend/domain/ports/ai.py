from __future__ import annotations

from typing import Any, Protocol

from backend.domain.ai_schemas import (
    ExtractedQuestionSet,
    JudgementSet,
    RecognizedStudentAnswers,
    ReferenceAnswerSet,
    StudentProfileDraft,
)


class QuestionExtractor(Protocol):
    def extract_questions(self, *, paper_pages: list[str], context: dict[str, Any]) -> ExtractedQuestionSet:
        ...


class StudentAnswerRecognizer(Protocol):
    def recognize_student_answers(
        self,
        *,
        answer_pages: list[str],
        questions: ExtractedQuestionSet,
        context: dict[str, Any],
    ) -> RecognizedStudentAnswers:
        ...


class ReferenceAnswerExtractor(Protocol):
    def extract_reference_answers(
        self,
        *,
        answer_key_pages: list[str],
        questions: ExtractedQuestionSet,
        context: dict[str, Any],
    ) -> ReferenceAnswerSet:
        ...


class AnswerJudge(Protocol):
    def judge_answers(
        self,
        *,
        questions: ExtractedQuestionSet,
        student_answers: RecognizedStudentAnswers,
        reference_answers: ReferenceAnswerSet,
        context: dict[str, Any],
    ) -> JudgementSet:
        ...


class ProfileBuilder(Protocol):
    def build_profile(
        self,
        *,
        student_id: str,
        questions: ExtractedQuestionSet,
        judgements: JudgementSet,
        context: dict[str, Any],
    ) -> StudentProfileDraft:
        ...
