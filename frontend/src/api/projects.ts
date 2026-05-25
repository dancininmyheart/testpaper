import { apiDelete, apiGet, apiGetBlob, apiPost, apiPostForm } from "./client";

export interface ProjectData {
  project_id: string;
  title: string;
  subject: string;
  grade: string;
  status: string;
  mode?: string;
  question_count: number;
  student_count: number;
  reference_answer_count?: number;
  created_at: string;
  error_message?: string;
}

export interface ModelProfiles {
  visionProfile: string;
  textProfile: string;
}

export interface ProjectStudentRun {
  job_id: string;
  student_id: string;
  input_mode: string;
  status: string;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  error_message?: string | null;
  has_result: boolean;
}

function appendModelProfileQuery(path: string, profiles?: ModelProfiles): string {
  if (!profiles) return path;
  const params = new URLSearchParams();
  if (profiles.visionProfile) params.set("vision_profile", profiles.visionProfile);
  if (profiles.textProfile) params.set("text_profile", profiles.textProfile);
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

export async function listProjects(): Promise<ProjectData[]> {
  const data = await apiGet<{ items: ProjectData[] }>("/paper-projects?limit=50");
  return data.items;
}

export async function getProject(projectId: string): Promise<ProjectData> {
  return apiGet<ProjectData>(`/paper-projects/${encodeURIComponent(projectId)}`);
}

export async function createProject(
  title: string, subject?: string, grade?: string
): Promise<{ project_id: string; status: string }> {
  return apiPost("/paper-projects", { title, subject: subject || "", grade: grade || "" });
}

export async function uploadProjectFiles(
  projectId: string, paperFiles: File[], answerKeyFiles: File[]
): Promise<{ file_count: number }> {
  const form = new FormData();
  paperFiles.forEach((f) => form.append("paper_files", f));
  answerKeyFiles.forEach((f) => form.append("answer_key_files", f));
  return apiPostForm(`/paper-projects/${encodeURIComponent(projectId)}/files`, form);
}

export async function triggerExtraction(projectId: string, profiles?: ModelProfiles): Promise<{ job_id: string; status: string }> {
  return apiPost(appendModelProfileQuery(`/paper-projects/${encodeURIComponent(projectId)}/extract`, profiles));
}

export async function getProjectReview(projectId: string): Promise<{
  questions: Array<Record<string, unknown>>;
  files: Record<string, Array<Record<string, unknown>>>;
}> {
  return apiGet(`/paper-projects/${encodeURIComponent(projectId)}/review`);
}

export async function getMineruReview(projectId: string): Promise<{
  questions: Array<Record<string, unknown>>;
  files: Record<string, Array<Record<string, unknown>>>;
  source: string;
}> {
  return apiGet(`/paper-projects/${encodeURIComponent(projectId)}/mineru-review`);
}

export async function getProjectFileBlob(projectId: string, fileId: number): Promise<Blob> {
  return apiGetBlob(`/paper-projects/${encodeURIComponent(projectId)}/files/${fileId}/content`);
}

export async function approveQuestions(
  projectId: string, questions?: unknown[]
): Promise<{ status: string }> {
  return apiPost(`/paper-projects/${encodeURIComponent(projectId)}/approve-questions`,
    questions ? { questions } : {});
}

export async function generateReferenceAnswers(projectId: string, profiles?: ModelProfiles): Promise<{ job_id: string; status: string }> {
  return apiPost(appendModelProfileQuery(`/paper-projects/${encodeURIComponent(projectId)}/stage/generate-answers`, profiles));
}

export async function uploadAnswerKeyFiles(
  projectId: string, answerKeyFiles: File[], profiles?: ModelProfiles
): Promise<{ job_id: string; status: string }> {
  const form = new FormData();
  answerKeyFiles.forEach((f) => form.append("answer_key_files", f));
  if (profiles?.visionProfile) form.append("vision_profile", profiles.visionProfile);
  if (profiles?.textProfile) form.append("text_profile", profiles.textProfile);
  return apiPostForm(appendModelProfileQuery(`/paper-projects/${encodeURIComponent(projectId)}/stage/upload-answer-key`, profiles), form);
}

export async function approveReferenceAnswers(projectId: string): Promise<{ status: string }> {
  return apiPost(`/paper-projects/${encodeURIComponent(projectId)}/stage/approve-answers`);
}

export async function approveRecognition(projectId: string): Promise<{ status: string }> {
  return apiPost(`/paper-projects/${encodeURIComponent(projectId)}/stage/approve-recognition`);
}

export async function analyzeAnswerSheet(
  projectId: string, studentId: string, files: File[], profiles?: ModelProfiles
): Promise<{ job_id: string; project_id: string; student_id: string; status: string }> {
  const form = new FormData();
  form.append("student_id", studentId);
  if (profiles?.visionProfile) form.append("vision_profile", profiles.visionProfile);
  if (profiles?.textProfile) form.append("text_profile", profiles.textProfile);
  files.forEach((f) => form.append("answer_sheet_files", f));
  return apiPostForm(`/paper-projects/${encodeURIComponent(projectId)}/analyze-answer-sheet`, form);
}

export async function getScoreReview(projectId: string): Promise<Record<string, unknown>> {
  return apiGet(`/paper-projects/${encodeURIComponent(projectId)}/score-review`);
}

export async function listProjectStudentRuns(projectId: string): Promise<ProjectStudentRun[]> {
  const data = await apiGet<{ items: ProjectStudentRun[] }>(`/paper-projects/${encodeURIComponent(projectId)}/student-runs`);
  return data.items;
}

export async function getStudentRunScoreReview(projectId: string, jobId: string): Promise<Record<string, unknown>> {
  return apiGet(`/paper-projects/${encodeURIComponent(projectId)}/student-runs/${encodeURIComponent(jobId)}/score-review`);
}

export async function getProjectReport(projectId: string): Promise<Record<string, unknown>> {
  return apiGet(`/paper-projects/${encodeURIComponent(projectId)}/report`);
}

export async function approveScores(projectId: string): Promise<{ status: string }> {
  return apiPost(`/paper-projects/${encodeURIComponent(projectId)}/approve-scores`);
}

export async function approveStudentRunScores(
  projectId: string, jobId: string
): Promise<{ project_id: string; job_id: string; student_id: string; status: string }> {
  return apiPost(`/paper-projects/${encodeURIComponent(projectId)}/student-runs/${encodeURIComponent(jobId)}/approve-scores`);
}

export async function deleteProject(projectId: string): Promise<{ deleted: boolean }> {
  const data = await apiDelete<{ deleted: boolean }>(`/paper-projects/${encodeURIComponent(projectId)}`);
  return data;
}

// Exam generation endpoints
export async function generateSimilarPaper(projectId: string): Promise<{ project_id: string; status: string }> {
  return apiPost(`/paper-projects/${encodeURIComponent(projectId)}/generate-similar-paper`);
}

export async function resetProjectToReady(projectId: string): Promise<{ project_id: string; status: string }> {
  return apiPost(`/paper-projects/${encodeURIComponent(projectId)}/reset-to-ready`);
}

export async function downloadGeneratedPaper(projectId: string): Promise<Blob> {
  return apiGetBlob(`/paper-projects/${encodeURIComponent(projectId)}/generated-paper`);
}

export async function fetchGeneratedPaperContent(projectId: string): Promise<{ content: string }> {
  return apiGet(`/paper-projects/${encodeURIComponent(projectId)}/generated-paper/content`);
}

export async function downloadGeneratedPaperPdf(projectId: string): Promise<Blob> {
  return apiGetBlob(`/paper-projects/${encodeURIComponent(projectId)}/generated-paper/pdf`);
}

// MinerU endpoints
const MINERU_REQUEST_TIMEOUT_MS = 1_800_000;

export async function mineruParse(projectId: string, profiles?: ModelProfiles): Promise<{ page_count: number; pages: Array<Record<string, unknown>> }> {
  return apiPost(appendModelProfileQuery(`/paper-projects/${encodeURIComponent(projectId)}/mineru/parse`, profiles), undefined, { timeout: MINERU_REQUEST_TIMEOUT_MS });
}

export async function mineruLlmParse(projectId: string, profiles?: ModelProfiles): Promise<{ question_count: number; questions: Array<Record<string, unknown>> }> {
  return apiPost(appendModelProfileQuery(`/paper-projects/${encodeURIComponent(projectId)}/mineru/llm-parse`, profiles), undefined, { timeout: MINERU_REQUEST_TIMEOUT_MS });
}

export async function mineruTagKnowledge(projectId: string, profiles?: ModelProfiles): Promise<{ question_count: number; tagged_count: number }> {
  return apiPost(appendModelProfileQuery(`/paper-projects/${encodeURIComponent(projectId)}/mineru/tag-knowledge`, profiles), undefined, { timeout: MINERU_REQUEST_TIMEOUT_MS });
}

export async function mineruVlmMatch(projectId: string, profiles?: ModelProfiles): Promise<{ matched_count: number; results: Array<Record<string, unknown>> }> {
  return apiPost(appendModelProfileQuery(`/paper-projects/${encodeURIComponent(projectId)}/mineru/vlm-match`, profiles), undefined, { timeout: MINERU_REQUEST_TIMEOUT_MS });
}

export async function mineruSave(projectId: string): Promise<Record<string, unknown>> {
  return apiPost(`/paper-projects/${encodeURIComponent(projectId)}/mineru/save`, undefined, { timeout: MINERU_REQUEST_TIMEOUT_MS });
}
