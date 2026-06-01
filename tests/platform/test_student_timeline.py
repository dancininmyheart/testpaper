from __future__ import annotations

from pathlib import Path


def _login_headers(client) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher", "password": "teacher123"},
    )
    token = login.get_json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


def _create_student(client, headers: dict[str, str], student_id: str = "S001") -> None:
    response = client.post(
        "/api/v1/students",
        headers=headers,
        json={"student_id": student_id, "name": "Student One", "grade": "8"},
    )
    assert response.status_code == 200


def _seed_project(ctx, project_id: str, title: str) -> None:
    ctx.paper_repo.create_project(
        project_id=project_id,
        title=title,
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
                "content": "solve equation",
                "skill_tags": ["linear_equation"],
            },
            {
                "question_id": "Q2",
                "question_no": "2",
                "content": "geometry proof",
                "skill_tags": ["geometry_reasoning"],
            },
        ],
    )


def _seed_job(
    ctx,
    *,
    project_id: str,
    job_id: str,
    student_id: str = "S001",
    result: dict,
) -> None:
    ctx.analysis_service.repo.create_job(
        job_id=job_id,
        student_id=student_id,
        input_mode="pre_split_questions",
        payload={"student_id": student_id, "input_mode": "pre_split_questions"},
        created_by=2,
        paper_project_id=project_id,
    )
    ctx.analysis_service.repo.save_job_result(job_id=job_id, result=result)
    ctx.analysis_service.repo.mark_job_succeeded(job_id, stage_logs=[])


def _profile_result(student_id: str, algebra: float, geometry: float) -> dict:
    return {
        "student_id": student_id,
        "student_profile": {
            "mastery": [
                {
                    "skill_id": "linear_equation",
                    "skill_name": "Linear Equation",
                    "value": algebra,
                },
                {
                    "skill_id": "geometry_reasoning",
                    "skill_name": "Geometry Reasoning",
                    "value": geometry,
                },
            ],
            "literacy": [
                {
                    "literacy_id": "logical_reasoning",
                    "name": "Logical Reasoning",
                    "value": 0.7,
                }
            ],
        },
        "answer_trace_display": [
            {
                "question_id": "Q1",
                "score": algebra * 10,
                "max_score": 10,
                "skill_tags": ["linear_equation"],
            }
        ],
    }


def test_student_timeline_uses_approved_reports_and_computes_deltas(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("WORKER_ENABLED", "false")

    from backend.main import create_app

    app = create_app(start_worker=False)
    try:
        client = app.test_client()
        headers = _login_headers(client)
        _create_student(client, headers)
        ctx = app.config["ctx"]
        _seed_project(ctx, "project_1", "First Exam")
        _seed_project(ctx, "project_2", "Second Exam")
        _seed_job(ctx, project_id="project_1", job_id="job_first", result=_profile_result("S001", 0.4, 0.82))
        _seed_job(ctx, project_id="project_1", job_id="job_first_retry", result=_profile_result("S001", 0.5, 0.82))
        _seed_job(ctx, project_id="project_2", job_id="job_second", result=_profile_result("S001", 0.7, 0.88))

        before = client.get("/api/v1/students/S001/timeline", headers=headers)
        first_approve = client.post(
            "/api/v1/paper-projects/project_1/student-runs/job_first/approve-scores",
            headers=headers,
        )
        retry_approve = client.post(
            "/api/v1/paper-projects/project_1/student-runs/job_first_retry/approve-scores",
            headers=headers,
        )
        second_approve = client.post(
            "/api/v1/paper-projects/project_2/student-runs/job_second/approve-scores",
            headers=headers,
        )
        after = client.get("/api/v1/students/S001/timeline", headers=headers)
    finally:
        app.config["ctx"].close()

    assert before.status_code == 200
    assert before.get_json()["data"]["items"] == []
    assert first_approve.status_code == 200
    assert retry_approve.status_code == 200
    assert second_approve.status_code == 200

    data = after.get_json()["data"]
    assert data["source_version"] == "student_profile_timeline_v1"
    assert [item["report_id"] for item in data["items"]] == ["job_first_retry", "job_second"]
    assert data["items"][0]["summary"]["weak_skill_count"] == 1
    assert data["items"][1]["summary"]["weak_skill_count"] == 0
    assert data["items"][1]["delta"]["weak_skill_count"] == -1
    assert data["items"][1]["delta"]["overall_mastery"] > 0
    assert [item["skill_id"] for item in data["items"][1]["improved_skills"]] == ["linear_equation"]
