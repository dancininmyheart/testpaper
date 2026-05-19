import { normalizeAnalysisReport, type NormalizedAnalysisReport, type ReportMetric } from "./normalizeAnalysisReport";

interface ProjectMeta {
  title?: string;
  subject?: string;
  grade?: string;
}

interface Props {
  report?: Record<string, unknown> | null;
  project?: ProjectMeta | null;
  studentId?: string;
  mode?: "student" | "review";
}

const toneClasses: Record<NonNullable<ReportMetric["tone"]>, string> = {
  primary: "border-primary/20 bg-primary-light/60 text-primary",
  success: "border-emerald-200 bg-emerald-50 text-emerald-700",
  warning: "border-amber-200 bg-amber-50 text-amber-700",
  danger: "border-red-200 bg-red-50 text-red-700",
  muted: "border-[var(--color-border)] bg-gray-50 text-[var(--color-text-secondary)]",
};

function formatDate(value: string): string {
  if (!value) return "暂无数据";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white border border-[var(--color-border)] rounded-card p-5">
      <h2 className="text-sm font-semibold text-[var(--color-text)] mb-4">{title}</h2>
      {children}
    </section>
  );
}

function EmptyText({ children = "暂无数据" }: { children?: string }) {
  return <div className="text-sm text-[var(--color-text-muted)]">{children}</div>;
}

function MetricCard({ metric }: { metric: ReportMetric }) {
  return (
    <div className={`border rounded-card p-4 ${toneClasses[metric.tone || "muted"]}`}>
      <div className="text-xs font-medium opacity-80">{metric.label}</div>
      <div className="text-2xl font-bold mt-2 break-words">{metric.value}</div>
      {metric.helper && <div className="text-[11px] mt-2 opacity-80">{metric.helper}</div>}
    </div>
  );
}

function renderReportHeader(report: NormalizedAnalysisReport, project?: ProjectMeta | null, studentId?: string) {
  const resolvedStudentId = studentId || report.studentId;
  return (
    <div className="bg-white border border-[var(--color-border)] rounded-card p-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="text-xs font-medium text-primary mb-2">学习分析报告</div>
          <h1 className="text-xl font-bold text-[var(--color-text)] break-words">
            {project?.title || "学生项目报告"}
          </h1>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--color-text-secondary)]">
            <span>学生：{resolvedStudentId || "暂无数据"}</span>
            <span>学科：{project?.subject || "暂无数据"}</span>
            <span>年级：{project?.grade || "暂无数据"}</span>
          </div>
        </div>
        <div className="text-xs text-[var(--color-text-muted)] md:text-right">
          <div>生成时间</div>
          <div className="mt-1 text-[var(--color-text-secondary)]">{formatDate(report.generatedAt)}</div>
        </div>
      </div>
    </div>
  );
}

