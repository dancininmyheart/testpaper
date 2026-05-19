// 与后端 Pydantic schema 一一对应的 TypeScript 类型

export interface ApiResponse<T> {
  ok: true;
  data: T;
}

export interface ApiErrorResponse {
  ok: false;
  error: { code: string; message: string };
}

export type UserInfo = {
  id: number;
  username: string;
  role: string;
};

export type LoginResult = {
  token: string;
  expires_at: string;
  user: UserInfo;
};

export type ProjectData = {
  project_id: string;
  title: string;
  subject: string;
  grade: string;
  status: ProjectStatus;
  student_count: number;
  paper_page_count: number;
  answer_key_source: string;
  error_message: string | null;
  question_count: number;
  reference_answer_count: number;
  created_by: number;
  created_at: string;
  updated_at: string;
};

export type ProjectStatus =
  | "draft"
  | "extracting"
  | "review_questions"
  | "ready"
  | "generating_answers"
  | "review_answers"
  | "recognizing"
  | "review_recognition"
  | "analyzing"
  | "review_scores"
  | "profiling"
  | "completed"
  | "error";

export type JobData = {
  job_id: string;
  student_id: string;
  input_mode: string;
  status: JobStatus;
  attempt_count: number;
  created_at: string;
  updated_at: string;
  error_message: string | null;
  stage_logs?: StageLog[];
};

export type StageLog = {
  stage: string;
  status: string;
  elapsed_ms?: number;
  warnings?: string[];
  error_message?: string;
  [key: string]: unknown;
};

export type JobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "canceled"
  | "unknown";

export type MasteryData = {
  student_id: string;
  skills: SkillMasteryData[];
  skill_count: number;
  weak_count: number;
  average_mastery: number;
};

export type SkillMasteryData = {
  skill_id: string;
  mastery: number;
  level: string;
  uncertainty: number | null;
};

export type GroupExamSummary = {
  paper_id: string;
  problem_count: number;
  skill_count: number;
  skills: GroupSkillRisk[];
};

export type GroupSkillRisk = {
  skill_id: string;
  total_count: number;
  avg_score_ratio: number;
  top_error_type: string;
  risk_level: string;
};

export type ProjectReview = {
  project_id: string;
  question_count: number;
  reference_answer_count: number;
  questions: ReviewQuestion[];
  files: {
    paper_pages: FileRef[];
    answer_key_pages: FileRef[];
  };
};

export type ReviewQuestion = {
  question_id: string;
  question_no: string;
  question_type: string;
  content: string;
  max_score: number | null;
  page_index: number;
  skill_tags: string[];
  reference_answer: ReferenceAnswer | null;
  paper_page_file_id: number | null;
  images?: Array<{ id: number; file_name: string; sort_order: number }>;
};

export type ReferenceAnswer = {
  answer_text: string;
  final_answer: string | null;
  steps: string[];
  source: string;
};

export type FileRef = {
  id: number;
  file_name: string;
  page_index: number;
};

// 状态中文映射
export const STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "成功",
  failed: "失败",
  canceled: "已取消",
  unknown: "未知",
  draft: "草稿",
  extracting: "提取中",
  review_questions: "待审题",
  ready: "试题已确认",
  generating_answers: "生成答案中",
  review_answers: "待审答案",
  recognizing: "识别答题卡中",
  review_recognition: "待审识别结果",
  analyzing: "评分中",
  review_scores: "待审分",
  profiling: "生成画像中",
  completed: "已完成",
  error: "异常",
};
