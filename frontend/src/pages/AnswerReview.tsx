import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getProject, getProjectReview, generateReferenceAnswers, approveReferenceAnswers, type ModelProfiles } from "../api/projects";
import Button from "../components/ui/Button";
import MathText from "../components/MathText";
import { ArrowLeft, Brain, Cpu, Check, Play, RefreshCw, Loader2, Sparkles, HelpCircle, Award } from "lucide-react";

type ModelMode = "fast" | "standard";

const MODEL_PROFILE_MODES: Record<ModelMode, ModelProfiles> = {
  fast: {
    visionProfile: "openai_vision_gemini_3_flash",
    textProfile: "openai_text_gemini_3_flash",
  },
  standard: {
    visionProfile: "openai_vision_gemini_3_1_pro",
    textProfile: "openai_text_gemini_3_1_pro",
  },
};

const REFERENCE_STATUS_LABELS: Record<string, string> = {
  uploaded: "上传答案提取",
  generated_fallback: "AI 补齐",
  generated: "AI 生成",
  missing: "未提取",
};

const REFERENCE_STATUS_STYLES: Record<string, string> = {
  uploaded: "bg-emerald-50 text-emerald-700 border-emerald-100",
  generated_fallback: "bg-amber-50 text-amber-700 border-amber-100",
  generated: "bg-indigo-50 text-indigo-700 border-indigo-100",
  missing: "bg-slate-50 text-slate-500 border-slate-200",
};

