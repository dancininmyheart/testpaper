import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getStudentState, listStudentProjects, rebuildStudentState } from "../api/students";
import Button from "../components/ui/Button";
import EmptyState from "../components/layout/EmptyState";

function percent(value?: number) {
  return `${Math.round((value || 0) * 100)}%`;
}

function riskLabel(value?: string) {
  if (value === "high") return "高风险";
  if (value === "medium") return "需关注";
  if (value === "low") return "稳定";
  return "暂无数据";
}

export default function StudentDetailPage() {
  const { studentId } = useParams<{ studentId: string }>();
  const queryClient = useQueryClient();
  const { data: projects = [], isLoading } = useQuery({
    queryKey: ["student-projects", studentId],
    queryFn: () => listStudentProjects(studentId!),
    enabled: !!studentId,
  });
  const { data: studentState } = useQuery({
    queryKey: ["student-state", studentId],
    queryFn: () => getStudentState(studentId!),
    enabled: !!studentId,
  });
  const rebuildMut = useMutation({
    mutationFn: () => rebuildStudentState(studentId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["student-state", studentId] });
    },
  });

  const summary = studentState?.summary;
  const weakMastery = (studentState?.mastery || []).filter((item) => item.value < 0.6).slice(0, 5);
  const strongMastery = (studentState?.mastery || []).filter((item) => item.value >= 0.8).slice(0, 5);
  const literacy = (studentState?.literacy || []).slice(0, 5);

  return (
    <div>
      <Link to="/students" className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]">返回学生管理</Link>
      <h1 className="text-lg font-bold text-[var(--color-text)] mt-2 mb-6">{studentId} · 历史分析报告</h1>

      <section className="bg-white border border-[var(--color-border)] rounded-card p-4 mb-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <div className="text-sm font-semibold text-[var(--color-text)]">最新学生状态</div>
            <div className="text-xs text-[var(--color-text-muted)] mt-1">
              {summary?.exam_count ? `已纳入 ${summary.exam_count} 次已确认考试` : "老师确认评分后自动更新"}
              {studentState?.updated_at ? ` · ${studentState.updated_at.slice(0, 10)}` : ""}
            </div>
          </div>
          <Button variant="secondary" size="sm" onClick={() => rebuildMut.mutate()} disabled={rebuildMut.isPending || !studentId}>
            {rebuildMut.isPending ? "重建中..." : "重建状态"}
          </Button>
        </div>
        <div className="grid gap-3 md:grid-cols-4 mt-4">
          <div className="rounded-btn bg-gray-50 px-3 py-2">
            <div className="text-xs text-[var(--color-text-muted)]">综合掌握度</div>
            <div className="text-lg font-semibold text-[var(--color-text)] mt-1">{percent(summary?.overall_mastery)}</div>
          </div>
          <div className="rounded-btn bg-gray-50 px-3 py-2">
            <div className="text-xs text-[var(--color-text-muted)]">数学素养</div>
            <div className="text-lg font-semibold text-[var(--color-text)] mt-1">{percent(summary?.overall_literacy)}</div>
          </div>
          <div className="rounded-btn bg-gray-50 px-3 py-2">
            <div className="text-xs text-[var(--color-text-muted)]">风险等级</div>
            <div className="text-lg font-semibold text-[var(--color-text)] mt-1">{riskLabel(summary?.risk_level)}</div>
          </div>
          <div className="rounded-btn bg-gray-50 px-3 py-2">
            <div className="text-xs text-[var(--color-text-muted)]">薄弱知识点</div>
            <div className="text-lg font-semibold text-[var(--color-text)] mt-1">{summary?.weak_skill_count || 0}</div>
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-3 mt-4">
          <div>
            <div className="text-xs font-semibold text-[var(--color-text-secondary)] mb-2">薄弱知识点</div>
            {weakMastery.length ? weakMastery.map((item) => (
              <div key={item.skill_id} className="flex items-center justify-between gap-2 py-1 text-xs">
                <span className="truncate text-[var(--color-text)]">{item.name || item.skill_id}</span>
                <span className="text-danger">{percent(item.value)}</span>
              </div>
            )) : <div className="text-xs text-[var(--color-text-muted)]">暂无</div>}
          </div>
          <div>
            <div className="text-xs font-semibold text-[var(--color-text-secondary)] mb-2">优势知识点</div>
            {strongMastery.length ? strongMastery.map((item) => (
              <div key={item.skill_id} className="flex items-center justify-between gap-2 py-1 text-xs">
                <span className="truncate text-[var(--color-text)]">{item.name || item.skill_id}</span>
                <span className="text-emerald-600">{percent(item.value)}</span>
              </div>
            )) : <div className="text-xs text-[var(--color-text-muted)]">暂无</div>}
          </div>
          <div>
            <div className="text-xs font-semibold text-[var(--color-text-secondary)] mb-2">数学素养</div>
            {literacy.length ? literacy.map((item) => (
              <div key={item.literacy_id} className="flex items-center justify-between gap-2 py-1 text-xs">
                <span className="truncate text-[var(--color-text)]">{item.name || item.literacy_id}</span>
                <span className="text-primary">{percent(item.value)}</span>
              </div>
            )) : <div className="text-xs text-[var(--color-text-muted)]">暂无</div>}
          </div>
        </div>
      </section>

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
