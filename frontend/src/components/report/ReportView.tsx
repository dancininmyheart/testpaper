import { normalizeAnalysisReport, type NormalizedAnalysisReport } from "./normalizeAnalysisReport";
import MathText from "../MathText";
import {
  User,
  BookOpen,
  GraduationCap,
  Calendar,
  AlertTriangle,
  TrendingUp,
  BarChart2,
  Brain,
  Sparkles,
  ChevronDown,
  CheckCircle,
  XCircle,
  AlertCircle,
  BookOpenCheck,
  Zap,
  Check,
  Info
} from "lucide-react";

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

function formatDate(value: string): string {
  if (!value) return "暂无数据";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

function Section({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="bg-white border border-slate-200/80 rounded-2xl p-5 md:p-6 shadow-[0_2px_12px_rgba(0,0,0,0.015)] transition-all duration-300 hover:shadow-premium">
      <div className="flex items-center gap-2 mb-5 border-b border-slate-50 pb-3">
        {icon && <div className="text-primary">{icon}</div>}
        <h2 className="text-sm font-bold text-slate-800 tracking-tight">{title}</h2>
      </div>
      {children}
    </section>
  );
}

function EmptyText({ children = "暂无数据" }: { children?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-8 text-slate-400 space-y-1">
      <Info className="w-5 h-5 opacity-40" />
      <span className="text-xs font-medium">{children}</span>
    </div>
  );
}

function renderReportHeader(report: NormalizedAnalysisReport, project?: ProjectMeta | null, studentId?: string) {
  const resolvedStudentId = studentId || report.studentId;
  return (
    <div className="bg-gradient-to-br from-white via-slate-50/30 to-slate-50/70 border border-slate-200/80 rounded-2xl p-6 shadow-[0_2px_12px_rgba(0,0,0,0.015)] relative overflow-hidden">
      <div className="absolute top-0 right-0 w-48 h-48 bg-primary/5 rounded-full blur-3xl pointer-events-none"></div>
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between relative z-10">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-1 bg-primary/10 text-primary text-[10px] font-bold px-2 py-0.5 rounded-full tracking-wider uppercase">
            <BookOpenCheck className="w-3 h-3" /> 学情分析报告
          </div>
          <h1 className="text-lg md:text-xl font-bold text-slate-800 break-words tracking-tight leading-snug">
            {project?.title || "学生项目报告"}
          </h1>
          <div className="pt-1 flex flex-wrap gap-x-4 gap-y-2 text-xs">
            <span className="inline-flex items-center gap-1 text-slate-600 bg-white border border-slate-100 px-2.5 py-1 rounded-lg">
              <User className="w-3.5 h-3.5 text-slate-400" />
              <span>学生：<span className="font-semibold text-slate-800">{resolvedStudentId || "暂无数据"}</span></span>
            </span>
            <span className="inline-flex items-center gap-1 text-slate-600 bg-white border border-slate-100 px-2.5 py-1 rounded-lg">
              <BookOpen className="w-3.5 h-3.5 text-slate-400" />
              <span>学科：<span className="font-semibold text-slate-800">{project?.subject || "暂无数据"}</span></span>
            </span>
            <span className="inline-flex items-center gap-1 text-slate-600 bg-white border border-slate-100 px-2.5 py-1 rounded-lg">
              <GraduationCap className="w-3.5 h-3.5 text-slate-400" />
              <span>年级：<span className="font-semibold text-slate-800">{project?.grade || "暂无数据"}</span></span>
            </span>
          </div>
        </div>
        <div className="text-xs text-[var(--color-text-muted)] md:text-right bg-white/60 backdrop-blur-sm border border-slate-100 px-3.5 py-2.5 rounded-xl self-start md:self-auto flex md:flex-col items-center md:items-end justify-between md:justify-start gap-4 md:gap-1.5 min-w-[150px]">
          <div className="flex items-center gap-1 text-slate-400">
            <Calendar className="w-3.5 h-3.5" />
            <span>生成时间</span>
          </div>
          <div className="font-medium text-slate-700 tracking-tight">{formatDate(report.generatedAt)}</div>
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
    <div className="space-y-6">
      {renderReportHeader(normalized, project, studentId)}

      {mode === "review" && normalized.warnings.length > 0 && (
        <div className="border border-amber-200/80 bg-gradient-to-r from-amber-50 to-orange-50/30 rounded-xl p-4 text-xs text-amber-800 flex items-start gap-2 shadow-sm">
          <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
          <div>
            本次分析包含 <span className="font-bold">{normalized.warnings.length}</span> 条识别过程提醒。在教师确认归档前，建议点击底部“技术详情”进行评估。
          </div>
        </div>
      )}

      <Section title="学习概览" icon={<BarChart2 className="w-4.5 h-4.5" />}>
        <div className="grid gap-3 sm:grid-cols-3 mb-4">
          {normalized.metrics.map((metric) => (
            <div
              key={metric.label}
              className={`rounded-xl border p-4 ${
                metric.tone === "primary" ? "border-primary/20 bg-primary/5" :
                metric.tone === "success" ? "border-emerald-200 bg-emerald-50/50" :
                metric.tone === "warning" ? "border-amber-200 bg-amber-50/50" :
                metric.tone === "danger" ? "border-red-200 bg-red-50/50" :
                "border-slate-200 bg-slate-50/50"
              }`}
            >
              <div className="text-[11px] font-bold text-slate-400 mb-1.5 tracking-wider">{metric.label}</div>
              <div className={`text-xl font-bold ${
                metric.tone === "warning" ? "text-amber-700" :
                metric.tone === "success" ? "text-emerald-700" :
                metric.tone === "danger" ? "text-red-700" :
                "text-primary"
              }`}>{metric.value}</div>
              {metric.helper && <div className="text-[10px] text-slate-400 mt-1">{metric.helper}</div>}
            </div>
          ))}
        </div>
        <div className="rounded-xl bg-gradient-to-r from-slate-50 to-white border border-slate-100 p-4 shadow-inner relative overflow-hidden">
          <div className="absolute top-0 right-0 w-24 h-24 bg-primary/5 rounded-full blur-2xl pointer-events-none"></div>
          <div className="text-xs font-bold text-slate-500 mb-2 tracking-wider flex items-center gap-1">
            <Brain className="w-3.5 h-3.5 text-primary" />
            <span>总体结论</span>
          </div>
          <p className="text-xs leading-6 text-slate-700 whitespace-pre-wrap">
            <MathText text={normalized.summary} />
          </p>
        </div>
      </Section>

      <Section title="学情画像" icon={<TrendingUp className="w-4.5 h-4.5" />}>
        <div className="space-y-6">
          <div>
            <div className="text-xs font-bold text-slate-500 mb-3 tracking-wider">掌握度较弱知识点</div>
            {weakMastery.length > 0 ? (
              <div className="space-y-3">
                {weakMastery.map((item) => (
                  <div key={item.skill} className="space-y-1.5">
                    <div className="flex items-center justify-between gap-3 text-xs">
                      <span className="font-semibold text-slate-700 break-words">{item.skill}</span>
                      <span className="text-primary font-bold font-mono">{item.label}</span>
                    </div>
                    <div className="h-2 rounded-full bg-slate-100 overflow-hidden shadow-inner">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-primary to-indigo-500"
                        style={{ width: item.value == null ? "0%" : `${Math.min(100, Math.max(0, item.value <= 1 ? item.value * 100 : item.value))}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            ) : <EmptyText>暂无掌握度数据</EmptyText>}
          </div>
          <div>
            <div className="text-xs font-bold text-slate-500 mb-3 tracking-wider">错因类型统计</div>
          {normalized.errorProfile.length > 0 ? (
            <div className="grid grid-cols-2 gap-3">
              {normalized.errorProfile.map((item) => (
                <div key={item.label} className="rounded-xl border border-slate-100 bg-slate-50/40 p-4 hover:shadow-sm transition-all">
                  <div className="text-[11px] font-semibold text-slate-400 break-words">{item.label}</div>
                  <div className="text-lg font-bold text-slate-800 mt-1">{item.value}</div>
                </div>
              ))}
            </div>
          ) : <EmptyText>暂无错因类型统计</EmptyText>}
          </div>
        </div>
      </Section>

      <Section title="数学素养画像" icon={<Brain className="w-4.5 h-4.5" />}>
        {normalized.literacy.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2">
            {normalized.literacy.map((item) => (
              <div key={item.id} className="rounded-xl border border-slate-100 bg-slate-50/30 p-5 hover:bg-slate-50/60 transition-all flex flex-col justify-between">
                <div className="space-y-1.5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="text-sm font-bold text-slate-800">{item.name}</div>
                    <span className="shrink-0 rounded-full bg-white px-2.5 py-0.5 text-[10px] font-bold text-primary border border-primary/20 shadow-sm">
                      {item.levelLabel}
                    </span>
                  </div>
                  {item.definition && (
                    <p className="text-[11px] leading-relaxed text-slate-500">
                      <MathText text={item.definition} />
                    </p>
                  )}
                </div>
                
                <div className="mt-4 pt-2 border-t border-slate-100/50">
                  <div className="flex items-center gap-3">
                    <div className="h-2 flex-1 rounded-full bg-slate-100 overflow-hidden relative shadow-inner">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-primary to-indigo-500"
                        style={{ width: item.value == null ? "0%" : `${Math.min(100, Math.max(0, item.value * 100))}%` }}
                      />
                    </div>
                    <span className="w-10 text-right text-xs font-bold text-primary font-mono">{item.label}</span>
                  </div>
                  
                  {item.evidence.length > 0 && (
                    <div className="mt-3 text-[11px] text-slate-600 bg-white/70 px-2.5 py-1.5 rounded-lg border border-slate-100 flex items-start gap-1">
                      <span className="text-primary font-bold">•</span>
                      <span><strong className="text-slate-500 font-semibold">分析证据：</strong><MathText text={item.evidence.join("、")} /></span>
                    </div>
                  )}
                  {item.reason && (
                    <div className="mt-2 text-[11px] text-slate-500 leading-normal pl-2 border-l-2 border-slate-200">
                      <strong>评定机制：</strong><MathText text={item.reason} />
                    </div>
                  )}
                  {item.suggestion && (
                    <div className="mt-2 text-[11px] text-indigo-700 bg-indigo-50/30 px-2.5 py-1.5 rounded-lg border border-indigo-100/50 leading-relaxed flex items-start gap-1">
                      <Sparkles className="w-3 h-3 text-indigo-500 shrink-0 mt-0.5" />
                      <span><strong>素养建议：</strong><MathText text={item.suggestion} /></span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : <EmptyText>暂无数学素养画像数据。</EmptyText>}
      </Section>

      <Section title="错题与提升建议" icon={<Sparkles className="w-4.5 h-4.5" />}>
        {topWeaknesses.length > 0 ? (
          <div className="space-y-3">
            {topWeaknesses.map((item) => (
              <details key={`${item.skill}-${item.priority}`} className="group rounded-xl border border-slate-200/80 bg-white hover:border-slate-300 transition-all overflow-hidden [&_summary::-webkit-details-marker]:hidden [&_summary]:list-none">
                <summary className="cursor-pointer p-4 select-none flex items-center justify-between gap-4 hover:bg-slate-50/50 transition-colors">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-bold text-slate-800">{item.skill}</div>
                    <div className="text-[11px] text-[var(--color-text-muted)] mt-1 truncate">
                      <MathText text={item.symptom} inline />
                    </div>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-[10px] font-bold text-amber-700 border border-amber-200/40">
                      {item.priority}
                    </span>
                    <ChevronDown className="w-4 h-4 text-slate-400 group-open:rotate-180 transition-transform duration-300" />
                  </div>
                </summary>
                <div className="px-4 pb-5 border-t border-slate-100 bg-slate-50/30 grid gap-4 text-xs text-slate-600 md:grid-cols-2 pt-4">
                  <div className="bg-white border border-slate-100 p-4 rounded-xl shadow-[0_2px_6px_rgba(0,0,0,0.01)]">
                    <div className="text-[10px] font-bold text-slate-400 mb-1.5 uppercase tracking-wider flex items-center gap-1">
                      <AlertCircle className="w-3.5 h-3.5 text-rose-500" /> 可能原因
                    </div>
                    <p className="leading-relaxed text-slate-700">
                      <MathText text={item.cause} />
                    </p>
                  </div>
                  <div className="bg-white border border-slate-100 p-4 rounded-xl shadow-[0_2px_6px_rgba(0,0,0,0.01)]">
                    <div className="text-[10px] font-bold text-slate-400 mb-1.5 uppercase tracking-wider flex items-center gap-1">
                      <Zap className="w-3.5 h-3.5 text-amber-500" /> 练习建议
                    </div>
                    <p className="leading-relaxed text-slate-700">
                      <MathText text={item.practicePlan || item.suggestion} />
                    </p>
                  </div>
                  {item.improvementSteps.length > 0 && (
                    <div className="md:col-span-2 bg-gradient-to-br from-indigo-50/20 to-purple-50/20 border border-indigo-50 p-4 rounded-xl">
                      <div className="text-[10px] font-bold text-indigo-700 mb-2 uppercase tracking-wider flex items-center gap-1">
                        <Check className="w-3.5 h-3.5 text-indigo-500" /> 改进步骤
                      </div>
                      <ol className="space-y-2 list-none pl-1">
                        {item.improvementSteps.map((step, i) => (
                          <li key={step} className="flex items-start gap-2 text-slate-700">
                            <span className="flex items-center justify-center w-4.5 h-4.5 rounded-full bg-indigo-100 text-[10px] text-indigo-700 font-bold font-mono shrink-0 mt-0.5">
                              {i + 1}
                            </span>
                            <span className="leading-normal">
                              <MathText text={step} />
                            </span>
                          </li>
                        ))}
                      </ol>
                    </div>
                  )}
                </div>
              </details>
            ))}
          </div>
        ) : <EmptyText>暂未识别出明确薄弱点。</EmptyText>}
      </Section>

      <Section title="逐题明细" icon={<BookOpenCheck className="w-4.5 h-4.5" />}>
        {normalized.questions.length > 0 ? (
          <div className="space-y-3">
            {normalized.questions.map((item) => {
              const isCorrect = item.result === "正确" || item.result.includes("对") || item.result.toLowerCase() === "correct";
              const isPartiallyCorrect = item.result === "部分正确" || item.result.includes("部分");
              return (
                <details key={item.id} className="group rounded-xl border border-slate-200/80 bg-white hover:border-slate-300 transition-all overflow-hidden [&_summary::-webkit-details-marker]:hidden [&_summary]:list-none">
                  <summary className="cursor-pointer p-4 select-none flex items-center justify-between gap-4 hover:bg-slate-50/50 transition-colors">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold text-slate-800">{item.title}</span>
                        {isCorrect ? (
                          <span className="inline-flex items-center gap-0.5 bg-emerald-50 text-emerald-700 text-[10px] font-bold px-2 py-0.5 rounded-full border border-emerald-200/30">
                            <CheckCircle className="w-3 h-3" /> 正确
                          </span>
                        ) : isPartiallyCorrect ? (
                          <span className="inline-flex items-center gap-0.5 bg-amber-50 text-amber-700 text-[10px] font-bold px-2 py-0.5 rounded-full border border-amber-200/30">
                            <AlertCircle className="w-3 h-3" /> 部分正确
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-0.5 bg-rose-50 text-rose-700 text-[10px] font-bold px-2 py-0.5 rounded-full border border-rose-200/30">
                            <XCircle className="w-3 h-3" /> 错误
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-[var(--color-text-muted)] mt-1 truncate">
                        <MathText text={item.questionText} inline />
                      </div>
                      {item.knowledgePoints.length > 0 && (
                        <div className="mt-2.5 flex flex-wrap gap-1">
                          {item.knowledgePoints.map((point) => (
                            <span key={point} className="rounded-full bg-slate-100 border border-slate-200/50 px-2.5 py-0.5 text-[9px] font-bold text-slate-600">
                              {point}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <ChevronDown className="w-4 h-4 text-slate-400 group-open:rotate-180 transition-transform duration-300" />
                  </summary>
                  <div className="px-4 pb-5 border-t border-slate-100 bg-slate-50/30 space-y-4 pt-4 text-xs">
                    <div className="rounded-xl bg-white border border-slate-100 p-4 shadow-[0_2px_6px_rgba(0,0,0,0.01)]">
                      <div className="text-[10px] font-bold text-slate-400 mb-1.5 tracking-wider uppercase">题干内容</div>
                      <div className="whitespace-pre-wrap leading-relaxed text-slate-700 font-medium">
                        <MathText text={item.questionText} />
                      </div>
                    </div>

                    {item.knowledgePoints.length > 0 && (
                      <div className="rounded-xl bg-white border border-slate-100 p-4 shadow-[0_2px_6px_rgba(0,0,0,0.01)]">
                        <div className="text-[10px] font-bold text-slate-400 mb-2 tracking-wider uppercase">关联知识点</div>
                        <div className="flex flex-wrap gap-1.5">
                          {item.knowledgePoints.map((point) => (
                            <span key={point} className="rounded-full bg-slate-100 border border-slate-200/50 px-2.5 py-1 text-[11px] font-semibold text-slate-700">
                              {point}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="rounded-xl bg-white border border-slate-100 p-4 shadow-[0_2px_6px_rgba(0,0,0,0.01)] flex flex-col justify-between">
                        <div>
                          <div className="text-[10px] font-bold text-slate-400 mb-2 tracking-wider uppercase">学生作答</div>
                          <div className="whitespace-pre-wrap leading-relaxed text-slate-700 font-medium bg-slate-50/50 p-2.5 rounded-lg border border-slate-100/50">
                            <MathText text={item.studentAnswer || "无"} />
                          </div>
                        </div>
                      </div>
                      <div className="rounded-xl bg-white border border-slate-100 p-4 shadow-[0_2px_6px_rgba(0,0,0,0.01)] flex flex-col justify-between">
                        <div>
                          <div className="text-[10px] font-bold text-slate-400 mb-2 tracking-wider uppercase">AI 错因分析</div>
                          <div className="space-y-2">
                            {item.errorType && (
                              <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                                item.errorType === "concept" ? "bg-violet-50 text-violet-700 border-violet-200/40" :
                                item.errorType === "calculation" ? "bg-orange-50 text-orange-700 border-orange-200/40" :
                                item.errorType === "reading" ? "bg-sky-50 text-sky-700 border-sky-200/40" :
                                item.errorType === "strategy" ? "bg-rose-50 text-rose-700 border-rose-200/40" :
                                "bg-slate-50 text-slate-600 border-slate-200/40"
                              }`}>
                                {item.errorType === "concept" && "概念错误"}
                                {item.errorType === "calculation" && "计算错误"}
                                {item.errorType === "reading" && "审题错误"}
                                {item.errorType === "strategy" && "策略错误"}
                                {item.errorType === "unknown" && "未知错误"}
                                {!["concept", "calculation", "reading", "strategy", "unknown"].includes(item.errorType) && item.errorType}
                              </span>
                            )}
                            <div className="whitespace-pre-wrap leading-relaxed text-slate-700 font-medium bg-slate-50/50 p-2.5 rounded-lg border border-slate-100/50">
                              <MathText text={item.issue || "暂无数据"} />
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                    {item.suggestion !== "暂无数据" && (
                      <div className="rounded-xl bg-gradient-to-br from-primary/5 to-indigo-50/30 border border-primary/10 p-4">
                        <div className="text-[10px] font-bold text-primary mb-1.5 tracking-wider uppercase flex items-center gap-1">
                          <Sparkles className="w-3.5 h-3.5 text-primary" /> 订正与提升建议
                        </div>
                        <div className="whitespace-pre-wrap leading-relaxed text-slate-700 font-semibold">
                          <MathText text={item.suggestion} />
                        </div>
                      </div>
                    )}
                  </div>
                </details>
              );
            })}
          </div>
        ) : <EmptyText>暂无逐题分析数据。</EmptyText>}
      </Section>

      <details className="group bg-white border border-slate-200/80 rounded-xl overflow-hidden shadow-[0_2px_12px_rgba(0,0,0,0.01)] [&_summary::-webkit-details-marker]:hidden [&_summary]:list-none">
        <summary className="cursor-pointer p-4 font-bold text-slate-700 select-none flex items-center justify-between hover:bg-slate-50/50 transition-colors">
          <span className="text-xs font-bold uppercase tracking-wider flex items-center gap-1.5">
            <Zap className="w-4 h-4 text-slate-400" /> 技术详情 (数据源)
          </span>
          <ChevronDown className="w-4 h-4 text-slate-400 group-open:rotate-180 transition-transform duration-300" />
        </summary>
        <div className="p-4 border-t border-slate-100 bg-slate-50/30 space-y-3 text-xs">
          <div className="grid gap-2 text-slate-600 sm:grid-cols-3">
            <span className="bg-white px-3 py-1.5 rounded-lg border border-slate-100">过程阶段：<span className="font-semibold text-slate-800">{normalized.stageCount || "0"}</span></span>
            <span className="bg-white px-3 py-1.5 rounded-lg border border-slate-100">提醒数量：<span className="font-semibold text-slate-800">{normalized.warnings.length}</span></span>
            <span className="bg-white px-3 py-1.5 rounded-lg border border-slate-100">题目明细：<span className="font-semibold text-slate-800">{normalized.questions.length}</span></span>
          </div>
          {normalized.warnings.length > 0 && (
            <div className="rounded-xl bg-amber-50 border border-amber-200/40 p-3.5 text-xs text-amber-800 space-y-1">
              {normalized.warnings.map((warning, idx) => (
                <div key={warning} className="flex items-start gap-1.5">
                  <span className="font-bold text-amber-600">{idx + 1}.</span>
                  <span>{warning}</span>
                </div>
              ))}
            </div>
          )}
          <pre className="max-h-72 overflow-auto rounded-xl bg-slate-900 p-4 text-[10px] text-slate-300 font-mono border border-slate-800 leading-normal">
            {JSON.stringify(normalized.raw, null, 2)}
          </pre>
        </div>
      </details>
    </div>
  );
}
