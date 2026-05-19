export interface Project {
  project_id: string;
  title: string;
  subject: string;
  grade: string;
  status: ProjectStatus;
  mode: ExtractionMode;
  question_count: number;
  student_count: number;
  created_at: string;
}

export type ProjectStatus =
  | "draft"
  | "uploaded"
  | "extracting"
  | "review_questions"
  | "generating_answers"
  | "review_answers"
  | "ready"
  | "recognizing"
  | "review_recognition"
  | "review_scores"
  | "completed";

export type ExtractionMode = "standard" | "mineru";

export interface PhaseState {
  phase: number;
  label: string;
  status: "done" | "active" | "pending";
  subActions: SubAction[];
}

export interface SubAction {
  key: string;
  label: string;
  done: boolean;
}

export interface Question {
  question_id: string;
  question_no: string;
  question_type: "choice" | "fill" | "solve" | "essay";
  content: string;
  max_score: number | null;
  page_index: number;
  skill_tags: string[];
  sub_questions: SubQuestion[];
  matched_image_ids: string[];
  reference_answer?: ReferenceAnswer;
}

export interface SubQuestion {
  sub_id: string;
  content: string;
  max_score: number | null;
}

export interface ReferenceAnswer {
  answer_text: string;
  final_answer: string | null;
  steps: AnswerStep[];
}

export interface AnswerStep { description: string; score: number; }

export interface StudentScore {
  student_id: string;
  student_name: string;
  total_score: number;
  max_score: number;
  question_scores: Record<string, number>;
}

export interface Task {
  job_id: string;
  student_id: string;
  project_id: string;
  status: string;
  created_at: string;
  result_summary?: string;
}
