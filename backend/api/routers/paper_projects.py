from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, request

from backend.api.deps import (
    ApiError,
    _get_ctx,
    _json_response,
    _parse_json_body,
    _parse_student_ids,
    _read_uploads,
    _require_user,
)
from backend.application.paper_project_artifacts import (
    MinerUArtifactError,
    MinerUArtifactNotFound,
    build_cached_image_lookup as _build_cached_image_lookup,
    build_mineru_review_payload as _build_mineru_review_payload,
    build_page_results_from_cache as _build_page_results_from_cache,
    content_disposition_header as _content_disposition_header,
    dedupe_review_images as _dedupe_review_images,
    persist_mineru_artifacts_to_disk as _persist_mineru_artifacts_to_disk,
    read_mineru_artifact_questions,
)
from backend.application.paper_service import PaperProjectCreateInput
from backend.domain.state_machine import InvalidProjectTransition

bp = Blueprint("paper_projects", __name__)


def _enrich_questions_with_skill_display(questions: list[dict[str, Any]]) -> None:
    """Map English skill IDs to Chinese names from key_word.json for display."""
    from backend.config import AppSettings
    from llm_knowledge_tagger import _load_key_word_payload, _extract_points_from_nodes

    try:
        settings = AppSettings.load()
        payload = _load_key_word_payload(settings.keyword_path)
        all_points = _extract_points_from_nodes(payload.get("nodes", []))
        id_to_name = {
            str(pt.get("id", "")): str(pt.get("name", ""))
            for pt in all_points
            if pt.get("id")
        }
    except Exception:
        id_to_name = {}

    for q in questions:
        tags = q.get("skill_tags") or []
        display = []
        for t in tags:
            display.append(id_to_name.get(t, t))
        q["skill_tags_display"] = display


def _read_mineru_artifact_questions(artifact_dir: str) -> list[dict[str, Any]]:
    try:
        return read_mineru_artifact_questions(artifact_dir)
    except MinerUArtifactNotFound as exc:
        raise ApiError(status_code=404, message=str(exc)) from exc
    except MinerUArtifactError as exc:
        raise ApiError(status_code=500, message=str(exc)) from exc


def _create_mineru_service(vision_profile: str = "", text_profile: str = ""):
    from backend.application.mineru_extraction import MinerUExtractionService
    from backend.config import AppSettings

    settings = AppSettings.load()
    try:
        return MinerUExtractionService(
            settings.llm_config_path,
            vision_profile_name=vision_profile or None,
            text_profile_name=text_profile or None,
            keyword_path=settings.keyword_path,
        )
    except (RuntimeError, ValueError) as exc:
        raise ApiError(status_code=400, message=str(exc), code="MINERU_CONFIG_ERROR") from exc


@bp.post("/api/v1/paper-projects")
def create_paper_project():
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    body = request.get_json(silent=True) or {}
    title = str(body.get("title", "")).strip()
    if not title:
        raise ApiError(status_code=400, message="title is required")
    subject = str(body.get("subject", "")).strip()
    grade = str(body.get("grade", "")).strip()
    project_id = ctx.paper_service.create_project(
        request=PaperProjectCreateInput(title=title, subject=subject, grade=grade),
        created_by=user.id,
    )
    return _json_response({"project_id": project_id, "status": "draft"}, status_code=201)


@bp.get("/api/v1/paper-projects")
def list_paper_projects():
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    limit_raw = request.args.get("limit", "50")
    try:
        safe_limit = max(1, min(200, int(limit_raw)))
    except ValueError:
        raise ApiError(status_code=400, message="limit must be integer")
    projects = ctx.paper_service.list_projects(role=user.role, user_id=user.id, limit=safe_limit)
    return _json_response({"items": [p.__dict__ for p in projects]})


@bp.get("/api/v1/paper-projects/<project_id>")
def get_paper_project(project_id: str):
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")
    return _json_response(project.__dict__)


@bp.delete("/api/v1/paper-projects/<project_id>")
def delete_paper_project(project_id: str):
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    deleted = ctx.paper_service.delete_project(project_id=project_id, actor_user_id=user.id)
    if not deleted:
        raise ApiError(status_code=404, message="project not found")
    return _json_response({"deleted": True})


@bp.post("/api/v1/paper-projects/<project_id>/mineru/parse")
def mineru_step1_parse(project_id: str):
    """Step 1: Run MinerU on paper pages, save text+images to state and cache images to disk."""
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")

    paper_files = [f for f in ctx.paper_repo.list_project_files(project_id)
                   if str(f.get("category") or "") == "paper_files"]
    if not paper_files:
        raise ApiError(status_code=400, message="no paper files uploaded")

    # Idempotent: ok if already in extracting state (retries).
    try:
        ctx.state_service.transition(project_id, "extracting", actor_user_id=user.id)
    except InvalidProjectTransition:
        pass

    vision_profile = str(request.args.get("vision_profile", "") or "")
    text_profile = str(request.args.get("text_profile", "") or "")
    service = _create_mineru_service(vision_profile=vision_profile, text_profile=text_profile)
    page_results = service.step1_parse(paper_files)

    state = ctx.paper_repo.get_mineru_state(project_id)
    pages_state: list[dict] = []
    for pr in page_results:
        cached_images: list[dict] = []
        for idx, (img_name, img_bytes) in enumerate(pr.get("images", [])):
            content_type = "image/png" if img_name.lower().endswith(".png") else "image/jpeg"
            saved = ctx.storage.save_job_file(
                job_id=project_id, category="mineru_page_images",
                original_name=img_name, content=img_bytes,
                content_type=content_type, index=idx,
            )
            cached_images.append({
                "name": img_name,
                "local_path": saved.local_path,
                "content_type": content_type,
            })
        pages_state.append({
            "page_index": pr["page_index"],
            "full_text": pr["full_text"],
            "raw_markdown": pr.get("raw_markdown", ""),
            "corrected_markdown": pr.get("corrected_markdown", pr.get("full_text", "")),
            "raw_markdown_path": pr.get("raw_markdown_path", ""),
            "corrected_markdown_path": pr.get("corrected_markdown_path", ""),
            "source_image": pr.get("source_image", ""),
            "asset_paths": pr.get("asset_paths", []),
            "image_names": [n for n, _ in pr.get("images", [])],
            "cached_images": cached_images,
            "has_error": pr.get("has_error", False),
        })
    state["pages"] = pages_state
    artifact_manifest = _persist_mineru_artifacts_to_disk(
        storage_root=ctx.storage.root,
        project_id=project_id,
        state=state,
    )
    state["artifact_dir"] = artifact_manifest["artifact_dir"]
    state["artifact_manifest_path"] = artifact_manifest["manifest_path"]
    state["artifact_manifest"] = artifact_manifest
    ctx.paper_repo.update_mineru_state(project_id, state)

    return _json_response({
        "page_count": len(page_results),
        "artifact_dir": artifact_manifest["artifact_dir"],
        "artifact_manifest_path": artifact_manifest["manifest_path"],
        "pages": [
            {"page_index": pr["page_index"], "image_count": len(pr.get("images", [])),
             "text_length": len(pr["full_text"]), "has_error": pr.get("has_error", False)}
            for pr in page_results
        ],
    })


