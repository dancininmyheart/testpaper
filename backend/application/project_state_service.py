from __future__ import annotations

from typing import Any

from backend.application.audit_service import AuditService
from backend.domain.state_machine import validate_transition
from backend.infrastructure.repositories import PaperRepository


class ProjectStateService:
    """Single seam for paper project status writes. See ADR-0006."""

    def __init__(self, paper_repo: PaperRepository, audit_service: AuditService):
        self._paper_repo = paper_repo
        self._audit = audit_service

    def transition(
        self,
        project_id: str,
        to_status: str,
        *,
        actor_user_id: int | None,
        error_message: str | None = None,
        paper_page_count: int | None = None,
        answer_key_source: str | None = None,
    ) -> None:
        project = self._paper_repo.get_project(project_id)
        if project is None:
            raise ValueError(f"project not found: {project_id}")
        from_status = str(project.get("status") or "")
        validate_transition(from_status, to_status)
        self._paper_repo._update_project_status_internal(
            project_id,
            status=to_status,
            error_message=error_message,
            paper_page_count=paper_page_count,
            answer_key_source=answer_key_source,
        )
        detail: dict[str, Any] = {"from": from_status, "to": to_status}
        if error_message:
            detail["error_message"] = error_message[:500]
        self._audit.log(
            actor_user_id=actor_user_id,
            action="project_transition",
            target_type="paper_project",
            target_id=project_id,
            detail=detail,
        )
