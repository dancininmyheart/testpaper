import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listProjects } from "../api/projects";
import Button from "../components/ui/Button";

export default function Dashboard() {
  const { data: projects = [], isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
  });

  const completed = projects.filter((p) => p.status === "completed").length;
  const inProgress = projects.filter((p) => p.status !== "completed" && p.status !== "draft").length;
  const tasks = 0; // placeholder until task API is available

  if (isLoading) {
    return <div className="flex items-center justify-center py-20"><div className="text-sm text-[var(--color-text-muted)]">加载中...</div></div>;
  }

  return (
    <div>
      <h1 className="text-lg font-bold text-[var(--color-text)] mb-6">工作台</h1>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        {[
          { label: "项目总数", value: projects.length, color: "text-primary" },
          { label: "进行中", value: inProgress, color: "text-amber-500" },
          { label: "已完成", value: completed, color: "text-emerald-500" },
          { label: "分析任务", value: tasks, color: "text-violet-500" },
        ].map((s) => (
          <div key={s.label} className="bg-white border border-[var(--color-border)] rounded-card p-4">
            <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
            <div className="text-xs text-[var(--color-text-muted)] mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-[var(--color-text)]">最近项目</h2>
            <Link to="/projects" className="text-xs text-primary hover:underline">查看全部</Link>
          </div>
          <div className="space-y-2">
            {projects.slice(0, 5).map((p) => (
              <Link key={p.project_id} to={`/projects/${p.project_id}`}
                className="block bg-white border border-[var(--color-border)] rounded-card p-4 hover:shadow-sm hover:border-primary/30 transition-all">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-[var(--color-text)]">{p.title}</div>
                    <div className="text-xs text-[var(--color-text-muted)] mt-0.5">
                      {p.subject} · {p.grade}
                    </div>
                  </div>
                  <span className={`inline-block px-2.5 py-0.5 text-[10px] font-medium rounded-pill ${
                    p.status === "completed" ? "bg-emerald-50 text-emerald-600" :
                    p.status === "draft" ? "bg-gray-100 text-gray-400" :
                    "bg-primary-light text-primary"
                  }`}>
                    {p.status === "completed" ? "已完成" : p.status === "draft" ? "草稿" : "进行中"}
                  </span>
                </div>
              </Link>
            ))}
            {projects.length === 0 && (
              <div className="text-center py-8 text-sm text-[var(--color-text-muted)]">暂无项目</div>
            )}
          </div>
        </div>

        <div>
          <h2 className="text-sm font-semibold text-[var(--color-text)] mb-3">快速操作</h2>
          <div className="space-y-2">
            <Link to="/projects/new">
              <Button className="w-full justify-center" variant="primary">+ 新建项目</Button>
            </Link>
            <Link to="/reports">
              <Button className="w-full justify-center" variant="secondary">📋 查看报告</Button>
            </Link>
            <Link to="/mastery">
              <Button className="w-full justify-center" variant="secondary">📈 学情追踪</Button>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
