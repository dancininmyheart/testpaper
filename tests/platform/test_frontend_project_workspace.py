from pathlib import Path


def test_project_workspace_exposes_stage_three_answer_sheet_flow():
    source = Path("frontend/src/pages/ProjectWorkspace.tsx").read_text(encoding="utf-8")

    assert "analyzeAnswerSheet" in source
    assert "answerSheetFiles" in source
    assert "handleAnalyzeAnswerSheet" in source
    assert "review_recognition" in source
    assert "canStartGrading" in source


def test_project_workspace_keeps_stage_two_active_until_reference_answers_are_ready():
    source = Path("frontend/src/pages/ProjectWorkspace.tsx").read_text(encoding="utf-8")

    assert "needsReferenceAnswers" in source
    assert "uploadAnswerKeyFiles" in source
    assert "generateReferenceAnswers" in source
    assert "answerKeyFiles" in source
    assert "project.reference_answer_count ?? 0" in source


def test_project_workspace_supports_fast_and_standard_model_modes_for_each_stage():
    source = Path("frontend/src/pages/ProjectWorkspace.tsx").read_text(encoding="utf-8")
    api_source = Path("frontend/src/api/projects.ts").read_text(encoding="utf-8")
    config_source = Path("llm_config.json").read_text(encoding="utf-8")

    assert "MODEL_PROFILE_MODES" in source
    assert "selectedModelMode" in source
    assert "selectedProfiles" in source
    assert "快速模式" in source
    assert "标准模式" in source
    assert "openai_vision_gemini_3_flash" in source
    assert "openai_text_gemini_3_flash" in source
    assert "openai_vision_gemini_3_1_pro" in source
    assert "openai_text_gemini_3_1_pro" in source
    assert "triggerExtraction(id!, selectedProfiles)" in source
    assert "uploadAnswerKeyFiles(id!, answerKeyFiles, selectedProfiles)" in source
    assert "generateReferenceAnswers(id!, selectedProfiles)" in source
    assert "mineruParse(id!, selectedProfiles)" in source
    assert "mineruLlmParse(id!, selectedProfiles)" in source
    assert "mineruVlmMatch(id!, selectedProfiles)" in source
    assert "analyzeAnswerSheet(id!, selectedStudentId, answerSheetFiles, selectedProfiles)" in source

    assert "ModelProfiles" in api_source
    assert "appendModelProfileQuery" in api_source
    assert "mineru/parse`, profiles)" in api_source
    assert "mineru/llm-parse`, profiles)" in api_source
    assert "mineru/vlm-match`, profiles)" in api_source
    assert 'form.append("vision_profile", profiles.visionProfile)' in api_source
    assert 'form.append("text_profile", profiles.textProfile)' in api_source

    assert '"model": "gemini-3-flash-preview"' in config_source
    assert '"model": "gemini-3.1-pro-preview"' in config_source


def test_mineru_frontend_requests_allow_long_running_extraction():
    api_source = Path("frontend/src/api/projects.ts").read_text(encoding="utf-8")

    assert "MINERU_REQUEST_TIMEOUT_MS = 1_800_000" in api_source
    assert "{ timeout: MINERU_REQUEST_TIMEOUT_MS }" in api_source


def test_project_workspace_keeps_review_links_available_after_stage_two():
    source = Path("frontend/src/pages/ProjectWorkspace.tsx").read_text(encoding="utf-8")

    assert "canInspectQuestions" in source
    assert "canInspectReferenceAnswers" in source
    assert "renderInspectionLinks" in source
    assert "/review" in source
    assert "/answers" in source


def test_score_review_confirms_recognition_before_scores():
    source = Path("frontend/src/pages/ScoreReview.tsx").read_text(encoding="utf-8")

    assert "approveRecognition" in source
    assert 'project?.status === "review_recognition"' in source
    assert "isRecognitionReview" in source


def test_frontend_supports_reusable_student_run_reviews():
    workspace_source = Path("frontend/src/pages/ProjectWorkspace.tsx").read_text(encoding="utf-8")
    score_source = Path("frontend/src/pages/ScoreReview.tsx").read_text(encoding="utf-8")
    api_source = Path("frontend/src/api/projects.ts").read_text(encoding="utf-8")
    app_source = Path("frontend/src/App.tsx").read_text(encoding="utf-8")

    assert "ProjectStudentRun" in api_source
    assert "listProjectStudentRuns" in api_source
    assert "getStudentRunScoreReview" in api_source
    assert "approveStudentRunScores" in api_source
    assert "listProjectStudentRuns" in workspace_source
    assert "/scoring/${run.job_id}" in workspace_source
    assert "getStudentRunScoreReview" in score_source
    assert "approveStudentRunScores" in score_source
    assert 'path="projects/:id/scoring/:jobId"' in app_source
