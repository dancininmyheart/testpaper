from __future__ import annotations

from flask import Blueprint, Response, request

from backend.api.deps import ApiError, _get_ctx, _json_response, _require_user

bp = Blueprint("students", __name__)


def _body() -> dict:
    raw = request.get_json(silent=True) or {}
    if not isinstance(raw, dict):
        raise ApiError(status_code=400, message="request body must be object")
    return raw


@bp.get("/api/v1/students")
def list_students() -> Response:
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    items = ctx.student_service.list_students(actor_user_id=user.id)
    return _json_response({"items": items})


@bp.post("/api/v1/students")
def create_student() -> Response:
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    try:
        item = ctx.student_service.create_student(payload=_body(), actor_user_id=user.id)
    except ValueError as exc:
        raise ApiError(status_code=400, message=str(exc)) from exc
    return _json_response(item)


@bp.patch("/api/v1/students/<student_id>")
def update_student(student_id: str) -> Response:
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    try:
        item = ctx.student_service.update_student(
            student_id=student_id,
            payload=_body(),
            actor_user_id=user.id,
        )
    except LookupError as exc:
        raise ApiError(status_code=404, message=str(exc)) from exc
    except ValueError as exc:
        raise ApiError(status_code=400, message=str(exc)) from exc
    return _json_response(item)


@bp.get("/api/v1/students/<student_id>/projects")
def list_student_projects(student_id: str) -> Response:
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    try:
        items = ctx.student_service.list_project_history(student_id=student_id, actor_user_id=user.id)
    except LookupError as exc:
        raise ApiError(status_code=404, message=str(exc)) from exc
    return _json_response({"items": items})


@bp.get("/api/v1/students/<student_id>/state")
def get_student_state(student_id: str) -> Response:
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    if ctx.student_state_service is None:
        raise ApiError(status_code=500, message="student state service unavailable")
    try:
        state = ctx.student_state_service.get_student_state(
            student_id=student_id,
            actor_user_id=user.id,
        )
    except LookupError as exc:
        raise ApiError(status_code=404, message=str(exc)) from exc
    except ValueError as exc:
        raise ApiError(status_code=400, message=str(exc)) from exc
    return _json_response(state)


@bp.post("/api/v1/students/<student_id>/state:rebuild")
def rebuild_student_state(student_id: str) -> Response:
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    if ctx.student_state_service is None:
        raise ApiError(status_code=500, message="student state service unavailable")
    try:
        state = ctx.student_state_service.refresh_student_state(
            student_id=student_id,
            actor_user_id=user.id,
        )
    except LookupError as exc:
        raise ApiError(status_code=404, message=str(exc)) from exc
    except ValueError as exc:
        raise ApiError(status_code=400, message=str(exc)) from exc
    return _json_response(state)


@bp.get("/api/v1/students/<student_id>/projects/<project_id>/report")
def get_student_project_report(student_id: str, project_id: str) -> Response:
    ctx = _get_ctx()
    user, _ = _require_user("teacher", "admin")
    try:
        report = ctx.student_service.get_project_report(
            student_id=student_id,
            project_id=project_id,
            actor_user_id=user.id,
        )
    except LookupError as exc:
        raise ApiError(status_code=404, message=str(exc)) from exc
    return _json_response(report)
