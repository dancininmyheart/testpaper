from __future__ import annotations

from flask import Blueprint, Response

from backend.api.deps import (
    ApiError,
    _get_ctx,
    _json_response,
    _parse_json_body,
    _require_user,
)

bp = Blueprint("auth", __name__)


@bp.post("/api/v1/auth/login")
def auth_login() -> Response:
    ctx = _get_ctx()
    body = _parse_json_body()
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    if not username or not password:
        raise ApiError(status_code=400, message="username and password are required")
    try:
        token, user, expires_at = ctx.auth_service.login(username=username, password=password)
    except ValueError as exc:
        raise ApiError(status_code=401, message=str(exc)) from exc
    ctx.audit_service.log(
        actor_user_id=user.id,
        action="auth_login",
        target_type="session",
        target_id=token[:12],
        detail={"role": user.role},
    )
    return _json_response(
        {
            "token": token,
            "expires_at": expires_at,
            "user": {"id": user.id, "username": user.username, "role": user.role},
        }
    )


@bp.post("/api/v1/auth/logout")
def auth_logout() -> Response:
    ctx = _get_ctx()
    user, token = _require_user()
    ctx.auth_service.logout(token=token)
    ctx.audit_service.log(
        actor_user_id=user.id,
        action="auth_logout",
        target_type="session",
        target_id=token[:12],
        detail={},
    )
    return _json_response({"ok": True})


@bp.get("/api/v1/auth/me")
def auth_me() -> Response:
    user, _ = _require_user()
    return _json_response({"id": user.id, "username": user.username, "role": user.role})
