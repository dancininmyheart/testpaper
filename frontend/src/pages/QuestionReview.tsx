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

import { ArrowLeft, ChevronLeft, ChevronRight, Check, Eye, Edit3, Image as ImageIcon, HelpCircle, Award, Sparkles, Loader2 } from "lucide-react";

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
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
        <div className="text-sm text-[var(--color-text-muted)] font-medium">智能试题提取数据载入中...</div>
      </div>
    );
  }

  return (
    <div className="flex gap-0 h-[calc(100vh-100px)] -mx-6 bg-slate-50/50">
      {/* 左侧栏：试题快速导航 */}
      <div className="w-64 flex-shrink-0 border-r border-slate-200/80 overflow-auto bg-white flex flex-col shadow-[1px_0_5px_rgba(0,0,0,0.02)]">
        <div className="p-4 border-b border-slate-100 sticky top-0 bg-white z-10">
          <Link to={`/projects/${id}`} className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-700 shadow-sm transition-colors hover:border-primary/30 hover:bg-primary/5 hover:text-primary mb-3">
            <ArrowLeft className="w-4 h-4" /> 返回项目
          </Link>
          <h2 className="text-sm font-bold text-slate-800 tracking-tight">试题审查</h2>
          <div className="flex items-center justify-between mt-1">
            <span className="text-[11px] text-[var(--color-text-muted)]">共 {questions.length} 道题</span>
            {isMineru && <span className="text-[10px] bg-indigo-50 text-primary px-1.5 py-0.5 rounded font-medium">AI 深度提取</span>}
          </div>
        </div>
        <div className="p-2 space-y-1 overflow-y-auto flex-1">
          {questions.map((q, i) => {
            const isSelected = i === selectedIdx;
            const contentText = q.content as string || "";
            const isCompleted = false; // 可扩展未来标记已确认状态
            return (
              <button
                key={q.question_id as string}
                onClick={() => {
                  setSelectedIdx(i);
                  setIsEditingContent(false);
                }}
                className={`w-full text-left px-3.5 py-2.5 rounded-xl text-xs transition-all duration-200 group flex items-start gap-2.5 ${
                  isSelected
                    ? "bg-gradient-to-r from-primary/10 to-indigo-50/50 text-primary font-semibold shadow-sm border-l-4 border-primary pl-2"
                    : "text-slate-600 hover:bg-slate-50 border-l-4 border-transparent pl-2 hover:pl-3"
                }`}
              >
                <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded ${
                  isSelected ? "bg-primary/20 text-primary font-bold" : "bg-slate-100 text-slate-500"
                }`}>
                  Q{String(q.question_no)}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="truncate font-medium group-hover:text-slate-900 transition-colors">
                    <MathText text={contentText.split("\n")[0] || "空文本题目"} inline />
                  </div>
                  <div className="text-[10px] text-[var(--color-text-muted)] mt-0.5 flex flex-wrap items-center gap-1.5">
                    <span>{String(q.question_type || "问答题")}</span>
                    {q.max_score != null && <span>• {q.max_score as number}分</span>}
                    {Array.isArray(q.skill_tags_display || q.skill_tags) && ((q.skill_tags_display || q.skill_tags) as string[]).length > 0 && (
                      <span className="bg-emerald-50 text-emerald-600 px-1.5 py-0.5 rounded text-[9px] scale-95 origin-left font-medium">
                        {((q.skill_tags_display || q.skill_tags) as string[])[0]}
                      </span>
                    )}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* 中间栏：试卷图片区域 (防眩光、电影级视效) */}
      <div className="flex-1 border-r border-slate-200/80 bg-slate-900/95 flex items-center justify-center p-6 overflow-auto relative group/canvas shadow-[inset_0_2px_12px_rgba(0,0,0,0.15)]">
        <div className="absolute inset-0 bg-[radial-gradient(#1e293b_1px,transparent_1px)] [background-size:16px_16px] opacity-30 pointer-events-none"></div>
        {pageFileId ? (
          <div className="relative max-w-full transition-transform duration-300">
            <ProjectFileImage
              projectId={id!}
              fileId={pageFileId}
              alt="试卷原图"
              className="max-w-full max-h-[calc(100vh-160px)] rounded-xl shadow-2xl border border-slate-800 object-contain bg-white"
            />
            <div className="absolute bottom-3 right-3 backdrop-blur-md bg-black/60 text-white/90 text-[10px] px-2.5 py-1 rounded-full border border-white/10 shadow-lg tracking-wider font-medium">
              第 {(current?.page_index as number ?? 0) + 1} 页
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center space-y-2 text-slate-500">
            <ImageIcon className="w-10 h-10 opacity-40" />
            <div className="text-sm font-medium">暂无当前试卷的匹配图片</div>
          </div>
        )}
      </div>

      {/* 右侧栏：试题详情与编辑区 (高精排版、色卡答案) */}
      <div className="w-[480px] flex-shrink-0 overflow-auto bg-white p-6 flex flex-col shadow-[-2px_0_12px_rgba(0,0,0,0.01)] border-l border-slate-200/80">
        {current ? (
          <div className="flex flex-col h-full justify-between">
            <div className="space-y-5 flex-1 overflow-y-auto pb-4">
              <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                <div className="flex items-center gap-2">
                  <span className="text-base font-bold text-slate-800">第 {current.question_no as string} 题</span>
                  <Badge color="purple">{(current.question_type as string) || "试题"}</Badge>
                  {current.max_score != null && (
                    <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full font-medium">
                      满分 {current.max_score as number} 分
                    </span>
                  )}
                </div>
              </div>

              {/* 考查知识点 */}
              {Array.isArray(current.skill_tags_display || current.skill_tags) && ((current.skill_tags_display || current.skill_tags) as string[]).length > 0 && (
                <div className="flex flex-wrap gap-1.5 items-center bg-slate-50/50 border border-slate-100 rounded-xl px-3.5 py-2.5 animate-fadeIn">
                  <span className="text-xs font-bold text-slate-500 mr-1 flex items-center gap-1">
                    <Sparkles className="w-3.5 h-3.5 text-emerald-500" />
                    考查知识点：
                  </span>
                  {((current.skill_tags_display || current.skill_tags) as string[]).map((tag: string, index: number) => (
                    <Badge key={index} color="green">{tag}</Badge>
                  ))}
                </div>
              )}

              {/* 题目题干框 */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-slate-500 tracking-wider">题目题干</label>
                  {isQuestionReviewEditable && (
                    <button
                      type="button"
                      onClick={() => setIsEditingContent((value) => !value)}
                      className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:text-primary-dark transition-colors"
                    >
                      {isEditingContent ? (
                        <>
                          <Eye className="w-3 h-3" /> 预览公式
                        </>
                      ) : (
                        <>
                          <Edit3 className="w-3 h-3" /> 编辑题目
                        </>
                      )}
                    </button>
                  )}
                </div>
                
                {isQuestionReviewEditable && isEditingContent ? (
                  <textarea
                    value={currentContent}
                    onChange={(event) => updateQuestionContent(event.target.value)}
                    className="w-full min-h-[140px] resize-y rounded-xl border border-primary-light focus:border-primary focus:ring-4 focus:ring-primary/5 bg-slate-50/30 px-3.5 py-3 text-sm leading-relaxed outline-none transition-all font-mono"
                    placeholder="请输入试题Markdown文本，支持LaTeX公式..."
                  />
                ) : (
                  <div className="w-[clamp(320px,38vw,520px)] min-w-0 max-w-full min-h-[100px] px-4 py-3.5 border border-slate-200/80 rounded-xl text-sm whitespace-pre-wrap break-words [overflow-wrap:anywhere] bg-slate-50/50 shadow-inner leading-relaxed">
                    <MathText text={isMineru ? cleanContent(currentContent) : currentContent} />
                  </div>
                )}
              </div>

              {/* 题目配图区 */}
              {matchedImages.length > 0 && (
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-slate-500 tracking-wider flex items-center gap-1">
                    <ImageIcon className="w-3.5 h-3.5 text-slate-400" /> 题目配图
                  </label>
                  <div className="rounded-xl border border-slate-100 bg-slate-50/30 p-3">
                    <div className="flex flex-wrap gap-3">
                      {matchedImages.map((image, i) => (
                        <div key={`${image.id ?? i}`} className="relative group/thumb rounded-lg overflow-hidden border border-slate-200 bg-white hover:shadow-md transition-all duration-200">
                          <ProjectFileImage
                            projectId={id!}
                            fileId={typeof image.id === "number" ? image.id : null}
                            alt={`配图${i + 1}`}
                            className="h-[140px] w-[min(220px,100%)] object-contain p-1 transition-transform duration-300 hover:scale-105"
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* 参考答案分类色卡 */}
              {current.reference_answer != null && (
                (() => {
                  const ref = current.reference_answer as Record<string, unknown>;
                  const analysis = typeof ref.analysis === "string" ? ref.analysis.trim() : "";
                  const steps = Array.isArray(ref.steps) ? (ref.steps as string[]).filter((s: string) => s.trim()) : [];
                  const finalAnswer = typeof ref.final_answer === "string" ? ref.final_answer.trim() : "";
                  const answerText = typeof ref.answer_text === "string" ? ref.answer_text.trim() : "";
                  const hasStructured = analysis || steps.length > 0 || finalAnswer;
                  
                  return (
                    <div className="space-y-3">
                      <label className="text-xs font-semibold text-slate-500 tracking-wider">参考答案</label>
                      {hasStructured ? (
                        <div className="space-y-3">
                          {/* 解题分析：淡蓝色卡片 */}
                          {analysis && (
                            <div className="bg-gradient-to-br from-blue-50/50 to-indigo-50/30 border border-blue-100/60 rounded-xl p-4 shadow-[0_2px_6px_rgba(59,130,246,0.02)]">
                              <div className="flex items-center gap-1.5 text-blue-700 font-bold text-xs mb-1.5">
                                <Sparkles className="w-3.5 h-3.5 text-blue-500" />
                                <span>解题分析</span>
                              </div>
                              <div className="text-sm text-slate-700 leading-relaxed pl-5">
                                <MathText text={analysis} />
                              </div>
                            </div>
                          )}

                          {/* 解题步骤：淡紫色卡片 */}
                          {steps.length > 0 && (
                            <div className="bg-gradient-to-br from-purple-50/50 to-pink-50/30 border border-purple-100/60 rounded-xl p-4 shadow-[0_2px_6px_rgba(147,51,234,0.02)]">
                              <div className="flex items-center gap-1.5 text-purple-700 font-bold text-xs mb-2">
                                <HelpCircle className="w-3.5 h-3.5 text-purple-500" />
                                <span>详细步骤</span>
                              </div>
                              <ol className="text-sm text-slate-700 space-y-2 list-none pl-5">
                                {steps.map((step, i) => (
                                  <li key={i} className="relative leading-relaxed pl-5">
                                    <span className="absolute left-0 top-[3px] flex items-center justify-center w-4 h-4 rounded-full bg-purple-100 text-[10px] text-purple-700 font-bold font-mono">
                                      {i + 1}
                                    </span>
                                    <MathText text={step} />
                                  </li>
                                ))}
                              </ol>
                            </div>
                          )}

                          {/* 最终答案：淡绿色卡片 */}
                          {finalAnswer && (
                            <div className="bg-gradient-to-br from-emerald-50/60 to-teal-50/30 border border-emerald-100/80 rounded-xl p-4 shadow-[0_2px_8px_rgba(16,185,129,0.04)]">
                              <div className="flex items-center gap-1.5 text-emerald-800 font-bold text-xs mb-2">
                                <Award className="w-3.5 h-3.5 text-emerald-600" />
                                <span>最终答案</span>
                              </div>
                              <div className="text-sm font-semibold text-emerald-900 bg-white/80 backdrop-blur-sm border border-emerald-100 rounded-lg px-3 py-2 pl-4 shadow-sm inline-block min-w-[120px]">
                                <MathText text={finalAnswer} />
                              </div>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="bg-slate-50 border border-slate-200/60 rounded-xl p-4 text-sm text-slate-700 leading-relaxed">
                          <MathText text={answerText || "暂无结构化答案"} />
                        </div>
                      )}
                    </div>
                  );
                })()
              )}
            </div>

            {/* 底部导航区 */}
            <div className="flex items-center justify-between border-t border-slate-100 pt-4 mt-4">
              <Button
                variant="ghost"
                size="sm"
                disabled={selectedIdx <= 0}
                onClick={() => setSelectedIdx(selectedIdx - 1)}
                className="gap-1 text-slate-600 hover:text-slate-800"
              >
                <ChevronLeft className="w-4 h-4" /> 上一题
              </Button>
              
              <div className="flex gap-2">
                {isQuestionReviewEditable && (
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={approveMut.isPending}
                    className="shadow-premium px-5 py-2"
                    onClick={() => {
                      if (selectedIdx < questions.length - 1) {
                        setSelectedIdx(selectedIdx + 1);
                        setIsEditingContent(false);
                      } else {
                        approveMut.mutate(questions);
                      }
                    }}
                  >
                    {approveMut.isPending ? (
                      <span className="flex items-center gap-1"><Loader2 className="w-3 h-3 animate-spin" /> 保存中...</span>
                    ) : selectedIdx < questions.length - 1 ? (
                      <span className="flex items-center gap-1"><Check className="w-3.5 h-3.5" /> 确认，下一题</span>
                    ) : (
                      <span className="flex items-center gap-1"><Check className="w-3.5 h-3.5" /> 全部确认完成</span>
                    )}
                  </Button>
                )}
              </div>

              <Button
                variant="ghost"
                size="sm"
                disabled={selectedIdx >= questions.length - 1}
                onClick={() => setSelectedIdx(selectedIdx + 1)}
                className="gap-1 text-slate-600 hover:text-slate-800"
              >
                下一题 <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 space-y-2">
            <HelpCircle className="w-10 h-10 opacity-30" />
            <div className="text-sm font-medium">请在左侧选择一道试题开始审查</div>
          </div>
        )}
      </div>
    </div>
  );
}
