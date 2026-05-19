from __future__ import annotations

import base64
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.application.audit_service import AuditService
from backend.application.project_state_service import ProjectStateService
from backend.infrastructure.repositories import PaperRepository
from backend.infrastructure.security import make_job_id
from backend.infrastructure.storage import LocalFileStorage


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
class PaperProjectCreateInput:
    title: str
    subject: str
    grade: str


@dataclass
class PaperProjectView:
    project_id: str
    title: str
    subject: str
    grade: str
    status: str
    student_count: int
    paper_page_count: int
    answer_key_source: str
    error_message: str | None
    question_count: int
    reference_answer_count: int
    created_by: int
    created_at: str
    updated_at: str


class PaperService:
    def __init__(
        self,
        *,
        paper_repo: PaperRepository,
        storage: LocalFileStorage,
        audit: AuditService,
        state_service: ProjectStateService,
    ):
        self.paper_repo = paper_repo
        self.storage = storage
        self.audit = audit
        self.state_service = state_service

    def create_project(
        self,
        *,
        request: PaperProjectCreateInput,
        created_by: int,
    ) -> str:
        project_id = make_job_id()
        self.paper_repo.create_project(
            project_id=project_id,
            title=request.title,
            subject=request.subject,
            grade=request.grade,
            created_by=created_by,
        )
        self.audit.log(
            actor_user_id=created_by,
            action="paper_project_created",
            target_type="paper_project",
            target_id=project_id,
            detail={"title": request.title, "subject": request.subject},
        )
        return project_id

    def upload_project_files(
        self,
        *,
        project_id: str,
        upload_groups: dict[str, list[tuple[str, bytes, str | None]]],
    ) -> None:
        for category, files in upload_groups.items():
            for index, (file_name, content, content_type) in enumerate(files, start=1):
                saved = self.storage.save_job_file(
                    job_id=project_id,
                    category=category,
                    original_name=file_name,
                    content=content,
                    content_type=content_type,
                    index=index,
                )
                self.paper_repo.add_project_file(
                    project_id=project_id,
                    category=saved.category,
                    file_name=saved.file_name,
                    local_path=saved.local_path,
                    content_type=saved.content_type,
                    size_bytes=saved.size_bytes,
                )

    def get_project(self, project_id: str) -> PaperProjectView | None:
        project = self.paper_repo.get_project(project_id)
        if project is None:
            return None
        questions = self.paper_repo.get_questions(project_id)
        ref_answers = self.paper_repo.get_reference_answers(project_id)
        return PaperProjectView(
            project_id=project["project_id"],
            title=project.get("title", ""),
            subject=project.get("subject", ""),
            grade=project.get("grade", ""),
            status=project.get("status", "draft"),
            student_count=project.get("student_count", 0),
            paper_page_count=project.get("paper_page_count", 0),
            answer_key_source=project.get("answer_key_source", ""),
            error_message=project.get("error_message"),
            question_count=len(questions),
            reference_answer_count=len(ref_answers),
            created_by=project.get("created_by", 0),
            created_at=project.get("created_at", ""),
            updated_at=project.get("updated_at", ""),
        )

    def list_projects(self, *, role: str, user_id: int, limit: int) -> list[PaperProjectView]:
        if role == "admin":
            projects = self.paper_repo.list_projects(limit=limit, created_by=None)
        else:
            projects = self.paper_repo.list_projects(limit=limit, created_by=user_id)
        result: list[PaperProjectView] = []
        for proj in projects:
            questions = self.paper_repo.get_questions(proj["project_id"])
            ref_answers = self.paper_repo.get_reference_answers(proj["project_id"])
            result.append(PaperProjectView(
                project_id=proj["project_id"],
                title=proj.get("title", ""),
                subject=proj.get("subject", ""),
                grade=proj.get("grade", ""),
                status=proj.get("status", "draft"),
                student_count=proj.get("student_count", 0),
                paper_page_count=proj.get("paper_page_count", 0),
                answer_key_source=proj.get("answer_key_source", ""),
                error_message=proj.get("error_message"),
                question_count=len(questions),
                reference_answer_count=len(ref_answers),
                created_by=proj.get("created_by", 0),
                created_at=proj.get("created_at", ""),
                updated_at=proj.get("updated_at", ""),
            ))
        return result

    def build_payload_for_answer_generation(
        self,
        project_id: str,
        *,
        vision_profile: str = "",
        text_profile: str = "",
    ) -> dict[str, Any]:
        """Build payload to generate reference answers from approved questions."""
        project = self.paper_repo.get_project(project_id)
        if project is None:
            raise ValueError("project not found")
        files = self.paper_repo.list_project_files(project_id)
        questions = self._attach_question_images(
            project_id=project_id,
            questions=self.paper_repo.get_questions(project_id),
        )

        paper_files_data: list[dict[str, Any]] = []
        answer_key_files_data: list[dict[str, Any]] = []
        for file_info in files:
            category = str(file_info.get("category") or "")
            local_path = str(file_info.get("local_path") or "")
            if not local_path:
                continue
            content = self.storage.read_bytes(local_path)
            mime = _mime_guess(
                file_name=str(file_info.get("file_name", "upload.bin")),
                content_type=file_info.get("content_type"),
            )
            entry = {
                "name": file_info.get("file_name"),
                "data_url": _encode_data_url(content=content, mime=mime),
            }
            if category == "paper_files":
                paper_files_data.append(entry)
            elif category == "answer_key_files":
                answer_key_files_data.append(entry)

        has_key = bool(answer_key_files_data)
        return {
            "student_id": f"__refgen__{project_id[:8]}",
            "input_mode": "paper_answer_with_key" if has_key else "paper_answer_auto_key",
            "vision_profile": vision_profile,
            "text_profile": text_profile,
            "paper_files": paper_files_data,
            "answer_sheet_files": [],
            "combined_files": [],
            "answer_key_files": answer_key_files_data,
            "pre_split_questions": [],
            "selected_answer_blocks": [],
            "_paper_project_id": project_id,
            "_skip_extraction": True,
            "_paper_questions": questions,
            "_stage_type": "generate_answers",
        }

    def _attach_question_images(
        self,
        *,
        project_id: str,
        questions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        images_by_qid: dict[str, list[dict[str, Any]]] = {}
        for image in self.paper_repo.get_question_images(project_id):
            qid = str(image.get("question_id") or "")
            if qid:
                images_by_qid.setdefault(qid, []).append(image)

        enriched: list[dict[str, Any]] = []
        for question in questions:
            item = dict(question)
            qid = str(item.get("question_id") or "")
            image_urls: list[str] = []
            image_meta: list[dict[str, Any]] = []
            for image in images_by_qid.get(qid, []):
                local_path = str(image.get("local_path") or "")
                if not local_path:
                    continue
                content = self.storage.read_bytes(local_path)
                mime = _mime_guess(
                    file_name=str(image.get("file_name") or "question-image.png"),
                    content_type=image.get("content_type"),
                )
                data_url = _encode_data_url(content=content, mime=mime)
                image_urls.append(data_url)
                image_meta.append(
                    {
                        "file_id": image.get("file_id"),
                        "file_name": image.get("file_name"),
                        "page_index": image.get("page_index"),
                        "sort_order": image.get("sort_order"),
                    }
                )
            if image_urls:
                item["question_image_urls"] = image_urls
                item["question_images"] = image_meta
            enriched.append(item)
        return enriched

    def approve_reference_answers(
        self,
        *,
        project_id: str,
        actor_user_id: int | None = None,
    ) -> None:
        """User approves generated reference answers."""
        self.state_service.transition(project_id, "ready", actor_user_id=actor_user_id)

    def approve_recognition_and_transition(
        self,
        *,
        project_id: str,
        actor_user_id: int | None = None,
    ) -> None:
        """After user approves recognition, reuse saved data for score review."""
        data = self.get_score_review_data(project_id)
        self.state_service.transition(project_id, "review_scores", actor_user_id=actor_user_id)
        self.paper_repo.update_project_data(project_id, score_review_data=data)

    def build_payload_for_extraction(
        self,
        project_id: str,
        *,
        vision_profile: str = "",
        text_profile: str = "",
    ) -> dict[str, Any]:
        project = self.paper_repo.get_project(project_id)
        if project is None:
            raise ValueError("project not found")
        files = self.paper_repo.list_project_files(project_id)

        paper_files_data: list[dict[str, Any]] = []
        answer_key_files_data: list[dict[str, Any]] = []
        for file_info in files:
            category = str(file_info.get("category") or "")
            local_path = str(file_info.get("local_path") or "")
            if not local_path:
                continue
            content = self.storage.read_bytes(local_path)
            mime = _mime_guess(
                file_name=str(file_info.get("file_name", "upload.bin")),
                content_type=file_info.get("content_type"),
            )
            entry = {
                "name": file_info.get("file_name"),
                "data_url": _encode_data_url(content=content, mime=mime),
            }
            if category == "paper_files":
                paper_files_data.append(entry)
            elif category == "answer_key_files":
                answer_key_files_data.append(entry)

        has_key = bool(answer_key_files_data)
        return {
            "student_id": f"__paper__{project_id[:8]}",
            "input_mode": "paper_answer_with_key" if has_key else "paper_answer_auto_key",
            "vision_profile": vision_profile,
            "text_profile": text_profile,
            "paper_files": paper_files_data,
            "answer_sheet_files": [],
            "combined_files": [],
            "answer_key_files": answer_key_files_data,
            "pre_split_questions": [],
            "selected_answer_blocks": [],
            "_paper_project_id": project_id,
        }

    def ingest_extraction_result(
        self,
        *,
        project_id: str,
        questions: list[dict[str, Any]],
        reference_answers: list[dict[str, Any]],
        answer_key_source: str,
        actor_user_id: int | None = None,
    ) -> None:
        """Save extracted questions and reference answers, await user review."""
        self.paper_repo.save_questions(project_id=project_id, questions=questions)
        self.paper_repo.save_reference_answers(project_id=project_id, answers=reference_answers)
        self.state_service.transition(
            project_id,
            "review_questions",
            actor_user_id=actor_user_id,
            answer_key_source=answer_key_source,
            paper_page_count=len(questions),
        )

    def approve_questions(
        self,
        *,
        project_id: str,
        updated_questions: list[dict[str, Any]] | None = None,
        actor_user_id: int | None = None,
    ) -> None:
        """User approves extracted questions. Optional edits applied before finalizing."""
        if updated_questions:
            self.paper_repo.save_questions(project_id=project_id, questions=updated_questions)
        ref_answers = self.paper_repo.get_reference_answers(project_id)
        target_status = "review_answers" if ref_answers else "ready"
        self.state_service.transition(project_id, target_status, actor_user_id=actor_user_id)

    @staticmethod
    def _question_lookup_key(value: Any) -> str:
        return str(value or "").replace("锛堟暣棰橈級", "").replace("(鏁撮)", "").strip()

    @staticmethod
    def _has_question_text(item: dict[str, Any]) -> bool:
        for key in ("problem_text_full", "problem_text", "question_anchor_text", "question_text", "sub_question_text"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return True
        return False

    @staticmethod
    def _has_question_skills(item: dict[str, Any]) -> bool:
        for key in ("skill_tags", "knowledge_points", "knowledge_tags", "skills"):
            value = item.get(key)
            if isinstance(value, list) and any(isinstance(entry, str) and entry.strip() for entry in value):
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
            key = PaperService._question_lookup_key(value)
            if key and key not in output:
                output.append(key)
        return output

    @staticmethod
    def _stored_question_text(question: dict[str, Any]) -> str:
        for key in ("content", "problem_text_full", "problem_text", "question_anchor_text", "question_text"):
            value = question.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        raw = question.get("raw")
        if isinstance(raw, dict):
            for key in ("problem_text_full", "problem_text", "content_markdown", "content", "question_text"):
                value = raw.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    @staticmethod
    def _stored_question_skills(question: dict[str, Any]) -> list[str]:
        for key in ("skill_tags", "knowledge_points", "knowledge_tags", "skills"):
            value = question.get(key)
            if isinstance(value, list):
                skills = [str(entry).strip() for entry in value if isinstance(entry, str) and entry.strip()]
                if skills:
                    return skills
        raw = question.get("raw")
        if isinstance(raw, dict):
            for key in ("skill_tags", "knowledge_points", "knowledge_tags", "skills"):
                value = raw.get(key)
                if isinstance(value, list):
                    skills = [str(entry).strip() for entry in value if isinstance(entry, str) and entry.strip()]
                    if skills:
                        return skills
        return []

    def _question_text_by_id(self, project_id: str) -> dict[str, str]:
        question_text_by_id: dict[str, str] = {}
        for question in self.paper_repo.get_questions(project_id):
            question_id = self._question_lookup_key(question.get("question_id"))
            content = self._stored_question_text(question)
            if question_id and content:
                question_text_by_id[question_id] = content
        return question_text_by_id

    def _question_skills_by_id(self, project_id: str) -> dict[str, list[str]]:
        question_skills_by_id: dict[str, list[str]] = {}
        for question in self.paper_repo.get_questions(project_id):
            question_id = self._question_lookup_key(question.get("question_id"))
            skills = self._stored_question_skills(question)
            if question_id and skills:
                question_skills_by_id[question_id] = skills
        return question_skills_by_id

    def _enrich_report_question_text(self, *, project_id: str, report: dict[str, Any]) -> dict[str, Any]:
        question_text_by_id = self._question_text_by_id(project_id)
        question_skills_by_id = self._question_skills_by_id(project_id)
        if not question_text_by_id and not question_skills_by_id:
            return report

        enriched = copy.deepcopy(report)
        for list_key in ("answer_trace_display", "answer_trace", "structured_questions_full", "question_analysis"):
            items = enriched.get(list_key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                candidate_ids = self._candidate_question_ids(item)
                if not self._has_question_text(item):
                    text = ""
                    for question_id in candidate_ids:
                        text = question_text_by_id.get(question_id, "")
                        if text:
                            break
                    if text:
                        item["problem_text"] = text
                        item["problem_text_full"] = text
                        item["question_anchor_text"] = text
                if not self._has_question_skills(item):
                    skills: list[str] = []
                    for question_id in candidate_ids:
                        skills = question_skills_by_id.get(question_id, [])
                        if skills:
                            break
                    if skills:
                        item["skill_tags"] = skills
        return enriched

    def enrich_project_report(self, *, project_id: str, report: dict[str, Any]) -> dict[str, Any]:
        return self._enrich_report_question_text(project_id=project_id, report=report)

    def save_score_review_data(
        self,
        *,
        project_id: str,
        data: dict[str, Any],
        target_status: str = "review_scores",
        actor_user_id: int | None = None,
    ) -> None:
        """Save answer scoring results for user review. target_status defaults to review_scores."""
        self.paper_repo.update_project_data(project_id, score_review_data=data)
        self.state_service.transition(project_id, target_status, actor_user_id=actor_user_id)

    def get_score_review_data(self, project_id: str) -> dict[str, Any]:
        project = self.paper_repo.get_project(project_id)
        if project is None:
            return {}
        raw = project.get("score_review_data")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
            if not isinstance(parsed, dict):
                return {}
            return self._enrich_report_question_text(project_id=project_id, report=parsed)
        if not isinstance(raw, dict):
            return {}
        return self._enrich_report_question_text(project_id=project_id, report=raw)

    def approve_scores_and_finalize(
        self,
        *,
        project_id: str,
        report_data: dict[str, Any],
        actor_user_id: int | None = None,
    ) -> None:
        """User approves scores, save final report."""
        self.paper_repo.save_final_report(project_id, report_data=report_data)
        self.state_service.transition(project_id, "completed", actor_user_id=actor_user_id)

    def get_final_report(self, project_id: str) -> dict[str, Any]:
        project = self.paper_repo.get_project(project_id)
        if project is None:
            return {}
        raw = project.get("final_report_data")
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        return raw or {}

    def delete_project(self, *, project_id: str, actor_user_id: int) -> bool:
        """Delete a project and log the action."""
        deleted = self.paper_repo.delete_project(project_id)
        if deleted:
            self.audit.log(
                actor_user_id=actor_user_id,
                action="paper_project_deleted",
                target_type="paper_project",
                target_id=project_id,
                detail={},
            )
        return deleted

    def build_student_payload_override(
        self,
        project_id: str,
        student_id: str,
        answer_sheet_files_data: list[dict[str, Any]],
        *,
        vision_profile: str = "",
        text_profile: str = "",
    ) -> dict[str, Any]:
        """Build payload for a student analysis that reuses a ready paper project.

        The payload injects pre-extracted questions/reference answers so the
        pipeline skips question extraction, knowledge tagging, and reference
        answer generation.
        """
        questions = self.paper_repo.get_questions(project_id)
        if not questions:
            raise ValueError(f"paper project {project_id} has no extracted questions")

        ref_answers = self.paper_repo.get_reference_answers(project_id)

        # Build pre_split_questions from the stored questions
        pre_split: list[dict[str, Any]] = []
        for q in questions:
            question_text = self._stored_question_text(q)
            question_skills = self._stored_question_skills(q)
            entry: dict[str, Any] = {
                "question_id": q.get("question_id", ""),
                "question_type": q.get("question_type", "unknown"),
            }
            if question_text:
                entry["content"] = question_text
                entry["problem_text"] = question_text
                entry["problem_text_full"] = question_text
                entry["question_anchor_text"] = question_text
            question_no = q.get("question_no")
            if question_no is not None:
                entry["question_no"] = question_no
            if question_skills:
                entry["skill_tags"] = question_skills
            max_score = q.get("max_score")
            if max_score is not None:
                entry["max_score"] = max_score
            pre_split.append(entry)

        # Extract paper-level skill_alias_map from raw data
        skill_alias_map: dict[str, str] = {}
        for q in questions:
            raw = q.get("raw", {})
            if isinstance(raw, dict):
                sam = raw.get("skill_alias_map", {})
                if isinstance(sam, dict):
                    skill_alias_map.update(sam)

        return {
            "student_id": student_id,
            "input_mode": "pre_split_questions",
            "vision_profile": vision_profile,
            "text_profile": text_profile,
            "paper_files": [],
            "answer_sheet_files": answer_sheet_files_data,
            "combined_files": [],
            "answer_key_files": [],
            "pre_split_questions": pre_split,
            "selected_answer_blocks": [],
            "_paper_project_id": project_id,
            "_skip_extraction": True,
            "_skip_reference_generation": True,
            "_paper_questions": questions,
            "_paper_reference_answers": ref_answers,
            "_skill_alias_map": skill_alias_map,
        }
