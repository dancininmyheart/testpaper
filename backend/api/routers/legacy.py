from __future__ import annotations

from flask import Blueprint, Response, render_template, request

from backend.api.deps import (
    ApiError,
    _get_ctx,
    _json_response,
    _parse_json_body,
)

bp = Blueprint("legacy", __name__)


@bp.get("/api/demo/model-options")
def legacy_model_options() -> Response:
    ctx = _get_ctx()
    return _json_response({"ok": True, "result": ctx.legacy_service.get_model_options()})


@bp.post("/api/demo/run")
def legacy_run() -> Response:
    ctx = _get_ctx()
    payload = _parse_json_body()
    try:
        result = ctx.legacy_service.run_demo(payload)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"ok": False, "error": str(exc)})
    return _json_response({"ok": True, "result": result})


@bp.post("/api/demo/export")
def legacy_export_json() -> Response:
    ctx = _get_ctx()
    payload = _parse_json_body()
    try:
        filename, body = ctx.legacy_service.export_json(payload)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(status_code=400, message=str(exc)) from exc
    return Response(
        response=body,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        mimetype="application/json; charset=utf-8",
    )


@bp.post("/api/demo/export/pdf")
def legacy_export_pdf() -> Response:
    ctx = _get_ctx()
    payload = _parse_json_body()
    try:
        filename, body = ctx.legacy_service.export_pdf(payload)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(status_code=400, message=str(exc)) from exc
    return Response(
        response=body,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        mimetype="application/pdf",
    )


@bp.post("/api/demo/temporal/run")
def legacy_temporal_run() -> Response:
    ctx = _get_ctx()
    payload = _parse_json_body()
    try:
        result = ctx.legacy_service.run_temporal(payload)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"ok": False, "error": str(exc)})
    return _json_response({"ok": True, "result": result})


@bp.post("/api/demo/segment/mineru")
def legacy_segment_mineru() -> Response:
    ctx = _get_ctx()
    payload = _parse_json_body()
    try:
        result = ctx.demo_service.build_mineru_segment_preview(payload)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"ok": False, "error": str(exc)})
    return _json_response({"ok": True, "result": result})


@bp.post("/api/demo/segment/refine")
def legacy_segment_refine() -> Response:
    ctx = _get_ctx()
    payload = _parse_json_body()
    try:
        result = ctx.demo_service.build_refine_segment_preview(payload)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"ok": False, "error": str(exc)})
    return _json_response({"ok": True, "result": result})


# --- Old demo analysis dashboard (mock data + UI) ---

from demo.mock_data import _build_mock_analysis_result, _build_mock_profile_export


@bp.get("/api/demo/analysis/mock")
def legacy_analysis_mock_get() -> Response | None:
    query = request.args
    payload = {key: values[-1] if isinstance(values := query.getlist(key), list) and values else query.get(key) for key in query.keys()}
    result = _build_mock_analysis_result(payload)
    return _json_response({"ok": True, "result": result})


@bp.post("/api/demo/analysis/mock")
def legacy_analysis_mock_post() -> Response | None:
    payload = _parse_json_body()
    result = _build_mock_analysis_result(payload)
    return _json_response({"ok": True, "result": result})


@bp.get("/api/demo/profile/mock-export")
def legacy_profile_mock_get() -> Response | None:
    query = request.args
    payload = {key: values[-1] if isinstance(values := query.getlist(key), list) and values else query.get(key) for key in query.keys()}
    result = _build_mock_profile_export(payload)
    return _json_response(result)


@bp.post("/api/demo/profile/mock-export")
def legacy_profile_mock_post() -> Response | None:
    payload = _parse_json_body()
    result = _build_mock_profile_export(payload)
    return _json_response(result)


@bp.get("/analysis")
@bp.get("/analysis.html")
def legacy_analysis_page() -> Response:
    return render_template("demo/analysis.html")


@bp.get("/demo")
@bp.get("/demo/index.html")
def legacy_demo_page() -> Response:
    return render_template("demo/index.html")


@bp.get("/demo/temporal")
@bp.get("/demo/temporal.html")
def legacy_demo_temporal_page() -> Response:
    return render_template("demo/temporal.html")


@bp.get("/mineru-debug")
def legacy_mineru_debug() -> Response:
    return render_template("demo/mineru_debug.html")
