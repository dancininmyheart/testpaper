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


def _seed_project(ctx, project_id: str = "project_1") -> None:
    ctx.paper_repo.create_project(
        project_id=project_id,
        title="state test paper",
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
    project_id: str = "project_1",
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


def _profile_result(student_id: str, mastery_value: float) -> dict:
    return {
        "student_id": student_id,
        "skill_alias_map": {"linear_equation": "一元一次方程"},
        "student_profile": {
            "mastery": [
                {
                    "skill_id": "linear_equation",
                    "skill_name": "Linear Equation",
                    "value": mastery_value,
                }
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
                "score": mastery_value * 10,
                "max_score": 10,
                "skill_tags": ["linear_equation"],
            }
        ],
    }


def test_student_state_updates_only_after_teacher_approves_scores(monkeypatch, tmp_path: Path):
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
        _seed_project(ctx)
        _seed_job(ctx, job_id="job_s001", result=_profile_result("S001", 0.82))

        before = client.get("/api/v1/students/S001/state", headers=headers)
        approve = client.post(
            "/api/v1/paper-projects/project_1/student-runs/job_s001/approve-scores",
            headers=headers,
        )
        after = client.get("/api/v1/students/S001/state", headers=headers)
    finally:
        app.config["ctx"].close()

    assert before.status_code == 200
    before_data = before.get_json()["data"]
    assert before_data["summary"]["exam_count"] == 0
    assert before_data["mastery"] == []

    assert approve.status_code == 200
    approved = approve.get_json()["data"]
    assert approved["status"] == "approved"
    assert approved["student_state"]["overall_mastery"] == 0.82
    assert approved["student_state"]["risk_level"] == "low"

    assert after.status_code == 200
    state = after.get_json()["data"]
    assert state["summary"]["exam_count"] == 1
    assert state["summary"]["overall_mastery"] == 0.82
    assert state["mastery"][0]["skill_id"] == "linear_equation"
    assert state["mastery"][0]["name"] == "一元一次方程"
    assert state["mastery"][0]["value"] == 0.82
    assert state["summary"]["recommendations"] == []
    assert state["literacy"][0]["literacy_id"] == "logical_reasoning"
    assert state["source_report_ids"] == ["job_s001"]


def test_student_state_resolves_standard_skill_ids_from_keyword_graph(monkeypatch, tmp_path: Path):
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
        _seed_project(ctx)
        _seed_job(
            ctx,
            job_id="job_standard_ids",
            result={
                "student_id": "S001",
                "student_profile": {
                    "mastery": [
                        {"skill_id": "geom.theorem.congruence", "value": 0.45},
                        {"skill_id": "root.method.add_sub", "value": 0.92},
                        {"skill_id": "eq.theorem.vieta", "value": 0.95},
                    ],
                },
            },
        )

        approve = client.post(
            "/api/v1/paper-projects/project_1/student-runs/job_standard_ids/approve-scores",
            headers=headers,
        )
        state_response = client.get("/api/v1/students/S001/state", headers=headers)
    finally:
        app.config["ctx"].close()

    assert approve.status_code == 200
    assert state_response.status_code == 200
    state = state_response.get_json()["data"]
    names_by_id = {item["skill_id"]: item["name"] for item in state["mastery"]}
    assert names_by_id["geom.theorem.congruence"] == "全等三角形的判定"
    assert names_by_id["root.method.add_sub"] == "二次根式的加减"
    assert names_by_id["eq.theorem.vieta"] == "韦达定理（根与系数的关系）"


def test_student_state_uses_latest_approved_run_per_project(monkeypatch, tmp_path: Path):
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
        _seed_project(ctx)
        _seed_job(ctx, job_id="job_old", result=_profile_result("S001", 0.25))
        _seed_job(ctx, job_id="job_new", result=_profile_result("S001", 0.9))

        old_response = client.post(
            "/api/v1/paper-projects/project_1/student-runs/job_old/approve-scores",
            headers=headers,
        )
        new_response = client.post(
            "/api/v1/paper-projects/project_1/student-runs/job_new/approve-scores",
            headers=headers,
        )
        state_response = client.get("/api/v1/students/S001/state", headers=headers)
    finally:
        app.config["ctx"].close()

    assert old_response.status_code == 200
    assert new_response.status_code == 200
    state = state_response.get_json()["data"]
    assert state["summary"]["exam_count"] == 1
    assert state["summary"]["overall_mastery"] == 0.9
    assert state["source_report_ids"] == ["job_new"]


def test_student_state_can_fallback_to_answer_trace_skills(monkeypatch, tmp_path: Path):
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
        _seed_project(ctx)
        _seed_job(
            ctx,
            job_id="job_trace_only",
            result={
                "student_id": "S001",
                "answer_trace_display": [
                    {
                        "question_id": "Q2",
                        "score": 3,
                        "max_score": 10,
                        "skill_tags": ["geometry_reasoning"],
                    }
                ],
            },
        )

        approve = client.post(
            "/api/v1/paper-projects/project_1/student-runs/job_trace_only/approve-scores",
            headers=headers,
        )
    finally:
        app.config["ctx"].close()

    assert approve.status_code == 200
    state = approve.get_json()["data"]["student_state"]
    assert state["overall_mastery"] == 0.3
    assert state["risk_level"] == "high"
    assert state["weak_skill_count"] == 1