@bp.get("/api/v1/paper-projects/<project_id>/mineru/page-text")
def mineru_get_page_text(project_id: str):
    """Inspect raw MinerU text for a given page."""
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    state = ctx.paper_repo.get_mineru_state(project_id)
    pages = state.get("pages", [])
    try:
        page_idx = int(request.args.get("page", "0"))
    except ValueError:
        raise ApiError(status_code=400, message="page must be integer")
    if page_idx < 0 or page_idx >= len(pages):
        raise ApiError(status_code=404, message=f"page {page_idx} not found")
    return _json_response({
        "page_index": page_idx,
        "full_text": pages[page_idx]["full_text"],
        "raw_markdown": pages[page_idx].get("raw_markdown", ""),
        "corrected_markdown": pages[page_idx].get("corrected_markdown", pages[page_idx].get("full_text", "")),
        "image_names": pages[page_idx].get("image_names", []),
    })


@bp.post("/api/v1/paper-projects/<project_id>/mineru/llm-parse")
def mineru_step2_llm_parse(project_id: str):
    """Step 2: LLM parses MinerU text into structured questions."""
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    state = ctx.paper_repo.get_mineru_state(project_id)
    pages = state.get("pages", [])
    if not pages:
        raise ApiError(status_code=400, message="no MinerU results found, run /mineru/parse first")

    vision_profile = str(request.args.get("vision_profile", "") or "")
    text_profile = str(request.args.get("text_profile", "") or "")
    service = _create_mineru_service(vision_profile=vision_profile, text_profile=text_profile)

    page_results = [
        {
            "page_index": p["page_index"],
            "full_text": p["full_text"],
            "raw_markdown": p.get("raw_markdown", ""),
            "corrected_markdown": p.get("corrected_markdown", p.get("full_text", "")),
            "raw_markdown_path": p.get("raw_markdown_path", ""),
            "corrected_markdown_path": p.get("corrected_markdown_path", ""),
            "source_image": p.get("source_image", ""),
            "asset_paths": p.get("asset_paths", []),
            "images": [],
            "has_error": p.get("has_error", False),
        }
        for p in pages
    ]
    questions, llm_artifact = service.step2_llm_parse_with_artifact(page_results)

    clean_questions = [{k: v for k, v in q.items() if not k.startswith("_")} for q in questions]
    for q, q_orig in zip(clean_questions, questions):
        q["images_on_page"] = q_orig.get("images_on_page", [])

    state["questions"] = clean_questions
    state["llm_structured_output"] = llm_artifact
    artifact_manifest = _persist_mineru_artifacts_to_disk(
        storage_root=ctx.storage.root,
        project_id=project_id,
        state=state,
    )
    state["artifact_dir"] = artifact_manifest["artifact_dir"]
    state["artifact_manifest_path"] = artifact_manifest["manifest_path"]
    state["artifact_manifest"] = artifact_manifest
    ctx.paper_repo.update_mineru_state(project_id, state)
    return _json_response({
        "question_count": len(clean_questions),
        "questions": clean_questions,
        "artifact_dir": artifact_manifest["artifact_dir"],
        "artifact_manifest_path": artifact_manifest["manifest_path"],
    })


@bp.get("/api/v1/paper-projects/<project_id>/mineru/questions")
def mineru_get_questions(project_id: str):
    """Inspect parsed questions from state."""
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    state = ctx.paper_repo.get_mineru_state(project_id)
    questions = state.get("questions", [])
    return _json_response({"question_count": len(questions), "questions": questions})


@bp.get("/api/v1/paper-projects/<project_id>/mineru/artifacts")
def mineru_get_artifacts(project_id: str):
    """Inspect MinerU intermediate artifacts and final LLM structured output."""
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    state = ctx.paper_repo.get_mineru_state(project_id)
    pages = state.get("pages", [])
    page_artifacts = []
    iter_pages = pages if isinstance(pages, list) else []
    for page in iter_pages:
        page_artifacts.append({
            "page_index": page.get("page_index"),
            "raw_markdown": page.get("raw_markdown", ""),
            "corrected_markdown": page.get("corrected_markdown", page.get("full_text", "")),
            "raw_markdown_path": page.get("raw_markdown_path", ""),
            "corrected_markdown_path": page.get("corrected_markdown_path", ""),
            "source_image": page.get("source_image", ""),
            "asset_paths": page.get("asset_paths", []),
            "image_names": page.get("image_names", []),
            "cached_images": page.get("cached_images", []),
            "has_error": page.get("has_error", False),
        })
    llm_artifact = state.get("llm_structured_output") or {}
    return _json_response({
        "page_count": len(page_artifacts),
        "pages": page_artifacts,
        "llm_structured_output": llm_artifact,
        "question_count": len(state.get("questions", [])),
        "questions": state.get("questions", []),
        "artifact_dir": state.get("artifact_dir", ""),
        "artifact_manifest_path": state.get("artifact_manifest_path", ""),
        "artifact_manifest": state.get("artifact_manifest", {}),
    })


