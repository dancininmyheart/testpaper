from __future__ import annotations

import io
from pathlib import Path


def _build_app(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("WORKER_ENABLED", "false")

    from backend.main import create_app

    return create_app(start_worker=False)


def _login_headers(client) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher", "password": "teacher123"},
    )
    token = login.get_json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


def _ready_project(ctx, project_id: str = "project_1") -> None:
    ctx.paper_repo.create_project(
        project_id=project_id,
        title="Student report project",
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
    ctx.state_service.transition(project_id, "review_answers", actor_user_id=2)
    ctx.state_service.transition(project_id, "ready", actor_user_id=2)


def test_students_crud_and_duplicate_validation(monkeypatch, tmp_path: Path):
    app = _build_app(monkeypatch, tmp_path)
    try:
        client = app.test_client()
        headers = _login_headers(client)

        created = client.post(
            "/api/v1/students",
            headers=headers,
            json={"student_id": "S001", "name": "张三", "grade": "八年级"},
        )
        duplicate = client.post(
            "/api/v1/students",
            headers=headers,
            json={"student_id": "S001", "name": "重复", "grade": "八年级"},
        )
        updated = client.patch(
            "/api/v1/students/S001",
            headers=headers,
            json={"name": "张三丰", "grade": "九年级"},
        )
        listed = client.get("/api/v1/students", headers=headers)
    finally:
        app.config["ctx"].close()

    assert created.status_code == 200
    assert created.get_json()["data"]["student_id"] == "S001"
    assert duplicate.status_code == 400
    assert updated.status_code == 200
    assert updated.get_json()["data"]["name"] == "张三丰"
    assert listed.get_json()["data"]["items"] == [updated.get_json()["data"]]


def test_analyze_answer_sheet_requires_existing_student(monkeypatch, tmp_path: Path):
    app = _build_app(monkeypatch, tmp_path)
    try:
        client = app.test_client()
        headers = _login_headers(client)
        ctx = app.config["ctx"]
        _ready_project(ctx)

        missing = client.post(
            "/api/v1/paper-projects/project_1/analyze-answer-sheet",
            headers=headers,
            data={
                "student_id": "S404",
                "answer_sheet_files": (io.BytesIO(b"answer-sheet"), "answer.png"),
            },
            content_type="multipart/form-data",
        )

        client.post(
            "/api/v1/students",
            headers=headers,
            json={"student_id": "S001", "name": "张三", "grade": "八年级"},
        )
        accepted = client.post(
            "/api/v1/paper-projects/project_1/analyze-answer-sheet",
            headers=headers,
            data={
                "student_id": "S001",
                "answer_sheet_files": (io.BytesIO(b"answer-sheet"), "answer.png"),
            },
            content_type="multipart/form-data",
        )
    finally:
        app.config["ctx"].close()

    assert missing.status_code == 400
    assert "student" in missing.get_json()["error"]["message"].lower()
    assert accepted.status_code == 200
    assert accepted.get_json()["data"]["student_id"] == "S001"


def test_student_history_returns_latest_successful_project_report(monkeypatch, tmp_path: Path):
    app = _build_app(monkeypatch, tmp_path)
    try:
        client = app.test_client()
        headers = _login_headers(client)
        ctx = app.config["ctx"]
        _ready_project(ctx, "project_1")
        _ready_project(ctx, "project_2")
        client.post(
            "/api/v1/students",
            headers=headers,
            json={"student_id": "S001", "name": "张三", "grade": "八年级"},
        )
        client.post(
            "/api/v1/students",
            headers=headers,
            json={"student_id": "S002", "name": "李四", "grade": "八年级"},
        )

        for job_id, project_id, student_id, marker in [
            ("job_old", "project_1", "S001", "old"),
            ("job_new", "project_1", "S001", "new"),
            ("job_other_project", "project_2", "S001", "project2"),
            ("job_other_student", "project_1", "S002", "other"),
        ]:
            ctx.analysis_service.repo.create_job(
                job_id=job_id,
                student_id=student_id,
                input_mode="pre_split_questions",
                payload={"student_id": student_id},
                created_by=2,
                paper_project_id=project_id,
            )
            result = {"student_id": student_id, "project_id": project_id, "marker": marker}
            if marker == "new":
                result.update({
                    "answer_trace_display": [
                        {"question_id": "Q1", "display_question_id": "Q1", "problem_text": ""}
                    ],
                    "structured_questions_full": [
                        {"question_id": "Q1", "problem_text_full": ""}
                    ],
                })
            ctx.analysis_service.repo.save_job_result(
                job_id=job_id,
                result=result,
            )
            ctx.analysis_service.repo.mark_job_succeeded(job_id, stage_logs=[])

        projects = client.get("/api/v1/students/S001/projects", headers=headers)
        report = client.get("/api/v1/students/S001/projects/project_1/report", headers=headers)
    finally:
        app.config["ctx"].close()

    assert projects.status_code == 200
    items = projects.get_json()["data"]["items"]
    assert [item["project_id"] for item in items] == ["project_2", "project_1"]
    project_1 = next(item for item in items if item["project_id"] == "project_1")
    assert project_1["job_id"] == "job_new"
    assert report.status_code == 200
    report_data = report.get_json()["data"]
    assert report_data["marker"] == "new"
    assert report_data["answer_trace_display"][0]["problem_text"] == "question"
    assert report_data["structured_questions_full"][0]["problem_text_full"] == "question"
