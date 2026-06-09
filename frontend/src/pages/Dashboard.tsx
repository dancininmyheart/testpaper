import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { FolderKanban, CheckCircle2, RefreshCw, BarChart3, Plus, ArrowRight } from "lucide-react";
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
    return (
      <div className="flex items-center justify-center py-32">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 rounded-full border-4 border-indigo-100 border-t-primary animate-spin" />
          <span className="text-sm text-slate-400 font-medium">加载中...</span>
        </div>
      </div>
    );
  }

  const stats = [
    { label: "项目总数", value: projects.length, icon: FolderKanban, color: "text-primary", bg: "bg-indigo-50/50 border-indigo-100/50" },
    { label: "进行中", value: inProgress, icon: RefreshCw, color: "text-amber-500", bg: "bg-amber-50/50 border-amber-100/50" },
    { label: "已完成", value: completed, icon: CheckCircle2, color: "text-emerald-500", bg: "bg-emerald-50/50 border-emerald-100/50" },
    { label: "分析任务", value: tasks, icon: BarChart3, color: "text-violet-500", bg: "bg-violet-50/50 border-violet-100/50" },
  ];

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-extrabold text-slate-800 tracking-tight">工作台</h1>
        <p className="text-sm text-slate-500 mt-1">欢迎回来，以下是您近期的试卷分析学情概览。</p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        {stats.map((s) => {
          const Icon = s.icon;
          return (
            <div
              key={s.label}
              className={`bg-white border rounded-card p-6 shadow-premium hover:shadow-cardHover hover:-translate-y-0.5 transition-all duration-300 ${s.bg}`}
            >
              <div className="flex items-center justify-between">
                <div className={`text-3xl font-extrabold font-mono tracking-tight ${s.color}`}>{s.value}</div>
                <div className={`p-2 rounded-xl bg-white shadow-sm border border-slate-100 ${s.color}`}>
                  <Icon className="w-5 h-5" />
                </div>
              </div>
              <div className="text-xs font-bold text-slate-400 mt-3 uppercase tracking-wider">{s.label}</div>
            </div>
          );
        })}
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Recent Projects */}
        <div className="lg:col-span-2 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-extrabold text-slate-800 tracking-tight">最近项目</h2>
            <Link to="/projects" className="text-xs font-bold text-primary hover:text-indigo-700 inline-flex items-center gap-1 group">
              查看全部 <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
            </Link>
          </div>
          <div className="space-y-3">
            {projects.slice(0, 5).map((p) => (
              <Link
                key={p.project_id}
                to={`/projects/${p.project_id}`}
                className="block bg-white border border-slate-100 rounded-card p-5 hover:shadow-cardHover hover:border-primary/20 transition-all duration-300"
              >
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <div className="text-sm font-bold text-slate-800 hover:text-primary transition-colors truncate">{p.title}</div>
                    <div className="flex items-center gap-2 mt-1.5 text-xs text-slate-400 font-semibold">
                      <span>{p.subject}</span>
                      <span>·</span>
                      <span>{p.grade}</span>
                      {p.created_at && (
                        <>
                          <span>·</span>
                          <span>{p.created_at.slice(0, 10)}</span>
                        </>
                      )}
                    </div>
                  </div>
                  <span
                    className={`inline-flex px-3 py-1 text-xs font-bold rounded-pill border ${
                      p.status === "completed"
                        ? "bg-emerald-50 text-emerald-600 border-emerald-100"
                        : p.status === "draft"
                        ? "bg-slate-100 text-slate-400 border-slate-200"
                        : "bg-indigo-50 text-primary border-indigo-100"
                    }`}
                  >
                    {p.status === "completed" ? "已完成" : p.status === "draft" ? "草稿" : "进行中"}
                  </span>
                </div>
              </Link>
            ))}
            {projects.length === 0 && (
              <div className="bg-white border border-dashed border-slate-200 rounded-card py-16 text-center text-sm text-slate-400">
                暂无项目，点击右侧“新建项目”开始吧！
              </div>
            )}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="space-y-4">
          <h2 className="text-base font-extrabold text-slate-800 tracking-tight">快速操作</h2>
          <div className="bg-white border border-slate-100 rounded-card p-5 shadow-premium space-y-3">
            <Link to="/projects/new" className="block">
              <Button className="w-full justify-center py-2.5 shadow-md shadow-indigo-100 hover:shadow-lg" variant="primary">
                <Plus className="w-4 h-4 mr-1" /> 新建项目
              </Button>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
