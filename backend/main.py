from __future__ import annotations

import atexit
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import HTTPException, MethodNotAllowed

from backend.api.deps import ApiError, IntakeDraftStore, _json_response
from backend.api.routers import analysis, auth, intake, legacy, mastery, paper_projects, students
from backend.app_context import AppContext
from backend.config import AppSettings
from backend.domain.state_machine import InvalidProjectTransition


_REACT_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _close_context(app: Flask) -> None:
    if app.config.get("_ctx_closed"):
        return
    ctx = app.config.get("ctx")
    if isinstance(ctx, AppContext):
        ctx.close()
    app.config["_ctx_closed"] = True


def create_app(*, start_worker: bool = True) -> Flask:
    settings = AppSettings.load()
    ctx = AppContext.build(settings)

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["ctx"] = ctx
    app.config["intake_store"] = IntakeDraftStore()
    app.config["_ctx_closed"] = False
    if start_worker and settings.worker_enabled:
        ctx.worker.start()
    atexit.register(_close_context, app)

    CORS(
        app,
        resources={r"/*": {"origins": settings.cors_allow_origins}},
        supports_credentials=True,
        allow_headers="*",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )

    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        return jsonify({"ok": False, "error": {"code": exc.code, "message": exc.message}}), exc.status_code

    @app.errorhandler(InvalidProjectTransition)
    def _handle_invalid_transition(exc: InvalidProjectTransition):
        return jsonify({
            "ok": False,
            "error": {
                "code": "INVALID_TRANSITION",
                "message": str(exc),
            },
        }), 400

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException):
        if request.path.startswith("/api/"):
            code = "METHOD_NOT_ALLOWED" if isinstance(exc, MethodNotAllowed) else f"HTTP_{exc.code}"
            return jsonify({
                "ok": False,
                "error": {
                    "code": code,
                    "message": exc.description,
                },
            }), exc.code or 500
        return exc

    @app.errorhandler(Exception)
    def _handle_generic_error(exc: Exception):
        import traceback
        app.logger.error(f"Unhandled exception: {traceback.format_exc()}")
        return jsonify({
            "ok": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(exc) or "服务器内部错误",
            },
        }), 500

    @app.get("/health")
    def health():
        return _json_response({"status": "ok"})

    @app.get("/")
    def index_page():
        """Serve the React SPA build."""
        if _REACT_DIST.joinpath("index.html").is_file():
            return send_from_directory(str(_REACT_DIST), "index.html")
        return render_template("platform/index.html")

    @app.get("/assets/<path:filename>")
    def react_assets(filename: str):
        """Serve React build static assets."""
        return send_from_directory(str(_REACT_DIST / "assets"), filename)

    @app.errorhandler(404)
    def fallback_to_react(_exc: Exception):
        if request.path.startswith("/api/"):
            return jsonify({
                "ok": False,
                "error": {
                    "code": "HTTP_404",
                    "message": "The requested URL was not found on the server.",
                },
            }), 404
        if _REACT_DIST.joinpath("index.html").is_file():
            return send_from_directory(str(_REACT_DIST), "index.html")
        return ("not found", 404)

    app.register_blueprint(auth.bp)
    app.register_blueprint(intake.bp)
    app.register_blueprint(analysis.bp)
    app.register_blueprint(mastery.bp)
    app.register_blueprint(legacy.bp)
    app.register_blueprint(paper_projects.bp)
    app.register_blueprint(students.bp)

    return app


# For WSGI integration. Local run should use run_platform_server.py
app = create_app(start_worker=False)
