import { create } from "zustand";
import type { Project, Question, StudentScore, Task } from "./types";

const now = new Date().toISOString();

// Mock page images — placeholder URLs for paper pages
export const mockPageImages: Record<string, string> = {
  "page_0": "data:image/svg+xml," + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect fill="#fff" width="600" height="800"/><rect fill="#f0f0f0" x="40" y="40" width="520" height="30" rx="4"/><rect fill="#f0f0f0" x="40" y="85" width="300" height="18" rx="3"/><rect fill="#f0f0f0" x="40" y="120" width="520" height="120" rx="4"/><rect fill="#eef" x="40" y="260" width="520" height="80" rx="4"/><text fill="#6366f1" font-size="14" font-family="sans-serif" x="60" y="310">📐 三角函数恒等式图</text><rect fill="#f0f0f0" x="40" y="360" width="520" height="80" rx="4"/><rect fill="#f0f0f0" x="40" y="460" width="520" height="80" rx="4"/><text fill="#999" font-size="12" font-family="sans-serif" x="280" y="760">第 1 页</text></svg>`),
  "page_1": "data:image/svg+xml," + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect fill="#fff" width="600" height="800"/><rect fill="#f0f0f0" x="40" y="40" width="520" height="30" rx="4"/><rect fill="#f0f0f0" x="40" y="85" width="200" height="18" rx="3"/><rect fill="#f0f0f0" x="40" y="120" width="520" height="200" rx="4"/><rect fill="#efe" x="40" y="340" width="240" height="160" rx="4"/><text fill="#10b981" font-size="14" font-family="sans-serif" x="70" y="430">📊 函数图像</text><rect fill="#f0f0f0" x="40" y="520" width="520" height="80" rx="4"/><text fill="#999" font-size="12" font-family="sans-serif" x="280" y="760">第 2 页</text></svg>`),
};

// Mock question images — placeholder thumbnails for matched images
export const mockQuestionImages: Record<string, string[]> = {
  "Q1": [
    "data:image/svg+xml," + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="200" height="150"><rect fill="#eef" width="200" height="150" rx="6"/><text fill="#6366f1" font-size="12" font-family="sans-serif" x="40" y="80">三角函数图</text></svg>`),
  ],
  "Q2": [
    "data:image/svg+xml," + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="200" height="150"><rect fill="#efe" width="200" height="150" rx="6"/><text fill="#10b981" font-size="12" font-family="sans-serif" x="50" y="80">函数图像</text></svg>`),
  ],
  "Q3": [],
};

const sampleQuestions: Question[] = [
  {
    question_id: "Q1", question_no: "1", question_type: "choice",
    content: "下列哪个选项是正确的三角函数恒等式？\nA. sin²θ + cos²θ = 1\nB. sin²θ - cos²θ = 1\nC. sin²θ + cos²θ = 0\nD. sinθ + cosθ = 1",
    max_score: 5, page_index: 0, skill_tags: ["三角函数"], sub_questions: [], matched_image_ids: ["三角函数图"],
    reference_answer: { answer_text: "A", final_answer: "A", steps: [{ description: "三角恒等式 sin²θ+cos²θ=1", score: 5 }] },
  },
  {
    question_id: "Q2", question_no: "2", question_type: "fill",
    content: "已知 f(x) = x² + 2x + 1，则 f(3) = ______",
    max_score: 5, page_index: 1, skill_tags: ["函数求值"], sub_questions: [], matched_image_ids: ["函数图像"],
    reference_answer: { answer_text: "16", final_answer: "16", steps: [{ description: "f(3)=3²+2×3+1=9+6+1=16", score: 5 }] },
  },
  {
    question_id: "Q3", question_no: "3", question_type: "solve",
    content: "解方程：2x + 5 = 3x - 1",
    max_score: 10, page_index: 1, skill_tags: ["方程"], sub_questions: [], matched_image_ids: [],
    reference_answer: { answer_text: "x = 6", final_answer: "6", steps: [
      { description: "移项：2x-3x=-1-5", score: 4 },
      { description: "得-x=-6，即x=6", score: 6 },
    ]},
  },
];

const seedProjects: Project[] = [
  {
    project_id: "proj-001", title: "初三数学期中试卷", subject: "数学", grade: "初三",
    status: "review_questions", mode: "standard", question_count: 15, student_count: 0,
    created_at: new Date(Date.now() - 86400000).toISOString(),
  },
  {
    project_id: "proj-002", title: "高二物理月考", subject: "物理", grade: "高二",
    status: "completed", mode: "mineru", question_count: 10, student_count: 42,
    created_at: new Date(Date.now() - 259200000).toISOString(),
  },
  {
    project_id: "proj-003", title: "初一英语单元测试", subject: "英语", grade: "初一",
    status: "draft", mode: "standard", question_count: 0, student_count: 0,
    created_at: new Date(Date.now() - 3600000).toISOString(),
  },
];

const seedTasks: Task[] = [
  { job_id: "job-001", student_id: "张三", project_id: "proj-002", status: "completed", created_at: now, result_summary: "85/100" },
  { job_id: "job-002", student_id: "李四", project_id: "proj-002", status: "completed", created_at: now, result_summary: "92/100" },
];

interface MockStore {
  projects: Project[];
  questions: Record<string, Question[]>;
  scores: Record<string, StudentScore[]>;
  tasks: Task[];

  getProject: (id: string) => Project | undefined;
  listProjects: () => Project[];
  createProject: (title: string, subject: string, grade: string, mode: Project["mode"]) => Project;
  updateProject: (id: string, patch: Partial<Project>) => void;
  deleteProject: (id: string) => void;

  getQuestions: (projectId: string) => Question[];
  updateQuestion: (projectId: string, qid: string, patch: Partial<Question>) => void;

  getTask: (id: string) => Task | undefined;
  listTasks: () => Task[];
}

let nextId = 4;

export const useMockStore = create<MockStore>((set, get) => ({
  projects: [...seedProjects],
  questions: { "proj-001": [...sampleQuestions] },
  scores: {},
  tasks: [...seedTasks],

  getProject: (id) => get().projects.find((p) => p.project_id === id),
  listProjects: () => get().projects,

  createProject: (title, subject, grade, mode) => {
    const project: Project = {
      project_id: `proj-${String(nextId++).padStart(3, "0")}`,
      title, subject, grade, status: "draft", mode,
      question_count: 0, student_count: 0, created_at: new Date().toISOString(),
    };
    set((s) => ({ projects: [...s.projects, project] }));
    return project;
  },

  updateProject: (id, patch) =>
    set((s) => ({
      projects: s.projects.map((p) => (p.project_id === id ? { ...p, ...patch } : p)),
    })),

  deleteProject: (id) =>
    set((s) => ({ projects: s.projects.filter((p) => p.project_id !== id) })),

  getQuestions: (projectId) => get().questions[projectId] || [],

  updateQuestion: (projectId, qid, patch) =>
    set((s) => ({
      questions: {
        ...s.questions,
        [projectId]: (s.questions[projectId] || []).map((q) =>
          q.question_id === qid ? { ...q, ...patch } : q
        ),
      },
    })),

  getTask: (id) => get().tasks.find((t) => t.job_id === id),
  listTasks: () => get().tasks,
}));