@bp.post("/api/v1/paper-projects/<project_id>/mineru/vlm-match")
def mineru_step3_vlm_match(project_id: str):
    """Step 3: VLM matches images to questions (uses cached images from step 1)."""
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    state = ctx.paper_repo.get_mineru_state(project_id)
    questions_data = state.get("questions", [])
    if not questions_data:
        raise ApiError(status_code=400, message="no questions found, run /mineru/llm-parse first")

    vision_profile = str(request.args.get("vision_profile", "") or "")
    text_profile = str(request.args.get("text_profile", "") or "")
    service = _create_mineru_service(vision_profile=vision_profile, text_profile=text_profile)

    img_lookup = _build_cached_image_lookup(state, ctx.storage)

    for q in questions_data:
        pi = q.get("page_index", 0)
        q["_candidate_images"] = []
        for name in q.get("images_on_page", []):
            if name in img_lookup.get(pi, {}):
                q["_candidate_images"].append({"name": name, "bytes": img_lookup[pi][name]})

    matched_questions = service.step3_vlm_match(questions_data)
    for q in matched_questions:
        q.pop("_candidate_images", None)
    state["questions"] = matched_questions
    artifact_manifest = _persist_mineru_artifacts_to_disk(
        storage_root=ctx.storage.root,
        project_id=project_id,
        state=state,
    )
    state["artifact_dir"] = artifact_manifest["artifact_dir"]
    state["artifact_manifest_path"] = artifact_manifest["manifest_path"]
    state["artifact_manifest"] = artifact_manifest
    ctx.paper_repo.update_mineru_state(project_id, state)

    results = [{"question_id": q.get("question_id", ""), "matched_images": q.get("matched_image_ids", [])}
               for q in matched_questions]
    return _json_response({
        "matched_count": len([r for r in results if r["matched_images"]]),
        "results": results,
    })


@bp.post("/api/v1/paper-projects/<project_id>/mineru/tag-knowledge")
def mineru_tag_knowledge(project_id: str):
    """Optional step: Tag structured questions with knowledge points from the curriculum graph.

    Run after /mineru/llm-parse (step 2), before /mineru/vlm-match (step 3).
    If skipped, questions are saved with empty skill_tags.
    """
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    state = ctx.paper_repo.get_mineru_state(project_id)
    questions_data = state.get("questions", [])
    if not questions_data:
        raise ApiError(status_code=400,
                       message="no questions found, run /mineru/llm-parse first")

    vision_profile = str(request.args.get("vision_profile", "") or "")
    text_profile = str(request.args.get("text_profile", "") or "")
    service = _create_mineru_service(vision_profile=vision_profile, text_profile=text_profile)
    tagged = service.tag_knowledge_points(questions_data)
    state["questions"] = tagged
    artifact_manifest = _persist_mineru_artifacts_to_disk(
        storage_root=ctx.storage.root,
        project_id=project_id,
        state=state,
    )
    state["artifact_dir"] = artifact_manifest["artifact_dir"]
    state["artifact_manifest_path"] = artifact_manifest["manifest_path"]
    state["artifact_manifest"] = artifact_manifest
    ctx.paper_repo.update_mineru_state(project_id, state)

    tagged_count = sum(
        1 for q in tagged
        if isinstance(q.get("skill_tags"), list) and len(q["skill_tags"]) > 0
    )
    return _json_response({
        "question_count": len(tagged),
        "tagged_count": tagged_count,
    })


@bp.post("/api/v1/paper-projects/<project_id>/mineru/save")
def mineru_step4_save(project_id: str):
    """Step 4: Save all mineru results to database (uses cached images from step 1)."""
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")

    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")

    # Idempotency: check if mineru artifacts were already persisted.
    # Using mineru_artifact_dir (not project.status) avoids collision with
    # the legacy extraction pipeline which also sets review_questions.
    if ctx.paper_repo.get_mineru_artifact_dir(project_id):
        return _json_response({"status": "already_saved"})

    state = ctx.paper_repo.get_mineru_state(project_id)
    questions_data = state.get("questions", [])
    if not questions_data:
        raise ApiError(status_code=400, message="no questions found, run /mineru/vlm-match first")

    service = _create_mineru_service()

    page_results = _build_page_results_from_cache(state, ctx.storage)

    result = service.step4_save(
        project_id=project_id, questions=questions_data,
        page_results=page_results, storage=ctx.storage, paper_repo=ctx.paper_repo,
    )
    # Persist the final questions with updated image refs to disk
    _persist_mineru_artifacts_to_disk(
        storage_root=ctx.storage.root,
        project_id=project_id,
        state=state,
    )
    try:
        ctx.state_service.transition(project_id, "review_questions", actor_user_id=user.id)
    except InvalidProjectTransition:
        pass  # already in or past review_questions

    # Persist the artifact directory path so review endpoints can read from disk
    artifact_dir = state.get("artifact_dir", "")
    if artifact_dir:
        ctx.paper_repo.set_mineru_artifact_dir(project_id, artifact_dir)

    ctx.paper_repo.clear_mineru_state(project_id)
    return _json_response(result)