export default function AnswerReview() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [selectedModelMode, setSelectedModelMode] = useState<ModelMode>("standard");
  const selectedProfiles = MODEL_PROFILE_MODES[selectedModelMode];

  const { data: project } = useQuery({
    queryKey: ["project", id],
    queryFn: () => getProject(id!),
    enabled: !!id,
  });

  const { data: review, isLoading } = useQuery({
    queryKey: ["review", id],
    queryFn: () => getProjectReview(id!),
    enabled: !!id,
  });

  const genMut = useMutation({
    mutationFn: () => generateReferenceAnswers(id!, selectedProfiles),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["project", id] }),
  });

  const approveMut = useMutation({
    mutationFn: () => approveReferenceAnswers(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", id] });
      queryClient.invalidateQueries({ queryKey: ["review", id] });
    },
  });

  const questions = (review?.questions || []) as Array<Record<string, unknown>>;
  const canGenerateReferenceAnswers = project?.status === "ready" || project?.status === "review_answers";
  const canApproveReferenceAnswers = project?.status === "review_answers";

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
        <div className="text-sm text-[var(--color-text-muted)] font-medium">参考答案数据载入中...</div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-6">
      {/* 头部导航与标题 */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <Link to={`/projects/${id}`} className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-700 shadow-sm transition-colors hover:border-primary/30 hover:bg-primary/5 hover:text-primary mb-3">
            <ArrowLeft className="w-4 h-4" /> 返回项目
          </Link>
          <div className="flex items-center gap-2.5">
            <div className="w-10 h-10 rounded-2xl bg-indigo-500/10 flex items-center justify-center text-primary shadow-sm">
              <Brain className="w-5.5 h-5.5" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-800 tracking-tight">审查参考答案</h1>
              <p className="text-xs text-[var(--color-text-muted)] mt-0.5">大模型基于 OCR 提取的试题内容智能生成标准答案</p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {canGenerateReferenceAnswers && (
            <Button
              variant="secondary"
              onClick={() => genMut.mutate()}
              disabled={genMut.isPending}
              className="rounded-xl py-2.5 flex items-center gap-1.5 border-slate-200 text-slate-700 hover:text-slate-900 bg-white"
            >
              {genMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
              <span>{questions.length === 0 ? "智能解答" : "重新生成"}</span>
            </Button>
          )}
          
          {canApproveReferenceAnswers && questions.length > 0 && (
            <Button
              variant="primary"
              onClick={() => approveMut.mutate()}
              disabled={approveMut.isPending}
              className="shadow-premium px-6 py-2.5 rounded-xl flex items-center gap-1.5"
            >
              {approveMut.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>提交确认中...</span>
                </>
              ) : (
                <>
                  <Check className="w-4 h-4" />
                  <span>全部确认无误</span>
                </>
              )}
            </Button>
          )}
        </div>
      </div>

      {/* 模型参数配置 */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-4 shadow-[0_2px_12px_rgba(0,0,0,0.015)] flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-primary" />
          <span className="text-xs font-semibold text-slate-700">解答大模型配置</span>
          <span className="text-[10px] bg-slate-100 text-slate-500 px-2 py-0.5 rounded font-mono">
            {selectedModelMode === "fast" ? "Gemini 3 Flash" : "Gemini 3.1 Pro"}
          </span>
        </div>
        <div className="inline-flex rounded-xl border border-slate-100 bg-slate-50/50 p-1 self-start sm:self-auto shadow-inner">
          <button
            type="button"
            onClick={() => setSelectedModelMode("fast")}
            className={`px-4 py-1.5 text-xs font-bold rounded-lg transition-all ${
              selectedModelMode === "fast"
                ? "bg-white text-primary shadow-sm"
                : "text-slate-500 hover:text-slate-800"
            }`}
          >
            快速模式 (Flash)
          </button>
          <button
            type="button"
            onClick={() => setSelectedModelMode("standard")}
            className={`px-4 py-1.5 text-xs font-bold rounded-lg transition-all ${
              selectedModelMode === "standard"
                ? "bg-white text-primary shadow-sm"
                : "text-slate-500 hover:text-slate-800"
            }`}
          >
            标准模式 (Pro)
          </button>
        </div>
      </div>

      {/* 问题展示区 */}
      {questions.length === 0 ? (
        <div className="text-center py-24 bg-white rounded-3xl border border-slate-200/80 shadow-sm flex flex-col items-center justify-center space-y-4">
          <Brain className="w-16 h-16 text-indigo-100 stroke-[1.5]" />
          <div className="space-y-1">
            <p className="text-sm font-bold text-slate-700">尚未生成参考答案</p>
            <p className="text-xs text-[var(--color-text-muted)]">点击右上角“智能解答”按钮以调用大模型生成结构化答案与步骤</p>
          </div>
          {canGenerateReferenceAnswers && (
            <Button
              variant="primary"
              onClick={() => genMut.mutate()}
              disabled={genMut.isPending}
              className="shadow-premium px-6 py-2.5 rounded-xl flex items-center gap-1.5"
            >
              {genMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              <span>开始智能解答</span>
            </Button>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          {questions.map((q) => {
            const ref = q.reference_answer as Record<string, unknown> | undefined;
            const analysis = typeof ref?.analysis === "string" ? ref.analysis.trim() : "";
            const steps = Array.isArray(ref?.steps) ? (ref.steps as string[]).filter((s: string) => s.trim()) : [];
            const finalAnswer = typeof ref?.final_answer === "string" ? ref.final_answer.trim() : "";
            const answerText = typeof ref?.answer_text === "string" ? ref.answer_text.trim() : "";
            const hasStructured = analysis || steps.length > 0 || finalAnswer;
            const referenceStatus = typeof q.reference_answer_status === "string" ? q.reference_answer_status : (ref ? "unknown" : "missing");
            const referenceWarning = typeof q.reference_answer_warning === "string" ? q.reference_answer_warning.trim() : "";
            
            return (
              <div
                key={q.question_id as string}
                className="bg-white border border-slate-200/80 rounded-2xl p-5 shadow-[0_2px_12px_rgba(0,0,0,0.015)] space-y-4 hover:shadow-premium transition-all duration-300"
              >
                {/* 题干展示 (支持 LaTeX) */}
                <div className="text-xs font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5 border-b border-slate-50 pb-2.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0"></span>
                  <span>Q{q.question_no as string} 题干内容</span>
                </div>
                <div className="text-sm font-semibold text-slate-800 leading-relaxed bg-slate-50/40 px-4 py-3 rounded-xl border border-slate-100/50">
                  <MathText text={q.content as string || ""} />
                </div>

                {/* 答案卡片 (支持 LaTeX) */}
                <div className="space-y-3 pt-2">
                  <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1">
                    <Sparkles className="w-3.5 h-3.5 text-primary" />
                    <span>大模型结构化答案</span>
                    <span
                      title={referenceWarning || undefined}
                      className={`ml-auto border rounded-full px-2 py-0.5 text-[10px] font-bold ${
                        REFERENCE_STATUS_STYLES[referenceStatus] || "bg-slate-50 text-slate-500 border-slate-200"
                      }`}
                    >
                      {REFERENCE_STATUS_LABELS[referenceStatus] || referenceStatus}
                    </span>
                  </div>
                  
                  {ref ? (
                    hasStructured ? (
                      <div className="grid gap-3">
                        {/* 解题分析 */}
                        {analysis && (
                          <div className="bg-gradient-to-br from-blue-50/40 to-indigo-50/20 border border-blue-100/40 rounded-xl p-4 shadow-[0_2px_6px_rgba(59,130,246,0.01)]">
                            <div className="flex items-center gap-1.5 text-blue-700 font-bold text-xs mb-1.5">
                              <Sparkles className="w-3.5 h-3.5 text-blue-500" />
                              <span>解题分析</span>
                            </div>
                            <div className="text-xs text-slate-700 leading-relaxed pl-5">
                              <MathText text={analysis} />
                            </div>
                          </div>
                        )}

                        {/* 解题步骤 */}
                        {steps.length > 0 && (
                          <div className="bg-gradient-to-br from-purple-50/40 to-pink-50/20 border border-purple-100/40 rounded-xl p-4 shadow-[0_2px_6px_rgba(147,51,234,0.01)]">
                            <div className="flex items-center gap-1.5 text-purple-700 font-bold text-xs mb-2">
                              <HelpCircle className="w-3.5 h-3.5 text-purple-500" />
                              <span>解答步骤</span>
                            </div>
                            <ol className="text-xs text-slate-700 space-y-2.5 list-none pl-5">
                              {steps.map((step, i) => (
                                  <li key={i} className="relative leading-relaxed pl-5">
                                    <span className="absolute left-0 top-[2px] flex items-center justify-center w-4.5 h-4.5 rounded-full bg-purple-100 text-[9px] text-purple-700 font-bold font-mono">
                                      {i + 1}
                                    </span>
                                    <MathText text={step} />
                                  </li>
                              ))}
                            </ol>
                          </div>
                        )}

                        {/* 最终答案 */}
                        {finalAnswer && (
                          <div className="bg-gradient-to-br from-emerald-50/50 to-teal-50/20 border border-emerald-100/60 rounded-xl p-4 shadow-[0_2px_8px_rgba(16,185,129,0.02)]">
                            <div className="flex items-center gap-1.5 text-emerald-800 font-bold text-xs mb-2">
                              <Award className="w-3.5 h-3.5 text-emerald-600" />
                              <span>最终答案</span>
                            </div>
                            <div className="text-xs font-semibold text-emerald-900 bg-white border border-emerald-100 rounded-lg px-3 py-2 pl-4 shadow-sm inline-block min-w-[120px]">
                              <MathText text={finalAnswer} />
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="bg-slate-50 border border-slate-200/60 rounded-xl p-4 text-xs text-slate-700 leading-relaxed pl-4 font-medium">
                        <MathText text={answerText || "无"} />
                      </div>
                    )
                  ) : (
                    <div className="text-xs text-slate-400 font-medium pl-2 italic">答案待生成...</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
