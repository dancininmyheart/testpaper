from __future__ import annotations

from pathlib import Path


def _login_headers(client) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher", "password": "teacher123"},
    )
    token = login.get_json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


def test_score_review_endpoint_backfills_question_text(monkeypatch, tmp_path: Path):
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
            title="score review text test",
            subject="math",
            grade="8",
            created_by=2,
        )
        ctx.paper_repo.save_questions(
            project_id=project_id,
            questions=[
                {
                    "question_id": "Q1",
                    "question_no": "1",
                    "content": "reviewed question text",
                    "skill_tags": ["quadratic_equation"],
                }
            ],
        )
        ctx.paper_repo.update_project_data(
            project_id,
            score_review_data={
                "answer_trace_display": [{"question_id": "Q1", "display_question_id": "Q1"}],
                "structured_questions_full": [{"question_id": "Q1"}],
            },
        )

        response = client.get(f"/api/v1/paper-projects/{project_id}/score-review", headers=headers)
    finally:
        app.config["ctx"].close()

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["answer_trace_display"][0]["problem_text_full"] == "reviewed question text"
    assert data["answer_trace_display"][0]["skill_tags"] == ["quadratic_equation"]
    assert data["structured_questions_full"][0]["question_anchor_text"] == "reviewed question text"
    assert data["structured_questions_full"][0]["skill_tags"] == ["quadratic_equation"]


def test_student_payload_override_includes_question_content(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("WORKER_ENABLED", "false")

    from backend.main import create_app

    app = create_app(start_worker=False)
    try:
        ctx = app.config["ctx"]
        project_id = "project_1"
        ctx.paper_repo.create_project(
            project_id=project_id,
            title="student payload text test",
            subject="math",
            grade="8",
            created_by=2,
        )
        ctx.paper_repo.save_questions(
            project_id=project_id,
            questions=[
                {
                    "question_id": "Q1",
                    "question_no": "1",
                    "content": "reviewed question text",
                    "skill_tags": ["quadratic_equation"],
                }
            ],
        )

        payload = ctx.paper_service.build_student_payload_override(
            project_id,
            "S001",
            [{"local_path": str(tmp_path / "answer.png"), "file_name": "answer.png"}],
        )
    finally:
        app.config["ctx"].close()

    assert payload["pre_split_questions"][0]["content"] == "reviewed question text"
    assert payload["pre_split_questions"][0]["problem_text_full"] == "reviewed question text"
    assert payload["pre_split_questions"][0]["skill_tags"] == ["quadratic_equation"]
