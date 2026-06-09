from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.infrastructure.repositories import (
    AnalysisReviewRepository,
    StudentRepository,
    StudentStateRepository,
    now_iso,
)


SOURCE_VERSION = "student_state_v1"
TIMELINE_SOURCE_VERSION = "student_profile_timeline_v1"


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


def _contains_chinese(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _load_keyword_skill_alias_map(keyword_path: Path | None) -> dict[str, str]:
    if keyword_path is None:
        return {}
    try:
        from llm_knowledge_tagger import _extract_points_from_nodes, _load_key_word_payload

        payload = _load_key_word_payload(keyword_path)
        points = _extract_points_from_nodes(payload.get("nodes", []))
    except Exception:
        return {}
    return {
        _clean_id(point.get("id")): _clean_id(point.get("name"))
        for point in points
        if _clean_id(point.get("id")) and _clean_id(point.get("name"))
    }


def _build_skill_alias_map(result: dict[str, Any], base_aliases: dict[str, str] | None = None) -> dict[str, str]:
    aliases: dict[str, str] = dict(base_aliases or {})
    raw_aliases = result.get("skill_alias_map")
    if isinstance(raw_aliases, dict):
        for key, value in raw_aliases.items():
            alias_key = _clean_id(key)
            alias_value = _clean_id(value)
            if alias_key and alias_value:
                aliases[alias_key] = alias_value

    new_points = result.get("new_knowledge_points")
    if isinstance(new_points, list):
        for point in new_points:
            if not isinstance(point, dict):
                continue
            point_id = _first_text(point, ["id", "skill_id", "knowledge_id"])
            point_name = _first_text(point, ["name", "short_name", "label", "skill_name", "knowledge_name"])
            if point_id and point_name:
                aliases[point_id] = point_name
    return aliases


def _resolve_skill_name(skill_id: str, raw_name: str, skill_alias_map: dict[str, str]) -> str:
    clean_skill_id = _clean_id(skill_id)
    clean_name = _clean_id(raw_name)
    if clean_name and _contains_chinese(clean_name):
        return clean_name
    alias = skill_alias_map.get(clean_skill_id) or skill_alias_map.get(clean_name)
    if alias:
        return alias
    return clean_name or clean_skill_id


def _latest_reports_for_state(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_project: dict[str, dict[str, Any]] = {}
    for report in reports:
        project_id = _clean_id(report.get("project_id"))
        if project_id and project_id not in latest_by_project:
            latest_by_project[project_id] = report
    return list(reversed(list(latest_by_project.values())))


class StudentStateService:
    def __init__(
        self,
        *,
        student_repo: StudentRepository,
        review_repo: AnalysisReviewRepository,
        state_repo: StudentStateRepository,
        keyword_path: Path | None = None,
    ) -> None:
        self.student_repo = student_repo
        self.review_repo = review_repo
        self.state_repo = state_repo
        self.keyword_path = keyword_path
        self._keyword_skill_alias_map: dict[str, str] | None = None

    def _skill_alias_base(self) -> dict[str, str]:
        if self._keyword_skill_alias_map is None:
            self._keyword_skill_alias_map = _load_keyword_skill_alias_map(self.keyword_path)
        return self._keyword_skill_alias_map

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
        reports = self.prepare_reports_for_state(student_id=clean_student_id, actor_user_id=actor_user_id)
        state = self.build_state_from_reports(student_id=clean_student_id, reports=reports)
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

    def prepare_reports_for_state(self, *, student_id: str, actor_user_id: int) -> list[dict[str, Any]]:
        clean_student_id = _clean_id(student_id)
        if not clean_student_id:
            raise ValueError("student_id is required")
        if self.student_repo.get_student(student_id=clean_student_id, created_by=actor_user_id) is None:
            raise LookupError("student not found")
        reports = self.review_repo.list_approved_student_reports(
            student_id=clean_student_id,
            created_by=actor_user_id,
        )
        return _latest_reports_for_state(reports)

    def build_state_from_reports(self, *, student_id: str, reports: list[dict[str, Any]]) -> dict[str, Any]:
        return self._build_state(student_id=student_id, reports=reports)

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
            skill_alias_map = _build_skill_alias_map(result, self._skill_alias_base())
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
            self._collect_profile_mastery(skill_samples, result, weight, report, skill_alias_map)
            self._collect_profile_literacy(literacy_samples, result, weight, report)
            if not skill_samples:
                self._collect_trace_mastery(skill_samples, weak_questions, result, weight, report, skill_alias_map)

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
        skill_alias_map: dict[str, str],
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
                    "name": _resolve_skill_name(
                        skill_id,
                        _first_text(item, ["skill_name", "name", "knowledge_name"]),
                        skill_alias_map,
                    ),
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
        skill_alias_map: dict[str, str],
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
                        "name": _resolve_skill_name(skill_id, "", skill_alias_map),
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


class StudentTimelineService:
    def __init__(
        self,
        *,
        student_repo: StudentRepository,
        review_repo: AnalysisReviewRepository,
        state_service: StudentStateService,
    ) -> None:
        self.student_repo = student_repo
        self.review_repo = review_repo
        self.state_service = state_service

    def get_student_timeline(
        self,
        *,
        student_id: str,
        actor_user_id: int,
        limit: int = 12,
    ) -> dict[str, Any]:
        clean_student_id = _clean_id(student_id)
        if not clean_student_id:
            raise ValueError("student_id is required")
        if self.student_repo.get_student(student_id=clean_student_id, created_by=actor_user_id) is None:
            raise LookupError("student not found")
        reports = self.state_service.prepare_reports_for_state(
            student_id=clean_student_id,
            actor_user_id=actor_user_id,
        )
        if limit > 0:
            reports = reports[-limit:]
        points: list[dict[str, Any]] = []
        previous_state: dict[str, Any] | None = None
        for index, report in enumerate(reports, start=1):
            current_state = self.state_service.build_state_from_reports(
                student_id=clean_student_id,
                reports=reports[:index],
            )
            points.append(self._build_point(report=report, state=current_state, previous_state=previous_state))
            previous_state = current_state
        return {
            "student_id": clean_student_id,
            "source_version": TIMELINE_SOURCE_VERSION,
            "items": points,
            "next_cursor": None,
        }

    def _build_point(
        self,
        *,
        report: dict[str, Any],
        state: dict[str, Any],
        previous_state: dict[str, Any] | None,
    ) -> dict[str, Any]:
        summary = state.get("summary") if isinstance(state.get("summary"), dict) else {}
        mastery = state.get("mastery") if isinstance(state.get("mastery"), list) else []
        literacy = state.get("literacy") if isinstance(state.get("literacy"), list) else []
        evidence = state.get("evidence") if isinstance(state.get("evidence"), dict) else {}

        weak_skills = sorted(
            [item for item in mastery if float(item.get("value") or 0.0) < 0.6],
            key=lambda item: (float(item.get("value") or 0.0), str(item.get("skill_id") or "")),
        )[:5]
        strong_skills = sorted(
            [item for item in mastery if float(item.get("value") or 0.0) >= 0.8],
            key=lambda item: (-float(item.get("value") or 0.0), str(item.get("skill_id") or "")),
        )[:5]

        previous_weak_ids: set[str] = set()
        previous_summary: dict[str, Any] = {}
        if previous_state is not None:
            prev_mastery = previous_state.get("mastery") if isinstance(previous_state.get("mastery"), list) else []
            previous_weak_ids = {
                str(item.get("skill_id") or "")
                for item in prev_mastery
                if float(item.get("value") or 0.0) < 0.6
            }
            previous_summary = previous_state.get("summary") if isinstance(previous_state.get("summary"), dict) else {}

        delta = {
            "overall_mastery": round(
                float(summary.get("overall_mastery") or 0.0) - float(previous_summary.get("overall_mastery") or 0.0),
                4,
            ),
            "overall_literacy": round(
                float(summary.get("overall_literacy") or 0.0) - float(previous_summary.get("overall_literacy") or 0.0),
                4,
            ),
            "weak_skill_count": int(summary.get("weak_skill_count") or 0) - int(previous_summary.get("weak_skill_count") or 0),
            "strong_skill_count": int(summary.get("strong_skill_count") or 0) - int(previous_summary.get("strong_skill_count") or 0),
        }
        new_weak_skills = [item for item in weak_skills if str(item.get("skill_id") or "") not in previous_weak_ids]
        improved_skills = [
            item
            for item in mastery
            if str(item.get("skill_id") or "") in previous_weak_ids and float(item.get("value") or 0.0) >= 0.6
        ]
        return {
            "report_id": _clean_id(report.get("job_id")),
            "project_id": _clean_id(report.get("project_id")),
            "title": _clean_id(report.get("title")),
            "subject": _clean_id(report.get("subject")),
            "grade": _clean_id(report.get("grade")),
            "reviewed_at": _clean_id(report.get("reviewed_at")),
            "summary": {
                "overall_mastery": float(summary.get("overall_mastery") or 0.0),
                "overall_literacy": float(summary.get("overall_literacy") or 0.0),
                "risk_level": _clean_id(summary.get("risk_level")) or "unknown",
                "exam_count": int(summary.get("exam_count") or 0),
                "weak_skill_count": int(summary.get("weak_skill_count") or 0),
                "strong_skill_count": int(summary.get("strong_skill_count") or 0),
                "recommendations": list(summary.get("recommendations") or []),
            },
            "delta": delta,
            "weak_skills": weak_skills,
            "strong_skills": strong_skills,
            "improved_skills": improved_skills[:5],
            "new_weak_skills": new_weak_skills[:5],
            "literacy": literacy[:5],
            "evidence": {
                "recent_reports": list(evidence.get("recent_reports") or [])[:5],
                "weak_questions": list(evidence.get("weak_questions") or [])[:10],
            },
        }
