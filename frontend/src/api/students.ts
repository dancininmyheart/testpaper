import { apiGet, apiPatch, apiPost } from "./client";

export interface StudentData {
  id: number;
  student_id: string;
  name: string;
  grade: string;
  created_by: number;
  created_at: string;
  updated_at: string;
}

export interface StudentProjectHistory {
  job_id: string;
  student_id: string;
  status: string;
  created_at: string;
  updated_at: string;
  finished_at?: string | null;
  analyzed_at?: string | null;
  project_id: string;
  title: string;
  subject: string;
  grade: string;
  question_count: number;
  student_count: number;
}

export interface StudentStateSummary {
  overall_mastery: number;
  overall_literacy: number;
  risk_level: string;
  exam_count: number;
  weak_skill_count: number;
  strong_skill_count: number;
  recommendations: string[];
}

export interface StudentStateMasteryItem {
  skill_id: string;
  name: string;
  value: number;
  trend: string;
  confidence: number;
  evidence_count: number;
  last_seen_at?: string;
}

export interface StudentStateLiteracyItem {
  literacy_id: string;
  name: string;
  value: number;
  trend: string;
  confidence: number;
  evidence_count: number;
  last_seen_at?: string;
}

export interface StudentStateSnapshot {
  student_id: string;
  summary: StudentStateSummary;
  mastery: StudentStateMasteryItem[];
  literacy: StudentStateLiteracyItem[];
  evidence: Record<string, unknown>;
  source_report_ids: string[];
  source_version: string;
  updated_at: string;
}

export async function listStudents(): Promise<StudentData[]> {
  const data = await apiGet<{ items: StudentData[] }>("/students");
  return data.items;
}

export async function createStudent(payload: {
  student_id: string;
  name: string;
  grade: string;
}): Promise<StudentData> {
  return apiPost<StudentData>("/students", payload);
}

export async function updateStudent(
  studentId: string,
  payload: { name?: string; grade?: string },
): Promise<StudentData> {
  return apiPatch<StudentData>(`/students/${encodeURIComponent(studentId)}`, payload);
}

export async function listStudentProjects(studentId: string): Promise<StudentProjectHistory[]> {
  const data = await apiGet<{ items: StudentProjectHistory[] }>(
    `/students/${encodeURIComponent(studentId)}/projects`,
  );
  return data.items;
}

export async function getStudentProjectReport(
  studentId: string,
  projectId: string,
): Promise<Record<string, unknown>> {
  return apiGet<Record<string, unknown>>(
    `/students/${encodeURIComponent(studentId)}/projects/${encodeURIComponent(projectId)}/report`,
  );
}

export async function getStudentState(studentId: string): Promise<StudentStateSnapshot> {
  return apiGet<StudentStateSnapshot>(`/students/${encodeURIComponent(studentId)}/state`);
}

export async function rebuildStudentState(studentId: string): Promise<StudentStateSnapshot> {
  return apiPost<StudentStateSnapshot>(`/students/${encodeURIComponent(studentId)}/state:rebuild`);
}
