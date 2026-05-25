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
    assert '"model": "gemini-3.5-flash"' in config_source


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


def test_frontend_displays_latest_student_state_after_score_approval():
    student_api_source = Path("frontend/src/api/students.ts").read_text(encoding="utf-8")
    student_detail_source = Path("frontend/src/pages/StudentDetailPage.tsx").read_text(encoding="utf-8")
    score_source = Path("frontend/src/pages/ScoreReview.tsx").read_text(encoding="utf-8")

    assert "StudentStateSnapshot" in student_api_source
    assert "getStudentState" in student_api_source
    assert "rebuildStudentState" in student_api_source
    assert "/state:rebuild" in student_api_source
    assert "getStudentState" in student_detail_source
    assert 'queryKey: ["student-state", studentId]' in student_detail_source
    assert "薄弱知识点" in student_detail_source
    assert "数学素养" in student_detail_source
    assert 'queryClient.invalidateQueries({ queryKey: ["student-state"' in score_source


def test_frontend_score_review_derives_score_from_deducted_score():
    source = Path("frontend/src/components/report/normalizeAnalysisReport.ts").read_text(encoding="utf-8")

    assert "resolveQuestionScore" in source
    assert "deducted_score" in source
    assert "lost_score" in source
    assert "maxScore - deductedScore" in source
    assert "is_correct" in source
    assert "acc.score += scoreInfo.score ?? 0" in source


def test_project_workspace_supports_return_to_grading():
    source = Path("frontend/src/pages/ProjectWorkspace.tsx").read_text(encoding="utf-8")
    api_source = Path("frontend/src/api/projects.ts").read_text(encoding="utf-8")
    router_source = Path("backend/api/routers/paper_projects.py").read_text(encoding="utf-8")

    assert "resetProjectToReady" in source
    assert "handleResetToReady" in source
    assert "返回批改与分析" in source
    assert "resetProjectToReady" in api_source
    assert "/reset-to-ready" in api_source
    assert "def reset_project_to_ready" in router_source
