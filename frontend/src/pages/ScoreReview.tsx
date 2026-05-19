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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", id] });
      queryClient.invalidateQueries({ queryKey: ["scores", id, jobId || "project"] });
      queryClient.invalidateQueries({ queryKey: ["project-student-runs", id] });
    },
  });

  if (isLoading) {
    return <div className="flex items-center justify-center py-20"><div className="text-sm text-[var(--color-text-muted)]">加载中...</div></div>;
  }

  return (
    <div className="max-w-5xl mx-auto">
      <Link to={`/projects/${id}`} className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]">← 返回项目</Link>
      <h1 className="text-lg font-bold text-[var(--color-text)] mt-2 mb-6">评分审查</h1>

      {scoreData ? (
        <>
          <ReportView report={scoreData} project={project} mode="review" />
          <div className="flex justify-end gap-2 mt-6">
            <Button variant="primary" onClick={() => approveMut.mutate()} disabled={approveMut.isPending}>
              {approveMut.isPending ? "确认中..." : isRecognitionReview ? "✓ 确认识别结果" : "✓ 确认评分"}
            </Button>
          </div>
        </>
      ) : (
        <div className="text-center py-12 text-sm text-[var(--color-text-muted)]">暂无评分数据</div>
      )}
    </div>
  );
}
