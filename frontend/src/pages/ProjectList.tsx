import { Link, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listProjects, deleteProject } from "../api/projects";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import EmptyState from "../components/layout/EmptyState";

const STATUS_MAP: Record<string, { label: string; color: "green" | "purple" | "gray" | "yellow" }> = {
  draft: { label: "草稿", color: "gray" },
  extracting: { label: "提取中", color: "purple" },
  review_questions: { label: "待审查", color: "yellow" },
  generating_answers: { label: "生成答案中", color: "purple" },
  review_answers: { label: "审查答案", color: "yellow" },
  ready: { label: "就绪", color: "purple" },
  completed: { label: "已完成", color: "green" },
};

export default function ProjectList() {
  const { data: projects = [], isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
  });
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const deleteMut = useMutation({
    mutationFn: deleteProject,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["projects"] }),
  });

  if (isLoading) {
    return <div className="flex items-center justify-center py-20"><div className="text-sm text-[var(--color-text-muted)]">加载中...</div></div>;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-bold text-[var(--color-text)]">项目</h1>
        <Link to="/projects/new">
          <Button variant="primary">+ 新建项目</Button>
        </Link>
      </div>

      {projects.length === 0 ? (
        <EmptyState icon="📁" title="暂无项目" description="创建第一个项目，开始分析试卷" action={<Link to="/projects/new"><Button variant="primary">+ 新建项目</Button></Link>} />
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {projects.map((p) => {
            const st = STATUS_MAP[p.status] || { label: p.status, color: "gray" as const };
            return (
              <div key={p.project_id} className="block bg-white border border-[var(--color-border)] rounded-card p-5 hover:shadow-sm hover:border-primary/30 transition-all">
                <div className="flex items-start justify-between mb-3">
                  <Link to={`/projects/${p.project_id}`} className="font-semibold text-sm text-[var(--color-text)] hover:text-primary">{p.title}</Link>
                  <Badge color={st.color}>{st.label}</Badge>
                </div>
                <div className="flex items-center gap-4 text-xs text-[var(--color-text-muted)]">
                  <span>{p.subject || "未设置学科"}</span>
                  <span>{p.grade || "未设置年级"}</span>
                  {p.question_count > 0 && <span>{p.question_count} 题</span>}
                  {p.student_count > 0 && <span>{p.student_count} 名学生</span>}
                </div>
                <div className="flex justify-between items-center mt-3 pt-3 border-t border-[var(--color-border)]">
                  <span className="text-[10px] text-[var(--color-text-muted)]">{p.created_at?.slice(0, 10)}</span>
                  <button onClick={(e) => { e.preventDefault(); if (confirm("确认删除此项目？")) deleteMut.mutate(p.project_id); }}
                    className="text-[10px] text-danger hover:underline">删除</button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
