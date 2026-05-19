from pathlib import Path


def test_report_view_component_and_normalizer_exist():
    component = Path("frontend/src/components/report/ReportView.tsx")
    normalizer = Path("frontend/src/components/report/normalizeAnalysisReport.ts")

    assert component.exists()
    assert normalizer.exists()

    component_source = component.read_text(encoding="utf-8")
    normalizer_source = normalizer.read_text(encoding="utf-8")

    assert "normalizeAnalysisReport" in component_source
    assert "学习概览" in component_source
    assert "学情画像" in component_source
    assert "错题与提升建议" in component_source
    assert "逐题明细" in component_source
    assert "技术详情" in component_source
    assert "answer_trace_display" in normalizer_source
    assert "answer_trace" in normalizer_source
    assert "structured_questions_full" in normalizer_source
    assert "question_analysis" in normalizer_source
    assert "problem_text_full" in normalizer_source
    assert "student_profile" in normalizer_source
    assert "mapping_report" in normalizer_source
    assert "skill_alias_map" in normalizer_source
    assert "resolveSkillName" in normalizer_source
    assert "buildSkillAliasMap" in normalizer_source
    assert "暂无数据" in normalizer_source


def test_report_pages_use_structured_report_view_instead_of_raw_json():
    score_source = Path("frontend/src/pages/ScoreReview.tsx").read_text(encoding="utf-8")
    student_report_source = Path("frontend/src/pages/StudentProjectReportPage.tsx").read_text(encoding="utf-8")
    report_center_source = Path("frontend/src/pages/ReportCenter.tsx").read_text(encoding="utf-8")
    projects_api_source = Path("frontend/src/api/projects.ts").read_text(encoding="utf-8")

    assert "ReportView" in score_source
    assert "ReportView" in student_report_source
    assert "JSON.stringify" not in score_source
    assert "JSON.stringify" not in student_report_source
    assert "查看报告" in report_center_source
    assert "/reports/" in report_center_source
    assert "getProjectReport" in projects_api_source


def test_report_question_details_show_full_problem_text():
    component_source = Path("frontend/src/components/report/ReportView.tsx").read_text(encoding="utf-8")
    normalizer_source = Path("frontend/src/components/report/normalizeAnalysisReport.ts").read_text(encoding="utf-8")

    assert "题干" in component_source
    assert "item.questionText" in component_source
    assert "知识点" in component_source
    assert "item.knowledgePoints" in component_source
    assert "problem_text_full" in normalizer_source
    assert "parent_question_id" in normalizer_source
    assert "buildQuestionSkillLookup" in normalizer_source
    assert "knowledgePoints" in normalizer_source


def test_report_skill_names_use_chinese_alias_map():
    normalizer_source = Path("frontend/src/components/report/normalizeAnalysisReport.ts").read_text(encoding="utf-8")

    assert "skill_alias_map" in normalizer_source
    assert "new_knowledge_points" in normalizer_source
    assert "resolveSkillName" in normalizer_source
    assert "normalizeWeakness(item, skillAliasMap)" in normalizer_source
    assert "normalizeMastery(item, skillAliasMap)" in normalizer_source


def test_report_migrates_demo_literacy_profile():
    component_source = Path("frontend/src/components/report/ReportView.tsx").read_text(encoding="utf-8")
    normalizer_source = Path("frontend/src/components/report/normalizeAnalysisReport.ts").read_text(encoding="utf-8")

    assert "数学素养画像" in component_source
    assert "item.definition" in component_source
    assert "item.reason" in component_source
    assert "item.suggestion" in component_source
    assert "ReportLiteracyItem" in normalizer_source
    assert "normalizeLiteracyItems" in normalizer_source
    assert "legacyLiteracyName" in normalizer_source
    assert "logical_reasoning" in normalizer_source
    assert "literacy_history" in normalizer_source
    assert "literacy_radar" in normalizer_source
