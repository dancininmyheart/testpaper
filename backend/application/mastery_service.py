from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.application.audit_service import AuditService
from backend.infrastructure.repositories import MasteryEventRepository
from mastery_api import MasteryApiService
from mastery_engine import EngineConfig, MasteryStore, ingest_records, utc_now


class MasteryService:
    def __init__(
        self,
        *,
        mastery_db_path: Path,
        event_repo: MasteryEventRepository,
        audit: AuditService,
    ) -> None:
        self.mastery_db_path = mastery_db_path
        self.event_repo = event_repo
        self.audit = audit

    def ingest(self, *, payload: dict[str, Any], actor_user_id: int) -> dict[str, Any]:
        records = payload.get("records")
        if not isinstance(records, list) or not records:
            raise ValueError("records is required and must be non-empty list")
        store = MasteryStore(self.mastery_db_path)
        try:
            result = ingest_records(store, records, EngineConfig())
        finally:
            store.close()
        student_id = ""
        for item in records:
            if isinstance(item, dict) and isinstance(item.get("student_id"), str):
                student_id = item["student_id"].strip()
                if student_id:
                    break
        if student_id:
            self.event_repo.add_event(student_id=student_id, payload=payload, created_by=actor_user_id)
        self.audit.log(
            actor_user_id=actor_user_id,
            action="mastery_events_ingested",
            target_type="mastery",
            target_id=student_id or None,
            detail={"records_in": len(records), "updates_applied": result.get("updates_applied")},
        )
        return result

    def get_student_mastery(self, student_id: str, recent_limit: int = 20) -> dict[str, Any]:
        service = MasteryApiService(self.mastery_db_path)
        try:
            return service.get_student_mastery(student_id=student_id, recent_limit=recent_limit)
        finally:
            service.close()

    def get_student_report(self, student_id: str, range_expr: str = "30d") -> dict[str, Any]:
        service = MasteryApiService(self.mastery_db_path)
        try:
            return service.get_student_report(student_id=student_id, range_expr=range_expr)
        finally:
            service.close()

    def get_exam_analysis(self, paper_id: str) -> dict[str, Any]:
        service = MasteryApiService(self.mastery_db_path)
        try:
            return service.get_exam_analysis(paper_id=paper_id)
        finally:
            service.close()

    def get_group_exam_summary(self, paper_id: str) -> dict[str, Any]:
        analysis = self.get_exam_analysis(paper_id)
        problems = analysis.get("problems")
        if not isinstance(problems, list):
            return {"paper_id": paper_id, "problem_count": 0, "skill_count": 0, "skills": []}
        by_skill: dict[str, dict[str, Any]] = {}
        for problem in problems:
            if not isinstance(problem, dict):
                continue
            skills = problem.get("skills")
            if not isinstance(skills, list):
                continue
            for item in skills:
                if not isinstance(item, dict):
                    continue
                skill_id = item.get("skill_id")
                if not isinstance(skill_id, str) or not skill_id.strip():
                    continue
                count = int(item.get("count") or 0)
                score_ratio = float(item.get("score_ratio") or 0.0)
                error_type = item.get("error_type")
                node = by_skill.setdefault(
                    skill_id,
                    {
                        "skill_id": skill_id,
                        "total_count": 0,
                        "weighted_sum": 0.0,
                        "error_types": {},
                    },
                )
                node["total_count"] += count
                node["weighted_sum"] += score_ratio * count
                if isinstance(error_type, str) and error_type.strip():
                    error_map = node["error_types"]
                    error_map[error_type] = int(error_map.get(error_type, 0)) + count
        skills_summary: list[dict[str, Any]] = []
        for node in by_skill.values():
            total_count = int(node["total_count"])
            if total_count <= 0:
                continue
            avg_ratio = float(node["weighted_sum"]) / float(total_count)
            error_types = node["error_types"]
            top_error = ""
            if error_types:
                top_error = sorted(error_types.items(), key=lambda x: x[1], reverse=True)[0][0]
            skills_summary.append(
                {
                    "skill_id": node["skill_id"],
                    "total_count": total_count,
                    "avg_score_ratio": round(avg_ratio, 4),
                    "top_error_type": top_error,
                    "risk_level": "high" if avg_ratio < 0.4 else ("medium" if avg_ratio < 0.7 else "low"),
                }
            )
        skills_summary.sort(key=lambda x: (x["avg_score_ratio"], -x["total_count"], x["skill_id"]))
        return {
            "paper_id": paper_id,
            "problem_count": len([p for p in problems if isinstance(p, dict)]),
            "skill_count": len(skills_summary),
            "skills": skills_summary,
        }
