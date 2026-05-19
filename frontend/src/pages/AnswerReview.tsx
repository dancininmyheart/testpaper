import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getProject, getProjectReview, generateReferenceAnswers, approveReferenceAnswers, type ModelProfiles } from "../api/projects";
import Button from "../components/ui/Button";

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
    return <div className="flex items-center justify-center py-20"><div className="text-sm text-[var(--color-text-muted)]">加载中...</div></div>;
  }

  return (
    <div className="max-w-3xl mx-auto">
      <Link to={`/projects/${id}`} className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]">← 返回项目</Link>
      <h1 className="text-lg font-bold text-[var(--color-text)] mt-2 mb-6">审查参考答案</h1>
      <div className="mb-4 flex flex-col gap-2 rounded-card border border-[var(--color-border)] bg-white p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-xs text-[var(--color-text-muted)]">
          模型模式：{selectedModelMode === "fast" ? "快速模式" : "标准模式"}
        </div>
        <div className="inline-flex w-fit rounded-btn border border-[var(--color-border)] bg-gray-50 p-1">
          <button
            type="button"
            onClick={() => setSelectedModelMode("fast")}
            className={`px-3 py-1.5 text-xs font-medium rounded-btn ${selectedModelMode === "fast" ? "bg-white text-primary shadow-sm" : "text-[var(--color-text-secondary)]"}`}
          >
            快速模式
          </button>
          <button
            type="button"
            onClick={() => setSelectedModelMode("standard")}
            className={`px-3 py-1.5 text-xs font-medium rounded-btn ${selectedModelMode === "standard" ? "bg-white text-primary shadow-sm" : "text-[var(--color-text-secondary)]"}`}
          >
            标准模式
          </button>
        </div>
      </div>
      {questions.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-sm text-[var(--color-text-muted)] mb-4">尚未生成参考答案</p>
          {canGenerateReferenceAnswers && (
            <Button variant="primary" onClick={() => genMut.mutate()} disabled={genMut.isPending}>
              {genMut.isPending ? "生成中..." : "🤖 生成参考答案"}
            </Button>
          )}
        </div>
      ) : (
        <>
          <div className="space-y-3 mb-6">
            {questions.map((q) => {
              const ref = q.reference_answer as Record<string, unknown> | undefined;
              const analysis = typeof ref?.analysis === "string" ? ref.analysis.trim() : "";
              const steps = Array.isArray(ref?.steps) ? (ref.steps as string[]).filter((s: string) => s.trim()) : [];
              const finalAnswer = typeof ref?.final_answer === "string" ? ref.final_answer.trim() : "";
              const answerText = typeof ref?.answer_text === "string" ? ref.answer_text.trim() : "";
              const hasStructured = analysis || steps.length > 0 || finalAnswer;
              return (
                <div key={q.question_id as string} className="bg-white border border-[var(--color-border)] rounded-card p-4">
                  <div className="text-sm font-medium text-[var(--color-text)] mb-2">Q{q.question_no as string}. {(q.content as string || "").slice(0, 60)}...</div>
                  <div className="bg-gray-50 rounded-btn p-3 text-xs text-[var(--color-text-secondary)]">
                    <span className="font-medium">参考答案：</span>
                    {ref ? (
                      hasStructured ? (
                        <div className="mt-1.5 space-y-1.5">
                          {analysis && (
                            <div>
                              <span className="text-[var(--color-text-muted)]">分析：</span>
                              <span className="text-[var(--color-text)]">{analysis.slice(0, 120)}{analysis.length > 120 ? "..." : ""}</span>
                            </div>
                          )}
                          {steps.length > 0 && (
                            <div>
                              <span className="text-[var(--color-text-muted)]">步骤：</span>
                              <ol className="mt-1 space-y-1 list-decimal list-inside text-[var(--color-text)]">
                                {steps.map((step, i) => (
                                  <li key={i} className="whitespace-pre-wrap leading-relaxed">{step}</li>
                                ))}
                              </ol>
                            </div>
                          )}
                          {finalAnswer && (
                            <div>
                              <span className="text-[var(--color-text-muted)]">答案：</span>
                              <span className="text-[var(--color-text)] font-bold">{finalAnswer}</span>
                            </div>
                          )}
                        </div>
                      ) : (
                        <span>{answerText || "无"}</span>
                      )
                    ) : "尚未生成"}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="flex justify-end gap-2">
            {canGenerateReferenceAnswers && (
              <Button variant="secondary" onClick={() => genMut.mutate()} disabled={genMut.isPending}>🔄 重新生成</Button>
            )}
            {canApproveReferenceAnswers && (
              <Button variant="primary" onClick={() => approveMut.mutate()} disabled={approveMut.isPending}>
                {approveMut.isPending ? "确认中..." : "✓ 全部确认"}
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
