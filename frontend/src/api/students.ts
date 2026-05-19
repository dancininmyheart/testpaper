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
