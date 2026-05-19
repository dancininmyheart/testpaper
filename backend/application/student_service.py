from __future__ import annotations

import copy
from typing import Any

from backend.infrastructure.repositories import PaperRepository, StudentRepository


class StudentService:
    def __init__(self, repo: StudentRepository, paper_repo: PaperRepository | None = None):
        self.repo = repo
        self.paper_repo = paper_repo

    @staticmethod
    def _clean_text(value: Any) -> str:
        return str(value or "").strip()

    def list_students(self, *, actor_user_id: int) -> list[dict[str, Any]]:
        return self.repo.list_students(created_by=actor_user_id)

    def create_student(self, *, payload: dict[str, Any], actor_user_id: int) -> dict[str, Any]:
        student_id = self._clean_text(payload.get("student_id"))
        name = self._clean_text(payload.get("name"))
        grade = self._clean_text(payload.get("grade"))
        if not student_id:
            raise ValueError("student_id is required")
        if not name:
            raise ValueError("name is required")
        return self.repo.create_student(
            student_id=student_id,
            name=name,
            grade=grade,
            created_by=actor_user_id,
        )

    def update_student(self, *, student_id: str, payload: dict[str, Any], actor_user_id: int) -> dict[str, Any]:
        clean_id = self._clean_text(student_id)
        if not clean_id:
            raise ValueError("student_id is required")
        if self.repo.get_student(student_id=clean_id, created_by=actor_user_id) is None:
            raise LookupError("student not found")
        name = self._clean_text(payload.get("name")) if "name" in payload else None
        grade = self._clean_text(payload.get("grade")) if "grade" in payload else None
        if name is not None and not name:
            raise ValueError("name is required")
        updated = self.repo.update_student(
            student_id=clean_id,
            created_by=actor_user_id,
            name=name,
            grade=grade,
        )
        if updated is None:
            raise LookupError("student not found")
        return updated

    def require_student(self, *, student_id: str, actor_user_id: int) -> dict[str, Any]:
        clean_id = self._clean_text(student_id)
        if not clean_id:
            raise ValueError("student_id is required")
        student = self.repo.get_student(student_id=clean_id, created_by=actor_user_id)
        if student is None:
            raise LookupError("student not found")
        return student

    def list_project_history(self, *, student_id: str, actor_user_id: int) -> list[dict[str, Any]]:
        self.require_student(student_id=student_id, actor_user_id=actor_user_id)
        return self.repo.list_latest_project_reports(student_id=student_id, created_by=actor_user_id)

    def get_project_report(self, *, student_id: str, project_id: str, actor_user_id: int) -> dict[str, Any]:
        self.require_student(student_id=student_id, actor_user_id=actor_user_id)
        report = self.repo.get_latest_project_report(
            student_id=student_id,
            project_id=project_id,
            created_by=actor_user_id,
        )
        if not isinstance(report, dict):
            raise LookupError("student project report not found")
        return self._enrich_report_question_text(report=report, project_id=project_id)

    @staticmethod
    def _question_lookup_key(value: Any) -> str:
        return str(value or "").replace("（整题）", "").replace("(整题)", "").strip()

    @staticmethod
    def _has_question_text(item: dict[str, Any]) -> bool:
        for key in ("problem_text_full", "problem_text", "question_anchor_text", "question_text"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return True
        return False

    @staticmethod
    def _candidate_question_ids(item: dict[str, Any]) -> list[str]:
        values = [
            item.get("display_question_id"),
            item.get("sub_question_id"),
            item.get("question_id"),
            item.get("parent_question_id"),
        ]
        output: list[str] = []
        for value in values:
            key = StudentService._question_lookup_key(value)
            if key and key not in output:
                output.append(key)
        return output

    def _enrich_report_question_text(self, *, report: dict[str, Any], project_id: str) -> dict[str, Any]:
        if self.paper_repo is None:
            return report
        questions = self.paper_repo.get_questions(project_id)
        question_text_by_id: dict[str, str] = {}
        for question in questions:
            question_id = self._question_lookup_key(question.get("question_id"))
            content = str(question.get("content") or "").strip()
            if question_id and content:
                question_text_by_id[question_id] = content

        if not question_text_by_id:
            return report

        enriched = copy.deepcopy(report)
        for list_key in ("answer_trace_display", "answer_trace", "structured_questions_full", "question_analysis"):
            items = enriched.get(list_key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or self._has_question_text(item):
                    continue
                text = ""
                for question_id in self._candidate_question_ids(item):
                    text = question_text_by_id.get(question_id, "")
                    if text:
                        break
                if not text:
                    continue
                item["problem_text"] = text
                item["problem_text_full"] = text
                item["question_anchor_text"] = text
        return enriched
