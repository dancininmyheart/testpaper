from __future__ import annotations

from pathlib import Path


def _login_headers(client) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher", "password": "teacher123"},
    )
    token = login.get_json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_project_with_runs(ctx, project_id: str) -> None:
    ctx.paper_repo.create_project(
        project_id=project_id,
        title="multi student test",
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
    for job_id, student_id, score in [
        ("job_s001", "S001", 5),
        ("job_s002", "S002", 2),
    ]:
        ctx.analysis_service.repo.create_job(
            job_id=job_id,
            student_id=student_id,
            input_mode="pre_split_questions",
            payload={"student_id": student_id, "input_mode": "pre_split_questions"},
            created_by=2,
            paper_project_id=project_id,
        )
        ctx.analysis_service.repo.save_job_result(
            job_id=job_id,
            result={
                "student_id": student_id,
                "answer_trace_display": [
                    {"question_id": "Q1", "display_question_id": "Q1", "score": score, "max_score": 5}
                ],
                "structured_questions_full": [{"question_id": "Q1"}],
            },
        )
        ctx.analysis_service.repo.mark_job_succeeded(job_id, stage_logs=[])


def test_project_student_runs_list_multiple_students(monkeypatch, tmp_path: Path):
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
        _seed_project_with_runs(ctx, project_id)

        response = client.get(f"/api/v1/paper-projects/{project_id}/student-runs", headers=headers)
    finally:
        app.config["ctx"].close()

    assert response.status_code == 200
    items = response.get_json()["data"]["items"]
    assert [item["student_id"] for item in items] == ["S002", "S001"]
    assert {item["job_id"] for item in items} == {"job_s001", "job_s002"}
    assert all(item["has_result"] is True for item in items)


def test_project_student_run_score_review_uses_job_result(monkeypatch, tmp_path: Path):
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
        _seed_project_with_runs(ctx, project_id)
        ctx.paper_repo.update_project_data(
            project_id,
            score_review_data={
                "student_id": "legacy",
                "answer_trace_display": [{"question_id": "Q1", "score": 0, "max_score": 5}],
            },
        )

        response = client.get(
            f"/api/v1/paper-projects/{project_id}/student-runs/job_s002/score-review",
            headers=headers,
        )
    finally:
        app.config["ctx"].close()

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["student_id"] == "S002"
    assert data["answer_trace_display"][0]["score"] == 2
    assert data["answer_trace_display"][0]["problem_text_full"] == "reviewed question text"
    assert data["answer_trace_display"][0]["skill_tags"] == ["quadratic_equation"]
