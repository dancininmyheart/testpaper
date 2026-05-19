from __future__ import annotations

from flask import Blueprint, Response, request

from backend.api.deps import (
    ApiError,
    _get_ctx,
    _json_response,
    _parse_json_list,
    _read_uploads,
    _require_job_access,
    _require_user,
)
from backend.application.analysis_service import JobCreateInput

bp = Blueprint("analysis", __name__)


@bp.post("/api/v1/analysis/jobs")
def analysis_create_job() -> Response:
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    request_model = JobCreateInput(
        student_id=request.form.get("student_id", ""),
        input_mode=request.form.get("input_mode", ""),
        vision_profile=(
            request.form.get("vision_profile", "").strip() or None
            if isinstance(request.form.get("vision_profile"), str)
            else None
        ),
        text_profile=(
            request.form.get("text_profile", "").strip() or None
            if isinstance(request.form.get("text_profile"), str)
            else None
        ),
        pre_split_questions=_parse_json_list(request.form.get("pre_split_questions"), "pre_split_questions"),
        selected_answer_blocks=_parse_json_list(request.form.get("selected_answer_blocks"), "selected_answer_blocks"),
    )
    groups = {
        "paper_files": _read_uploads("paper_files"),
        "answer_sheet_files": _read_uploads("answer_sheet_files"),
        "combined_files": _read_uploads("combined_files"),
        "answer_key_files": _read_uploads("answer_key_files"),
    }
    try:
        job_id = ctx.analysis_service.create_job(request=request_model, upload_groups=groups, created_by=user.id)
    except ValueError as exc:
        raise ApiError(status_code=400, message=str(exc)) from exc
    return _json_response({"job_id": job_id, "status": "queued"})


@bp.get("/api/v1/analysis/jobs")
def analysis_list_jobs() -> Response:
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    limit_raw = request.args.get("limit", "20")
    try:
        safe_limit = max(1, min(200, int(limit_raw)))
    except ValueError as exc:
        raise ApiError(status_code=400, message="limit must be integer") from exc
    jobs = ctx.analysis_service.list_jobs(role=user.role, user_id=user.id, limit=safe_limit)
    return _json_response({"items": jobs})


@bp.get("/api/v1/analysis/jobs/<job_id>")
def analysis_get_job(job_id: str) -> Response:
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    job = _require_job_access(user, job_id)
    return _json_response(job)


@bp.post("/api/v1/analysis/jobs/<job_id>/retry")
def analysis_retry_job(job_id: str) -> Response:
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    _require_job_access(user, job_id)
    try:
        updated = ctx.analysis_service.retry_job(job_id=job_id, actor_user_id=user.id)
    except ValueError as exc:
        raise ApiError(status_code=400, message=str(exc)) from exc
    return _json_response(updated)


@bp.get("/api/v1/analysis/reports/<job_id>")
def analysis_get_report(job_id: str) -> Response:
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    _require_job_access(user, job_id)
    try:
        result = ctx.analysis_service.get_report(job_id)
    except ValueError as exc:
        raise ApiError(status_code=400, message=str(exc)) from exc
    return _json_response(result)


@bp.get("/api/v1/analysis/reports/<job_id>/download.json")
def analysis_download_json(job_id: str) -> Response:
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    _require_job_access(user, job_id)
    filename, body = ctx.analysis_service.build_report_json_download(job_id)
    return Response(
        response=body,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        mimetype="application/json; charset=utf-8",
    )


@bp.get("/api/v1/analysis/reports/<job_id>/download.pdf")
def analysis_download_pdf(job_id: str) -> Response:
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    _require_job_access(user, job_id)
    filename, body = ctx.analysis_service.build_report_pdf_download(job_id)
    return Response(
        response=body,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        mimetype="application/pdf",
    )
