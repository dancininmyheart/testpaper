import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getStudentProjectReport } from "../api/students";
import { getProject } from "../api/projects";
import ReportView from "../components/report/ReportView";

export default function StudentProjectReportPage() {
  const { studentId, projectId } = useParams<{ studentId: string; projectId: string }>();
  const { data: report, isLoading } = useQuery({
    queryKey: ["student-project-report", studentId, projectId],
    queryFn: () => getStudentProjectReport(studentId!, projectId!),
    enabled: !!studentId && !!projectId,
  });
  const { data: project } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId!),
    enabled: !!projectId,
  });

  return (
    <div className="max-w-5xl mx-auto">
      <Link to={`/students/${encodeURIComponent(studentId || "")}`} className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]">← 返回历史分析报告</Link>
      <h1 className="text-lg font-bold text-[var(--color-text)] mt-2 mb-6">学生项目报告</h1>
      {isLoading ? (
        <div className="text-sm text-[var(--color-text-muted)]">加载中...</div>
      ) : (
        <ReportView report={report} project={project} studentId={studentId} mode="student" />
      )}
    </div>
  );
}
