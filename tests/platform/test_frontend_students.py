from pathlib import Path


def test_frontend_exposes_student_management_routes_and_nav():
    app_source = Path("frontend/src/App.tsx").read_text(encoding="utf-8")
    shell_source = Path("frontend/src/components/layout/AppShell.tsx").read_text(encoding="utf-8")

    assert "StudentListPage" in app_source
    assert "StudentDetailPage" in app_source
    assert "StudentProjectReportPage" in app_source
    assert 'path="students"' in app_source
    assert 'path="students/:studentId"' in app_source
    assert 'path="students/:studentId/projects/:projectId"' in app_source
    assert 'to: "/students"' in shell_source
    assert "学生管理" in shell_source


def test_students_api_client_supports_crud_history_and_report():
    source = Path("frontend/src/api/students.ts").read_text(encoding="utf-8")

    assert "listStudents" in source
    assert "createStudent" in source
    assert "updateStudent" in source
    assert "listStudentProjects" in source
    assert "getStudentProjectReport" in source
    assert "/students" in source


def test_student_pages_include_add_edit_history_and_report_links():
    list_source = Path("frontend/src/pages/StudentListPage.tsx").read_text(encoding="utf-8")
    detail_source = Path("frontend/src/pages/StudentDetailPage.tsx").read_text(encoding="utf-8")
    report_source = Path("frontend/src/pages/StudentProjectReportPage.tsx").read_text(encoding="utf-8")

    assert "createStudent" in list_source
    assert "updateStudent" in list_source
    assert "历史分析报告" in list_source
    assert "listStudentProjects" in detail_source
    assert "project_id" in detail_source
    assert "getStudentProjectReport" in report_source
    assert "ReportView" in report_source
    assert "JSON.stringify" not in report_source


def test_project_workspace_selects_student_from_student_library():
    source = Path("frontend/src/pages/ProjectWorkspace.tsx").read_text(encoding="utf-8")

    assert "listStudents" in source
    assert "selectedStudentId" in source
    assert "<select" in source
    assert 'useState("student_1")' not in source
    assert "analyzeAnswerSheet(id!, selectedStudentId" in source
    assert "先在学生管理中新增学生" in source
