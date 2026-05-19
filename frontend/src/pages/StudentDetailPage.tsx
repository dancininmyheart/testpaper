import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listStudentProjects } from "../api/students";
import Button from "../components/ui/Button";
import EmptyState from "../components/layout/EmptyState";

export default function StudentDetailPage() {
  const { studentId } = useParams<{ studentId: string }>();
  const { data: projects = [], isLoading } = useQuery({
    queryKey: ["student-projects", studentId],
    queryFn: () => listStudentProjects(studentId!),
    enabled: !!studentId,
  });

  return (
    <div>
      <Link to="/students" className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]">← 返回学生管理</Link>
      <h1 className="text-lg font-bold text-[var(--color-text)] mt-2 mb-6">{studentId} · 历史分析报告</h1>
      {isLoading ? (
        <div className="text-sm text-[var(--color-text-muted)]">加载中...</div>
      ) : projects.length === 0 ? (
        <EmptyState icon="📋" title="暂无历史报告" description="该学生完成答题卡分析后会出现在这里" />
      ) : (
        <div className="space-y-3">
          {projects.map((project) => (
            <div key={project.project_id} className="bg-white border border-[var(--color-border)] rounded-card p-4 flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-[var(--color-text)]">{project.title}</div>
                <div className="text-xs text-[var(--color-text-muted)] mt-0.5">
                  {project.subject} · {project.grade} · {project.question_count} 题 · {project.analyzed_at?.slice(0, 10)}
                </div>
              </div>
              <Link to={`/students/${encodeURIComponent(studentId!)}/projects/${encodeURIComponent(project.project_id)}`}>
                <Button variant="secondary" size="sm">查看报告</Button>
              </Link>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
