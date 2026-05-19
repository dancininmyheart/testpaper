from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from backend.application.analysis_service import AnalysisService, JobCreateInput
from backend.application.audit_service import AuditService
from backend.application.project_state_service import ProjectStateService
from backend.infrastructure.db import Database
from backend.infrastructure.repositories import AnalysisRepository, AuditRepository, PaperRepository
from backend.infrastructure.storage import LocalFileStorage


class _FakeRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, payload):
        self.calls += 1
        return {
            "student_id": payload.get("student_id"),
            "input_mode": payload.get("input_mode"),
            "analysis_process": {
                "stages": [
                    {"stage": "validate_input", "status": "ok"},
                    {"stage": "done", "status": "ok"},
                ]
            },
            "question_analysis": [],
            "answer_trace": [],
        }


def _build_service(tmp_dir: Path) -> tuple[AnalysisService, AnalysisRepository, _FakeRunner]:
    db = Database(tmp_dir / "app.db")
    repo = AnalysisRepository(db)
    paper_repo = PaperRepository(db)
    audit = AuditService(AuditRepository(db))
    storage = LocalFileStorage(tmp_dir / "storage")
    runner = _FakeRunner()
    state_service = ProjectStateService(paper_repo=paper_repo, audit_service=audit)
    service = AnalysisService(
        repo=repo, paper_repo=paper_repo, storage=storage, audit=audit, runner=runner,
        state_service=state_service,
    )
    return service, repo, runner


@contextmanager
def _workspace_temp_dir():
    root = Path.cwd() / "outputs" / "test_runtime"
    tmp_dir = root / f"analysis_service_{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield tmp_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_create_job_and_process_success() -> None:
    with _workspace_temp_dir() as tmp:
        service, repo, runner = _build_service(tmp)
        job_id = service.create_job(
            request=JobCreateInput(
                student_id="S001",
                input_mode="paper_answer_auto_key",
                vision_profile=None,
                text_profile=None,
                pre_split_questions=[],
                selected_answer_blocks=[],
            ),
            upload_groups={
                "paper_files": [("paper.png", b"abc", "image/png")],
                "answer_sheet_files": [("answer.png", b"def", "image/png")],
                "combined_files": [],
                "answer_key_files": [],
            },
            created_by=1,
        )
        assert job_id
        assert service.process_next_queued_job() is True
        assert runner.calls == 1
        job = repo.get_job(job_id)
        assert job is not None
        assert job["status"] == "succeeded"
        assert isinstance(job["stage_logs"], list)
        assert [entry["stage"] for entry in job["stage_logs"][:3]] == [
            "00_validate_input",
            "02_legacy_analysis_adapter",
            "03_collect_result",
        ]
        report = service.get_report(job_id)
        assert report["student_id"] == "S001"


def test_job_detail_includes_stage_logs_after_processing_v1_key_flow() -> None:
    with _workspace_temp_dir() as tmp:
        service, repo, runner = _build_service(tmp)
        job_id = service.create_job(
            request=JobCreateInput(
                student_id="S010",
                input_mode="paper_answer_with_key",
                vision_profile=None,
                text_profile=None,
                pre_split_questions=[],
                selected_answer_blocks=[],
            ),
            upload_groups={
                "paper_files": [("paper.png", b"paper", "image/png")],
                "answer_sheet_files": [("answer.png", b"answer", "image/png")],
                "combined_files": [],
                "answer_key_files": [("key.png", b"key", "image/png")],
            },
            created_by=1,
        )

        assert service.process_next_queued_job() is True

        assert runner.calls == 1
        job = service.get_job(job_id)
        assert job["status"] == "succeeded"
        assert [entry["stage"] for entry in job["stage_logs"][:3]] == [
            "01_validate_input",
            "02_normalize_files",
            "03_extract_questions",
        ]
        assert repo.get_job_result(job_id)["input_mode"] == "paper_answer_with_key"


def test_retry_failed_job() -> None:
    with _workspace_temp_dir() as tmp:
        service, repo, _ = _build_service(tmp)
        job_id = service.create_job(
            request=JobCreateInput(
                student_id="S002",
                input_mode="paper_same_page",
                vision_profile=None,
                text_profile=None,
                pre_split_questions=[],
                selected_answer_blocks=[],
            ),
            upload_groups={
                "paper_files": [],
                "answer_sheet_files": [],
                "combined_files": [("combined.png", b"xx", "image/png")],
                "answer_key_files": [],
            },
            created_by=2,
        )
        repo.mark_job_failed(job_id, error_message="boom")
        updated = service.retry_job(job_id=job_id, actor_user_id=2)
        assert updated["status"] == "queued"


def test_invalid_input_mode_rejected() -> None:
    with _workspace_temp_dir() as tmp:
        service, _, _ = _build_service(tmp)
        try:
            service.create_job(
                request=JobCreateInput(
                    student_id="S003",
                    input_mode="bad_mode",
                    vision_profile=None,
                    text_profile=None,
                    pre_split_questions=[],
                    selected_answer_blocks=[],
                ),
                upload_groups={
                    "paper_files": [],
                    "answer_sheet_files": [],
                    "combined_files": [],
                    "answer_key_files": [],
                },
                created_by=3,
            )
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "input_mode must be" in str(exc)
