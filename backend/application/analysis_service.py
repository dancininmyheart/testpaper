from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from backend.application.audit_service import AuditService
from backend.application.paper_service import PaperService
from backend.application.project_state_service import ProjectStateService
from backend.application.workflows import AnalysisWorkflow, AnalysisWorkflowResult
from backend.infrastructure.repositories import AnalysisRepository, PaperRepository
from backend.infrastructure.security import make_job_id
from backend.infrastructure.storage import LocalFileStorage
from demo.service import _build_export_payload, _build_export_pdf_bytes


def _mime_guess(file_name: str, content_type: str | None) -> str:
    if isinstance(content_type, str) and content_type.strip():
        return content_type.strip()
    suffix = Path(file_name).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".bmp":
        return "image/bmp"
    if suffix in {".tif", ".tiff"}:
        return "image/tiff"
    if suffix == ".pdf":
        return "application/pdf"
    return "application/octet-stream"


def _encode_data_url(*, content: bytes, mime: str) -> str:
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{encoded}"


@dataclass
class JobCreateInput:
    student_id: str
    input_mode: str
    vision_profile: str | None
    text_profile: str | None
    pre_split_questions: list[dict[str, Any]]
    selected_answer_blocks: list[dict[str, Any]]


class AnalysisService:
    def __init__(
        self,
        *,
        repo: AnalysisRepository,
        paper_repo: PaperRepository,
        storage: LocalFileStorage,
        audit: AuditService,
        runner: Any,
        state_service: ProjectStateService,
        paper_service: PaperService | None = None,
        workflow: AnalysisWorkflow | None = None,
    ):
        self.repo = repo
        self.paper_repo = paper_repo
        self.paper_service = paper_service
        self.storage = storage
        self.audit = audit
        self.runner = runner
        self.state_service = state_service
        self.workflow = workflow or AnalysisWorkflow(legacy_runner=runner)

    @staticmethod
    def _validate_input_mode(value: str) -> str:
        mode = (value or "").strip()
        allowed = {"paper_answer_with_key", "paper_answer_auto_key", "paper_same_page", "pre_split_questions"}
        if mode not in allowed:
            raise ValueError(
                "input_mode must be paper_answer_with_key | paper_answer_auto_key | paper_same_page | pre_split_questions"
            )
        return mode

    def create_job(
        self,
        *,
        request: JobCreateInput,
        upload_groups: dict[str, list[tuple[str, bytes, str | None]]],
        created_by: int,
    ) -> str:
        student_id = (request.student_id or "").strip()
        if not student_id:
            raise ValueError("student_id is required")
        input_mode = self._validate_input_mode(request.input_mode)
        payload = {
            "student_id": student_id,
            "input_mode": input_mode,
            "vision_profile": request.vision_profile or "",
            "text_profile": request.text_profile or "",
            "pre_split_questions": request.pre_split_questions,
            "selected_answer_blocks": request.selected_answer_blocks,
        }
        job_id = make_job_id()
        self.repo.create_job(
            job_id=job_id,
            student_id=student_id,
            input_mode=input_mode,
            payload=payload,
            created_by=created_by,
        )
        for category, files in upload_groups.items():
            for index, (file_name, content, content_type) in enumerate(files, start=1):
                saved = self.storage.save_job_file(
                    job_id=job_id,
                    category=category,
                    original_name=file_name,
                    content=content,
                    content_type=content_type,
                    index=index,
                )
                self.repo.add_job_file(
                    job_id=job_id,
                    category=saved.category,
                    file_name=saved.file_name,
                    local_path=saved.local_path,
                    content_type=saved.content_type,
                    size_bytes=saved.size_bytes,
                )
        self.audit.log(
            actor_user_id=created_by,
            action="analysis_job_created",
            target_type="analysis_job",
            target_id=job_id,
            detail={
                "student_id": student_id,
                "input_mode": input_mode,
                "file_count": sum(len(v) for v in upload_groups.values()),
            },
        )
        return job_id

    def list_jobs(self, *, role: str, user_id: int, limit: int) -> list[dict[str, Any]]:
        if role == "admin":
            return self.repo.list_jobs(limit=limit, created_by=None)
        return self.repo.list_jobs(limit=limit, created_by=user_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        job = self.repo.get_job(job_id)
        if job is None:
            raise KeyError("job not found")
        return job

    def retry_job(self, *, job_id: str, actor_user_id: int) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["status"] not in {"failed", "canceled"}:
            raise ValueError("only failed/canceled job can be retried")
        self.repo.retry_job(job_id)
        self.audit.log(
            actor_user_id=actor_user_id,
            action="analysis_job_retried",
            target_type="analysis_job",
            target_id=job_id,
            detail={},
        )
        return self.get_job(job_id)

    def recover_stale_running_jobs(self) -> int:
        count = self.repo.recover_stale_running_jobs()
        if count:
            print(f"[worker] recovered {count} stale running job(s) -> queued")
        return count

    def _build_demo_payload(
        self,
        *,
        payload_meta: dict[str, Any],
        job_files: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "student_id": str(payload_meta.get("student_id") or ""),
            "input_mode": str(payload_meta.get("input_mode") or ""),
            "vision_profile": str(payload_meta.get("vision_profile") or ""),
            "text_profile": str(payload_meta.get("text_profile") or ""),
            "pre_split_questions": payload_meta.get("pre_split_questions") or [],
            "selected_answer_blocks": payload_meta.get("selected_answer_blocks") or [],
            "paper_files": [],
            "answer_sheet_files": [],
            "combined_files": [],
            "answer_key_files": [],
        }
        by_category: dict[str, list[dict[str, Any]]] = {
            "paper_files": [],
            "answer_sheet_files": [],
            "combined_files": [],
            "answer_key_files": [],
        }
        for file_info in job_files:
            category = str(file_info.get("category") or "")
            if category not in by_category:
                continue
            file_name = str(file_info.get("file_name") or "upload.bin")
            local_path = str(file_info.get("local_path") or "")
            if not local_path:
                continue
            content = self.storage.read_bytes(local_path)
            mime = _mime_guess(file_name=file_name, content_type=file_info.get("content_type"))
            by_category[category].append(
                {
                    "name": file_name,
                    "data_url": _encode_data_url(content=content, mime=mime),
                }
            )
        payload.update(by_category)
        for category in by_category:
            if payload[category]:
                continue
            raw_items = payload_meta.get(category)
            if isinstance(raw_items, list):
                payload[category] = [item for item in raw_items if isinstance(item, dict)]
        return payload

    def process_next_queued_job(self) -> bool:
        job = self.repo.claim_next_queued_job()
        if job is None:
            return False
        job_id = str(job["job_id"])
        payload_meta = job.get("payload")
        if not isinstance(payload_meta, dict):
            payload_meta = {}
        files = self.repo.list_job_files(job_id)
        paper_project_id = job.get("paper_project_id") or payload_meta.get("_paper_project_id")
        is_paper_extraction = bool(paper_project_id) and not payload_meta.get("_paper_questions")
        is_student_via_paper = bool(paper_project_id) and bool(payload_meta.get("_paper_questions"))
        _stage_type = str(payload_meta.get("_stage_type", "") or "")
        is_reference_generation = is_student_via_paper and _stage_type == "generate_answers"
        _mock_was_enabled = False

        try:
            if is_paper_extraction:
                demo_payload = self.paper_service.build_payload_for_extraction(
                    paper_project_id,
                    vision_profile=payload_meta.get("vision_profile", ""),
                    text_profile=payload_meta.get("text_profile", ""),
                )
            else:
                demo_payload = self._build_demo_payload(payload_meta=payload_meta, job_files=files)
                if is_student_via_paper:
                    demo_payload["_paper_project_id"] = paper_project_id
                    demo_payload["_skip_extraction"] = True

                    if is_reference_generation:
                        # Generate reference answers: skip extraction but NOT reference generation
                        demo_payload["_skip_reference_generation"] = False
                        # Ensure paper files + answer key files are loaded
                        if payload_meta.get("_paper_questions"):
                            demo_payload["_paper_questions"] = list(payload_meta["_paper_questions"])
                    else:
                        # Standard student analysis: skip everything
                        demo_payload["_skip_reference_generation"] = True
                        if payload_meta.get("_paper_questions"):
                            demo_payload["_paper_questions"] = list(payload_meta["_paper_questions"])
                        if payload_meta.get("_paper_reference_answers"):
                            demo_payload["_paper_reference_answers"] = list(payload_meta["_paper_reference_answers"])

            # Paper project jobs must run real (non-mock) analysis
            if (is_paper_extraction or is_student_via_paper) and getattr(self.runner, 'mock_mode', False):
                _mock_was_enabled = True
                self.runner.mock_mode = False
                # Self-heal: ensure profile is loaded (initially None when mock_mode=True)
                if getattr(self.runner, 'profile', None) is None:
                    from llm_knowledge_tagger import _load_llm_profile  # type: ignore[import-untyped]
                    try:
                        loaded = _load_llm_profile(self.runner.config_path, None)
                        self.runner.profile = loaded
                        self.runner.text_profile = loaded
                        # Try loading dedicated text profile
                        text_name = getattr(self.runner, 'text_profile_name', '') or 'text_analysis'
                        try:
                            self.runner.text_profile = _load_llm_profile(self.runner.config_path, text_name)
                        except Exception:
                            pass  # fallback: text_profile = profile is fine
                    except Exception as exc:
                        print(f"[paper_project] failed to load llm profile: {exc}")

            workflow_result = self.workflow.run(demo_payload)
            result = workflow_result.result
            if not isinstance(result, dict):
                raise RuntimeError("runner result is not object")

            stage_logs = workflow_result.stage_logs

            if is_paper_extraction:
                # Ingest extraction result into paper tables → review_questions status
                questions = result.get("question_analysis", []) or result.get("structured_questions_full", [])
                ref_answers = result.get("reference_answers", [])
                answer_key_source = result.get("answer_key_source", "")
                self.paper_service.ingest_extraction_result(
                    project_id=paper_project_id,
                    questions=questions,
                    reference_answers=ref_answers,
                    answer_key_source=answer_key_source,
                )
                self.repo.mark_job_succeeded(job_id, stage_logs=stage_logs)
            elif is_reference_generation:
                # Stage: generate reference answers → save and transition to review_answers
                ref_answers = result.get("reference_answers", [])
                answer_key_source = result.get("answer_key_source", "")
                self.paper_repo.save_reference_answers(
                    project_id=paper_project_id,
                    answers=ref_answers,
                )
                self.state_service.transition(
                    paper_project_id,
                    "review_answers",
                    actor_user_id=None,
                    answer_key_source=answer_key_source,
                )
                self.repo.mark_job_succeeded(job_id, stage_logs=stage_logs)
            elif is_student_via_paper:
                # Answer analysis jobs are reusable per student; the project keeps paper data,
                # while each student's review data lives on its own job result.
                self.repo.save_job_result(job_id=job_id, result=result)
                # Mark job as succeeded BEFORE checking remaining jobs, so it is
                # not counted as "active" when we query the queue below.
                self.repo.mark_job_succeeded(job_id, stage_logs=stage_logs)
                self.paper_repo.increment_project_student_count(paper_project_id)
                # Only transition the project state when all queued/running jobs for
                # this project are finished.  Without this guard each successive job
                # completion tried ready→ready (an illegal transition) and the
                # exception was silently swallowed, leaving the project stuck.
                try:
                    remaining = self.paper_repo.count_active_jobs_for_project(paper_project_id)
                    if remaining == 0:
                        self.state_service.transition(paper_project_id, "ready", actor_user_id=None)
                except Exception:
                    # Project may already be in 'ready' or another non-recognizing
                    # state (e.g. a concurrent transition won the race).  Safe to ignore.
                    pass
                # Job is already marked succeeded above — skip the outer except path.
                return True
            else:
                # Normal student analysis result
                self.repo.save_job_result(job_id=job_id, result=result)
                self.repo.mark_job_succeeded(job_id, stage_logs=stage_logs)
        except Exception as exc:
            if paper_project_id and is_paper_extraction:
                self.state_service.transition(
                    paper_project_id, "error",
                    actor_user_id=None, error_message=str(exc),
                )
            elif paper_project_id and is_student_via_paper:
                # 回退到 ready 仅对处于 recognizing/generating_answers 等状态合法；
                # 若当前已是 review_* 之类，状态机会拒绝——此时直接走 error。
                try:
                    self.state_service.transition(
                        paper_project_id, "ready",
                        actor_user_id=None, error_message=str(exc),
                    )
                except Exception:
                    self.state_service.transition(
                        paper_project_id, "error",
                        actor_user_id=None, error_message=str(exc),
                    )
            self.repo.mark_job_failed(job_id, error_message=str(exc))
        finally:
            if _mock_was_enabled:
                self.runner.mock_mode = True
        return True

    def get_report(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["status"] != "succeeded":
            raise ValueError("job is not succeeded")
        result = self.repo.get_job_result(job_id)
        if not isinstance(result, dict):
            raise ValueError("result not found")
        return result

    def build_report_json_download(self, job_id: str) -> tuple[str, bytes]:
        job = self.get_job(job_id)
        result = self.get_report(job_id)
        payload = _build_export_payload(job.get("payload") or {}, result)
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        student_id = result.get("student_id") if isinstance(result.get("student_id"), str) else "unknown"
        filename = f"analysis_export_{student_id}_{job_id[:8]}.json"
        return filename, body

    def build_report_pdf_download(self, job_id: str) -> tuple[str, bytes]:
        job = self.get_job(job_id)
        result = self.get_report(job_id)
        body = _build_export_pdf_bytes(job.get("payload") or {}, result)
        student_id = result.get("student_id") if isinstance(result.get("student_id"), str) else "unknown"
        filename = f"analysis_report_{student_id}_{job_id[:8]}.pdf"
        return filename, body
