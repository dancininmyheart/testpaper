import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getStudentState,
  getStudentTimeline,
  listStudentProjects,
  rebuildStudentState,
  type StudentStateMasteryItem,
  type StudentTimelineItem,
} from "../api/students";
import Button from "../components/ui/Button";
import EmptyState from "../components/layout/EmptyState";

function percent(value?: number) {
  return `${Math.round((value || 0) * 100)}%`;
}

function signedPercent(value?: number) {
  const safeValue = value || 0;
  const sign = safeValue > 0 ? "+" : "";
  return `${sign}${Math.round(safeValue * 100)}%`;
}

function riskLabel(value?: string) {
  if (value === "high") return "高风险";
  if (value === "medium") return "需关注";
  if (value === "low") return "稳定";
  return "暂无数据";
}

function riskClass(value?: string) {
  if (value === "high") return "bg-red-50 text-red-700 border-red-200";
  if (value === "medium") return "bg-amber-50 text-amber-700 border-amber-200";
  if (value === "low") return "bg-emerald-50 text-emerald-700 border-emerald-200";
  return "bg-gray-50 text-[var(--color-text-muted)] border-[var(--color-border)]";
}

function dateText(value?: string) {
  return value ? value.slice(0, 10) : "暂无日期";
}

function skillName(item: StudentStateMasteryItem) {
  return item.name || item.skill_id;
}

function renderSkillRows(items: StudentStateMasteryItem[], tone: "weak" | "strong" | "neutral") {
  const color = tone === "weak" ? "text-danger" : tone === "strong" ? "text-emerald-600" : "text-primary";
  if (!items.length) {
    return <div className="text-xs text-[var(--color-text-muted)]">暂无</div>;
  }
  return items.map((item) => (
    <div key={item.skill_id} className="flex items-center justify-between gap-2 py-1 text-xs">
      <span className="truncate text-[var(--color-text)]">{skillName(item)}</span>
      <span className={color}>{percent(item.value)}</span>
    </div>
  ));
}

