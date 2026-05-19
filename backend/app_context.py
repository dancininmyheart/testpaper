from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.application.analysis_service import AnalysisService
from backend.application.audit_service import AuditService
from backend.application.auth_service import AuthService
from backend.application.job_worker import JobWorker
from backend.application.legacy_api import LegacyDemoApiService
from backend.application.mastery_service import MasteryService
from backend.application.paper_service import PaperService
from backend.application.project_state_service import ProjectStateService
from backend.application.student_service import StudentService
from backend.application.workflows import AnalysisWorkflow
from backend.config import AppSettings
from backend.infrastructure.db import Database
from backend.infrastructure.repositories import (
    AnalysisRepository,
    AuditRepository,
    MasteryEventRepository,
    PaperRepository,
    SessionRepository,
    StudentRepository,
    UserRepository,
)
from backend.infrastructure.storage import LocalFileStorage
from demo.service import DemoService


@dataclass
class AppContext:
    settings: AppSettings
    db: Database
    auth_service: AuthService
    audit_service: AuditService
    analysis_service: AnalysisService
    mastery_service: MasteryService
    legacy_service: LegacyDemoApiService
    worker: JobWorker
    demo_service: Any
    paper_service: PaperService | None = None
    paper_repo: PaperRepository | None = None
    student_service: StudentService | None = None
    student_repo: StudentRepository | None = None
    storage: LocalFileStorage | None = None
    state_service: ProjectStateService | None = None

    @classmethod
    def build(cls, settings: AppSettings) -> "AppContext":
        db = Database(settings.app_db_path)
        users = UserRepository(db)
        sessions = SessionRepository(db)
        analysis_repo = AnalysisRepository(db)
        audit_repo = AuditRepository(db)
        mastery_event_repo = MasteryEventRepository(db)
        student_repo = StudentRepository(db)
        audit_service = AuditService(audit_repo)
        auth_service = AuthService(users=users, sessions=sessions, session_ttl_hours=settings.session_ttl_hours)
        auth_service.ensure_default_user(
            username=settings.default_admin_username,
            password=settings.default_admin_password,
            role="admin",
        )
        auth_service.ensure_default_user(
            username=settings.default_teacher_username,
            password=settings.default_teacher_password,
            role="teacher",
        )
        storage = LocalFileStorage(settings.storage_root)
        demo_service = DemoService(
            settings.llm_config_path,
            None,
            settings.keyword_path,
            mock_mode=settings.demo_mock_mode,
        )
        paper_repo = PaperRepository(db)
        state_service = ProjectStateService(
            paper_repo=paper_repo,
            audit_service=audit_service,
        )
        paper_service = PaperService(
            paper_repo=paper_repo,
            storage=storage,
            audit=audit_service,
            state_service=state_service,
        )
        student_service = StudentService(repo=student_repo, paper_repo=paper_repo)
        analysis_workflow = AnalysisWorkflow(legacy_runner=demo_service)
        analysis_service = AnalysisService(
            repo=analysis_repo,
            paper_repo=paper_repo,
            paper_service=paper_service,
            storage=storage,
            audit=audit_service,
            runner=demo_service,
            workflow=analysis_workflow,
            state_service=state_service,
        )
        mastery_service = MasteryService(
            mastery_db_path=settings.mastery_db_path,
            event_repo=mastery_event_repo,
            audit=audit_service,
        )
        legacy_service = LegacyDemoApiService(demo_service=demo_service)
        worker = JobWorker(analysis_service=analysis_service, poll_sec=settings.worker_poll_sec)
        return cls(
            settings=settings,
            db=db,
            auth_service=auth_service,
            audit_service=audit_service,
            analysis_service=analysis_service,
            mastery_service=mastery_service,
            legacy_service=legacy_service,
            worker=worker,
            demo_service=demo_service,
            paper_service=paper_service,
            paper_repo=paper_repo,
            student_service=student_service,
            student_repo=student_repo,
            storage=storage,
            state_service=state_service,
        )

    def close(self) -> None:
        self.worker.stop()
        self.db.close()
