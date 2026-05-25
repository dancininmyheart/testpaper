from __future__ import annotations

from typing import Any

from backend.infrastructure.repositories import (
    AnalysisReviewRepository,
    StudentRepository,
    StudentStateRepository,
    now_iso,
)


SOURCE_VERSION = "student_state_v1"


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number > 1.0 and number <= 100.0:
        number = number / 100.0
    return round(max(0.0, min(1.0, number)), 4)


def _clean_id(value: Any) -> str:
    return str(value or "").strip()


def _list_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _first_text(item: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


class StudentStateService:
    def __init__(
        self,
        *,
        student_repo: StudentRepository,
        review_repo: AnalysisReviewRepository,
        state_repo: StudentStateRepository,
    ) -> None:
        self.student_repo = student_repo
        self.review_repo = review_repo
        self.state_repo = state_repo

    def empty_state(self, *, student_id: str) -> dict[str, Any]:
        return {
            "student_id": student_id,
            "summary": {
                "overall_mastery": 0.0,
                "overall_literacy": 0.0,
                "risk_level": "unknown",
                "exam_count": 0,
                "weak_skill_count": 0,
                "strong_skill_count": 0,
                "recommendations": [],
            },
            "mastery": [],
            "literacy": [],
            "evidence": {"recent_reports": [], "weak_questions": []},
            "source_report_ids": [],
            "source_version": SOURCE_VERSION,
            "updated_at": "",
        }

    def get_student_state(self, *, student_id: str, actor_user_id: int) -> dict[str, Any]:
        clean_student_id = _clean_id(student_id)
        if not clean_student_id:
            raise ValueError("student_id is required")
        if self.student_repo.get_student(student_id=clean_student_id, created_by=actor_user_id) is None:
            raise LookupError("student not found")
        snapshot = self.state_repo.get_snapshot(student_id=clean_student_id, created_by=actor_user_id)
        if snapshot is None:
            return self.empty_state(student_id=clean_student_id)
        return snapshot

    def refresh_student_state(self, *, student_id: str, actor_user_id: int) -> dict[str, Any]:
        clean_student_id = _clean_id(student_id)
        if not clean_student_id:
            raise ValueError("student_id is required")
        if self.student_repo.get_student(student_id=clean_student_id, created_by=actor_user_id) is None:
            raise LookupError("student not found")
        reports = self.review_repo.list_approved_student_reports(
            student_id=clean_student_id,
            created_by=actor_user_id,
        )
        latest_by_project: dict[str, dict[str, Any]] = {}
        for report in reports:
            project_id = _clean_id(report.get("project_id"))
            if project_id and project_id not in latest_by_project:
                latest_by_project[project_id] = report
        selected_reports = list(reversed(list(latest_by_project.values())))
        state = self._build_state(student_id=clean_student_id, reports=selected_reports)
        self.state_repo.save_snapshot(
            student_id=clean_student_id,
            created_by=actor_user_id,
            summary=state["summary"],
            mastery=state["mastery"],
            literacy=state["literacy"],
            evidence=state["evidence"],
            source_report_ids=state["source_report_ids"],
            source_version=SOURCE_VERSION,
            updated_at=state["updated_at"],
        )
        return state

    def approve_report_and_refresh(
        self,
        *,
        job_id: str,
        project_id: str,
        student_id: str,
        actor_user_id: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        review = self.review_repo.approve_job(
            job_id=job_id,
            project_id=project_id,
            student_id=student_id,
            reviewed_by=actor_user_id,
        )
        state = self.refresh_student_state(student_id=student_id, actor_user_id=actor_user_id)
        return review, state

    def _build_state(self, *, student_id: str, reports: list[dict[str, Any]]) -> dict[str, Any]:
        if not reports:
            return self.empty_state(student_id=student_id)

        skill_samples: dict[str, list[dict[str, Any]]] = {}
        literacy_samples: dict[str, list[dict[str, Any]]] = {}
        weak_questions: list[dict[str, Any]] = []
        recent_reports: list[dict[str, Any]] = []
        source_report_ids: list[str] = []

        for index, report in enumerate(reports, start=1):
            result = report.get("result") if isinstance(report.get("result"), dict) else {}
            weight = float(index)
            job_id = _clean_id(report.get("job_id"))
            if job_id:
                source_report_ids.append(job_id)
            recent_reports.append(
                {
                    "job_id": job_id,
                    "project_id": _clean_id(report.get("project_id")),
                    "title": _clean_id(report.get("title")),
                    "reviewed_at": _clean_id(report.get("reviewed_at")),
                }
            )
            self._collect_profile_mastery(skill_samples, result, weight, report)
            self._collect_profile_literacy(literacy_samples, result, weight, report)
            if not skill_samples:
                self._collect_trace_mastery(skill_samples, weak_questions, result, weight, report)

        mastery = self._summarize_samples(skill_samples, id_key="skill_id")
        literacy = self._summarize_samples(literacy_samples, id_key="literacy_id")
        overall_mastery = self._average([item["value"] for item in mastery])
        overall_literacy = self._average([item["value"] for item in literacy])
        weak_skill_count = len([item for item in mastery if item["value"] < 0.6])
        strong_skill_count = len([item for item in mastery if item["value"] >= 0.8])
        summary = {
            "overall_mastery": overall_mastery,
            "overall_literacy": overall_literacy,
            "risk_level": self._risk_level(overall_mastery, weak_skill_count),
            "exam_count": len(reports),
            "weak_skill_count": weak_skill_count,
            "strong_skill_count": strong_skill_count,
            "recommendations": self._recommendations(mastery),
        }
        return {
            "student_id": student_id,
            "summary": summary,
            "mastery": mastery,
            "literacy": literacy,
            "evidence": {
                "recent_reports": list(reversed(recent_reports[-5:])),
                "weak_questions": weak_questions[-10:],
            },
            "source_report_ids": source_report_ids,
            "source_version": SOURCE_VERSION,
            "updated_at": now_iso(),
        }

    def _collect_profile_mastery(
        self,
        samples: dict[str, list[dict[str, Any]]],
        result: dict[str, Any],
        weight: float,
        report: dict[str, Any],
    ) -> None:
        profile = result.get("student_profile") if isinstance(result.get("student_profile"), dict) else {}
        mastery = profile.get("mastery") if isinstance(profile, dict) else []
        if not isinstance(mastery, list):
            return
        for item in mastery:
            if not isinstance(item, dict):
                continue
            skill_id = _first_text(item, ["skill_id", "id", "knowledge_id", "knowledge_point"])
            if not skill_id:
                continue
            value = _clamp01(item.get("value", item.get("mastery", item.get("score"))))
            samples.setdefault(skill_id, []).append(
                {
                    "value": value,
                    "weight": weight,
                    "name": _first_text(item, ["skill_name", "name", "knowledge_name"]) or skill_id,
                    "last_seen_at": _clean_id(report.get("reviewed_at")),
                }
            )

    def _collect_profile_literacy(
        self,
        samples: dict[str, list[dict[str, Any]]],
        result: dict[str, Any],
        weight: float,
        report: dict[str, Any],
    ) -> None:
        profile = result.get("student_profile") if isinstance(result.get("student_profile"), dict) else {}
        literacy = profile.get("literacy") if isinstance(profile, dict) else []
        if not isinstance(literacy, list):
            return
        for item in literacy:
            if not isinstance(item, dict):
                continue
            literacy_id = _first_text(item, ["literacy_id", "dimension_id", "id"])
            if not literacy_id:
                continue
            value = _clamp01(item.get("value", item.get("score", item.get("mastery"))))
            samples.setdefault(literacy_id, []).append(
                {
                    "value": value,
                    "weight": weight,
                    "name": _first_text(item, ["name", "label"]) or literacy_id,
                    "last_seen_at": _clean_id(report.get("reviewed_at")),
                }
            )

    def _collect_trace_mastery(
        self,
        samples: dict[str, list[dict[str, Any]]],
        weak_questions: list[dict[str, Any]],
        result: dict[str, Any],
        weight: float,
        report: dict[str, Any],
    ) -> None:
        traces = result.get("answer_trace_display") or result.get("answer_trace") or []
        if not isinstance(traces, list):
            return
        for item in traces:
            if not isinstance(item, dict):
                continue
            max_score = _clamp01(item.get("max_score"), default=0.0)
            raw_max = item.get("max_score")
            try:
                score_ratio = float(item.get("score") or 0.0) / float(raw_max or 0.0)
            except (TypeError, ValueError, ZeroDivisionError):
                score_ratio = 0.0
            score_ratio = _clamp01(score_ratio)
            skills: list[str] = []
            for key in ("skill_tags", "knowledge_points", "knowledge_tags", "skills"):
                skills.extend(_list_strings(item.get(key)))
            if not skills:
                skill = _first_text(item, ["skill_id", "skill_name", "knowledge_point"])
                if skill:
                    skills.append(skill)
            for skill_id in dict.fromkeys(skills):
                samples.setdefault(skill_id, []).append(
                    {
                        "value": score_ratio,
                        "weight": weight,
                        "name": skill_id,
                        "last_seen_at": _clean_id(report.get("reviewed_at")),
                    }
                )
            if score_ratio < 0.6 and skills:
                weak_questions.append(
                    {
                        "job_id": _clean_id(report.get("job_id")),
                        "project_id": _clean_id(report.get("project_id")),
                        "question_id": _clean_id(item.get("question_id")),
                        "score_ratio": score_ratio,
                        "skills": list(dict.fromkeys(skills)),
                    }
                )

    def _summarize_samples(self, samples: dict[str, list[dict[str, Any]]], *, id_key: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item_id, entries in samples.items():
            total_weight = sum(float(entry["weight"]) for entry in entries)
            value = 0.0
            if total_weight > 0:
                value = sum(float(entry["value"]) * float(entry["weight"]) for entry in entries) / total_weight
            first = entries[-1] if entries else {}
            trend = "stable"
            if len(entries) >= 2:
                delta = float(entries[-1]["value"]) - float(entries[0]["value"])
                trend = "up" if delta > 0.05 else ("down" if delta < -0.05 else "stable")
            items.append(
                {
                    id_key: item_id,
                    "name": str(first.get("name") or item_id),
                    "value": round(value, 4),
                    "trend": trend,
                    "confidence": round(min(1.0, len(entries) / 5.0), 4),
                    "evidence_count": len(entries),
                    "last_seen_at": str(first.get("last_seen_at") or ""),
                }
            )
        items.sort(key=lambda item: (float(item["value"]), item[id_key]))
        return items

    @staticmethod
    def _average(values: list[float]) -> float:
        if not values:
            return 0.0
        return round(sum(values) / len(values), 4)

    @staticmethod
    def _risk_level(overall_mastery: float, weak_skill_count: int) -> str:
        if overall_mastery < 0.55 or weak_skill_count >= 3:
            return "high"
        if overall_mastery < 0.75 or weak_skill_count >= 1:
            return "medium"
        return "low"

    @staticmethod
    def _recommendations(mastery: list[dict[str, Any]]) -> list[str]:
        weak = [item for item in mastery if float(item.get("value") or 0.0) < 0.6]
        return [f"优先复习：{item.get('name') or item.get('skill_id')}" for item in weak[:3]]
