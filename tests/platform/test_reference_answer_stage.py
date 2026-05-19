from __future__ import annotations

import io
from pathlib import Path


def _login_headers(client) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher", "password": "teacher123"},
    )
    token = login.get_json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


def test_approve_questions_moves_to_answer_review_when_reference_answers_exist(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("WORKER_ENABLED", "false")

    from backend.main import create_app

    app = create_app(start_worker=False)
    try:
        client = app.test_client()
        headers = _login_headers(client)
        ctx = app.config["ctx"]
        project_id = "project_1"
        ctx.paper_repo.create_project(
            project_id=project_id,
            title="answer review test",
            subject="math",
            grade="8",
            created_by=2,
        )
        ctx.paper_repo.save_questions(
            project_id=project_id,
            questions=[{"question_id": "Q1", "question_no": "1", "content": "question"}],
        )
        ctx.paper_repo.save_reference_answers(
            project_id=project_id,
            answers=[{"question_id": "Q1", "answer_text": "answer"}],
        )
        ctx.state_service.transition(project_id, "extracting", actor_user_id=2)
        ctx.state_service.transition(project_id, "review_questions", actor_user_id=2)

        response = client.post(f"/api/v1/paper-projects/{project_id}/approve-questions", headers=headers, json={})
    finally:
        app.config["ctx"].close()

    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "review_answers"


def test_upload_answer_key_starts_reference_answer_stage(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("WORKER_ENABLED", "false")

    from backend.main import create_app

    app = create_app(start_worker=False)
    try:
        client = app.test_client()
        headers = _login_headers(client)
        ctx = app.config["ctx"]
        project_id = "project_1"
        ctx.paper_repo.create_project(
            project_id=project_id,
            title="answer key upload test",
            subject="math",
            grade="8",
            created_by=2,
        )
        ctx.paper_repo.save_questions(
            project_id=project_id,
            questions=[{"question_id": "Q1", "question_no": "1", "content": "question"}],
        )
        ctx.state_service.transition(project_id, "extracting", actor_user_id=2)
        ctx.state_service.transition(project_id, "review_questions", actor_user_id=2)
        ctx.state_service.transition(project_id, "ready", actor_user_id=2)

        response = client.post(
            f"/api/v1/paper-projects/{project_id}/stage/upload-answer-key",
            headers=headers,
            data={"answer_key_files": (io.BytesIO(b"answer-key-image"), "answer.jpg")},
            content_type="multipart/form-data",
        )
        project = ctx.paper_repo.get_project(project_id)
        files = ctx.paper_repo.list_project_files(project_id)
    finally:
        app.config["ctx"].close()

    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "generating_answers"
    assert project["status"] == "generating_answers"
    assert any(file["category"] == "answer_key_files" for file in files)


def test_generate_answers_creates_job_with_complete_payload(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("WORKER_ENABLED", "false")

    from backend.main import create_app

    app = create_app(start_worker=False)
    try:
        client = app.test_client()
        headers = _login_headers(client)
        ctx = app.config["ctx"]
        project_id = "project_1"
        ctx.paper_repo.create_project(
            project_id=project_id,
            title="answer generation payload test",
            subject="math",
            grade="8",
            created_by=2,
        )
        ctx.paper_repo.save_questions(
            project_id=project_id,
            questions=[{"question_id": "Q1", "question_no": "1", "content": "reviewed question"}],
        )
        paper_path = tmp_path / "paper.png"
        paper_path.write_bytes(b"paper-image-bytes")
        ctx.paper_repo.add_project_file(
            project_id=project_id,
            category="paper_files",
            file_name="paper.png",
            local_path=str(paper_path),
            content_type="image/png",
            size_bytes=paper_path.stat().st_size,
        )
        diagram_path = tmp_path / "diagram.png"
        diagram_path.write_bytes(b"diagram-image-bytes")
        diagram_file_id = ctx.paper_repo.add_project_file(
            project_id=project_id,
            category="question_images",
            file_name="diagram.png",
            local_path=str(diagram_path),
            content_type="image/png",
            size_bytes=diagram_path.stat().st_size,
        )
        ctx.paper_repo.save_question_image(
            project_id=project_id,
            question_id="Q1",
            file_id=diagram_file_id,
            page_index=0,
            sort_order=0,
        )
        ctx.state_service.transition(project_id, "extracting", actor_user_id=2)
        ctx.state_service.transition(project_id, "review_questions", actor_user_id=2)
        ctx.state_service.transition(project_id, "ready", actor_user_id=2)

        response = client.post(f"/api/v1/paper-projects/{project_id}/stage/generate-answers", headers=headers)
        job_id = response.get_json()["data"]["job_id"]
        job = ctx.analysis_service.get_job(job_id)
        payload = job["payload"]
    finally:
        app.config["ctx"].close()

    assert response.status_code == 200
    assert payload["input_mode"] == "paper_answer_auto_key"
    assert payload["paper_files"]
    assert payload["_paper_questions"]
    assert payload["_paper_questions"][0]["content"] == "reviewed question"
    assert payload["_paper_questions"][0]["question_image_urls"] == [
        "data:image/png;base64,ZGlhZ3JhbS1pbWFnZS1ieXRlcw=="
    ]