@bp.post("/api/v1/paper-projects/<project_id>/files")
def upload_paper_project_files(project_id: str):
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")
    if project.status not in {"draft", "error"}:
        raise ApiError(status_code=400, message=f"project status is {project.status}, expected draft or error")
    groups = {
        "paper_files": _read_uploads("paper_files"),
        "answer_key_files": _read_uploads("answer_key_files"),
    }
    file_count = sum(len(items) for items in groups.values())
    if file_count == 0:
        raise ApiError(status_code=400, message="no files uploaded")
    ctx.paper_service.upload_project_files(project_id=project_id, upload_groups=groups)
    return _json_response({"project_id": project_id, "file_count": file_count})


@bp.post("/api/v1/paper-projects/<project_id>/extract")
def trigger_paper_extraction(project_id: str):
    """Trigger paper extraction as an analysis job."""
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")
    if project.status not in {"draft", "error"}:
        raise ApiError(status_code=400, message=f"project status is {project.status}, expected draft or error")

    # Check files exist before creating extraction job
    files = ctx.paper_repo.list_project_files(project_id)
    paper_files = [f for f in files if str(f.get("category") or "") == "paper_files"]
    if not paper_files:
        raise ApiError(status_code=400, message="请先上传试卷图片文件(paper_files)后再提取试题。当前项目无试卷文件。")

    # Build extraction payload
    vision_profile = str(request.args.get("vision_profile", "") or "")
    text_profile = str(request.args.get("text_profile", "") or "")
    payload = ctx.paper_service.build_payload_for_extraction(
        project_id,
        vision_profile=vision_profile,
        text_profile=text_profile,
    )

    # Create analysis job linked to this project
    from backend.application.analysis_service import JobCreateInput
    job_id = ctx.analysis_service.create_job(
        request=JobCreateInput(
            student_id=payload["student_id"],
            input_mode=payload["input_mode"],
            vision_profile=vision_profile or None,
            text_profile=text_profile or None,
            pre_split_questions=[],
            selected_answer_blocks=[],
        ),
        upload_groups={
            "paper_files": [],
            "answer_sheet_files": [],
            "combined_files": [],
            "answer_key_files": [],
        },
        created_by=user.id,
    )
    # Link job to paper project via raw SQL (PaperRepository helper)
    ctx.paper_repo.update_job_paper_project_id(job_id, project_id)

    # Update project to extracting status
    ctx.state_service.transition(project_id, "extracting", actor_user_id=user.id)

    return _json_response({"job_id": job_id, "project_id": project_id, "status": "extracting"})


@bp.post("/api/v1/paper-projects/<project_id>/analyze-students")
def analyze_students_against_project(project_id: str):
    """Submit student answer sheets for analysis against a ready paper project."""
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")

    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")
    if project.status != "ready":
        raise ApiError(status_code=400, message=f"project status is {project.status}, expected ready")

    # Parse student_ids from JSON body or form data
    student_ids: list[str] = []
    json_body = request.get_json(silent=True)
    if json_body and isinstance(json_body, dict):
        student_ids = _parse_student_ids(json_body)

    # Fall back to single student via form
    if not student_ids:
        sid = request.form.get("student_id", "").strip()
        if sid:
            student_ids = [sid]

    if not student_ids:
        raise ApiError(status_code=400, message="student_ids or student_id required")
    for student_id in student_ids:
        try:
            ctx.student_service.require_student(student_id=student_id, actor_user_id=user.id)
        except LookupError as exc:
            raise ApiError(status_code=400, message=str(exc)) from exc
        except ValueError as exc:
            raise ApiError(status_code=400, message=str(exc)) from exc

    # Read answer sheet uploads once — shared across students
    answer_sheets = _read_uploads("answer_sheet_files")
    if not answer_sheets:
        raise ApiError(status_code=400, message="answer_sheet_files required")

    vision_profile = str(request.form.get("vision_profile", "") or "")
    text_profile = str(request.form.get("text_profile", "") or "")

    # Build answer sheet data URLs (same for all students)
    answer_sheet_data: list[dict[str, str]] = []
    for file_name, content, content_type in answer_sheets:
        from backend.application.paper_service import _encode_data_url, _mime_guess
        mime = _mime_guess(file_name, content_type)
        answer_sheet_data.append({
            "name": file_name,
            "data_url": _encode_data_url(content=content, mime=mime),
        })

    # Create one full paper-analysis job per student, sharing the same answer sheet files.
    from backend.infrastructure.security import make_job_id
    job_ids: list[str] = []
    for student_id in student_ids:
        payload = ctx.paper_service.build_student_payload_override(
            project_id,
            student_id,
            answer_sheet_data,
            vision_profile=vision_profile,
            text_profile=text_profile,
        )
        payload["_stage_type"] = "recognize"

        job_id = make_job_id()
        ctx.paper_repo.create_paper_analysis_job(
            job_id=job_id,
            student_id=student_id,
            payload=payload,
            created_by=user.id,
            paper_project_id=project_id,
        )
        for index, (file_name, content, content_type) in enumerate(answer_sheets, start=1):
            saved = ctx.storage.save_job_file(
                job_id=job_id, category="answer_sheet_files",
                original_name=file_name, content=content, content_type=content_type, index=index,
            )
            ctx.analysis_service.repo.add_job_file(
                job_id=job_id, category=saved.category, file_name=saved.file_name,
                local_path=saved.local_path, content_type=saved.content_type, size_bytes=saved.size_bytes,
            )
        job_ids.append(job_id)

    ctx.state_service.transition(project_id, "recognizing", actor_user_id=user.id)

    return _json_response({
        "project_id": project_id,
        "job_ids": job_ids,
        "job_count": len(job_ids),
    })