export default function ReportView({ report, project, studentId, mode = "student" }: Props) {
  const normalized = normalizeAnalysisReport(report || {});
  const topWeaknesses = normalized.weaknesses.slice(0, 4);
  const weakMastery = normalized.mastery
    .slice()
    .sort((a, b) => (a.value ?? 999) - (b.value ?? 999))
    .slice(0, 6);

  return (
    <div className="space-y-5">
      {renderReportHeader(normalized, project, studentId)}

      {mode === "review" && normalized.warnings.length > 0 && (
        <div className="border border-amber-200 bg-amber-50 rounded-card p-4 text-sm text-amber-800">
          本次分析有 {normalized.warnings.length} 条过程提醒，教师确认前建议查看“技术详情”。
        </div>
      )}

      <Section title="学习概览">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {normalized.metrics.map((metric) => <MetricCard key={metric.label} metric={metric} />)}
        </div>
        <div className="mt-4 rounded-card bg-gray-50 border border-[var(--color-border)] p-4">
          <div className="text-xs font-medium text-[var(--color-text-muted)] mb-2">总体结论</div>
          <p className="text-sm leading-6 text-[var(--color-text)] whitespace-pre-wrap">{normalized.summary}</p>
        </div>
      </Section>

      <Section title="学情画像">
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <div className="text-xs font-medium text-[var(--color-text-muted)] mb-3">掌握度较弱知识点</div>
            {weakMastery.length > 0 ? (
              <div className="space-y-3">
                {weakMastery.map((item) => (
                  <div key={item.skill} className="space-y-1.5">
                    <div className="flex items-center justify-between gap-3 text-xs">
                      <span className="font-medium text-[var(--color-text)] break-words">{item.skill}</span>
                      <span className="text-primary font-semibold">{item.label}</span>
                    </div>
                    <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
                      <div className="h-full rounded-full bg-primary" style={{ width: item.value == null ? "0%" : `${Math.min(100, Math.max(0, item.value <= 1 ? item.value * 100 : item.value))}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : <EmptyText />}
          </div>
          <div>
            <div className="text-xs font-medium text-[var(--color-text-muted)] mb-3">错因类型</div>
            {normalized.errorProfile.length > 0 ? (
              <div className="grid grid-cols-2 gap-2">
                {normalized.errorProfile.map((item) => (
                  <div key={item.label} className="rounded-card border border-[var(--color-border)] bg-gray-50 p-3">
                    <div className="text-[11px] text-[var(--color-text-muted)] break-words">{item.label}</div>
                    <div className="text-base font-semibold text-[var(--color-text)] mt-1">{item.value}</div>
                  </div>
                ))}
              </div>
            ) : <EmptyText />}
          </div>
        </div>
      </Section>

      <Section title="数学素养画像">
        {normalized.literacy.length > 0 ? (
          <div className="grid gap-3 md:grid-cols-2">
            {normalized.literacy.map((item) => (
              <div key={item.id} className="rounded-card border border-[var(--color-border)] bg-gray-50 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-[var(--color-text)]">{item.name}</div>
                    {item.definition && <div className="mt-1 text-xs leading-5 text-[var(--color-text-secondary)]">{item.definition}</div>}
                  </div>
                  <span className="shrink-0 rounded-pill bg-white px-2 py-1 text-[11px] font-medium text-primary border border-[var(--color-border)]">
                    {item.levelLabel}
                  </span>
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <div className="h-2 flex-1 rounded-full bg-white overflow-hidden border border-[var(--color-border)]">
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{ width: item.value == null ? "0%" : `${Math.min(100, Math.max(0, item.value * 100))}%` }}
                    />
                  </div>
                  <span className="w-12 text-right text-xs font-semibold text-primary">{item.label}</span>
                </div>
                {item.evidence.length > 0 && (
                  <div className="mt-3 text-xs text-[var(--color-text-secondary)]">
                    证据：{item.evidence.join("、")}
                  </div>
                )}
                {item.reason && (
                  <div className="mt-3 text-xs leading-5 text-[var(--color-text-secondary)]">
                    判断：{item.reason}
                  </div>
                )}
                {item.suggestion && (
                  <div className="mt-2 text-xs leading-5 text-[var(--color-text-secondary)]">
                    建议：{item.suggestion}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : <EmptyText>暂无数学素养画像数据。</EmptyText>}
      </Section>

      <Section title="错题与提升建议">
        {topWeaknesses.length > 0 ? (
          <div className="space-y-3">
            {topWeaknesses.map((item) => (
              <details key={`${item.skill}-${item.priority}`} className="group rounded-card border border-[var(--color-border)] bg-white p-4 open:bg-gray-50">
                <summary className="cursor-pointer list-none">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <div className="text-sm font-semibold text-[var(--color-text)]">{item.skill}</div>
                      <div className="text-xs text-[var(--color-text-secondary)] mt-1">{item.symptom}</div>
                    </div>
                    <span className="self-start rounded-pill bg-amber-50 px-2 py-1 text-[11px] font-medium text-amber-700">
                      {item.priority}
                    </span>
                  </div>
                </summary>
                <div className="mt-4 grid gap-3 text-sm text-[var(--color-text-secondary)] md:grid-cols-2">
                  <div>
                    <div className="text-xs font-medium text-[var(--color-text-muted)] mb-1">可能原因</div>
                    <p className="leading-6">{item.cause}</p>
                  </div>
                  <div>
                    <div className="text-xs font-medium text-[var(--color-text-muted)] mb-1">练习建议</div>
                    <p className="leading-6">{item.practicePlan || item.suggestion}</p>
                  </div>
                  {item.improvementSteps.length > 0 && (
                    <div className="md:col-span-2">
                      <div className="text-xs font-medium text-[var(--color-text-muted)] mb-1">改进步骤</div>
                      <ol className="list-decimal list-inside space-y-1">
                        {item.improvementSteps.map((step) => <li key={step}>{step}</li>)}
                      </ol>
                    </div>
                  )}
                </div>
              </details>
            ))}
          </div>
        ) : <EmptyText>暂未识别出明确薄弱点。</EmptyText>}
      </Section>

      <Section title="逐题明细">
        {normalized.questions.length > 0 ? (
          <div className="space-y-3">
            {normalized.questions.map((item) => (
              <details key={item.id} className="rounded-card border border-[var(--color-border)] bg-white p-4">
                <summary className="cursor-pointer list-none">
                  <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_96px_96px] md:items-center">
                    <div>
                      <div className="text-sm font-semibold text-[var(--color-text)]">{item.title}</div>
                      <div className="text-xs text-[var(--color-text-muted)] mt-1 truncate">{item.questionText}</div>
                      {item.knowledgePoints.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {item.knowledgePoints.map((point) => (
                            <span key={point} className="rounded-pill bg-primary-light px-2 py-0.5 text-[11px] font-medium text-primary">
                              {point}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="text-xs text-[var(--color-text-secondary)]">结果：{item.result}</div>
                    <div className="text-xs font-semibold text-primary">得分：{item.scoreText}</div>
                  </div>
                </summary>
                <div className="mt-4 grid gap-3 text-sm md:grid-cols-2">
                  <div className="rounded-card bg-gray-50 border border-[var(--color-border)] p-3 md:col-span-2">
                    <div className="text-xs font-medium text-[var(--color-text-muted)] mb-1">题干</div>
                    <div className="whitespace-pre-wrap leading-6 text-[var(--color-text)]">{item.questionText}</div>
                  </div>
                  {item.knowledgePoints.length > 0 && (
                    <div className="rounded-card bg-gray-50 border border-[var(--color-border)] p-3 md:col-span-2">
                      <div className="text-xs font-medium text-[var(--color-text-muted)] mb-2">知识点</div>
                      <div className="flex flex-wrap gap-1.5">
                        {item.knowledgePoints.map((point) => (
                          <span key={point} className="rounded-pill bg-white border border-[var(--color-border)] px-2 py-1 text-xs text-[var(--color-text-secondary)]">
                            {point}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="rounded-card bg-gray-50 border border-[var(--color-border)] p-3">
                    <div className="text-xs font-medium text-[var(--color-text-muted)] mb-1">学生作答</div>
                    <div className="whitespace-pre-wrap leading-6 text-[var(--color-text)]">{item.studentAnswer}</div>
                  </div>
                  <div className="rounded-card bg-gray-50 border border-[var(--color-border)] p-3">
                    <div className="text-xs font-medium text-[var(--color-text-muted)] mb-1">问题说明</div>
                    <div className="whitespace-pre-wrap leading-6 text-[var(--color-text)]">{item.issue}</div>
                  </div>
                  {item.suggestion !== "暂无数据" && (
                    <div className="rounded-card bg-gray-50 border border-[var(--color-border)] p-3 md:col-span-2">
                      <div className="text-xs font-medium text-[var(--color-text-muted)] mb-1">订正建议</div>
                      <div className="whitespace-pre-wrap leading-6 text-[var(--color-text)]">{item.suggestion}</div>
                    </div>
                  )}
                </div>
              </details>
            ))}
          </div>
        ) : <EmptyText>暂无逐题分析数据。</EmptyText>}
      </Section>

      <details className="bg-white border border-[var(--color-border)] rounded-card p-5">
        <summary className="cursor-pointer text-sm font-semibold text-[var(--color-text)]">技术详情</summary>
        <div className="mt-4 space-y-3">
          <div className="grid gap-2 text-xs text-[var(--color-text-secondary)] sm:grid-cols-3">
            <span>过程阶段：{normalized.stageCount || "暂无数据"}</span>
            <span>提醒数量：{normalized.warnings.length}</span>
            <span>题目明细：{normalized.questions.length}</span>
          </div>
          {normalized.warnings.length > 0 && (
            <div className="rounded-card bg-amber-50 border border-amber-200 p-3 text-xs text-amber-800">
              {normalized.warnings.map((warning) => <div key={warning}>{warning}</div>)}
            </div>
          )}
          <pre className="max-h-72 overflow-auto rounded-card bg-gray-950 p-4 text-xs text-gray-100">
            {JSON.stringify(normalized.raw, null, 2)}
          </pre>
        </div>
      </details>
    </div>
  );
}
