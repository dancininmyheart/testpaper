from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from backend.application.audit_service import AuditService
from backend.application.project_state_service import ProjectStateService
from backend.domain.models import PaperProjectStatus
from backend.domain.state_machine import InvalidProjectTransition
from backend.infrastructure.db import Database
from backend.infrastructure.repositories import AuditRepository, PaperRepository
from backend.infrastructure.security import make_job_id


@contextmanager
def _workspace_temp_dir():
    root = Path.cwd() / "outputs" / "test_runtime"
    tmp_dir = root / f"project_state_service_{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield tmp_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _build(tmp: Path) -> tuple[ProjectStateService, PaperRepository, Database, str]:
    db = Database(tmp / "app.db")
    paper_repo = PaperRepository(db)
    audit_repo = AuditRepository(db)
    audit = AuditService(audit_repo)
    service = ProjectStateService(paper_repo=paper_repo, audit_service=audit)
    project_id = make_job_id()
    paper_repo.create_project(
        project_id=project_id, title="test", subject="math", grade="g1", created_by=1,
    )
    return service, paper_repo, db, project_id


def _list_transitions(db: Database, project_id: str) -> list[dict]:
    rows = db.query_all(
        "SELECT * FROM audit_logs WHERE target_type='paper_project' AND target_id=? AND action='project_transition' ORDER BY id ASC",
        (project_id,),
    )
    return [dict(r) for r in rows]


def test_transition_updates_status_and_writes_audit():
    with _workspace_temp_dir() as tmp:
        service, paper_repo, db, project_id = _build(tmp)
        service.transition(project_id, PaperProjectStatus.EXTRACTING.value, actor_user_id=42)
        proj = paper_repo.get_project(project_id)
        assert proj["status"] == "extracting"
        assert len(_list_transitions(db, project_id)) == 1


def test_transition_invalid_raises_and_does_not_write():
    with _workspace_temp_dir() as tmp:
        service, paper_repo, db, project_id = _build(tmp)
        with pytest.raises(InvalidProjectTransition):
            service.transition(project_id, PaperProjectStatus.ANALYZING.value, actor_user_id=42)
        proj = paper_repo.get_project(project_id)
        assert proj["status"] == "draft"
        assert len(_list_transitions(db, project_id)) == 0


def test_transition_unknown_project_raises():
    with _workspace_temp_dir() as tmp:
        service, _, _, _ = _build(tmp)
        with pytest.raises(ValueError):
            service.transition("nonexistent", PaperProjectStatus.EXTRACTING.value, actor_user_id=42)


def test_transition_with_error_message_writes_audit_detail():
    import json

    with _workspace_temp_dir() as tmp:
        service, paper_repo, db, project_id = _build(tmp)
        service.transition(
            project_id,
            PaperProjectStatus.ERROR.value,
            actor_user_id=None,
            error_message="something went wrong",
        )
        proj = paper_repo.get_project(project_id)
        assert proj["status"] == "error"
        assert proj["error_message"] == "something went wrong"
        transitions = _list_transitions(db, project_id)
        assert len(transitions) == 1
        detail = json.loads(transitions[0]["detail_json"])
        assert detail.get("from") == "draft"
        assert detail.get("to") == "error"
        assert detail.get("error_message") == "something went wrong"


def test_successful_transition_clears_previous_error_message():
    with _workspace_temp_dir() as tmp:
        service, paper_repo, _, project_id = _build(tmp)
        service.transition(
            project_id,
            PaperProjectStatus.ERROR.value,
            actor_user_id=None,
            error_message="something went wrong",
        )
        service.transition(project_id, PaperProjectStatus.DRAFT.value, actor_user_id=42)

        proj = paper_repo.get_project(project_id)
        assert proj["status"] == "draft"
        assert proj["error_message"] is None