@bp.post("/api/v1/paper-projects/<project_id>/approve-questions")
def approve_project_questions(project_id: str):
    """User approves extracted questions, optionally with edits."""
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")
    if project.status != "review_questions":
        raise ApiError(status_code=400, message=f"project status is {project.status}, expected review_questions")

    body = request.get_json(silent=True) or {}
    updated_questions = body.get("questions") if isinstance(body.get("questions"), list) else None
    ctx.paper_service.approve_questions(
        project_id=project_id, updated_questions=updated_questions, actor_user_id=user.id,
    )
    updated_project = ctx.paper_service.get_project(project_id)
    return _json_response({"project_id": project_id, "status": updated_project.status if updated_project else "ready"})


@bp.post("/api/v1/paper-projects/<project_id>/analyze-answer-sheet")
def analyze_single_answer_sheet(project_id: str):
    """Upload a student's answer sheet and trigger answer recognition + scoring."""
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")
    if project.status not in {"ready", "review_scores", "review_recognition"}:
        raise ApiError(status_code=400, message=f"project status is {project.status}, expected ready or review_recognition")

    student_id = request.form.get("student_id", "").strip()
    if not student_id:
        raise ApiError(status_code=400, message="student_id required")
    try:
        ctx.student_service.require_student(student_id=student_id, actor_user_id=user.id)
    except LookupError as exc:
        raise ApiError(status_code=400, message=str(exc)) from exc
    except ValueError as exc:
        raise ApiError(status_code=400, message=str(exc)) from exc
    answer_sheets = _read_uploads("answer_sheet_files")
    if not answer_sheets:
        raise ApiError(status_code=400, message="answer_sheet_files required")

    vision_profile = str(request.form.get("vision_profile", "") or "")
    text_profile = str(request.form.get("text_profile", "") or "")

    # Build answer sheet data URLs
    answer_sheet_data: list[dict[str, str]] = []
    for file_name, content, content_type in answer_sheets:
        from backend.application.paper_service import _encode_data_url, _mime_guess
        mime = _mime_guess(file_name, content_type)
        answer_sheet_data.append({
            "name": file_name,
            "data_url": _encode_data_url(content=content, mime=mime),
        })

    # Build payload for answer-only analysis (includes _paper_questions, _skip_extraction)
    payload = ctx.paper_service.build_student_payload_override(
        project_id, student_id, answer_sheet_data,
        vision_profile=vision_profile, text_profile=text_profile,
    )
    # Mark as recognition stage so job worker transitions to review_recognition
    payload["_stage_type"] = "recognize"

    # Create job with complete payload in one shot (avoids worker race condition)
    from backend.infrastructure.security import make_job_id
    job_id = make_job_id()
    ctx.paper_repo.create_paper_analysis_job(
        job_id=job_id,
        student_id=student_id,
        payload=payload,
        created_by=user.id,
        paper_project_id=project_id,
    )
    # Save uploaded files
    for index, (file_name, content, content_type) in enumerate(answer_sheets, start=1):
        saved = ctx.storage.save_job_file(
            job_id=job_id, category="answer_sheet_files",
            original_name=file_name, content=content, content_type=content_type, index=index,
        )
        ctx.analysis_service.repo.add_job_file(
            job_id=job_id, category=saved.category, file_name=saved.file_name,
            local_path=saved.local_path, content_type=saved.content_type, size_bytes=saved.size_bytes,
        )
    ctx.state_service.transition(project_id, "recognizing", actor_user_id=user.id)

    return _json_response({"job_id": job_id, "project_id": project_id, "student_id": student_id, "status": "recognizing"})


@bp.post("/api/v1/paper-projects/<project_id>/approve-scores")
def approve_project_scores(project_id: str):
    """User approves scores, generate final report."""
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")
    if project.status != "review_scores":
        raise ApiError(status_code=400, message=f"project status is {project.status}, expected review_scores")

    # The score review data is already saved; mark as completed
    score_data = ctx.paper_service.get_score_review_data(project_id)
    ctx.paper_service.approve_scores_and_finalize(
        project_id=project_id, report_data=score_data, actor_user_id=user.id,
    )
    return _json_response({"project_id": project_id, "status": "completed"})


@bp.get("/api/v1/paper-projects/<project_id>/score-review")
def get_score_review(project_id: str):
    """Return answer scoring results for user review."""
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    data = ctx.paper_service.get_score_review_data(project_id)
    return _json_response(data)


@bp.get("/api/v1/paper-projects/<project_id>/student-runs")
def list_project_student_runs(project_id: str):
    """Return student analysis runs for a reusable paper project."""
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")
    items = ctx.analysis_service.repo.list_project_runs(project_id=project_id, created_by=user.id)
    return _json_response({"items": items})


@bp.get("/api/v1/paper-projects/<project_id>/student-runs/<job_id>/score-review")
def get_project_student_run_score_review(project_id: str, job_id: str):
    """Return one student's scoring result from its own analysis job."""
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    run = ctx.analysis_service.repo.get_project_run(
        project_id=project_id, job_id=job_id, created_by=user.id,
    )
    if run is None:
        raise ApiError(status_code=404, message="student run not found")
    result = ctx.analysis_service.repo.get_job_result(job_id)
    if not isinstance(result, dict):
        raise ApiError(status_code=404, message="score review not ready")
    data = ctx.paper_service.enrich_project_report(project_id=project_id, report=result)
    return _json_response(data)


@bp.post("/api/v1/paper-projects/<project_id>/student-runs/<job_id>/approve-scores")
def approve_project_student_run_scores(project_id: str, job_id: str):
    """Approve one student's reusable scoring run without finalizing the paper project."""
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    run = ctx.analysis_service.repo.get_project_run(
        project_id=project_id, job_id=job_id, created_by=user.id,
    )
    if run is None:
        raise ApiError(status_code=404, message="student run not found")
    result = ctx.analysis_service.repo.get_job_result(job_id)
    if not isinstance(result, dict):
        raise ApiError(status_code=404, message="score review not ready")
    if ctx.student_state_service is None:
        raise ApiError(status_code=500, message="student state service unavailable")
    try:
        review, state = ctx.student_state_service.approve_report_and_refresh(
            job_id=job_id,
            project_id=project_id,
            student_id=str(run.get("student_id") or ""),
            actor_user_id=user.id,
        )
    except LookupError as exc:
        raise ApiError(status_code=404, message=str(exc)) from exc
    except ValueError as exc:
        raise ApiError(status_code=400, message=str(exc)) from exc
    return _json_response({
        "project_id": project_id,
        "job_id": job_id,
        "student_id": run.get("student_id"),
        "status": review.get("review_status", "approved"),
        "reviewed_at": review.get("reviewed_at"),
        "student_state": state.get("summary", {}),
    })


