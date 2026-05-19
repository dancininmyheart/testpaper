import type { JobData } from "./types";
import { apiGet, apiPost, apiPostForm } from "./client";

export interface CreateTaskPayload {
  studentId: string;
  inputMode: string;
  visionProfile?: string;
  textProfile?: string;
  preSplitQuestions?: string;
  selectedAnswerBlocks?: string;
  paperFiles: File[];
  answerSheetFiles: File[];
  combinedFiles: File[];
  answerKeyFiles: File[];
}

export async function createTask(payload: CreateTaskPayload): Promise<{ job_id: string; status: string }> {
  const form = new FormData();
  form.append("student_id", payload.studentId);
  form.append("input_mode", payload.inputMode);
  if (payload.visionProfile) form.append("vision_profile", payload.visionProfile);
  if (payload.textProfile) form.append("text_profile", payload.textProfile);
  if (payload.preSplitQuestions) form.append("pre_split_questions", payload.preSplitQuestions);
  if (payload.selectedAnswerBlocks) form.append("selected_answer_blocks", payload.selectedAnswerBlocks);
  payload.paperFiles.forEach((f) => form.append("paper_files", f));
  payload.answerSheetFiles.forEach((f) => form.append("answer_sheet_files", f));
  payload.combinedFiles.forEach((f) => form.append("combined_files", f));
  payload.answerKeyFiles.forEach((f) => form.append("answer_key_files", f));
  return apiPostForm("/analysis/jobs", form);
}

export async function listTasks(): Promise<JobData[]> {
  const data = await apiGet<{ items: JobData[] }>("/analysis/jobs?limit=50");
  return data.items;
}

export async function getTask(jobId: string): Promise<JobData> {
  return apiGet<JobData>(`/analysis/jobs/${encodeURIComponent(jobId)}`);
}

export async function retryTask(jobId: string): Promise<JobData> {
  return apiPost<JobData>(`/analysis/jobs/${encodeURIComponent(jobId)}/retry`);
}

export async function getReport(jobId: string): Promise<Record<string, unknown>> {
  return apiGet<Record<string, unknown>>(`/analysis/reports/${encodeURIComponent(jobId)}`);
}

export async function downloadReport(jobId: string, kind: "json" | "pdf"): Promise<void> {
  const response = await fetch(`/api/v1/analysis/reports/${encodeURIComponent(jobId)}/download.${kind}`, {
    headers: { Authorization: `Bearer ${localStorage.getItem("platform_token")}` },
  });
  if (!response.ok) throw new Error("下载失败");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `report.${kind}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
