import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getProject, getProjectReview, getMineruReview, approveQuestions, getProjectFileBlob } from "../api/projects";
import Button from "../components/ui/Button";
import Badge from "../components/ui/Badge";
import MathText from "../components/MathText";

function ProjectFileImage({
  projectId,
  fileId,
  alt,
  className,
}: {
  projectId: string;
  fileId: number | null | undefined;
  alt: string;
  className: string;
}) {
  const { data: blob, isLoading } = useQuery({
    queryKey: ["project-file-blob", projectId, fileId],
    queryFn: () => getProjectFileBlob(projectId, fileId as number),
    enabled: Number.isInteger(fileId),
    staleTime: 10 * 60 * 1000,
  });
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!blob) {
      setObjectUrl(null);
      return;
    }
    const url = URL.createObjectURL(blob);
    setObjectUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [blob]);

  if (!fileId) return null;
  if (isLoading || !objectUrl) {
    return <div className="text-xs text-[var(--color-text-muted)]">加载图片中...</div>;
  }
  return <img src={objectUrl} alt={alt} className={className} />;
}

function dedupeImages(images: Array<Record<string, unknown>>): Array<Record<string, unknown>> {
  const seen = new Set<string>();
  return images.filter((image) => {
    const key = typeof image.id === "number"
      ? `id:${image.id}`
      : `name:${String(image.file_name ?? "")}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function cleanContent(raw: string): string {
  // Images are rendered in the matched-image panel, so keep the text area text-only.
  return raw
    .replace(/!\[[^\]]*]\([^)]+\)/g, "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export default function QuestionReview() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  const { data: project } = useQuery({
    queryKey: ["project", id],
    queryFn: () => getProject(id!),
    enabled: !!id,
  });

  // Try mineru artifacts first (clean UTF-8 JSON from disk), fallback to legacy DB
  const { data: mineruReview, isLoading: mineruLoading, isError: mineruError } = useQuery({
    queryKey: ["mineru-review", id],
    queryFn: () => getMineruReview(id!),
    enabled: !!id,
    retry: false,
  });

  const { data: legacyReview, isLoading: legacyLoading } = useQuery({
    queryKey: ["review", id],
    queryFn: () => getProjectReview(id!),
    enabled: !!id && !!mineruError,
  });

  const review = mineruReview || legacyReview;
  const isLoading = mineruLoading || (legacyLoading && !mineruReview);
  const isMineru = !!mineruReview;

  const approveMut = useMutation({
    mutationFn: (questions?: unknown[]) => approveQuestions(id!, questions),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["project", id] }),
  });

  const fetchedQuestions = (review?.questions || []) as Array<Record<string, unknown>>;
  const [draftQuestions, setDraftQuestions] = useState<Array<Record<string, unknown>>>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [isEditingContent, setIsEditingContent] = useState(false);
  useEffect(() => {
    setDraftQuestions(fetchedQuestions.map((question) => ({
      ...question,
      content: String(question.content || ""),
    })));
    setSelectedIdx(0);
    setIsEditingContent(false);
  }, [review]);

  const questions = draftQuestions.length > 0 ? draftQuestions : fetchedQuestions;
  const current = questions[selectedIdx] as Record<string, unknown> | undefined;
  const pageFileId = typeof current?.paper_page_file_id === "number" ? current.paper_page_file_id : null;
  const matchedImages = Array.isArray(current?.images)
    ? dedupeImages(current.images as Array<Record<string, unknown>>)
    : [];
  const currentContent = String(current?.content || "");
  const isQuestionReviewEditable = project?.status === "review_questions";

  function updateQuestionContent(value: string) {
    setDraftQuestions((items) => items.map((item, index) => (
      index === selectedIdx ? { ...item, content: value } : item
    )));
  }

  if (isLoading) {
    return <div className="flex items-center justify-center py-20"><div className="text-sm text-[var(--color-text-muted)]">加载中...</div></div>;
  }

  return (
    <div className="flex gap-0 h-[calc(100vh-100px)] -mx-6">
      <div className="w-56 flex-shrink-0 border-r border-[var(--color-border)] overflow-auto bg-white">
        <div className="p-3 border-b border-[var(--color-border)] sticky top-0 bg-white z-10">
          <Link to={`/projects/${id}`} className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]">← 返回项目</Link>
          <h2 className="text-sm font-bold text-[var(--color-text)] mt-1">试题审查</h2>
          <p className="text-[10px] text-[var(--color-text-muted)]">{questions.length} 道题</p>
        </div>
        <div className="p-2">
          {questions.map((q, i) => (
            <button key={q.question_id as string} onClick={() => setSelectedIdx(i)}
              className={`w-full text-left px-3 py-2 rounded-btn text-xs mb-1 transition-colors ${
                i === selectedIdx ? "bg-primary-light text-primary font-medium" : "text-[var(--color-text-secondary)] hover:bg-gray-50"
              }`}>
              <span className="text-[var(--color-text-muted)] font-mono text-[11px]">Q{String(q.question_no)}</span>
              <span className="ml-1 truncate inline-block max-w-[140px] align-bottom">{(q.content as string || "").split("\n")[0].slice(0, 18)}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 border-r border-[var(--color-border)] bg-gray-100 flex items-center justify-center p-4 overflow-auto">
        {pageFileId ? (
          <div className="relative">
            <ProjectFileImage
              projectId={id!}
              fileId={pageFileId}
              alt="试卷页"
              className="max-w-full max-h-[calc(100vh-180px)] rounded-lg shadow-md"
            />
            <div className="absolute bottom-2 right-2 bg-black/50 text-white text-[10px] px-2 py-0.5 rounded-pill">第 {(current?.page_index as number ?? 0) + 1} 页</div>
          </div>
        ) : <div className="text-sm text-[var(--color-text-muted)]">暂无试卷图片</div>}
      </div>

      <div className="w-[clamp(320px,38vw,520px)] min-w-0 flex-shrink-0 overflow-auto bg-white p-5">
        {current ? (
          <div className="min-w-0 max-w-full">
            <div className="flex items-center gap-2 mb-4">
              <span className="text-sm font-bold text-[var(--color-text)]">第 {current.question_no as string} 题</span>
              <Badge color="purple">{(current.question_type as string) || "未知"}</Badge>
              {current.max_score != null && <span className="text-xs text-[var(--color-text-muted)]">{current.max_score as number} 分</span>}
            </div>

            <div className="mb-5 min-w-0 max-w-full">
              <div className="mb-2 flex items-center justify-between gap-2">
                <label className="block text-xs font-medium text-[var(--color-text-secondary)]">题目内容</label>
                {isQuestionReviewEditable && (
                  <button
                    type="button"
                    onClick={() => setIsEditingContent((value) => !value)}
                    className="text-xs font-medium text-primary hover:underline"
                  >
                    {isEditingContent ? "预览公式" : "编辑题目"}
                  </button>
                )}
              </div>
              {isQuestionReviewEditable && isEditingContent && (
                <textarea
                  value={currentContent}
                  onChange={(event) => updateQuestionContent(event.target.value)}
                  className="mb-2 w-full min-h-[140px] resize-y rounded-btn border border-primary/40 bg-white px-3 py-2.5 text-sm leading-relaxed outline-none focus:border-primary focus:ring-1 focus:ring-primary/20"
                />
              )}
              <div className="w-full min-w-0 max-w-full min-h-[80px] px-3 py-2.5 border border-[var(--color-border)] rounded-btn text-sm whitespace-pre-wrap break-words [overflow-wrap:anywhere] bg-gray-50">
                <MathText text={isMineru ? cleanContent(currentContent) : currentContent} />
              </div>
            </div>

            {matchedImages.length > 0 && (
              <div className="mb-5 min-w-0 max-w-full">
                <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-2">🖼 题目配图</label>
                <div className="min-w-0 max-w-full overflow-hidden rounded-btn border border-[var(--color-border)] bg-gray-50 p-3">
                  <div className="flex max-w-full flex-wrap gap-3">
                    {matchedImages.map((image, i) => (
                      <ProjectFileImage
                        key={`${image.id ?? i}`}
                        projectId={id!}
                        fileId={typeof image.id === "number" ? image.id : null}
                        alt={`配图${i + 1}`}
                        className="h-[140px] w-[min(220px,100%)] max-w-full object-contain rounded-btn border border-[var(--color-border)] bg-white"
                      />
                    ))}
                  </div>
                </div>
              </div>
            )}

            {current.reference_answer != null && (
              (() => {
                const ref = current.reference_answer as Record<string, unknown>;
                const analysis = typeof ref.analysis === "string" ? ref.analysis.trim() : "";
                const steps = Array.isArray(ref.steps) ? (ref.steps as string[]).filter((s: string) => s.trim()) : [];
                const finalAnswer = typeof ref.final_answer === "string" ? ref.final_answer.trim() : "";
                const answerText = typeof ref.answer_text === "string" ? ref.answer_text.trim() : "";
                const hasStructured = analysis || steps.length > 0 || finalAnswer;
                return (
                  <div className="mb-5 p-4 bg-gray-50 rounded-card border border-[var(--color-border)]">
                    <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-3">参考答案</label>
                    {hasStructured ? (
                      <div className="space-y-3">
                        {analysis && (
                          <div>
                            <label className="block text-[11px] font-medium text-[var(--color-text-muted)] mb-1">解题分析</label>
                            <div className="text-sm text-[var(--color-text)] whitespace-pre-wrap leading-relaxed">{analysis}</div>
                          </div>
                        )}
                        {steps.length > 0 && (
                          <div>
                            <label className="block text-[11px] font-medium text-[var(--color-text-muted)] mb-1">解题步骤</label>
                            <ol className="text-sm text-[var(--color-text)] space-y-0.5 list-decimal list-inside">
                              {steps.map((step, i) => (
                                <li key={i} className="whitespace-pre-wrap leading-relaxed">{step}</li>
                              ))}
                            </ol>
                          </div>
                        )}
                        {finalAnswer && (
                          <div>
                            <label className="block text-[11px] font-medium text-[var(--color-text-muted)] mb-1">最终答案</label>
                            <div className="text-sm font-bold text-[var(--color-text)] bg-green-50 border border-green-200 rounded-btn px-3 py-1.5">{finalAnswer}</div>
                          </div>
                        )}
                      </div>
                    ) : (
                      <p className="text-sm text-[var(--color-text)] whitespace-pre-wrap">{answerText || "无"}</p>
                    )}
                  </div>
                );
              })()
            )}

            <div className="flex justify-between border-t border-[var(--color-border)] pt-4">
              <Button variant="ghost" size="sm" disabled={selectedIdx <= 0} onClick={() => setSelectedIdx(selectedIdx - 1)}>← 上一题</Button>
              <div className="flex gap-2">
                {isQuestionReviewEditable && (
                  <Button variant="primary" size="sm" disabled={approveMut.isPending}
                    onClick={() => {
                      if (selectedIdx < questions.length - 1) {
                        setSelectedIdx(selectedIdx + 1);
                        setIsEditingContent(false);
                      } else approveMut.mutate(questions);
                    }}>
                    {selectedIdx < questions.length - 1 ? "✓ 确认，下一题" : "✓ 全部确认"}
                  </Button>
                )}
              </div>
              <Button variant="ghost" size="sm" disabled={selectedIdx >= questions.length - 1} onClick={() => setSelectedIdx(selectedIdx + 1)}>下一题 →</Button>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-sm text-[var(--color-text-muted)]">选择一道题目开始审查</div>
        )}
      </div>
    </div>
  );
}