@bp.get("/api/v1/paper-projects/<project_id>/report")
def get_project_report(project_id: str):
    """Return the final report for a completed project."""
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    data = ctx.paper_service.get_final_report(project_id)
    return _json_response(data)


@bp.get("/api/v1/paper-projects/<project_id>/files")
def list_project_files(project_id: str):
    """List project files with info for rendering in frontend."""
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")
    files = ctx.paper_repo.list_project_files(project_id)
    items = []
    for f in files:
        local_path = str(f.get("local_path") or "")
        content_type = f.get("content_type")
        if content_type and isinstance(content_type, str) and content_type.strip():
            ct = content_type.strip()
        else:
            suffix = Path(str(f.get("file_name", ""))).suffix.lower()
            ct = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "pdf": "application/pdf"}.get(suffix.lstrip("."), "application/octet-stream")
        items.append({
            "id": f.get("id"),
            "file_name": f.get("file_name"),
            "category": f.get("category"),
            "content_type": ct,
            "size_bytes": f.get("size_bytes"),
            "local_path": local_path,
        })
    return _json_response({"items": items})


@bp.get("/api/v1/paper-projects/<project_id>/files/<int:file_id>/content")
def serve_project_file(project_id: str, file_id: int):
    """Serve a project file's content bytes."""
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    files = ctx.paper_repo.list_project_files(project_id)
    match = None
    for f in files:
        if int(f.get("id", 0)) == file_id:
            match = f
            break
    if match is None:
        raise ApiError(status_code=404, message="file not found")
    local_path = str(match.get("local_path") or "")
    if not local_path:
        raise ApiError(status_code=404, message="file path missing")
    try:
        content = ctx.storage.read_bytes(local_path)
    except FileNotFoundError:
        raise ApiError(status_code=404, message="file not found on disk")
    content_type = match.get("content_type") or "application/octet-stream"
    file_name = match.get("file_name") or "file"
    return Response(content, mimetype=content_type, headers={
        "Content-Disposition": _content_disposition_header(str(file_name)),
        "Cache-Control": "private, max-age=3600",
    })


@bp.get("/api/v1/paper-projects/<project_id>/review")
def get_project_review(project_id: str):
    """Return questions with reference answers and page image references for frontend review."""
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")

    artifact_dir = ctx.paper_repo.get_mineru_artifact_dir(project_id)
    if artifact_dir:
        questions_raw = _read_mineru_artifact_questions(artifact_dir)
        payload = _build_mineru_review_payload(ctx, project_id, questions_raw)
        _enrich_questions_with_skill_display(payload.get("questions", []))
        return _json_response(payload)

    questions = ctx.paper_repo.get_questions(project_id)
    ref_answers = ctx.paper_repo.get_reference_answers(project_id)
    files = ctx.paper_repo.list_project_files(project_id)

    # Build answer lookup by question_id
    answer_by_qid: dict[str, dict] = {}
    for a in ref_answers:
        qid = str(a.get("question_id") or "")
        if qid:
            answer_by_qid[qid] = {
                "answer_text": a.get("answer_text", ""),
                "analysis": a.get("analysis", ""),
                "final_answer": a.get("final_answer"),
                "steps": a.get("steps", []),
                "source": a.get("source", ""),
            }

    # Build file lookup by category
    paper_page_files = [f for f in files if str(f.get("category") or "") == "paper_files"]
    key_page_files = [f for f in files if str(f.get("category") or "") == "answer_key_files"]

    # Map questions to their page image, enrich content with options from raw data
    questions_out = []
    for q in questions:
        qid = str(q.get("question_id") or "")
        page_idx = q.get("page_index")
        if not isinstance(page_idx, int):
            page_idx = 0
        paper_file = paper_page_files[page_idx] if page_idx < len(paper_page_files) else None

        # Build full content: merge main content with sub-question texts (which contain options)
        content = str(q.get("content") or "")
        raw_raw = q.get("raw_json")
        if isinstance(raw_raw, str):
            try:
                raw = json.loads(raw_raw)
            except (json.JSONDecodeError, TypeError):
                raw = {}
        elif isinstance(raw_raw, dict):
            raw = raw_raw
        else:
            raw = {}

        # Use problem_text_full if it has more detail than content
        full_text = raw.get("problem_text_full") or raw.get("problem_text") or ""
        if len(full_text) > len(content):
            content = full_text

        # Append sub-question texts (options for choice questions)
        sub_questions = raw.get("sub_questions") or q.get("sub_questions") or []
        if sub_questions and isinstance(sub_questions, list):
            for sub in sub_questions:
                sub_text = (sub.get("sub_text") or sub.get("content") or "").strip()
                if sub_text and sub_text not in content:
                    content += "\n" + sub_text

        # Append options for choice/fill-in questions (mineru pipeline outputs options as a dict)
        options = raw.get("options") or q.get("options")
        if isinstance(options, dict) and options:
            for key in sorted(str(k) for k in options.keys()):
                opt_text = str(options[key]).strip()
                line = f"{key}. {opt_text}"
                if opt_text and line not in content:
                    content += "\n" + line

        questions_out.append({
            "question_id": qid,
            "question_no": q.get("question_no", ""),
            "question_type": q.get("question_type", "unknown"),
            "content": content,
            "max_score": q.get("max_score"),
            "page_index": page_idx,
            "skill_tags": q.get("skill_tags", []),
            "reference_answer": answer_by_qid.get(qid),
            "paper_page_file_id": paper_file.get("id") if paper_file else None,
        })

    # Attach question images to review output
    question_images = ctx.paper_repo.get_question_images(project_id)
    images_by_qid: dict[str, list[dict]] = {}
    for img in question_images:
        qid = str(img.get("question_id") or "")
        images_by_qid.setdefault(qid, []).append(dict(img))
    images_by_qid = {
        qid: _dedupe_review_images(ctx, images)
        for qid, images in images_by_qid.items()
    }
    for q in questions_out:
        q["images"] = images_by_qid.get(q["question_id"], [])

    _enrich_questions_with_skill_display(questions_out)

    return _json_response({
        "project_id": project_id,
        "question_count": len(questions),
        "reference_answer_count": len(ref_answers),
        "questions": questions_out,
        "files": {
            "paper_pages": [
                {"id": f.get("id"), "file_name": f.get("file_name"), "page_index": idx}
                for idx, f in enumerate(paper_page_files)
            ],
            "answer_key_pages": [
                {"id": f.get("id"), "file_name": f.get("file_name"), "page_index": idx}
                for idx, f in enumerate(key_page_files)
            ],
        },
    })