function TimelineNode({
  item,
  active,
  onSelect,
}: {
  item: StudentTimelineItem;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full text-left rounded-card border p-3 transition ${
        active ? "border-primary bg-primary/5" : "border-[var(--color-border)] bg-white hover:border-primary/40"
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-[var(--color-text)]">{item.title || item.project_id}</div>
          <div className="mt-0.5 text-xs text-[var(--color-text-muted)]">{dateText(item.reviewed_at)}</div>
        </div>
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] ${riskClass(item.summary.risk_level)}`}>
          {riskLabel(item.summary.risk_level)}
        </span>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div>
          <div className="text-[var(--color-text-muted)]">掌握度</div>
          <div className="font-semibold text-[var(--color-text)]">{percent(item.summary.overall_mastery)}</div>
        </div>
        <div>
          <div className="text-[var(--color-text-muted)]">素养</div>
          <div className="font-semibold text-[var(--color-text)]">{percent(item.summary.overall_literacy)}</div>
        </div>
        <div>
          <div className="text-[var(--color-text-muted)]">薄弱</div>
          <div className="font-semibold text-[var(--color-text)]">{item.summary.weak_skill_count}</div>
        </div>
      </div>
    </button>
  );
}

function TrendBars({ items, selectedId }: { items: StudentTimelineItem[]; selectedId?: string }) {
  if (!items.length) return null;
  return (
    <div className="rounded-card border border-[var(--color-border)] bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-semibold text-[var(--color-text)]">整体趋势</div>
        <div className="text-xs text-[var(--color-text-muted)]">按已确认考试时间排序</div>
      </div>
      <div className="flex h-28 items-end gap-2">
        {items.map((item) => {
          const height = Math.max(10, Math.round((item.summary.overall_mastery || 0) * 100));
          const active = selectedId === item.report_id;
          return (
            <div key={item.report_id} className="flex min-w-10 flex-1 flex-col items-center gap-1">
              <div
                className={`w-full rounded-t-sm ${active ? "bg-primary" : "bg-primary/30"}`}
                style={{ height: `${height}%` }}
              />
              <div className="w-full truncate text-center text-[10px] text-[var(--color-text-muted)]">
                {dateText(item.reviewed_at).slice(5)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TimelineDetail({ point, studentId }: { point?: StudentTimelineItem; studentId: string }) {
  if (!point) {
    return (
      <div className="rounded-card border border-[var(--color-border)] bg-white p-4">
        <EmptyState icon="📈" title="暂无时序画像" description="确认至少一次考试后会生成时间线" />
      </div>
    );
  }
  const weakQuestions = point.evidence?.weak_questions || [];
  return (
    <div className="rounded-card border border-[var(--color-border)] bg-white p-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-[var(--color-text)]">{point.title || point.project_id}</div>
          <div className="mt-1 text-xs text-[var(--color-text-muted)]">
            {point.subject || "科目未填"} · {point.grade || "年级未填"} · {dateText(point.reviewed_at)}
          </div>
        </div>
        <Link to={`/students/${encodeURIComponent(studentId)}/projects/${encodeURIComponent(point.project_id)}`}>
          <Button variant="secondary" size="sm">查看报告</Button>
        </Link>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <div className="rounded-btn bg-gray-50 px-3 py-2">
          <div className="text-xs text-[var(--color-text-muted)]">掌握度变化</div>
          <div className="mt-1 text-lg font-semibold text-[var(--color-text)]">{signedPercent(point.delta.overall_mastery)}</div>
        </div>
        <div className="rounded-btn bg-gray-50 px-3 py-2">
          <div className="text-xs text-[var(--color-text-muted)]">素养变化</div>
          <div className="mt-1 text-lg font-semibold text-[var(--color-text)]">{signedPercent(point.delta.overall_literacy)}</div>
        </div>
        <div className="rounded-btn bg-gray-50 px-3 py-2">
          <div className="text-xs text-[var(--color-text-muted)]">薄弱变化</div>
          <div className="mt-1 text-lg font-semibold text-[var(--color-text)]">{point.delta.weak_skill_count}</div>
        </div>
        <div className={`rounded-btn border px-3 py-2 ${riskClass(point.summary.risk_level)}`}>
          <div className="text-xs opacity-80">风险等级</div>
          <div className="mt-1 text-lg font-semibold">{riskLabel(point.summary.risk_level)}</div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <div>
          <div className="mb-2 text-xs font-semibold text-[var(--color-text-secondary)]">新增薄弱项</div>
          {renderSkillRows(point.new_weak_skills, "weak")}
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold text-[var(--color-text-secondary)]">已改善项</div>
          {renderSkillRows(point.improved_skills, "strong")}
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold text-[var(--color-text-secondary)]">当前薄弱项</div>
          {renderSkillRows(point.weak_skills, "weak")}
        </div>
      </div>

      <div className="mt-4">
        <div className="mb-2 text-xs font-semibold text-[var(--color-text-secondary)]">证据题目</div>
        {weakQuestions.length ? (
          <div className="space-y-2">
            {weakQuestions.slice(0, 5).map((item, index) => (
              <div key={index} className="rounded-btn bg-gray-50 px-3 py-2 text-xs text-[var(--color-text-secondary)]">
                题目 {String(item.question_id || index + 1)} · 相关技能 {Array.isArray(item.skills) ? item.skills.join(", ") : "暂无"}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-xs text-[var(--color-text-muted)]">暂无证据题目</div>
        )}
      </div>
    </div>
  );
}

export default function StudentDetailPage() {
  const { studentId } = useParams<{ studentId: string }>();
  const queryClient = useQueryClient();
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
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
  const { data: timeline, isLoading: isTimelineLoading } = useQuery({
    queryKey: ["student-timeline", studentId],
    queryFn: () => getStudentTimeline(studentId!, 12),
    enabled: !!studentId,
  });
  const rebuildMut = useMutation({
    mutationFn: () => rebuildStudentState(studentId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["student-state", studentId] });
      queryClient.invalidateQueries({ queryKey: ["student-timeline", studentId] });
    },
  });

  const timelineItems = timeline?.items || [];
  const selectedPoint = useMemo(() => {
    if (!timelineItems.length) return undefined;
    return timelineItems.find((item) => item.report_id === selectedReportId) || timelineItems[timelineItems.length - 1];
  }, [selectedReportId, timelineItems]);

  const summary = studentState?.summary;
  const weakMastery = (studentState?.mastery || []).filter((item) => item.value < 0.6).slice(0, 5);
  const strongMastery = (studentState?.mastery || []).filter((item) => item.value >= 0.8).slice(0, 5);
  const literacy = (studentState?.literacy || []).slice(0, 5);

  return (
    <div>
      <Link to="/students" className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]">返回学生管理</Link>
      <h1 className="mt-2 mb-6 text-lg font-bold text-[var(--color-text)]">{studentId} · 学生时序画像</h1>

      <section className="mb-5 rounded-card border border-[var(--color-border)] bg-white p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <div className="text-sm font-semibold text-[var(--color-text)]">最新学生状态</div>
            <div className="mt-1 text-xs text-[var(--color-text-muted)]">
              {summary?.exam_count ? `已纳入 ${summary.exam_count} 次已确认考试` : "老师确认评分后自动更新"}
              {studentState?.updated_at ? ` · ${studentState.updated_at.slice(0, 10)}` : ""}
            </div>
          </div>
          <Button variant="secondary" size="sm" onClick={() => rebuildMut.mutate()} disabled={rebuildMut.isPending || !studentId}>
            {rebuildMut.isPending ? "重建中..." : "重建状态"}
          </Button>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <div className="rounded-btn bg-gray-50 px-3 py-2">
            <div className="text-xs text-[var(--color-text-muted)]">综合掌握度</div>
            <div className="mt-1 text-lg font-semibold text-[var(--color-text)]">{percent(summary?.overall_mastery)}</div>
          </div>
          <div className="rounded-btn bg-gray-50 px-3 py-2">
            <div className="text-xs text-[var(--color-text-muted)]">数学素养</div>
            <div className="mt-1 text-lg font-semibold text-[var(--color-text)]">{percent(summary?.overall_literacy)}</div>
          </div>
          <div className="rounded-btn bg-gray-50 px-3 py-2">
            <div className="text-xs text-[var(--color-text-muted)]">风险等级</div>
            <div className="mt-1 text-lg font-semibold text-[var(--color-text)]">{riskLabel(summary?.risk_level)}</div>
          </div>
          <div className="rounded-btn bg-gray-50 px-3 py-2">
            <div className="text-xs text-[var(--color-text-muted)]">薄弱知识点</div>
            <div className="mt-1 text-lg font-semibold text-[var(--color-text)]">{summary?.weak_skill_count || 0}</div>
          </div>
        </div>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <div>
            <div className="mb-2 text-xs font-semibold text-[var(--color-text-secondary)]">薄弱知识点</div>
            {renderSkillRows(weakMastery, "weak")}
          </div>
          <div>
            <div className="mb-2 text-xs font-semibold text-[var(--color-text-secondary)]">优势知识点</div>
            {renderSkillRows(strongMastery, "strong")}
          </div>
          <div>
            <div className="mb-2 text-xs font-semibold text-[var(--color-text-secondary)]">数学素养</div>
            {literacy.length ? literacy.map((item) => (
              <div key={item.literacy_id} className="flex items-center justify-between gap-2 py-1 text-xs">
                <span className="truncate text-[var(--color-text)]">{item.name || item.literacy_id}</span>
                <span className="text-primary">{percent(item.value)}</span>
              </div>
            )) : <div className="text-xs text-[var(--color-text-muted)]">暂无</div>}
          </div>
        </div>
      </section>

      <section className="mb-5 grid gap-5 lg:grid-cols-[minmax(280px,360px)_1fr]">
        <div className="space-y-3">
          <TrendBars items={timelineItems} selectedId={selectedPoint?.report_id} />
          <div className="rounded-card border border-[var(--color-border)] bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="text-sm font-semibold text-[var(--color-text)]">考试时间线</div>
              <div className="text-xs text-[var(--color-text-muted)]">{timelineItems.length} 次</div>
            </div>
            {isTimelineLoading ? (
              <div className="text-sm text-[var(--color-text-muted)]">加载中...</div>
            ) : timelineItems.length ? (
              <div className="space-y-2">
                {timelineItems.map((item) => (
                  <TimelineNode
                    key={item.report_id}
                    item={item}
                    active={selectedPoint?.report_id === item.report_id}
                    onSelect={() => setSelectedReportId(item.report_id)}
                  />
                ))}
              </div>
            ) : (
              <EmptyState icon="📊" title="暂无时序画像" description="确认考试报告后会生成时间线" />
            )}
          </div>
        </div>
        <TimelineDetail point={selectedPoint} studentId={studentId || ""} />
      </section>

      <section>
        <div className="mb-3 text-sm font-semibold text-[var(--color-text)]">历史考试报告</div>
        {isLoading ? (
          <div className="text-sm text-[var(--color-text-muted)]">加载中...</div>
        ) : projects.length === 0 ? (
          <EmptyState icon="📋" title="暂无历史报告" description="该学生完成答题卡分析后会出现在这里" />
        ) : (
          <div className="space-y-3">
            {projects.map((project) => (
              <div key={project.project_id} className="flex items-center justify-between gap-3 rounded-card border border-[var(--color-border)] bg-white p-4">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-[var(--color-text)]">{project.title}</div>
                  <div className="mt-0.5 text-xs text-[var(--color-text-muted)]">
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
      </section>
    </div>
  );
}
