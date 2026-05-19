import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getProject, getProjectReport } from "../api/projects";
import ReportView from "../components/report/ReportView";

export default function ProjectReportPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: report, isLoading } = useQuery({
    queryKey: ["project-report", projectId],
    queryFn: () => getProjectReport(projectId!),
    enabled: !!projectId,
  });
  const { data: project } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId!),
    enabled: !!projectId,
  });

  return (
    <div className="max-w-5xl mx-auto">
      <Link to="/reports" className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]">← 返回报告中心</Link>
      <h1 className="text-lg font-bold text-[var(--color-text)] mt-2 mb-6">项目报告</h1>
      {isLoading ? (
        <div className="text-sm text-[var(--color-text-muted)]">加载中...</div>
      ) : (
        <ReportView report={report} project={project} mode="student" />
      )}
    </div>
  );
}