# ---- MinerU review (reads clean artifacts from disk, bypasses DB) ----

@bp.get("/api/v1/paper-projects/<project_id>/mineru-review")
def get_mineru_review(project_id: str):
    """Return mineru-extracted questions directly from disk artifacts.

    Avoids DB encoding issues by reading questions.json produced by the
    mineru pipeline in UTF-8 directly from the filesystem.  Images still
    come from paper_project_files (which only stores IDs/paths).
    """
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")

    artifact_dir = ctx.paper_repo.get_mineru_artifact_dir(project_id)
    if not artifact_dir:
        raise ApiError(status_code=404, message="no mineru artifacts found for this project")

    questions_raw = _read_mineru_artifact_questions(artifact_dir)
    payload = _build_mineru_review_payload(ctx, project_id, questions_raw)
    _enrich_questions_with_skill_display(payload.get("questions", []))
    return _json_response(payload)


# ---- Stage workflow endpoints (分步验证) ----

def _start_reference_answer_job(
    ctx: Any,
    *,
    project_id: str,
    actor_user_id: int,
    vision_profile: str = "",
    text_profile: str = "",
) -> str:
    payload = ctx.paper_service.build_payload_for_answer_generation(
        project_id,
        vision_profile=vision_profile,
        text_profile=text_profile,
    )

    from backend.infrastructure.security import make_job_id
    job_id = make_job_id()
    ctx.paper_repo.create_paper_analysis_job(
        job_id=job_id,
        student_id=str(payload["student_id"]),
        payload=payload,
        created_by=actor_user_id,
        paper_project_id=project_id,
    )
    ctx.state_service.transition(project_id, "generating_answers", actor_user_id=actor_user_id)
    return str(job_id)


@bp.post("/api/v1/paper-projects/<project_id>/stage/upload-answer-key")
def stage_upload_answer_key(project_id: str):
    """Upload answer key files and start reference-answer extraction for user review."""
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")
    if project.status not in {"ready", "review_answers"}:
        raise ApiError(status_code=400, message=f"project status is {project.status}, expected ready or review_answers")

    answer_key_files = _read_uploads("answer_key_files")
    if not answer_key_files:
        raise ApiError(status_code=400, message="answer_key_files required")
    ctx.paper_service.upload_project_files(
        project_id=project_id,
        upload_groups={"answer_key_files": answer_key_files},
    )

    vision_profile = str(request.args.get("vision_profile", "") or "")
    text_profile = str(request.args.get("text_profile", "") or "")
    job_id = _start_reference_answer_job(
        ctx,
        project_id=project_id,
        actor_user_id=user.id,
        vision_profile=vision_profile,
        text_profile=text_profile,
    )
    return _json_response({"job_id": job_id, "project_id": project_id, "status": "generating_answers"})


@bp.post("/api/v1/paper-projects/<project_id>/stage/generate-answers")
def stage_generate_answers(project_id: str):
    """Stage: generate reference answers from approved questions for user review."""
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")
    if project.status not in {"ready", "review_answers"}:
        raise ApiError(status_code=400, message=f"project status is {project.status}, expected ready or review_answers")

    vision_profile = str(request.args.get("vision_profile", "") or "")
    text_profile = str(request.args.get("text_profile", "") or "")
    job_id = _start_reference_answer_job(
        ctx,
        project_id=project_id,
        actor_user_id=user.id,
        vision_profile=vision_profile,
        text_profile=text_profile,
    )
    return _json_response({"job_id": job_id, "project_id": project_id, "status": "generating_answers"})


@bp.post("/api/v1/paper-projects/<project_id>/stage/approve-answers")
def stage_approve_answers(project_id: str):
    """User approves generated reference answers."""
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")
    if project.status != "review_answers":
        raise ApiError(status_code=400, message=f"project status is {project.status}, expected review_answers")

    ctx.paper_service.approve_reference_answers(project_id=project_id, actor_user_id=user.id)
    return _json_response({"project_id": project_id, "status": "ready"})


@bp.post("/api/v1/paper-projects/<project_id>/stage/approve-recognition")
def stage_approve_recognition(project_id: str):
    """User approves answer recognition, transition to score review."""
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")
    if project.status not in {"review_scores", "review_recognition"}:
        raise ApiError(status_code=400, message=f"project status is {project.status}, expected review_recognition or review_scores")

    if project.status == "review_recognition":
        ctx.paper_service.approve_recognition_and_transition(project_id=project_id, actor_user_id=user.id)
    return _json_response({"project_id": project_id, "status": "review_scores"})


