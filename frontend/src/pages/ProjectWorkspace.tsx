import { useEffect, useState, useMemo } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getProject, uploadProjectFiles, uploadAnswerKeyFiles, triggerExtraction, generateReferenceAnswers, analyzeAnswerSheet, listProjectStudentRuns, mineruParse, mineruLlmParse, mineruVlmMatch, mineruSave, type ModelProfiles } from "../api/projects";
import { listStudents } from "../api/students";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import PhaseCard from "../components/project/PhaseCard";
import UploadZone from "../components/project/UploadZone";
import type { PhaseState } from "../mock/types";

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿", error: "错误", extracting: "提取中",
  review_questions: "待审查试题", generating_answers: "生成答案中",
  review_answers: "待审查答案", ready: "就绪",
  recognizing: "识别中", review_recognition: "待审查识别结果", review_scores: "待审查评分", completed: "已完成",
};

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

export default function ProjectWorkspace() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: project, isLoading } = useQuery({
    queryKey: ["project", id],
    queryFn: () => getProject(id!),
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ["extracting", "generating_answers", "recognizing"].includes(status) ? 2000 : false;
    },
  });

  const [paperFiles, setPaperFiles] = useState<File[]>([]);
  const [answerKeyFiles, setAnswerKeyFiles] = useState<File[]>([]);
  const [answerSheetFiles, setAnswerSheetFiles] = useState<File[]>([]);
  const [selectedStudentId, setSelectedStudentId] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadingAnswerKey, setUploadingAnswerKey] = useState(false);
  const [generatingAnswers, setGeneratingAnswers] = useState(false);
  const [analyzingSheet, setAnalyzingSheet] = useState(false);
  const [fileUploaded, setFileUploaded] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [mineruRunning, setMineruRunning] = useState(false);
  const [mineruStep, setMineruStep] = useState(0); // 0=idle, 1-4=steps, -1=done
  const [mineruStepStatus, setMineruStepStatus] = useState<Record<number, "running" | "done" | "error">>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [selectedModelMode, setSelectedModelMode] = useState<ModelMode>("standard");
  const selectedProfiles = MODEL_PROFILE_MODES[selectedModelMode];

  const { data: students = [] } = useQuery({
    queryKey: ["students"],
    queryFn: listStudents,
  });

  const { data: studentRuns = [] } = useQuery({
    queryKey: ["project-student-runs", id],
    queryFn: () => listProjectStudentRuns(id!),
    enabled: !!id,
    refetchInterval: (query) => {
      const runs = query.state.data || [];
      return runs.some((run) => ["queued", "running"].includes(run.status)) ? 2000 : false;
    },
  });

  useEffect(() => {
    if (!selectedStudentId && students.length > 0) {
      setSelectedStudentId(students[0].student_id);
    }
  }, [selectedStudentId, students]);

  const clearMessage = () => setActionMessage(null);
  const clearError = () => setActionError(null);

  const phases: PhaseState[] = useMemo(() => {
    if (!project) return [];
    const st = project.status;
    const hasReferenceAnswers = (project.reference_answer_count ?? 0) > 0;
    const needsReferenceAnswers = st === "ready" && !hasReferenceAnswers;
    const canStartGrading = st === "ready" && hasReferenceAnswers;
    const isStandard = true; // simplified

    return [
      {
        phase: 1, label: "阶段一 · 准备",
        status: fileUploaded || !(st === "draft" || st === "error") ? "done" : "active",
        subActions: [
          { key: "upload", label: "上传试卷图片", done: fileUploaded || !(st === "draft" || st === "error") },
        ],
      },
      {
        phase: 2, label: "阶段二 · 提取与审查",
        status: !fileUploaded && (st === "draft" || st === "error") ? "pending"
          : ["extracting", "review_questions", "generating_answers", "review_answers"].includes(st) || needsReferenceAnswers ? "active"
          : st === "draft" || st === "error" ? "active"
          : "done",
        subActions: [
          { key: "extract", label: "AI 提取试题", done: !["draft","error","extracting"].includes(st) },
          { key: "review_q", label: "审查试题", done: !["draft","error","extracting","review_questions"].includes(st) },
          { key: "prepare_a", label: "准备参考答案", done: hasReferenceAnswers || ["generating_answers","review_answers","recognizing","review_recognition","review_scores","completed"].includes(st) },
          { key: "review_a", label: "审查参考答案", done: canStartGrading || ["recognizing","review_recognition","review_scores","completed"].includes(st) },
        ],
      },
      {
        phase: 3, label: "阶段三 · 批改",
        status: canStartGrading || ["recognizing","review_recognition","review_scores"].includes(st) ? "active" : st === "completed" ? "done" : "pending",
        subActions: [
          { key: "upload_sheets", label: "上传学生答题卡", done: !canStartGrading },
          { key: "recognize_sheets", label: "识别学生作答", done: !["recognizing"].includes(st) },
          { key: "review_recognition", label: "审查识别结果", done: !["review_recognition"].includes(st) },
          { key: "review_scores", label: "审查评分", done: !["review_scores"].includes(st) },
        ],
      },
      {
        phase: 4, label: "阶段四 · 报告",
        status: st === "completed" ? "active" : "pending",
        subActions: [
          { key: "view_report", label: "查看成绩报告", done: false },
        ],
      },
    ];
  }, [project, fileUploaded, uploadSuccess]);

  const handleUpload = async () => {
    if (paperFiles.length === 0) return;
    setUploading(true);
    setActionError(null);
    setActionMessage(null);
    try {
      await uploadProjectFiles(id!, paperFiles, []);
      setPaperFiles([]);
      setFileUploaded(true);
      setUploadSuccess(true);
      setActionMessage(`上传成功！已保存 ${paperFiles.length} 个文件。现在可以点击"AI 提取试题"开始分析。`);
      queryClient.invalidateQueries({ queryKey: ["project", id] });
    } catch (e: any) {
      setActionError(e?.message || "上传失败，请检查后端服务是否运行");
    } finally { setUploading(false); }
  };

  const handleExtract = async () => {
    setExtracting(true);
    setActionError(null);
    try {
      await triggerExtraction(id!, selectedProfiles);
      queryClient.invalidateQueries({ queryKey: ["project", id] });
    } catch (e: any) {
      setActionError(e?.message || "提取失败，请检查后端服务是否运行");
    } finally { setExtracting(false); }
  };

  const handleUploadAnswerKey = async () => {
    if (answerKeyFiles.length === 0) return;
    setUploadingAnswerKey(true);
    setActionError(null);
    setActionMessage(null);
    try {
      await uploadAnswerKeyFiles(id!, answerKeyFiles, selectedProfiles);
      setAnswerKeyFiles([]);
      setActionMessage("答案文件已提交，系统正在整理参考答案，完成后请校验。");
      queryClient.invalidateQueries({ queryKey: ["project", id] });
    } catch (e: any) {
      setActionError(e?.message || "答案文件上传失败，请检查后端服务是否运行。");
    } finally {
      setUploadingAnswerKey(false);
    }
  };

  const handleGenerateReferenceAnswers = async () => {
    setGeneratingAnswers(true);
    setActionError(null);
    setActionMessage(null);
    try {
      await generateReferenceAnswers(id!, selectedProfiles);
      setActionMessage("AI 已开始生成参考答案，完成后请校验。");
      queryClient.invalidateQueries({ queryKey: ["project", id] });
    } catch (e: any) {
      setActionError(e?.message || "AI 生成参考答案失败，请检查后端服务是否运行。");
    } finally {
      setGeneratingAnswers(false);
    }
  };

  const MINERU_STEPS = [
    { step: 1, key: "parse", label: "MinerU 解析试卷", desc: "上传图片到 MinerU API，OCR 识别文字与图片区域" },
    { step: 2, key: "llm", label: "LLM 整理题目", desc: "AI 分析 OCR 结果，结构化提取题目列表" },
    { step: 3, key: "vlm", label: "VLM 匹配配图", desc: "视觉模型匹配每道题的配图" },
    { step: 4, key: "save", label: "保存结果", desc: "将题目和配图写入数据库" },
  ];

  const handleMineru = async () => {
    setMineruRunning(true);
    setMineruStep(1);
    setMineruStepStatus({});
    setActionError(null);
    setActionMessage(null);

    const runStep = async (step: number, fn: () => Promise<unknown>) => {
      setMineruStep(step);
      setMineruStepStatus((prev) => ({ ...prev, [step]: "running" }));
      try {
        const result = await fn();
        setMineruStepStatus((prev) => ({ ...prev, [step]: "done" }));
        return result;
      } catch (e: any) {
        setMineruStepStatus((prev) => ({ ...prev, [step]: "error" }));
        throw e;
      }
    };

    try {
      // Step 1: MinerU parse
      const parseResult: any = await runStep(1, () => mineruParse(id!, selectedProfiles));
      const pageCount = parseResult?.page_count ?? 0;
      if (pageCount === 0) {
        setActionError("MinerU 解析未返回任何页面内容。请确认上传的是清晰的试卷图片。");
        return;
      }

      // Step 2: LLM question extraction
      const llmResult: any = await runStep(2, () => mineruLlmParse(id!, selectedProfiles));
      const questionCount = llmResult?.question_count ?? 0;
      if (questionCount === 0) {
        setActionError("LLM 未能从试卷中提取到题目。可能原因：MinerU OCR 文字为空、试卷图片不清晰、或 LLM API 异常。请尝试用标准 AI 提取。");
        return;
      }

      // Step 3: VLM image matching (skip if no images on pages)
      const hasImages = parseResult?.pages?.some((p: any) => (p.image_count ?? 0) > 0);
      if (hasImages) {
        await runStep(3, () => mineruVlmMatch(id!, selectedProfiles));
      } else {
        setMineruStep(3);
        setMineruStepStatus((prev) => ({ ...prev, 3: "done" }));
      }

      // Step 4: Save
      await runStep(4, () => mineruSave(id!));
      setActionMessage(`MinerU 智能提取完成！共提取 ${questionCount} 道题。请审查试题。`);
      queryClient.invalidateQueries({ queryKey: ["project", id] });
    } catch (e: any) {
      setActionError(e?.message || "MinerU 处理失败，请检查后端日志");
    } finally {
      setMineruRunning(false);
      setMineruStep(-1); // signal completion
    }
  };

  const handleAnalyzeAnswerSheet = async () => {
    if (answerSheetFiles.length === 0) return;
    if (!selectedStudentId) {
      setActionError("请先在学生管理中新增学生，并选择对应学生。");
      return;
    }
    setAnalyzingSheet(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const result = await analyzeAnswerSheet(id!, selectedStudentId, answerSheetFiles, selectedProfiles);
      setAnswerSheetFiles([]);
      setActionMessage("学生答题卡已提交识别，完成后会进入识别结果审查。");
      queryClient.invalidateQueries({ queryKey: ["project", id] });
      queryClient.invalidateQueries({ queryKey: ["project-student-runs", id] });
      queryClient.invalidateQueries({ queryKey: ["scores", id, result.job_id] });
    } catch (e: any) {
      setActionError(e?.message || "学生答题卡识别提交失败，请检查后端服务是否运行。");
    } finally {
      setAnalyzingSheet(false);
    }
  };

  if (isLoading) {
    return <div className="flex items-center justify-center py-20"><div className="text-sm text-[var(--color-text-muted)]">加载中...</div></div>;
  }
  if (!project) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <p className="text-sm text-[var(--color-text-muted)] mb-4">项目不存在</p>
        <Link to="/projects"><Button variant="secondary">返回项目列表</Button></Link>
      </div>
    );
  }
  const hasReferenceAnswers = (project.reference_answer_count ?? 0) > 0;
  const needsReferenceAnswers = project.status === "ready" && !hasReferenceAnswers;
  const canStartGrading = project.status === "ready" && hasReferenceAnswers;
  const canInspectQuestions = project.question_count > 0;
  const canInspectReferenceAnswers = hasReferenceAnswers;
  const renderInspectionLinks = (size: "sm" | "md" = "sm") => {
    if (!canInspectQuestions && !canInspectReferenceAnswers) return null;
    return (
      <div className="flex flex-wrap gap-2">
        {canInspectQuestions && (
          <Button variant="ghost" size={size} onClick={() => navigate(`/projects/${id}/review`)}>查看试题抽取</Button>
        )}
        {canInspectReferenceAnswers && (
          <Button variant="ghost" size={size} onClick={() => navigate(`/projects/${id}/answers`)}>查看参考答案</Button>
        )}
      </div>
    );
  };

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <Link to="/projects" className="text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors">←</Link>
            <h1 className="text-lg font-bold text-[var(--color-text)]">{project.title}</h1>
            <Badge color={project.status === "completed" ? "green" : project.status === "draft" ? "gray" : "purple"}>
              {STATUS_LABELS[project.status] || project.status}
            </Badge>
          </div>
          <p className="text-xs text-[var(--color-text-muted)]">
            {project.subject} · {project.grade} · 创建于 {project.created_at?.slice(0, 10)}
            {project.question_count > 0 && ` · ${project.question_count} 题`}
            {project.student_count > 0 && ` · ${project.student_count} 名学生`}
          </p>
          {project.error_message && (
            <p className="text-xs text-danger mt-1">⚠ {project.error_message}</p>
          )}
        </div>
        {project.status === "completed" && (
          <Link to={`/projects/${project.project_id}/scoring`}>
            <Button variant="primary">📊 查看报告</Button>
          </Link>
        )}
      </div>

      <div className="mb-5 bg-white border border-[var(--color-border)] rounded-card p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="text-sm font-semibold text-[var(--color-text)]">模型模式</div>
            <div className="text-xs text-[var(--color-text-muted)] mt-1">
              当前阶段动作会使用：VLM {selectedProfiles.visionProfile}，LLM {selectedProfiles.textProfile}
            </div>
          </div>
          <div className="inline-flex w-fit rounded-btn border border-[var(--color-border)] bg-gray-50 p-1">
            <button
              type="button"
              onClick={() => setSelectedModelMode("fast")}
              className={`px-3 py-1.5 text-xs font-medium rounded-btn transition-colors ${
                selectedModelMode === "fast"
                  ? "bg-white text-primary shadow-sm"
                  : "text-[var(--color-text-secondary)] hover:text-[var(--color-text)]"
              }`}
            >
              快速模式
            </button>
            <button
              type="button"
              onClick={() => setSelectedModelMode("standard")}
              className={`px-3 py-1.5 text-xs font-medium rounded-btn transition-colors ${
                selectedModelMode === "standard"
                  ? "bg-white text-primary shadow-sm"
                  : "text-[var(--color-text-secondary)] hover:text-[var(--color-text)]"
              }`}
            >
              标准模式
            </button>
          </div>
        </div>
      </div>

      {/* Phase cards */}
      <div className="space-y-3">
        {phases.map((phase) => (
          <PhaseCard key={phase.phase} phase={phase}>
            {phase.phase === 1 && phase.status === "active" && !fileUploaded && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-6">
                  <UploadZone label="试卷图片" hint="支持 JPG/PNG，可多选" files={paperFiles} onFiles={setPaperFiles} />
                  <UploadZone label="标准答案（可选）" hint="提供更精准的参考答案" files={[]} onFiles={() => {}} />
                </div>
                <div className="flex items-center gap-3">
                  <Button variant="primary" onClick={handleUpload} disabled={paperFiles.length === 0 || uploading}>
                    {uploading ? "⏳ 上传中..." : "上传文件"}
                  </Button>
                  {paperFiles.length > 0 && !uploading && (
                    <span className="text-xs text-[var(--color-text-muted)]">已选择 {paperFiles.length} 个文件，点击上传</span>
                  )}
                </div>
                {actionError && (
                  <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-btn">
                    <span className="text-xs text-danger flex-1">{actionError}</span>
                    <button onClick={clearError} className="text-danger text-xs hover:underline flex-shrink-0">关闭</button>
                  </div>
                )}
              </div>
            )}
            {phase.phase === 1 && uploadSuccess && (
              <div className="flex items-start gap-2 p-3 bg-emerald-50 border border-emerald-200 rounded-btn">
                <span className="text-emerald-600 text-xs flex-1">{actionMessage}</span>
                <button onClick={() => { setUploadSuccess(false); clearMessage(); }} className="text-emerald-600 text-xs hover:underline flex-shrink-0">关闭</button>
              </div>
            )}

            {(phase.phase === 2 && (phase.status === "active" || phase.status === "done")) && !mineruRunning && (
              <div className="space-y-3">
                {(project.status === "draft" || project.status === "error" || project.status === "extracting" || project.status === "review_questions") && (
                  <div className="flex flex-wrap gap-2">
                    <Button variant="primary" onClick={handleExtract} disabled={extracting}>
                      {extracting ? "提取中..." : "🔍 AI 提取试题"}
                    </Button>
                    <Button variant="secondary" onClick={handleMineru} disabled={extracting}>
                      🔬 MinerU 智能提取
                    </Button>
                    {["review_questions"].includes(project.status) && (
                      <Button variant="secondary" onClick={() => navigate(`/projects/${id}/review`)}>审查试题</Button>
                    )}
                  </div>
                )}
                {needsReferenceAnswers && (
                  <div className="space-y-3">
                    <UploadZone label="试题答案文件" hint="支持 JPG/PNG，可多页上传" files={answerKeyFiles} onFiles={setAnswerKeyFiles} />
                    <div className="flex flex-wrap items-center gap-2">
                      <Button variant="primary" onClick={handleUploadAnswerKey} disabled={answerKeyFiles.length === 0 || uploadingAnswerKey}>
                        {uploadingAnswerKey ? "提交中..." : "上传答案并整理"}
                      </Button>
                      <Button variant="secondary" onClick={handleGenerateReferenceAnswers} disabled={generatingAnswers || uploadingAnswerKey}>
                        {generatingAnswers ? "生成中..." : "AI 生成试题答案"}
                      </Button>
                    </div>
                  </div>
                )}
                {project.status === "generating_answers" && (
                  <div className="p-3 bg-primary-light border border-primary/20 rounded-btn text-xs text-primary">
                    正在整理参考答案，完成后请进入参考答案校验。
                  </div>
                )}
                {project.status === "review_answers" && (
                  <div className="flex flex-wrap gap-2">
                    <Button variant="secondary" onClick={() => navigate(`/projects/${id}/answers`)}>校验参考答案</Button>
                    <Button variant="ghost" onClick={handleGenerateReferenceAnswers} disabled={generatingAnswers}>
                      {generatingAnswers ? "生成中..." : "重新生成"}
                    </Button>
                  </div>
                )}
                {phase.status === "done" && renderInspectionLinks("sm")}
                {actionError && (
                  <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-btn mt-2">
                    <span className="text-xs text-danger flex-1">{actionError}</span>
                    <button onClick={clearError} className="text-danger text-xs hover:underline flex-shrink-0">关闭</button>
                  </div>
                )}
                {actionMessage && (
                  <div className="flex items-start gap-2 p-3 bg-emerald-50 border border-emerald-200 rounded-btn mt-2">
                    <span className="text-emerald-600 text-xs flex-1">{actionMessage}</span>
                    <button onClick={clearMessage} className="text-emerald-600 text-xs hover:underline flex-shrink-0">关闭</button>
                  </div>
                )}
              </div>
            )}

            {/* MinerU step-by-step progress */}
            {phase.phase === 2 && mineruRunning && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-primary">🔬 MinerU 处理中...</p>
                {MINERU_STEPS.map((s) => {
                  const status = mineruStepStatus[s.step];
                  const isActive = mineruStep === s.step;
                  const isDone = status === "done";
                  const isError = status === "error";
                  return (
                    <div key={s.step}
                      className={`flex items-center gap-3 px-3 py-2 rounded-btn text-xs transition-colors ${
                        isActive ? "bg-primary-light border border-primary/30" :
                        isDone ? "bg-emerald-50 border border-emerald-200" :
                        isError ? "bg-red-50 border border-red-200" :
                        "bg-gray-50 border border-gray-200"
                      }`}>
                      <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0 ${
                        isActive ? "bg-primary text-white animate-pulse" :
                        isDone ? "bg-emerald-500 text-white" :
                        isError ? "bg-danger text-white" :
                        "bg-gray-200 text-gray-400"
                      }`}>
                        {isDone ? "✓" : isError ? "✕" : s.step}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className={`font-medium ${isActive ? "text-primary" : isDone ? "text-emerald-700" : isError ? "text-danger" : "text-gray-400"}`}>
                          {s.label}
                        </div>
                        <div className="text-[10px] text-[var(--color-text-muted)] mt-0.5">{s.desc}</div>
                      </div>
                      <span className="text-[10px] flex-shrink-0">
                        {isActive && "⏳"}
                        {isDone && "✅"}
                        {isError && "❌"}
                        {!isActive && !isDone && !isError && "○"}
                      </span>
                    </div>
                  );
                })}
                {actionError && (
                  <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-btn">
                    <span className="text-xs text-danger flex-1">{actionError}</span>
                    <button onClick={clearError} className="text-danger text-xs hover:underline flex-shrink-0">关闭</button>
                  </div>
                )}
              </div>
            )}

            {phase.phase === 3 && phase.status === "active" && (
              <div className="space-y-3">
                {renderInspectionLinks("sm")}
                {studentRuns.length > 0 && (
                  <div className="border border-[var(--color-border)] rounded-card bg-white">
                    <div className="px-3 py-2 border-b border-[var(--color-border)] text-xs font-semibold text-[var(--color-text-secondary)]">
                      学生批改记录
                    </div>
                    <div className="divide-y divide-[var(--color-border)]">
                      {studentRuns.map((run) => (
                        <div key={run.job_id} className="flex items-center justify-between gap-3 px-3 py-2 text-xs">
                          <div className="min-w-0">
                            <div className="font-medium text-[var(--color-text)] truncate">
                              {run.student_id || "未命名学生"}
                            </div>
                            <div className="text-[var(--color-text-muted)]">
                              {run.status} · {run.finished_at || run.updated_at || run.created_at}
                            </div>
                          </div>
                          <Button
                            variant={run.has_result ? "secondary" : "ghost"}
                            size="sm"
                            onClick={() => navigate(`/projects/${id}/scoring/${run.job_id}`)}
                            disabled={!run.has_result}
                          >
                            查看明细
                          </Button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {canStartGrading && (
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">学生标识</label>
                      <select
                        value={selectedStudentId}
                        onChange={(e) => setSelectedStudentId(e.target.value)}
                        className="w-full max-w-xs px-3 py-2 border border-[var(--color-border)] rounded-btn text-sm outline-none focus:border-primary bg-white"
                      >
                        {students.map((student) => (
                          <option key={student.student_id} value={student.student_id}>
                            {student.student_id} · {student.name} · {student.grade || "未填写年级"}
                          </option>
                        ))}
                      </select>
                      {students.length === 0 && (
                        <div className="mt-1.5 text-xs text-danger">先在学生管理中新增学生，再上传答题卡。</div>
                      )}
                    </div>
                    <UploadZone label="学生答题卡" hint="支持 JPG/PNG，可多页上传" files={answerSheetFiles} onFiles={setAnswerSheetFiles} />
                    <div className="flex items-center gap-3">
                      <Button variant="primary" onClick={handleAnalyzeAnswerSheet} disabled={answerSheetFiles.length === 0 || !selectedStudentId || analyzingSheet}>
                        {analyzingSheet ? "提交中..." : "上传并识别答题卡"}
                      </Button>
                      {answerSheetFiles.length > 0 && !analyzingSheet && (
                        <span className="text-xs text-[var(--color-text-muted)]">已选择 {answerSheetFiles.length} 个文件</span>
                      )}
                    </div>
                  </div>
                )}
                {project.status === "recognizing" && (
                  <div className="p-3 bg-primary-light border border-primary/20 rounded-btn text-xs text-primary">
                    正在识别学生答题卡，完成后会进入识别结果审查。
                  </div>
                )}
                {project.status === "review_recognition" && (
                  <div className="flex gap-2">
                    <Button variant="secondary" onClick={() => navigate(`/projects/${id}/scoring`)}>审查识别结果</Button>
                  </div>
                )}
                {project.status === "review_scores" && (
                  <Button variant="secondary" onClick={() => navigate(`/projects/${id}/scoring`)}>审查评分</Button>
                )}
                {actionError && (
                  <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-btn">
                    <span className="text-xs text-danger flex-1">{actionError}</span>
                    <button onClick={clearError} className="text-danger text-xs hover:underline flex-shrink-0">关闭</button>
                  </div>
                )}
                {actionMessage && (
                  <div className="flex items-start gap-2 p-3 bg-emerald-50 border border-emerald-200 rounded-btn">
                    <span className="text-emerald-600 text-xs flex-1">{actionMessage}</span>
                    <button onClick={clearMessage} className="text-emerald-600 text-xs hover:underline flex-shrink-0">关闭</button>
                  </div>
                )}
              </div>
            )}

            {phase.phase === 4 && phase.status === "active" && (
              <div className="flex gap-2">
                <Button variant="primary" onClick={() => navigate(`/projects/${id}/scoring`)}>📊 查看报告</Button>
                <Button variant="secondary">📥 导出 JSON</Button>
              </div>
            )}
          </PhaseCard>
        ))}
      </div>
    </div>
  );
}
