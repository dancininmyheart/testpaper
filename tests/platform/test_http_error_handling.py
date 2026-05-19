from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def _workspace_temp_dir():
    root = Path.cwd() / "outputs" / "test_runtime"
    tmp_dir = root / f"http_errors_{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield tmp_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_api_method_not_allowed_returns_405_json(monkeypatch):
    with _workspace_temp_dir() as tmp:
        monkeypatch.setenv("APP_DB_PATH", str(tmp / "app.db"))
        monkeypatch.setenv("APP_STORAGE_ROOT", str(tmp / "storage"))
        monkeypatch.setenv("WORKER_ENABLED", "false")

        from backend.main import create_app

        app = create_app(start_worker=False)
        try:
            response = app.test_client().post("/api/v1/paper-projects/project_1")
        finally:
            app.config["ctx"].close()

    assert response.status_code == 405
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_unknown_api_route_returns_404_json_not_spa(monkeypatch):
    with _workspace_temp_dir() as tmp:
        monkeypatch.setenv("APP_DB_PATH", str(tmp / "app.db"))
        monkeypatch.setenv("APP_STORAGE_ROOT", str(tmp / "storage"))
        monkeypatch.setenv("WORKER_ENABLED", "false")

        from backend.main import create_app

        app = create_app(start_worker=False)
        try:
            response = app.test_client().get("/api/v1/not-a-route")
        finally:
            app.config["ctx"].close()

    assert response.status_code == 404
    assert response.content_type.startswith("application/json")
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "HTTP_404"


def test_project_file_content_disposition_supports_chinese_filename():
    from backend.application.paper_project_artifacts import content_disposition_header

    header = content_disposition_header("屏幕截图 2026-03-02.png")

    header.encode("latin-1")
    assert "filename=" in header
    assert "filename*=UTF-8''" in header
    assert "屏幕截图" not in header