# ---- Exam Generation endpoints ----

def _run_generation_in_background(
    project_id: str,
    *,
    paper_repo: Any,
    storage: Any,
    state_service: Any,
    host_url: str = "",
) -> None:
    import logging
    import sys

    # Ensure exam_generation loggers are visible in the background thread
    for name in ("exam_generation", "exam_generator"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            h = logging.StreamHandler(sys.stdout)
            h.setLevel(logging.INFO)
            h.setFormatter(logging.Formatter(
                "[%(asctime)s] %(name)s %(levelname)s %(message)s",
                datefmt="%H:%M:%S",
            ))
            logger.addHandler(h)

    _log = logging.getLogger(__name__)

    _log.info("[exam_gen] Background thread started for project=%s", project_id)
    print(f"[exam_gen] Background generation started for project={project_id}")
    try:
        from backend.application.exam_generation_service import ExamGenerationService

        service = ExamGenerationService(
            paper_repo=paper_repo,
            storage=storage,
        )
        result_path = service.run_generation(project_id=project_id, host_url=host_url)
        if result_path:
            paper_repo.update_project_data(project_id, generated_paper_path=result_path)
            pdf_path = os.path.splitext(result_path)[0] + ".pdf"
            if os.path.exists(pdf_path):
                paper_repo.update_project_data(project_id, generated_paper_pdf_path=pdf_path)
            try:
                state_service.transition(project_id, "paper_ready", actor_user_id=None)
            except InvalidProjectTransition:
                pass
            _log.info("[exam_gen] Success for project=%s, result=%s", project_id, result_path)
            print(f"[exam_gen] SUCCESS: project={project_id}, result={result_path}")
        else:
            raise RuntimeError("generation returned no output")
    except Exception as exc:
        _log.error("[exam_gen] Failed for project=%s: %s", project_id, exc, exc_info=True)
        print(f"[exam_gen] FAILED: project={project_id}, error={exc}")
        try:
            paper_repo.update_project_data(project_id,
                generated_paper_error=str(exc))
            try:
                state_service.transition(project_id, "error", actor_user_id=None)
            except InvalidProjectTransition:
                pass
        except Exception:
            pass


@bp.post("/api/v1/paper-projects/<project_id>/generate-similar-paper")
def generate_similar_paper(project_id: str):
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")
    if project.status not in {"ready", "completed", "paper_ready", "generating_paper", "error"}:
        raise ApiError(status_code=400,
                       message=f"project status is {project.status}, expected ready, completed, paper_ready, or error")

    questions = ctx.paper_repo.get_questions(project_id)
    if not questions:
        raise ApiError(status_code=400, message="no questions found in project")

    try:
        ctx.state_service.transition(project_id, "generating_paper", actor_user_id=user.id)
    except InvalidProjectTransition:
        pass

    host_url = request.host_url
    thread = threading.Thread(
        target=_run_generation_in_background,
        args=(project_id,),
        kwargs={
            "paper_repo": ctx.paper_repo,
            "storage": ctx.storage,
            "state_service": ctx.state_service,
            "host_url": host_url,
        },
        name=f"exam-gen-{project_id}",
        daemon=True,
    )
    thread.start()

    return _json_response({"project_id": project_id, "status": "generating_paper"})


@bp.post("/api/v1/paper-projects/<project_id>/reset-to-ready")
def reset_project_to_ready(project_id: str):
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")
    try:
        ctx.state_service.transition(project_id, "ready", actor_user_id=user.id)
    except InvalidProjectTransition as exc:
        raise ApiError(status_code=400, message=str(exc))
    return _json_response({"project_id": project_id, "status": "ready"})


@bp.get("/api/v1/paper-projects/<project_id>/generated-paper")
def get_generated_paper(project_id: str):
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    project = ctx.paper_service.get_project(project_id)
    if project is None:
        raise ApiError(status_code=404, message="project not found")

    extra = ctx.paper_repo.get_project_extra(project_id) or {}
    md_path = extra.get("generated_paper_path", "")
    error_msg = extra.get("generated_paper_error", "")

    if error_msg:
        raise ApiError(status_code=500, message=error_msg, code="GENERATION_ERROR")
    if not md_path or not Path(md_path).is_file():
        raise ApiError(status_code=404, message="generated paper not found, may still be generating")

    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    return Response(content, mimetype="text/markdown; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="generated_exam.md"',
        "Cache-Control": "private, max-age=3600",
    })


@bp.get("/api/v1/paper-projects/<project_id>/generated-paper/content")
def get_generated_paper_content(project_id: str):
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    extra = ctx.paper_repo.get_project_extra(project_id) or {}
    md_path = extra.get("generated_paper_path", "")
    error_msg = extra.get("generated_paper_error", "")

    if error_msg:
        raise ApiError(status_code=500, message=error_msg, code="GENERATION_ERROR")
    if not md_path or not Path(md_path).is_file():
        raise ApiError(status_code=404, message="generated paper not found, may still be generating")

    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    return _json_response({"content": content})


@bp.get("/api/v1/paper-projects/<project_id>/generated-paper/pdf")
def get_generated_paper_pdf(project_id: str):
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    extra = ctx.paper_repo.get_project_extra(project_id) or {}
    pdf_path = extra.get("generated_paper_pdf_path", "")
    error_msg = extra.get("generated_paper_error", "")

    if error_msg:
        raise ApiError(status_code=500, message=error_msg, code="GENERATION_ERROR")
    if not pdf_path or not Path(pdf_path).is_file():
        raise ApiError(status_code=404, message="generated PDF not found, may still be generating")

    with open(pdf_path, "rb") as f:
        content = f.read()

    return Response(content, mimetype="application/pdf", headers={
        "Content-Disposition": 'attachment; filename="generated_exam.pdf"',
        "Cache-Control": "no-cache, no-store, must-revalidate",
    })
