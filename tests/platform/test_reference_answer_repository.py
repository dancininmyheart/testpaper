from __future__ import annotations

from backend.infrastructure.db import Database
from backend.infrastructure.repositories import PaperRepository
from backend.application.paper_project_artifacts import reference_answer_review_state


def test_save_reference_answers_accepts_legacy_reference_field_names(tmp_path):
    db = Database(tmp_path / "app.db")
    repo = PaperRepository(db)
    try:
        repo.create_project(
            project_id="project_1",
            title="reference field compatibility",
            subject="math",
            grade="8",
            created_by=1,
        )

        repo.save_reference_answers(
            project_id="project_1",
            answers=[
                {
                    "question_id": "Q1",
                    "reference_answer_text": "reference body",
                    "reference_final_answer": "42",
                    "reference_steps": ["step 1", "step 2"],
                    "source": "generated",
                }
            ],
        )

        answers = repo.get_reference_answers("project_1")
    finally:
        db.close()

    assert answers[0]["answer_text"] == "reference body"
    assert answers[0]["final_answer"] == "42"
    assert answers[0]["steps"] == ["step 1", "step 2"]


def test_reference_answer_review_state_marks_uploaded_fallback():
    status, warning = reference_answer_review_state(
        answer={"question_id": "Q2", "source": "generated"},
        answer_key_source="uploaded",
    )

    assert status == "generated_fallback"
    assert "uploaded extraction missed" in warning
