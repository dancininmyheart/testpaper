import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getProject,
  getScoreReview,
  getStudentRunScoreReview,
  approveRecognition,
  approveScores,
  approveStudentRunScores,
} from "../api/projects";
import Button from "../components/ui/Button";
import ReportView from "../components/report/ReportView";
import { AlertCircle, ArrowLeft, CheckCircle2, ClipboardCheck, Loader2 } from "lucide-react";

export default function ScoreReview() {
  const { id, jobId } = useParams<{ id: string; jobId?: string }>();
  const queryClient = useQueryClient();
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data: scoreData, isLoading } = useQuery({
    queryKey: ["scores", id, jobId || "project"],
    queryFn: () => jobId ? getStudentRunScoreReview(id!, jobId) : getScoreReview(id!),
    enabled: !!id,
  });

  const { data: project } = useQuery({
    queryKey: ["project", id],
    queryFn: () => getProject(id!),
    enabled: !!id,
  });

  const isRecognitionReview = project?.status === "review_recognition";
  const canApprove = !!jobId || project?.status === "review_recognition" || project?.status === "review_scores";
  const approveLabel = isRecognitionReview ? "确认识别结果并发布" : "确认评分并发布";
  const unavailableReason = !jobId && project && !canApprove
    ? `当前项目状态为 ${project.status}，不能执行项目级评分发布。请从项目工作台的学生批改运行记录进入单个学生作答明细，或等待项目进入待审查评分状态。`
    : "";
  const approveMut = useMutation({
    mutationFn: () => jobId
      ? approveStudentRunScores(id!, jobId)
      : isRecognitionReview ? approveRecognition(id!) : approveScores(id!),
    onMutate: () => {
      setActionMessage(null);
      setActionError(null);
    },
    onSuccess: (data) => {
      const studentId = typeof (data as any)?.student_id === "string" ? (data as any).student_id : "";
      queryClient.invalidateQueries({ queryKey: ["project", id] });
      queryClient.invalidateQueries({ queryKey: ["scores", id, jobId || "project"] });
      queryClient.invalidateQueries({ queryKey: ["project-student-runs", id] });
      if (studentId) {
        queryClient.invalidateQueries({ queryKey: ["student-state", studentId] });
        queryClient.invalidateQueries({ queryKey: ["student-projects", studentId] });
      }
      setActionMessage(
        jobId
          ? "评分已发布，学生学情已更新。"
          : isRecognitionReview
            ? "识别结果已确认，项目已进入评分审查。"
            : "评分已发布，项目报告已生成。"
      );
    },
    onError: (err: any) => {
      setActionError(err?.message || "发布失败，请检查项目状态或后端服务。");
    },
  });

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
        <div className="text-sm text-[var(--color-text-muted)] font-medium">评分审查数据载入中...</div>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <Link to={`/projects/${id}`} className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-700 shadow-sm transition-colors hover:border-primary/30 hover:bg-primary/5 hover:text-primary mb-3">
            <ArrowLeft className="w-4 h-4" /> 返回项目
          </Link>
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center text-primary">
              <ClipboardCheck className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-800 tracking-tight">作答审查</h1>
              <p className="text-xs text-[var(--color-text-muted)] mt-0.5">请仔细核对识别与对错判定结果，确认无误后提交</p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {scoreData && (
            <Button
              variant="primary"
              onClick={() => approveMut.mutate()}
              disabled={approveMut.isPending || !canApprove}
              className="shadow-premium px-6 py-2.5 flex items-center gap-2"
            >
              {approveMut.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>提交确认中...</span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-4 h-4" />
                  <span>{approveLabel}</span>
                </>
              )}
            </Button>
          )}
        </div>
      </div>

      {unavailableReason && (
        <div className="flex items-start gap-2.5 rounded-2xl border border-amber-100 bg-amber-50 px-4 py-3 text-xs font-medium text-amber-700">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{unavailableReason}</span>
        </div>
      )}
      {actionError && (
        <div className="flex items-start gap-2.5 rounded-2xl border border-rose-100 bg-rose-50 px-4 py-3 text-xs font-medium text-rose-700">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{actionError}</span>
        </div>
      )}
      {actionMessage && (
        <div className="flex items-start gap-2.5 rounded-2xl border border-emerald-100 bg-emerald-50 px-4 py-3 text-xs font-medium text-emerald-700">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{actionMessage}</span>
        </div>
      )}

      {scoreData ? (
        <div className="bg-slate-50/40 rounded-3xl p-1.5 border border-slate-100 shadow-sm">
          <ReportView report={scoreData} project={project} mode="review" />
        </div>
      ) : (
        <div className="text-center py-20 bg-white rounded-3xl border border-slate-200/80 shadow-sm flex flex-col items-center justify-center space-y-3">
          <ClipboardCheck className="w-12 h-12 text-slate-300 stroke-[1.5]" />
          <div className="text-sm font-semibold text-slate-600">暂无评分数据</div>
          <p className="text-xs text-[var(--color-text-muted)]">当前项目下暂无可进行评分审查的答题卡</p>
        </div>
      )}
    </div>
  );
}
