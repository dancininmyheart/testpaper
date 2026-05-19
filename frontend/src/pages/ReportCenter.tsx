import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listProjects } from "../api/projects";
import Button from "../components/ui/Button";
import EmptyState from "../components/layout/EmptyState";

export default function ReportCenter() {
  const { data: projects = [] } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const completed = projects.filter((p) => p.status === "completed");

  return (
    <div>
      <h1 className="text-lg font-bold text-[var(--color-text)] mb-6">报告中心</h1>
      {completed.length === 0 ? (
        <EmptyState icon="📋" title="暂无报告" description="完成项目评分后将自动生成报告" />
      ) : (
        <div className="space-y-3">
          {completed.map((p) => (
            <div key={p.project_id} className="bg-white border border-[var(--color-border)] rounded-card p-4 flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-[var(--color-text)]">{p.title}</div>
                <div className="text-xs text-[var(--color-text-muted)] mt-0.5">
                  {p.subject || "未填写学科"} · {p.grade || "未填写年级"} · {p.question_count} 题 · {p.student_count} 名学生
                </div>
              </div>
              <div className="flex gap-2">
                <Link to={`/reports/${encodeURIComponent(p.project_id)}`}>
                  <Button variant="secondary" size="sm">查看报告</Button>
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
