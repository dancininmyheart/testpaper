import { useEffect, useState, useMemo } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Sparkles, Settings, Eye, CheckCircle2, ChevronRight, UploadCloud, Cpu, Award, RefreshCw, FileText, Download } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import { getProject, uploadProjectFiles, uploadAnswerKeyFiles, triggerExtraction, generateReferenceAnswers, analyzeAnswerSheet, listProjectStudentRuns, mineruParse, mineruLlmParse, mineruTagKnowledge, mineruVlmMatch, mineruSave, generateSimilarPaper, downloadGeneratedPaper, fetchGeneratedPaperContent, downloadGeneratedPaperPdf, resetProjectToReady, type ModelProfiles } from "../api/projects";
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
  recognizing: "识别中", review_recognition: "待审查识别结果", review_scores: "待审查作答", completed: "已完成",
  generating_paper: "试卷生成中", paper_ready: "试卷已生成",
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
      return status && ["extracting", "generating_answers", "recognizing", "generating_paper"].includes(status) ? 2000 : false;
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
  const [generatingPaper, setGeneratingPaper] = useState(false);
  const [downloadingPaper, setDownloadingPaper] = useState(false);
  const [resettingToReady, setResettingToReady] = useState(false);

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

  const { data: paperContent } = useQuery({
    queryKey: ["generated-paper-content", id],
    queryFn: () => fetchGeneratedPaperContent(id!),
    enabled: !!id && project?.status === "paper_ready",
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
          { key: "review_scores", label: "审查作答", done: !["review_scores"].includes(st) },
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
    { step: 3, key: "tag", label: "AI 分析知识点", desc: "基于课程图谱和题目内容自动匹配知识点" },
    { step: 4, key: "vlm", label: "VLM 匹配配图", desc: "视觉模型匹配每道题的配图" },
    { step: 5, key: "save", label: "保存结果", desc: "将题目、知识点和配图写入数据库" },
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

      // Step 3: AI Tag Knowledge Points
      await runStep(3, () => mineruTagKnowledge(id!, selectedProfiles));

      // Step 4: VLM image matching (skip if no images on pages)
      const hasImages = parseResult?.pages?.some((p: any) => (p.image_count ?? 0) > 0);
      if (hasImages) {
        await runStep(4, () => mineruVlmMatch(id!, selectedProfiles));
      } else {
        setMineruStep(4);
        setMineruStepStatus((prev) => ({ ...prev, 4: "done" }));
      }

      // Step 5: Save
      await runStep(5, () => mineruSave(id!));
      setActionMessage(`MinerU 智能提取完成！共提取 ${questionCount} 道题，并完成了知识点匹配。请审查试题。`);
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

  const handleGenerateSimilarPaper = async () => {
    setGeneratingPaper(true);
    setActionError(null);
    setActionMessage(null);
    try {
      await generateSimilarPaper(id!);
      setActionMessage("试卷生成已启动，系统正在依次分析知识点、设计情境、生成新题目。请耐心等待...");
      queryClient.invalidateQueries({ queryKey: ["project", id] });
    } catch (e: any) {
      setActionError(e?.message || "试卷生成失败，请检查后端服务是否运行");
    } finally {
      setGeneratingPaper(false);
    }
  };

  const handleResetToReady = async () => {
    setResettingToReady(true);
    setActionError(null);
    setActionMessage(null);
    try {
      await resetProjectToReady(id!);
      setActionMessage("已成功返回批改与分析流程。");
      queryClient.invalidateQueries({ queryKey: ["project", id] });
    } catch (e: any) {
      setActionError(e?.message || "返回分析流程失败，请重试");
    } finally {
      setResettingToReady(false);
    }
  };

  const handleDownloadGeneratedPaper = async () => {
    setDownloadingPaper(true);
    try {
      const blob = await downloadGeneratedPaper(id!);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `generated_exam_${id}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setActionError(e?.message || "下载试卷失败");
    } finally {
      setDownloadingPaper(false);
    }
  };

  const handleDownloadPdf = async () => {
    setDownloadingPaper(true);
    try {
      const blob = await downloadGeneratedPaperPdf(id!);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `generated_exam_${id}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setActionError(e?.message || "下载 PDF 失败");
    } finally {
      setDownloadingPaper(false);
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
    const phase2Done = !["draft","error","extracting","review_questions","generating_answers","review_answers"].includes(project.status);
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
    <div className="space-y-6 animate-fadeIn pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-slate-100 pb-5">
        <div>
          <div className="flex items-center gap-3.5 mb-2">
            <Link
              to="/projects"
              className="w-8 h-8 rounded-full border border-slate-200 flex items-center justify-center text-slate-400 hover:text-slate-700 hover:border-slate-300 transition-all"
            >
              <ArrowLeft className="w-4 h-4" />
            </Link>
            <h1 className="text-xl font-extrabold text-slate-800 tracking-tight">{project.title}</h1>
            <Badge color={project.status === "completed" ? "green" : project.status === "draft" ? "gray" : project.status === "paper_ready" ? "green" : project.status === "generating_paper" ? "yellow" : project.status === "error" ? "red" : "purple"}>
              {STATUS_LABELS[project.status] || project.status}
            </Badge>
          </div>
          <p className="text-xs text-slate-400 font-semibold flex flex-wrap gap-x-3 gap-y-1">
            <span>学科: {project.subject}</span>
            <span>·</span>
            <span>年级: {project.grade}</span>
            <span>·</span>
            <span>创建时间: {project.created_at?.slice(0, 10)}</span>
            {project.question_count > 0 && (
              <>
                <span>·</span>
                <span>试题: {project.question_count} 题</span>
              </>
            )}
            {project.student_count > 0 && (
              <>
                <span>·</span>
                <span>学生: {project.student_count} 名</span>
              </>
            )}
          </p>
          {project.error_message && (
            <p className="text-xs text-red-500 font-medium mt-2 flex items-center gap-1.5 bg-red-50/50 border border-red-100 rounded-lg px-2.5 py-1 w-fit">
              <span>⚠ {project.error_message}</span>
            </p>
          )}
        </div>
        {project.status === "completed" && (
          <Link to={`/projects/${project.project_id}/scoring`}>
            <Button variant="primary" className="shadow-md shadow-indigo-100">
              <Award className="w-4 h-4 mr-1.5" /> 查看学情报告
            </Button>
          </Link>
        )}
        {phase2Done && !["generating_paper","paper_ready"].includes(project.status) && !generatingPaper && (
          <Button variant="secondary" onClick={handleGenerateSimilarPaper} className="border-indigo-200 text-primary">
            <FileText className="w-4 h-4 mr-1.5" />
            生成相似试卷
          </Button>
        )}
        {project.status === "paper_ready" && (
          <div className="flex items-center gap-3">
            <Button variant="secondary" onClick={handleResetToReady} disabled={resettingToReady} className="border-indigo-200 text-primary bg-white hover:bg-slate-50">
              <ArrowLeft className="w-4 h-4 mr-1.5" />
              {resettingToReady ? "返回中..." : "返回批改与分析"}
            </Button>
            <Button variant="primary" onClick={handleDownloadGeneratedPaper} disabled={downloadingPaper} className="shadow-md shadow-emerald-100 bg-emerald-600 hover:bg-emerald-700">
              <Download className="w-4 h-4 mr-1.5" />
              {downloadingPaper ? "下载中..." : "下载生成试卷"}
            </Button>
          </div>
        )}
        {project.status === "generating_paper" && (
          <Button variant="secondary" onClick={handleGenerateSimilarPaper} disabled={generatingPaper} className="bg-amber-50 border-amber-200 text-amber-700 hover:bg-amber-100">
            {generatingPaper ? (
              <><RefreshCw className="w-4 h-4 mr-1.5 animate-spin" /> 试卷生成中…</>
            ) : (
              <><RefreshCw className="w-4 h-4 mr-1.5" /> 重新生成试卷</>
            )}
          </Button>
        )}
      </div>

      {/* Model Profiles selector */}
      <div className="bg-white border border-slate-100 rounded-card p-5 shadow-premium flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-indigo-50 text-primary">
            <Cpu className="w-5 h-5" />
          </div>
          <div>
            <div className="text-sm font-bold text-slate-700">智能引擎配置</div>
            <div className="text-[11px] text-slate-400 font-semibold mt-0.5">
              识别将调用：VLM {selectedProfiles.visionProfile}，LLM {selectedProfiles.textProfile}
            </div>
          </div>
        </div>
        <div className="inline-flex rounded-btn border border-slate-100 bg-slate-50/50 p-1">
          <button
            type="button"
            onClick={() => setSelectedModelMode("fast")}
            className={`px-4 py-2 text-xs font-bold rounded-btn transition-all duration-200 ${
              selectedModelMode === "fast"
                ? "bg-white text-primary shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            快速模式 (Gemini Flash)
          </button>
          <button
            type="button"
            onClick={() => setSelectedModelMode("standard")}
            className={`px-4 py-2 text-xs font-bold rounded-btn transition-all duration-200 ${
              selectedModelMode === "standard"
                ? "bg-white text-primary shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            标准模式 (Gemini Pro)
          </button>
        </div>
      </div>

      {/* Phase cards */}
      <div className="space-y-4">
        {phases.map((phase) => (
          <PhaseCard key={phase.phase} phase={phase}>
            {phase.phase === 1 && phase.status === "active" && !fileUploaded && (
              <div className="space-y-5">
                <div className="grid grid-cols-1 gap-5">
                  <UploadZone label="试卷图片" hint="支持 JPG/PNG，可多张选择" files={paperFiles} onFiles={setPaperFiles} />
                </div>
                <div className="flex items-center gap-3">
                  <Button variant="primary" onClick={handleUpload} disabled={paperFiles.length === 0 || uploading} className="shadow-md shadow-indigo-100">
                    <UploadCloud className="w-4 h-4 mr-1.5" />
                    {uploading ? "正在上传..." : "上传文件并保存"}
                  </Button>
                  {paperFiles.length > 0 && !uploading && (
                    <span className="text-[11px] text-slate-400 font-bold">已选择 {paperFiles.length} 张试卷图片</span>
                  )}
                </div>
                {actionError && (
                  <div className="flex items-start justify-between gap-3 p-3.5 bg-red-50 border border-red-100 rounded-btn text-xs text-red-600 animate-fadeIn">
                    <span className="font-semibold">{actionError}</span>
                    <button onClick={clearError} className="hover:underline font-bold flex-shrink-0">关闭</button>
                  </div>
                )}
              </div>
            )}
            {phase.phase === 1 && uploadSuccess && (
              <div className="flex items-start justify-between gap-3 p-3.5 bg-emerald-50 border border-emerald-100 rounded-btn text-xs text-emerald-700 animate-fadeIn">
                <span className="font-semibold">{actionMessage}</span>
                <button onClick={() => { setUploadSuccess(false); clearMessage(); }} className="hover:underline font-bold flex-shrink-0">确认并关闭</button>
              </div>
            )}

            {(phase.phase === 2 && (phase.status === "active" || phase.status === "done")) && !mineruRunning && (
              <div className="space-y-4">
                {(project.status === "draft" || project.status === "error" || project.status === "extracting" || project.status === "review_questions") && (
                  <div className="flex flex-wrap gap-3">
                    <Button variant="primary" onClick={handleMineru} disabled={extracting} className="shadow-md shadow-indigo-100">
                      <Cpu className="w-4 h-4 mr-1.5" />
                      MinerU 深度视觉分析
                    </Button>
                    {["review_questions"].includes(project.status) && (
                      <Button variant="secondary" onClick={() => navigate(`/projects/${id}/review`)} className="border-indigo-200 text-primary">
                        <Eye className="w-4 h-4 mr-1.5" />
                        审查并核对试题
                      </Button>
                    )}
                  </div>
                )}
                {needsReferenceAnswers && (
                  <div className="space-y-4 border-t border-slate-100 pt-4">
                    <UploadZone label="参考答案图片 / 扫描件" hint="提供已批改好的正确答案图或标准打印版" files={answerKeyFiles} onFiles={setAnswerKeyFiles} />
                    <div className="flex flex-wrap items-center gap-3">
                      <Button variant="primary" onClick={handleUploadAnswerKey} disabled={answerKeyFiles.length === 0 || uploadingAnswerKey} className="shadow-md shadow-indigo-100">
                        <UploadCloud className="w-4 h-4 mr-1.5" />
                        {uploadingAnswerKey ? "正在上传..." : "上传并开始解析参考答案"}
                      </Button>
                      <Button variant="secondary" onClick={handleGenerateReferenceAnswers} disabled={generatingAnswers || uploadingAnswerKey} className="bg-slate-50 border-slate-200 text-slate-700 hover:bg-slate-100">
                        <Sparkles className="w-4 h-4 mr-1.5 text-indigo-500" />
                        {generatingAnswers ? "生成中..." : "由 AI 生成参考答案"}
                      </Button>
                    </div>
                  </div>
                )}
                {project.status === "generating_answers" && (
                  <div className="p-4 bg-indigo-50/50 border border-indigo-100 text-xs text-primary font-semibold rounded-btn animate-pulse">
                    正在分析并整理参考答案，完成后即可进入参考答案校验。请稍候...
                  </div>
                )}
                {project.status === "review_answers" && (
                  <div className="flex flex-wrap gap-3">
                    <Button variant="primary" onClick={() => navigate(`/projects/${id}/answers`)} className="shadow-md shadow-indigo-100">
                      <Eye className="w-4 h-4 mr-1.5" />
                      校验并审核参考答案
                    </Button>
                    <Button variant="secondary" onClick={handleGenerateReferenceAnswers} disabled={generatingAnswers} className="bg-slate-50 border-slate-200 text-slate-600">
                      <RefreshCw className="w-4 h-4 mr-1.5" />
                      {generatingAnswers ? "生成中..." : "重新由 AI 生成"}
                    </Button>
                  </div>
                )}
                {phase.status === "done" && renderInspectionLinks("sm")}
                {actionError && (
                  <div className="flex items-start justify-between gap-3 p-3.5 bg-red-50 border border-red-100 rounded-btn text-xs text-red-600 mt-3 animate-fadeIn">
                    <span className="font-semibold">{actionError}</span>
                    <button onClick={clearError} className="hover:underline font-bold flex-shrink-0">关闭</button>
                  </div>
                )}
                {actionMessage && (
                  <div className="flex items-start justify-between gap-3 p-3.5 bg-emerald-50 border border-emerald-100 rounded-btn text-xs text-emerald-700 mt-3 animate-fadeIn">
                    <span className="font-semibold">{actionMessage}</span>
                    <button onClick={clearMessage} className="hover:underline font-bold flex-shrink-0">关闭</button>
                  </div>
                )}
              </div>
            )}

            {/* MinerU step-by-step progress */}
            {phase.phase === 2 && mineruRunning && (
              <div className="space-y-3 bg-slate-50/80 border border-slate-100 rounded-card p-5 animate-fadeIn">
                <div className="flex items-center justify-between border-b border-slate-100 pb-3 mb-2">
                  <span className="text-xs font-bold text-slate-700 flex items-center gap-2">
                    <span className="inline-block w-2.5 h-2.5 rounded-full bg-primary animate-ping" />
                    <span>🔬 MinerU 视觉识别深度分析中...</span>
                  </span>
                  <span className="text-[10px] text-slate-400 font-bold">请勿关闭本页面</span>
                </div>
                <div className="space-y-2">
                  {MINERU_STEPS.map((s) => {
                    const status = mineruStepStatus[s.step];
                    const isActive = mineruStep === s.step;
                    const isDone = status === "done";
                    const isError = status === "error";
                    return (
                      <div key={s.step}
                        className={`flex items-center gap-4 px-4 py-3 rounded-btn border transition-all duration-300 ${
                          isActive ? "bg-white border-primary/20 shadow-md ring-1 ring-primary/5" :
                          isDone ? "bg-emerald-50/40 border-emerald-100" :
                          isError ? "bg-red-50/40 border-red-100" :
                          "bg-slate-50/30 border-slate-100 opacity-60"
                        }`}>
                        <div className={`w-6 h-6 rounded-lg flex items-center justify-center text-xs font-bold flex-shrink-0 shadow-sm transition-colors duration-300 ${
                          isActive ? "bg-primary text-white animate-pulse" :
                          isDone ? "bg-emerald-500 text-white" :
                          isError ? "bg-red-500 text-white" :
                          "bg-slate-200 text-slate-400"
                        }`}>
                          {isDone ? "✓" : isError ? "✕" : s.step}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className={`text-xs font-bold ${isActive ? "text-primary" : isDone ? "text-emerald-700" : isError ? "text-red-700" : "text-slate-500"}`}>
                            {s.label}
                          </div>
                          <div className="text-[10px] text-slate-400 mt-0.5 font-medium">{s.desc}</div>
                        </div>
                        <span className="text-xs">
                          {isActive && <span className="animate-spin inline-block mr-1">⌛</span>}
                          {isDone && "✅"}
                          {isError && "❌"}
                        </span>
                      </div>
                    );
                  })}
                </div>
                {actionError && (
                  <div className="flex items-start justify-between p-3.5 bg-red-50 border border-red-100 rounded-btn text-xs text-red-600 mt-2">
                    <span className="font-semibold">{actionError}</span>
                    <button onClick={clearError} className="hover:underline font-bold flex-shrink-0">关闭</button>
                  </div>
                )}
              </div>
            )}

            {phase.phase === 3 && phase.status === "active" && (
              <div className="space-y-4">
                {renderInspectionLinks("sm")}
                
                {/* Grading list (student runs) */}
                {studentRuns.length > 0 && (
                  <div className="border border-slate-100 rounded-card bg-white shadow-premium">
                    <div className="px-4 py-3.5 border-b border-slate-100 text-xs font-bold text-slate-600 flex items-center gap-2">
                      <div className="w-1.5 h-3 bg-primary rounded-full" />
                      <span>学生批改运行记录</span>
                    </div>
                    <div className="divide-y divide-slate-50">
                      {studentRuns.map((run) => (
                        <div key={run.job_id} className="flex items-center justify-between gap-4 px-4 py-3.5 text-xs hover:bg-slate-50/50 transition-colors">
                          <div className="min-w-0">
                            <div className="font-bold text-slate-700">
                              学号: {run.student_id || "未指定学号"}
                            </div>
                            <div className="text-slate-400 font-semibold mt-0.5 flex items-center gap-2">
                              <span>状态: {run.status}</span>
                              <span>·</span>
                              <span>时间: {run.finished_at || run.updated_at || run.created_at}</span>
                            </div>
                          </div>
                          <Button
                            variant={run.has_result ? "secondary" : "ghost"}
                            size="sm"
                            onClick={() => navigate(`/projects/${id}/scoring/${run.job_id}`)}
                            disabled={!run.has_result}
                            className={`${run.has_result ? "bg-indigo-50 border-indigo-100 text-primary" : ""}`}
                          >
                            <Eye className="w-3.5 h-3.5 mr-1" />
                            查看作答明细
                          </Button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {canStartGrading && (
                  <div className="space-y-4 border-t border-slate-100 pt-4">
                    <div className="max-w-md">
                      <label className="block text-xs font-bold text-slate-500 mb-2">匹配录入学生</label>
                      <select
                        value={selectedStudentId}
                        onChange={(e) => setSelectedStudentId(e.target.value)}
                        className="w-full px-3.5 py-2.5 border border-slate-200 rounded-btn text-sm outline-none focus:border-primary bg-white shadow-sm font-medium text-slate-700"
                      >
                        {students.map((student) => (
                          <option key={student.student_id} value={student.student_id}>
                            {student.name} ({student.student_id}) · {student.grade || "未设置年级"}
                          </option>
                        ))}
                      </select>
                      {students.length === 0 && (
                        <div className="mt-2 text-xs text-red-500 font-medium">请先至“学生管理”新增学生，再上传对应的答题卡。</div>
                      )}
                    </div>

                    <UploadZone label="学生答题卡图片" hint="支持 JPG/PNG，可上传多页" files={answerSheetFiles} onFiles={setAnswerSheetFiles} />
                    
                    <div className="flex items-center gap-3">
                      <Button variant="primary" onClick={handleAnalyzeAnswerSheet} disabled={answerSheetFiles.length === 0 || !selectedStudentId || analyzingSheet} className="shadow-md shadow-indigo-100">
                        {analyzingSheet ? "正在提交并运行批改..." : "上传并开启答题卡智能识别"}
                      </Button>
                      {answerSheetFiles.length > 0 && !analyzingSheet && (
                        <span className="text-[11px] text-slate-400 font-semibold">已选中 {answerSheetFiles.length} 张图片</span>
                      )}
                    </div>
                  </div>
                )}
                {project.status === "recognizing" && (
                  <div className="p-4 bg-indigo-50/50 border border-indigo-100 text-xs text-primary font-semibold rounded-btn animate-pulse">
                    正在识别并批改学生答题卡，完成后将进入识别结果审查。请稍候...
                  </div>
                )}
                {project.status === "review_recognition" && (
                  <div className="flex gap-3 border-t border-slate-100 pt-4">
                    <Button variant="primary" onClick={() => navigate(`/projects/${id}/scoring`)} className="shadow-md shadow-indigo-100">
                      <Eye className="w-4 h-4 mr-1.5" />
                      核对答题卡识别结果
                    </Button>
                  </div>
                )}
                {project.status === "review_scores" && (
                  <div className="flex gap-3 border-t border-slate-100 pt-4">
                    <Button variant="primary" onClick={() => navigate(`/projects/${id}/scoring`)} className="shadow-md shadow-indigo-100">
                      <Eye className="w-4 h-4 mr-1.5" />
                      审查对错判定
                    </Button>
                  </div>
                )}
                {actionError && (
                  <div className="flex items-start justify-between gap-3 p-3.5 bg-red-50 border border-red-100 rounded-btn text-xs text-red-600 mt-2">
                    <span className="font-semibold">{actionError}</span>
                    <button onClick={clearError} className="hover:underline font-bold flex-shrink-0">关闭</button>
                  </div>
                )}
                {actionMessage && (
                  <div className="flex items-start justify-between gap-3 p-3.5 bg-emerald-50 border border-emerald-100 rounded-btn text-xs text-emerald-700 mt-2">
                    <span className="font-semibold">{actionMessage}</span>
                    <button onClick={clearMessage} className="hover:underline font-bold flex-shrink-0">关闭</button>
                  </div>
                )}
              </div>
            )}

            {phase.phase === 4 && phase.status === "active" && (
              <div className="flex gap-3 flex-wrap">
                <Button variant="primary" onClick={() => navigate(`/projects/${id}/scoring`)} className="shadow-md shadow-indigo-100">
                  <Award className="w-4 h-4 mr-1.5" />
                  查看学情统计报告
                </Button>
                <Button variant="secondary" className="bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100">
                  导出分析数据 (JSON)
                </Button>
              </div>
            )}

            {phase.phase === 2 && project.status === "generating_paper" && (
              <div className="p-5 bg-amber-50/50 border border-amber-100 rounded-card animate-fadeIn space-y-3">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center">
                    <RefreshCw className="w-4 h-4 text-amber-600 animate-spin" />
                  </div>
                  <div>
                    <div className="text-sm font-bold text-amber-700">AI 正在生成相似试卷</div>
                    <div className="text-xs text-amber-500 mt-0.5">系统正在依次：分析知识点 → 设计新情境 → 生成新题目 → 排版组装</div>
                  </div>
                </div>
                <div className="text-[11px] text-amber-600 font-semibold">
                  每题需要约 15-30 秒，共 {project.question_count || 0} 题，请耐心等待...
                </div>
              </div>
            )}

            {phase.phase === 2 && project.status === "paper_ready" && (
              <div className="p-5 bg-emerald-50/50 border border-emerald-100 rounded-card animate-fadeIn space-y-4">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-emerald-100 flex items-center justify-center">
                    <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                  </div>
                  <div>
                    <div className="text-sm font-bold text-emerald-700">试卷已生成</div>
                    <div className="text-xs text-emerald-500 mt-0.5">AI 已根据原始试卷的题型和知识点生成了全新试卷</div>
                  </div>
                </div>

                {paperContent?.content && (
                  <div className="paper-preview bg-white border border-gray-200 rounded-btn p-6 max-h-[500px] overflow-y-auto text-sm leading-relaxed">
                    <ReactMarkdown
                      remarkPlugins={[remarkMath as any]}
                      rehypePlugins={[rehypeKatex as any, rehypeRaw]}
                    >
                      {paperContent.content}
                    </ReactMarkdown>
                  </div>
                )}

                <div className="flex gap-3 flex-wrap items-center">
                  <Button variant="primary" onClick={handleDownloadPdf} disabled={downloadingPaper} className="shadow-md shadow-emerald-100 bg-emerald-600 hover:bg-emerald-700">
                    <Download className="w-4 h-4 mr-1.5" />
                    {downloadingPaper ? "下载中..." : "下载 PDF"}
                  </Button>
                  <Button variant="secondary" onClick={handleDownloadGeneratedPaper} className="bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100">
                    <Download className="w-4 h-4 mr-1.5" />
                    下载 Markdown
                  </Button>
                  <Button variant="ghost" onClick={handleResetToReady} disabled={resettingToReady} className="border-slate-200 text-slate-600 hover:bg-slate-50 md:ml-auto">
                    <ArrowLeft className="w-4 h-4 mr-1.5" />
                    {resettingToReady ? "返回中..." : "返回批改与分析"}
                  </Button>
                </div>
              </div>
            )}
          </PhaseCard>
        ))}
      </div>
    </div>
  );
}
