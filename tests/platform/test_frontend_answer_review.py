from pathlib import Path


def test_answer_review_limits_mutating_actions_to_answer_review_stage():
    source = Path("frontend/src/pages/AnswerReview.tsx").read_text(encoding="utf-8")

    assert "getProject" in source
    assert "canGenerateReferenceAnswers" in source
    assert "canApproveReferenceAnswers" in source
    assert 'project?.status === "review_answers"' in source
    assert 'project?.status === "ready"' in source
    assert "MODEL_PROFILE_MODES" in source
    assert "selectedProfiles" in source
    assert "generateReferenceAnswers(id!, selectedProfiles)" in source
    assert "快速模式" in source
    assert "标准模式" in source


def test_answer_review_renders_analysis_and_step_details():
    source = Path("frontend/src/pages/AnswerReview.tsx").read_text(encoding="utf-8")

    assert "steps.map" in source
    assert "<ol" in source
    assert "analysis" in source
    assert "answerText" in source
