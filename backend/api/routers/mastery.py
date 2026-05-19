from __future__ import annotations

from flask import Blueprint, Response, request

from backend.api.deps import (
    ApiError,
    _get_ctx,
    _json_response,
    _parse_json_body,
    _require_user,
)

bp = Blueprint("mastery", __name__)


@bp.post("/api/v1/mastery/events:ingest")
def mastery_ingest() -> Response:
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    body = _parse_json_body()
    try:
        result = ctx.mastery_service.ingest(payload=body, actor_user_id=user.id)
    except ValueError as exc:
        raise ApiError(status_code=400, message=str(exc)) from exc
    return _json_response(result)


@bp.get("/api/v1/students/<student_id>/mastery")
def mastery_get_student_mastery(student_id: str) -> Response:
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    limit_raw = request.args.get("recent_limit", "20")
    try:
        safe_limit = max(1, min(100, int(limit_raw)))
    except ValueError as exc:
        raise ApiError(status_code=400, message="recent_limit must be integer") from exc
    try:
        result = ctx.mastery_service.get_student_mastery(student_id=student_id, recent_limit=safe_limit)
    except KeyError as exc:
        raise ApiError(status_code=404, message=str(exc)) from exc
    except ValueError as exc:
        raise ApiError(status_code=400, message=str(exc)) from exc
    return _json_response(result)


@bp.get("/api/v1/students/<student_id>/report")
def mastery_get_student_report(student_id: str) -> Response:
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    range_expr = request.args.get("range", "30d")
    try:
        result = ctx.mastery_service.get_student_report(student_id=student_id, range_expr=range_expr)
    except KeyError as exc:
        raise ApiError(status_code=404, message=str(exc)) from exc
    except ValueError as exc:
        raise ApiError(status_code=400, message=str(exc)) from exc
    return _json_response(result)


@bp.get("/api/v1/exams/<paper_id>/analysis")
def mastery_get_exam_analysis(paper_id: str) -> Response:
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    try:
        result = ctx.mastery_service.get_exam_analysis(paper_id=paper_id)
    except KeyError as exc:
        raise ApiError(status_code=404, message=str(exc)) from exc
    return _json_response(result)


@bp.get("/api/v1/exams/<paper_id>/group-summary")
def mastery_get_group_summary(paper_id: str) -> Response:
    ctx = _get_ctx()
    _require_user("teacher", "admin")
    try:
        result = ctx.mastery_service.get_group_exam_summary(paper_id=paper_id)
    except KeyError as exc:
        raise ApiError(status_code=404, message=str(exc)) from exc
    return _json_response(result)
