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
import { ArrowLeft, CheckCircle2, ClipboardCheck, Loader2 } from "lucide-react";

export default function ScoreReview() {
  const { id, jobId } = useParams<{ id: string; jobId?: string }>();
  const queryClient = useQueryClient();

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
  const approveMut = useMutation({
    mutationFn: () => jobId
      ? approveStudentRunScores(id!, jobId)
      : isRecognitionReview ? approveRecognition(id!) : approveScores(id!),
    onSuccess: (data) => {
      const studentId = typeof (data as any)?.student_id === "string" ? (data as any).student_id : "";
      queryClient.invalidateQueries({ queryKey: ["project", id] });
      queryClient.invalidateQueries({ queryKey: ["scores", id, jobId || "project"] });
      queryClient.invalidateQueries({ queryKey: ["project-student-runs", id] });
      if (studentId) {
        queryClient.invalidateQueries({ queryKey: ["student-state", studentId] });
        queryClient.invalidateQueries({ queryKey: ["student-projects", studentId] });
      }
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
          <Link to={`/projects/${id}`} className="inline-flex items-center gap-1 text-xs text-[var(--color-text-muted)] hover:text-primary transition-colors mb-2">
            <ArrowLeft className="w-3.5 h-3.5" /> 返回项目
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
              disabled={approveMut.isPending}
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
                  <span>{isRecognitionReview ? "确认识别结果并发布" : "确认评分并发布"}</span>
                </>
              )}
            </Button>
          )}
        </div>
      </div>

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
