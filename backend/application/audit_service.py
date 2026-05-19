from __future__ import annotations

from typing import Any

from backend.infrastructure.repositories import AuditRepository


class AuditService:
    def __init__(self, repo: AuditRepository):
        self.repo = repo

    def log(
        self,
        *,
        actor_user_id: int | None,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.repo.log(
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail or {},
        )

