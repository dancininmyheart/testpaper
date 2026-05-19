# 前端重设计 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Tailwind CSS + Zustand + 仿真数据重建 testpaper 前端，阶段卡片驱动的项目 workspace，模式优先设计

**Architecture:** 单页应用，React Router 管理路由，Zustand 管理 mock 数据状态，`api/` 层暂用 mock 实现，后端接入时替换。左侧导航 + 右侧工作区布局，项目内用阶段卡片组织

**Tech Stack:** React 18 + TypeScript + Vite 5 + Tailwind CSS 3 + Zustand 5 + React Router 6 + Axios

---

## 文件结构

```
frontend/
├── src/
│   ├── main.tsx                     # 入口
│   ├── App.tsx                      # 路由配置
│   ├── index.css                    # Tailwind directives + 自定义变量
│   ├── mock/
│   │   ├── data.ts                  # 仿真数据 + Zustand mockStore
│   │   └── types.ts                 # 领域类型定义
│   ├── stores/
│   │   └── authStore.ts             # 认证状态（保留结构，mock 模式始终已登录）
│   ├── api/
│   │   ├── client.ts                # HTTP 客户端（mock 模式短路）
│   │   ├── projects.ts             # 项目 API（mock 调用 store）
│   │   └── tasks.ts                # 任务 API（mock 调用 store）
│   ├── components/
│   │   ├── layout/
│   │   │   ├── AppShell.tsx         # 左侧导航 + Outlet
│   │   │   └── EmptyState.tsx       # 空状态占位
│   │   ├── project/
│   │   │   ├── PhaseCard.tsx        # 阶段卡片
│   │   │   └── UploadZone.tsx       # 文件拖拽上传
│   │   └── ui/
│   │       ├── Button.tsx           # 按钮
│   │       └── Badge.tsx            # 状态徽章
│   └── pages/
│       ├── Dashboard.tsx
│       ├── ProjectList.tsx
│       ├── ProjectCreate.tsx
│       ├── ProjectWorkspace.tsx
│       ├── QuestionReview.tsx
│       ├── AnswerReview.tsx
│       ├── ScoreReview.tsx
│       ├── TaskCenter.tsx
│       ├── MasteryPage.tsx
│       └── ReportCenter.tsx
```

---

## Phase 1: Foundation

### Task 1: Install Tailwind CSS & remove Ant Design

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/postcss.config.js`
- Create: `frontend/tailwind.config.js`

- [ ] **Step 1: Install Tailwind and uninstall Antd**

```bash
cd frontend
npm uninstall antd
npm install -D tailwindcss@3 postcss autoprefixer
npx tailwindcss init -p
```

- [ ] **Step 2: Configure tailwind.config.js**

Write `frontend/tailwind.config.js`:

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: "#6366f1", light: "#f0f0ff" },
        success: "#10b981",
        warning: "#f59e0b",
        danger: "#ef4444",
      },
      borderRadius: { card: "10px", btn: "8px", pill: "20px" },
    },
  },
  plugins: [],
};
```

- [ ] **Step 3: Write index.css**

Write `frontend/src/index.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --color-primary: #6366f1;
  --color-primary-light: #f0f0ff;
  --color-success: #10b981;
  --color-warning: #f59e0b;
  --color-danger: #ef4444;
  --color-text: #111827;
  --color-text-secondary: #6b7280;
  --color-text-muted: #9ca3af;
  --color-border: #e5e7eb;
  --color-bg: #fafbfc;
}

body {
  font-family: -apple-system, "Segoe UI", "PingFang SC", "Noto Sans SC", sans-serif;
  color: var(--color-text);
  background: var(--color-bg);
  margin: 0;
}
```

- [ ] **Step 4: Verify setup**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No errors related to missing antd imports.

### Task 2: Create mock data store

**Files:**
- Create: `frontend/src/mock/types.ts`
- Create: `frontend/src/mock/data.ts`

- [ ] **Step 1: Write domain types**

Write `frontend/src/mock/types.ts`:

```typescript
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
```

- [ ] **Step 2: Write mock data and store**

Write `frontend/src/mock/data.ts`:

```typescript
import { create } from "zustand";
import type { Project, Question, StudentScore, Task } from "./types";

// ── seed data ──

const now = new Date().toISOString();

const sampleQuestions: Question[] = [
  {
    question_id: "Q1", question_no: "1", question_type: "choice",
    content: "下列哪个选项是正确的三角函数恒等式？\nA. sin²θ + cos²θ = 1\nB. sin²θ - cos²θ = 1\nC. sin²θ + cos²θ = 0\nD. sinθ + cosθ = 1",
    max_score: 5, page_index: 0, skill_tags: ["三角函数"], sub_questions: [], matched_image_ids: [],
    reference_answer: { answer_text: "A", final_answer: "A", steps: [{ description: "三角恒等式 sin²θ+cos²θ=1", score: 5 }] },
  },
  {
    question_id: "Q2", question_no: "2", question_type: "fill",
    content: "已知 f(x) = x² + 2x + 1，则 f(3) = ______",
    max_score: 5, page_index: 0, skill_tags: ["函数求值"], sub_questions: [], matched_image_ids: [],
    reference_answer: { answer_text: "16", final_answer: "16", steps: [{ description: "f(3)=3²+2×3+1=9+6+1=16", score: 5 }] },
  },
  {
    question_id: "Q3", question_no: "3", question_type: "solve",
    content: "解方程：2x + 5 = 3x - 1",
    max_score: 10, page_index: 0, skill_tags: ["方程"], sub_questions: [], matched_image_ids: [],
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

// ── store ──

interface MockStore {
  projects: Project[];
  questions: Record<string, Question[]>;
  scores: Record<string, StudentScore[]>;
  tasks: Task[];

  // Project
  getProject: (id: string) => Project | undefined;
  listProjects: () => Project[];
  createProject: (title: string, subject: string, grade: string, mode: Project["mode"]) => Project;
  updateProject: (id: string, patch: Partial<Project>) => void;
  deleteProject: (id: string) => void;

  // Questions
  getQuestions: (projectId: string) => Question[];
  updateQuestion: (projectId: string, qid: string, patch: Partial<Question>) => void;

  // Tasks
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
```

### Task 3: Rewrite App.tsx entry & AppShell

**Files:**
- Rewrite: `frontend/src/main.tsx`
- Rewrite: `frontend/src/App.tsx`
- Create: `frontend/src/components/layout/AppShell.tsx`

- [ ] **Step 1: Write main.tsx**

Write `frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
```

- [ ] **Step 2: Write AppShell component**

Write `frontend/src/components/layout/AppShell.tsx`:

```tsx
import { NavLink, Outlet } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "工作台", icon: "📊" },
  { to: "/projects", label: "项目", icon: "📁" },
  { to: "/tasks", label: "任务", icon: "📝" },
  { to: "/mastery", label: "学情追踪", icon: "📈" },
  { to: "/reports", label: "报告中心", icon: "📋" },
];

export default function AppShell() {
  return (
    <div className="flex h-screen bg-[var(--color-bg)]">
      {/* Sidebar */}
      <aside className="w-[220px] flex-shrink-0 bg-white border-r border-[var(--color-border)] flex flex-col p-4">
        <div className="flex items-center gap-2.5 mb-8 px-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-primary to-purple-500" />
          <span className="font-bold text-sm text-[var(--color-text)]">PaperFlow</span>
        </div>
        <nav className="flex flex-col gap-1 flex-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-2.5 rounded-btn text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-primary-light text-primary"
                    : "text-[var(--color-text-secondary)] hover:bg-gray-50"
                }`
              }
            >
              <span>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="text-xs text-[var(--color-text-muted)] px-3 py-2">
          👤 张老师
        </div>
      </aside>
      {/* Main */}
      <main className="flex-1 overflow-auto">
        <div className="max-w-6xl mx-auto p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
```

- [ ] **Step 3: Write App.tsx**

Write `frontend/src/App.tsx`:

```tsx
import { Routes, Route } from "react-router-dom";
import AppShell from "./components/layout/AppShell";
import Dashboard from "./pages/Dashboard";
import ProjectList from "./pages/ProjectList";
import ProjectCreate from "./pages/ProjectCreate";
import ProjectWorkspace from "./pages/ProjectWorkspace";
import QuestionReview from "./pages/QuestionReview";
import AnswerReview from "./pages/AnswerReview";
import ScoreReview from "./pages/ScoreReview";
import TaskCenter from "./pages/TaskCenter";
import MasteryPage from "./pages/MasteryPage";
import ReportCenter from "./pages/ReportCenter";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Dashboard />} />
        <Route path="projects" element={<ProjectList />} />
        <Route path="projects/new" element={<ProjectCreate />} />
        <Route path="projects/:id" element={<ProjectWorkspace />} />
        <Route path="projects/:id/review" element={<QuestionReview />} />
        <Route path="projects/:id/answers" element={<AnswerReview />} />
        <Route path="projects/:id/scoring" element={<ScoreReview />} />
        <Route path="tasks" element={<TaskCenter />} />
        <Route path="mastery" element={<MasteryPage />} />
        <Route path="mastery/:studentId" element={<MasteryPage />} />
        <Route path="reports" element={<ReportCenter />} />
      </Route>
    </Routes>
  );
}
```

- [ ] **Step 4: Clean old files, verify compilation**

```bash
cd frontend
rm -f src/pages/LoginPage.tsx src/pages/TaskListPage.tsx src/pages/TaskDetailPage.tsx src/pages/ProjectDetailPage.tsx
rm -rf src/components/common src/components/layout/AppLayout.tsx
rm -f src/stores/uiStore.ts src/hooks/useProjects.ts src/hooks/useTasks.ts src/hooks/useMastery.ts
npx tsc --noEmit
```

Expected: No errors.

### Task 4: Create UI primitives

**Files:**
- Create: `frontend/src/components/ui/Button.tsx`
- Create: `frontend/src/components/ui/Badge.tsx`
- Create: `frontend/src/components/layout/EmptyState.tsx`

- [ ] **Step 1: Write Button**

Write `frontend/src/components/ui/Button.tsx`:

```tsx
import { type ButtonHTMLAttributes } from "react";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
}

const variants: Record<string, string> = {
  primary: "bg-primary text-white hover:bg-indigo-600",
  secondary: "bg-white text-primary border border-primary hover:bg-primary-light",
  ghost: "text-[var(--color-text-secondary)] hover:bg-gray-100",
  danger: "bg-danger text-white hover:bg-red-600",
};

const sizes: Record<string, string> = {
  sm: "px-3 py-1.5 text-xs", md: "px-4 py-2 text-sm", lg: "px-6 py-3 text-sm",
};

export default function Button({ variant = "primary", size = "md", className = "", children, ...props }: Props) {
  return (
    <button
      className={`inline-flex items-center gap-1.5 font-medium rounded-btn transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
```

- [ ] **Step 2: Write Badge**

Write `frontend/src/components/ui/Badge.tsx`:

```tsx
interface Props { children: React.ReactNode; color?: "green" | "purple" | "gray" | "yellow" | "red"; }

const colors: Record<string, string> = {
  green: "bg-emerald-50 text-emerald-600",
  purple: "bg-primary-light text-primary",
  gray: "bg-gray-100 text-[var(--color-text-muted)]",
  yellow: "bg-amber-50 text-amber-600",
  red: "bg-red-50 text-red-600",
};

export default function Badge({ children, color = "gray" }: Props) {
  return (
    <span className={`inline-block px-2.5 py-0.5 text-[10px] font-medium rounded-pill ${colors[color]}`}>
      {children}
    </span>
  );
}
```

- [ ] **Step 3: Write EmptyState**

Write `frontend/src/components/layout/EmptyState.tsx`:

```tsx
interface Props { icon?: string; title: string; description?: string; action?: React.ReactNode; }

export default function EmptyState({ icon = "📭", title, description, action }: Props) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="text-4xl mb-4">{icon}</div>
      <h3 className="text-sm font-semibold text-[var(--color-text)] mb-1">{title}</h3>
      {description && <p className="text-xs text-[var(--color-text-muted)] mb-4 max-w-xs">{description}</p>}
      {action}
    </div>
  );
}
```

- [ ] **Step 4: Verify**

```bash
cd frontend && npx tsc --noEmit
```

---

## Phase 2: Core pages

### Task 5: Dashboard

**Files:**
- Create: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Write Dashboard**

Write `frontend/src/pages/Dashboard.tsx`:

```tsx
import { Link } from "react-router-dom";
import { useMockStore } from "../mock/data";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";

export default function Dashboard() {
  const projects = useMockStore((s) => s.projects);
  const tasks = useMockStore((s) => s.tasks);
  const completed = projects.filter((p) => p.status === "completed").length;
  const inProgress = projects.filter((p) => p.status !== "completed" && p.status !== "draft").length;

  return (
    <div>
      <h1 className="text-lg font-bold text-[var(--color-text)] mb-6">工作台</h1>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        {[
          { label: "项目总数", value: projects.length, color: "text-primary" },
          { label: "进行中", value: inProgress, color: "text-amber-500" },
          { label: "已完成", value: completed, color: "text-emerald-500" },
          { label: "分析任务", value: tasks.length, color: "text-violet-500" },
        ].map((s) => (
          <div key={s.label} className="bg-white border border-[var(--color-border)] rounded-card p-4">
            <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
            <div className="text-xs text-[var(--color-text-muted)] mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Recent projects */}
        <div className="col-span-2">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-[var(--color-text)]">最近项目</h2>
            <Link to="/projects" className="text-xs text-primary hover:underline">查看全部</Link>
          </div>
          <div className="space-y-2">
            {projects.slice(0, 3).map((p) => (
              <Link key={p.project_id} to={`/projects/${p.project_id}`}
                className="block bg-white border border-[var(--color-border)] rounded-card p-4 hover:shadow-sm hover:border-primary/30 transition-all">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-[var(--color-text)]">{p.title}</div>
                    <div className="text-xs text-[var(--color-text-muted)] mt-0.5">
                      {p.subject} · {p.grade} · {p.mode === "mineru" ? "MinerU" : "标准提取"}
                    </div>
                  </div>
                  <Badge color={p.status === "completed" ? "green" : p.status === "draft" ? "gray" : "purple"}>
                    {p.status === "completed" ? "已完成" : p.status === "draft" ? "草稿" : "进行中"}
                  </Badge>
                </div>
              </Link>
            ))}
          </div>
        </div>

        {/* Quick actions */}
        <div>
          <h2 className="text-sm font-semibold text-[var(--color-text)] mb-3">快速操作</h2>
          <div className="space-y-2">
            <Link to="/projects/new">
              <Button className="w-full justify-center" variant="primary">+ 新建项目</Button>
            </Link>
            <Link to="/reports">
              <Button className="w-full justify-center" variant="secondary">📋 查看报告</Button>
            </Link>
            <Link to="/mastery">
              <Button className="w-full justify-center" variant="secondary">📈 学情追踪</Button>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd frontend && npx tsc --noEmit
```

### Task 6: ProjectList

**Files:**
- Create: `frontend/src/pages/ProjectList.tsx`

- [ ] **Step 1: Write ProjectList**

Write `frontend/src/pages/ProjectList.tsx`:

```tsx
import { Link } from "react-router-dom";
import { useMockStore } from "../mock/data";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import EmptyState from "../components/layout/EmptyState";

const STATUS_MAP: Record<string, { label: string; color: "green" | "purple" | "gray" | "yellow" }> = {
  draft: { label: "草稿", color: "gray" },
  extracting: { label: "提取中", color: "purple" },
  review_questions: { label: "待审查", color: "yellow" },
  ready: { label: "就绪", color: "purple" },
  completed: { label: "已完成", color: "green" },
};

export default function ProjectList() {
  const projects = useMockStore((s) => s.projects);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-bold text-[var(--color-text)]">项目</h1>
        <Link to="/projects/new">
          <Button variant="primary">+ 新建项目</Button>
        </Link>
      </div>

      {projects.length === 0 ? (
        <EmptyState icon="📁" title="暂无项目" description="创建第一个项目，开始分析试卷" action={<Link to="/projects/new"><Button variant="primary">+ 新建项目</Button></Link>} />
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {projects.map((p) => {
            const st = STATUS_MAP[p.status] || { label: p.status, color: "gray" as const };
            return (
              <Link key={p.project_id} to={`/projects/${p.project_id}`}
                className="block bg-white border border-[var(--color-border)] rounded-card p-5 hover:shadow-sm hover:border-primary/30 transition-all">
                <div className="flex items-start justify-between mb-3">
                  <div className="font-semibold text-sm text-[var(--color-text)]">{p.title}</div>
                  <Badge color={st.color}>{st.label}</Badge>
                </div>
                <div className="flex items-center gap-4 text-xs text-[var(--color-text-muted)]">
                  <span>{p.subject || "未设置学科"}</span>
                  <span>{p.grade || "未设置年级"}</span>
                  <span>{p.mode === "mineru" ? "🔬 MinerU" : "🤖 标准AI"}</span>
                  {p.question_count > 0 && <span>{p.question_count} 题</span>}
                  {p.student_count > 0 && <span>{p.student_count} 名学生</span>}
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd frontend && npx tsc --noEmit
```

### Task 7: ProjectCreate (two-step)

**Files:**
- Create: `frontend/src/pages/ProjectCreate.tsx`

- [ ] **Step 1: Write ProjectCreate**

Write `frontend/src/pages/ProjectCreate.tsx`:

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMockStore } from "../mock/data";
import Button from "../components/ui/Button";
import type { ExtractionMode } from "../mock/types";

export default function ProjectCreate() {
  const navigate = useNavigate();
  const createProject = useMockStore((s) => s.createProject);
  const [step, setStep] = useState<1 | 2>(1);
  const [title, setTitle] = useState("");
  const [subject, setSubject] = useState("");
  const [grade, setGrade] = useState("");
  const [mode, setMode] = useState<ExtractionMode>("standard");

  const handleCreate = () => {
    if (!title.trim()) return;
    const proj = createProject(title.trim(), subject, grade, mode);
    navigate(`/projects/${proj.project_id}`);
  };

  return (
    <div className="max-w-lg mx-auto">
      {/* Step indicator */}
      <div className="flex items-center justify-center gap-3 mb-8">
        <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${step >= 1 ? "bg-primary text-white" : "bg-gray-200 text-gray-400"}`}>1</div>
        <div className={`w-8 h-0.5 ${step >= 2 ? "bg-primary" : "bg-gray-200"}`} />
        <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${step >= 2 ? "bg-primary text-white" : "bg-gray-200 text-gray-400"}`}>2</div>
      </div>

      {step === 1 && (
        <div className="bg-white border border-[var(--color-border)] rounded-card p-8">
          <h2 className="text-base font-bold text-[var(--color-text)] mb-6">创建新项目</h2>
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">项目名称 *</label>
              <input value={title} onChange={(e) => setTitle(e.target.value)}
                className="w-full px-3 py-2.5 border border-[var(--color-border)] rounded-btn text-sm outline-none focus:border-primary focus:ring-1 focus:ring-primary/20"
                placeholder="例如：初三数学期中试卷" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">学科</label>
                <select value={subject} onChange={(e) => setSubject(e.target.value)}
                  className="w-full px-3 py-2.5 border border-[var(--color-border)] rounded-btn text-sm outline-none focus:border-primary">
                  <option value="">选择学科</option>
                  {["语文","数学","英语","物理","化学","生物","历史","地理","政治"].map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">年级</label>
                <select value={grade} onChange={(e) => setGrade(e.target.value)}
                  className="w-full px-3 py-2.5 border border-[var(--color-border)] rounded-btn text-sm outline-none focus:border-primary">
                  <option value="">选择年级</option>
                  {["初一","初二","初三","高一","高二","高三"].map((g) => <option key={g} value={g}>{g}</option>)}
                </select>
              </div>
            </div>
          </div>
          <div className="flex justify-end mt-8">
            <Button onClick={() => { if (title.trim()) setStep(2); }} variant="primary">下一步</Button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="bg-white border border-[var(--color-border)] rounded-card p-8">
          <h2 className="text-base font-bold text-[var(--color-text)] mb-2">选择提取方式</h2>
          <p className="text-xs text-[var(--color-text-muted)] mb-6">不同的提取方式适用于不同的试卷类型</p>
          <div className="grid grid-cols-2 gap-4 mb-8">
            <button onClick={() => setMode("standard")}
              className={`text-left p-5 rounded-card border-2 transition-all ${
                mode === "standard" ? "border-primary bg-primary-light" : "border-[var(--color-border)] hover:border-gray-300"
              }`}>
              <div className="text-2xl mb-2">🤖</div>
              <div className="font-semibold text-sm mb-1">标准 AI 提取</div>
              <div className="text-xs text-[var(--color-text-muted)] leading-relaxed">AI 自动识别试卷图片中的试题和答案区域，提取后人工审查确认。</div>
              <div className="mt-3">
                <span className="text-[10px] bg-primary-light text-primary px-2 py-0.5 rounded-pill font-medium">推荐 · 适合大多数场景</span>
              </div>
            </button>
            <button onClick={() => setMode("mineru")}
              className={`text-left p-5 rounded-card border-2 transition-all ${
                mode === "mineru" ? "border-primary bg-primary-light" : "border-[var(--color-border)] hover:border-gray-300"
              }`}>
              <div className="text-2xl mb-2">🔬</div>
              <div className="font-semibold text-sm mb-1">MinerU 智能提取</div>
              <div className="text-xs text-[var(--color-text-muted)] leading-relaxed">使用 MinerU OCR 引擎精准解析，适合复杂排版、含图表的试卷。</div>
              <div className="mt-3">
                <span className="text-[10px] bg-gray-100 text-[var(--color-text-muted)] px-2 py-0.5 rounded-pill font-medium">需配置 MinerU 服务</span>
              </div>
            </button>
          </div>
          <div className="flex justify-between">
            <Button onClick={() => setStep(1)} variant="ghost">← 返回</Button>
            <Button onClick={handleCreate} variant="primary">创建项目</Button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd frontend && npx tsc --noEmit
```

---

## Phase 3: Project workspace

### Task 8: PhaseCard component

**Files:**
- Create: `frontend/src/components/project/PhaseCard.tsx`

- [ ] **Step 1: Write PhaseCard**

Write `frontend/src/components/project/PhaseCard.tsx`:

```tsx
import type { PhaseState } from "../../mock/types";

interface Props {
  phase: PhaseState;
  children?: React.ReactNode;
}

export default function PhaseCard({ phase, children }: Props) {
  const isDone = phase.status === "done";
  const isActive = phase.status === "active";

  return (
    <div className={`border rounded-card p-4 transition-all ${
      isActive ? "border-primary bg-primary-light/30 ring-1 ring-primary/20" :
      isDone ? "border-emerald-200 bg-gray-50/50" :
      "border-[var(--color-border)] bg-white"
    }`}>
      <div className="flex items-center gap-3">
        {/* Status circle */}
        <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${
          isDone ? "bg-emerald-500 text-white" :
          isActive ? "bg-primary text-white" :
          "bg-gray-200 text-gray-400"
        }`}>
          {isDone ? "✓" : phase.phase}
        </div>
        {/* Label */}
        <div className="flex-1 min-w-0">
          <div className={`text-sm font-semibold ${isDone ? "text-[var(--color-text-muted)]" : "text-[var(--color-text)]"}`}>
            {phase.label}
          </div>
          {!isDone && (
            <div className="text-xs text-[var(--color-text-muted)] mt-0.5">
              {phase.subActions.filter((a) => !a.done).length} 项待处理
            </div>
          )}
        </div>
        {/* Status badge */}
        <span className={`text-[10px] font-medium px-2.5 py-0.5 rounded-pill ${
          isDone ? "bg-emerald-50 text-emerald-600" :
          isActive ? "bg-primary-light text-primary" :
          "bg-gray-100 text-[var(--color-text-muted)]"
        }`}>
          {isDone ? "已完成" : isActive ? "进行中" : "待开始"}
        </span>
      </div>
      {/* Expanded content */}
      {isActive && children && (
        <div className="mt-4 pl-10">{children}</div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd frontend && npx tsc --noEmit
```

### Task 9: UploadZone component

**Files:**
- Create: `frontend/src/components/project/UploadZone.tsx`

- [ ] **Step 1: Write UploadZone**

Write `frontend/src/components/project/UploadZone.tsx`:

```tsx
import { useState, type DragEvent } from "react";
import Button from "../ui/Button";

interface Props {
  label: string;
  hint: string;
  files: File[];
  onFiles: (files: File[]) => void;
}

export default function UploadZone({ label, hint, files, onFiles }: Props) {
  const [dragging, setDragging] = useState(false);

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const dropped = Array.from(e.dataTransfer.files);
    onFiles([...files, ...dropped]);
  };

  return (
    <div>
      <div className="text-xs font-medium text-[var(--color-text-secondary)] mb-2">{label}</div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`border-2 border-dashed rounded-card p-6 text-center transition-colors ${
          dragging ? "border-primary bg-primary-light/50" : "border-[var(--color-border)] hover:border-gray-300"
        }`}
      >
        <div className="text-2xl mb-2">📤</div>
        <p className="text-xs text-[var(--color-text-muted)] mb-1">拖拽文件到此处</p>
        <p className="text-[10px] text-[var(--color-text-muted)] mb-3">{hint}</p>
        <label>
          <Button variant="secondary" size="sm" onClick={() => {}}>选择文件</Button>
          <input type="file" multiple accept="image/*" className="hidden"
            onChange={(e) => {
              const selected = Array.from(e.target.files || []);
              onFiles([...files, ...selected]);
            }} />
        </label>
      </div>
      {files.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {files.map((f, i) => (
            <span key={i} className="inline-flex items-center gap-1 px-2 py-1 bg-gray-100 rounded text-xs text-[var(--color-text-secondary)]">
              {f.name}
              <button className="text-gray-400 hover:text-danger" onClick={() => onFiles(files.filter((_, j) => j !== i))}>×</button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd frontend && npx tsc --noEmit
```

### Task 10: ProjectWorkspace page

**Files:**
- Create: `frontend/src/pages/ProjectWorkspace.tsx`

- [ ] **Step 1: Write ProjectWorkspace**

Write `frontend/src/pages/ProjectWorkspace.tsx`:

```tsx
import { useState, useMemo } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useMockStore } from "../mock/data";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import PhaseCard from "../components/project/PhaseCard";
import UploadZone from "../components/project/UploadZone";
import type { PhaseState } from "../mock/types";

export default function ProjectWorkspace() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const project = useMockStore((s) => s.projects.find((p) => p.project_id === id));
  const updateProject = useMockStore((s) => s.updateProject);
  const [paperFiles, setPaperFiles] = useState<File[]>([]);

  const phases: PhaseState[] = useMemo(() => {
    if (!project) return [];
    const isStandard = project.mode === "standard";

    return [
      {
        phase: 1, label: `阶段一 · 准备`,
        status: project.status === "draft" ? "active" : "done",
        subActions: [
          { key: "upload_paper", label: "上传试卷图片", done: project.status !== "draft" },
          { key: "upload_key", label: "上传答案图片（可选）", done: project.status !== "draft" },
        ],
      },
      {
        phase: 2, label: isStandard ? "阶段二 · 提取与审查" : "阶段二 · MinerU 提取",
        status: project.status === "draft" ? "pending"
          : ["extracting","review_questions","generating_answers","review_answers"].includes(project.status) ? "active"
          : "done",
        subActions: isStandard
          ? [
              { key: "extract", label: "AI 提取试题", done: project.status !== "draft" && project.status !== "extracting" },
              { key: "review_q", label: "审查试题", done: project.status !== "draft" && project.status !== "extracting" && project.status !== "review_questions" },
              { key: "review_a", label: "审查参考答案", done: ["ready","recognizing","review_scores","completed"].includes(project.status) },
            ]
          : [
              { key: "mineru1", label: "MinerU 解析试卷", done: project.status !== "draft" },
              { key: "mineru2", label: "LLM 整理题目", done: project.status !== "draft" },
              { key: "mineru3", label: "VLM 匹配配图", done: project.status !== "draft" },
              { key: "mineru4", label: "保存结果", done: project.status !== "draft" },
            ],
      },
      {
        phase: isStandard ? 3 : 4, label: `阶段${isStandard ? "三" : "四"} · 批改`,
        status: ["ready","recognizing","review_scores"].includes(project.status) ? "active"
          : project.status === "completed" ? "done" : "pending",
        subActions: [
          { key: "upload_sheets", label: "上传学生答题卡", done: project.status !== "ready" },
          { key: "review_scores", label: "审查评分", done: project.status === "completed" },
        ],
      },
      {
        phase: isStandard ? 4 : 5, label: `阶段${isStandard ? "四" : "五"} · 报告`,
        status: project.status === "completed" ? "active" : "pending",
        subActions: [
          { key: "view_report", label: "查看成绩报告", done: false },
          { key: "export", label: "导出报告", done: false },
        ],
      },
    ];
  }, [project]);

  if (!project) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <p className="text-sm text-[var(--color-text-muted)] mb-4">项目不存在</p>
        <Link to="/projects"><Button variant="secondary">返回项目列表</Button></Link>
      </div>
    );
  }

  const handleUpload = () => {
    if (paperFiles.length === 0) return;
    updateProject(project.project_id, { status: "review_questions", question_count: 15 });
  };

  const handleStartExtract = () => {
    updateProject(project.project_id, { status: "extracting" });
    setTimeout(() => updateProject(project.project_id, { status: "review_questions", question_count: 15 }), 2000);
  };

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <Link to="/projects" className="text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors">←</Link>
            <h1 className="text-lg font-bold text-[var(--color-text)]">{project.title}</h1>
            <Badge color={project.status === "completed" ? "green" : project.status === "draft" ? "gray" : "purple"}>
              {project.mode === "mineru" ? "🔬 MinerU" : "🤖 标准"}
            </Badge>
          </div>
          <p className="text-xs text-[var(--color-text-muted)]">
            {project.subject} · {project.grade} · 创建于 {project.created_at.slice(0, 10)}
            {project.question_count > 0 && ` · ${project.question_count} 题`}
          </p>
        </div>
        {project.status === "completed" && (
          <Link to={`/projects/${project.project_id}/scoring`}>
            <Button variant="primary">📊 查看报告</Button>
          </Link>
        )}
      </div>

      {/* Phase cards */}
      <div className="space-y-3">
        {phases.map((phase) => (
          <PhaseCard key={phase.phase} phase={phase}>
            {/* Phase 1: Upload */}
            {phase.phase === 1 && phase.status === "active" && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-6">
                  <UploadZone label="试卷图片" hint="支持 JPG/PNG，可多选" files={paperFiles} onFiles={setPaperFiles} />
                  <UploadZone label="标准答案（可选）" hint="提供更精准的参考答案" files={[]} onFiles={() => {}} />
                </div>
                <Button variant="primary" onClick={handleUpload} disabled={paperFiles.length === 0}>上传文件</Button>
              </div>
            )}

            {/* Phase 2: Extract & Review */}
            {(phase.phase === 2) && phase.status === "active" && project.mode === "standard" && (
              <div className="flex gap-2">
                <Button variant="primary" onClick={handleStartExtract}>🔍 AI 提取试题</Button>
                {project.status === "review_questions" && (
                  <Button variant="secondary" onClick={() => navigate(`/projects/${project.project_id}/review`)}>审查试题</Button>
                )}
                {["ready","recognizing","review_scores","completed"].includes(project.status) && (
                  <Button variant="secondary" onClick={() => navigate(`/projects/${project.project_id}/answers`)}>审查答案</Button>
                )}
              </div>
            )}
            {phase.phase === 2 && phase.status === "active" && project.mode === "mineru" && (
              <Button variant="primary" onClick={handleStartExtract}>🔬 启动 MinerU 智能提取</Button>
            )}

            {/* Phase 3/4: Scoring */}
            {(phase.phase === 3 || phase.phase === 4) && phase.status === "active" && phase.label.includes("批改") && (
              <div className="flex gap-2">
                <Button variant="primary">📝 上传答题卡</Button>
                {project.status === "review_scores" && (
                  <Button variant="secondary" onClick={() => navigate(`/projects/${project.project_id}/scoring`)}>审查评分</Button>
                )}
              </div>
            )}

            {/* Last phase: Report */}
            {(phase.phase === 4 || phase.phase === 5) && phase.status === "active" && phase.label.includes("报告") && (
              <div className="flex gap-2">
                <Button variant="primary" onClick={() => navigate(`/projects/${project.project_id}/scoring`)}>📊 查看报告</Button>
                <Button variant="secondary">📥 导出 JSON</Button>
                <Button variant="secondary">📥 导出 PDF</Button>
              </div>
            )}
          </PhaseCard>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd frontend && npx tsc --noEmit
```

---

## Phase 4: Review pages

### Task 11: QuestionReview page

**Files:**
- Create: `frontend/src/pages/QuestionReview.tsx`

- [ ] **Step 1: Write QuestionReview**

Write `frontend/src/pages/QuestionReview.tsx`:

```tsx
import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useMockStore } from "../mock/data";
import Button from "../components/ui/Button";
import Badge from "../components/ui/Badge";
import type { Question } from "../mock/types";

export default function QuestionReview() {
  const { id } = useParams<{ id: string }>();
  const project = useMockStore((s) => s.projects.find((p) => p.project_id === id));
  const questions = useMockStore((s) => s.getQuestions(id || ""));
  const updateQuestion = useMockStore((s) => s.updateQuestion);
  const updateProject = useMockStore((s) => s.updateProject);
  const [selectedQ, setSelectedQ] = useState<string | null>(questions[0]?.question_id || null);

  const current = questions.find((q) => q.question_id === selectedQ);

  const typeLabel: Record<string, string> = {
    choice: "选择题", fill: "填空题", solve: "解答题", essay: "作文题",
  };

  return (
    <div className="flex gap-0 h-[calc(100vh-100px)]">
      {/* Left: question list */}
      <div className="w-64 flex-shrink-0 border-r border-[var(--color-border)] overflow-auto bg-white rounded-l-card">
        <div className="p-4 border-b border-[var(--color-border)]">
          <Link to={`/projects/${id}`} className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]">← 返回项目</Link>
          <h2 className="text-sm font-bold text-[var(--color-text)] mt-2">试题审查</h2>
          <p className="text-[10px] text-[var(--color-text-muted)]">{questions.length} 道题</p>
        </div>
        <div className="p-2">
          {questions.map((q) => (
            <button key={q.question_id} onClick={() => setSelectedQ(q.question_id)}
              className={`w-full text-left px-3 py-2.5 rounded-btn text-xs mb-1 transition-colors ${
                selectedQ === q.question_id ? "bg-primary-light text-primary font-medium" : "text-[var(--color-text-secondary)] hover:bg-gray-50"
              }`}>
              <span className="text-[var(--color-text-muted)]">Q{q.question_no}.</span> {q.content.slice(0, 20)}...
              <Badge color="purple">{typeLabel[q.question_type] || q.question_type}</Badge>
            </button>
          ))}
        </div>
      </div>

      {/* Right: question detail */}
      <div className="flex-1 overflow-auto bg-white rounded-r-card p-6">
        {current ? (
          <div>
            <div className="flex items-center gap-2 mb-4">
              <span className="text-sm font-bold text-[var(--color-text)]">第 {current.question_no} 题</span>
              <Badge color="purple">{typeLabel[current.question_type]}</Badge>
              {current.max_score && <span className="text-xs text-[var(--color-text-muted)]">{current.max_score} 分</span>}
            </div>

            {/* Question content */}
            <div className="mb-6">
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-2">题目内容</label>
              <textarea value={current.content} onChange={(e) => updateQuestion(id!, current.question_id, { content: e.target.value })}
                className="w-full min-h-[120px] px-3 py-2.5 border border-[var(--color-border)] rounded-btn text-sm outline-none focus:border-primary resize-y" />
            </div>

            {/* Reference answer */}
            {current.reference_answer && (
              <div className="mb-6 p-4 bg-gray-50 rounded-card border border-[var(--color-border)]">
                <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-2">参考答案</label>
                <p className="text-sm text-[var(--color-text)] whitespace-pre-wrap">{current.reference_answer.answer_text}</p>
                {current.reference_answer.final_answer && (
                  <p className="text-xs text-[var(--color-text-muted)] mt-2">最终答案：{current.reference_answer.final_answer}</p>
                )}
                {current.reference_answer.steps.length > 0 && (
                  <div className="mt-3 space-y-1">
                    {current.reference_answer.steps.map((step, i) => (
                      <div key={i} className="text-xs text-[var(--color-text-secondary)] flex justify-between">
                        <span>{step.description}</span>
                        <span className="text-[var(--color-text-muted)]">{step.score} 分</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Actions */}
            <div className="flex justify-between border-t border-[var(--color-border)] pt-4 mt-6">
              <Button variant="ghost" onClick={() => {
                const idx = questions.findIndex((q) => q.question_id === current.question_id);
                if (idx > 0) setSelectedQ(questions[idx - 1].question_id);
              }}>← 上一题</Button>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm">标记有问题</Button>
                <Button variant="primary" size="sm" onClick={() => {
                  const idx = questions.findIndex((q) => q.question_id === current.question_id);
                  if (idx < questions.length - 1) setSelectedQ(questions[idx + 1].question_id);
                  else {
                    updateProject(id!, { status: "ready" });
                  }
                }}>✓ 确认</Button>
              </div>
              <Button variant="ghost" onClick={() => {
                const idx = questions.findIndex((q) => q.question_id === current.question_id);
                if (idx < questions.length - 1) setSelectedQ(questions[idx + 1].question_id);
              }}>下一题 →</Button>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-sm text-[var(--color-text-muted)]">选择一道题目开始审查</div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd frontend && npx tsc --noEmit
```

### Task 12: AnswerReview, ScoreReview (lightweight)

**Files:**
- Create: `frontend/src/pages/AnswerReview.tsx`
- Create: `frontend/src/pages/ScoreReview.tsx`

- [ ] **Step 1: Write AnswerReview**

Write `frontend/src/pages/AnswerReview.tsx`:

```tsx
import { useParams, Link } from "react-router-dom";
import { useMockStore } from "../mock/data";
import Button from "../components/ui/Button";

export default function AnswerReview() {
  const { id } = useParams<{ id: string }>();
  const questions = useMockStore((s) => s.getQuestions(id || ""));

  return (
    <div className="max-w-3xl mx-auto">
      <Link to={`/projects/${id}`} className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]">← 返回项目</Link>
      <h1 className="text-lg font-bold text-[var(--color-text)] mt-2 mb-6">审查参考答案</h1>
      <div className="space-y-3">
        {questions.map((q) => (
          <div key={q.question_id} className="bg-white border border-[var(--color-border)] rounded-card p-4">
            <div className="text-sm font-medium text-[var(--color-text)] mb-2">Q{q.question_no}. {q.content.slice(0, 60)}{q.content.length > 60 ? "..." : ""}</div>
            <div className="bg-gray-50 rounded-btn p-3 text-xs text-[var(--color-text-secondary)]">
              <span className="font-medium">参考答案：</span>
              {q.reference_answer?.answer_text || "尚未生成"}
            </div>
          </div>
        ))}
      </div>
      <div className="flex justify-end mt-6">
        <Button variant="primary">✓ 全部确认</Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Write ScoreReview**

Write `frontend/src/pages/ScoreReview.tsx`:

```tsx
import { useParams, Link } from "react-router-dom";
import { useMockStore } from "../mock/data";
import Button from "../components/ui/Button";

const MOCK_STUDENTS = [
  { id: "S1", name: "张三", scores: { Q1: 5, Q2: 4, Q3: 8 }, total: 17, max: 20 },
  { id: "S2", name: "李四", scores: { Q1: 5, Q2: 5, Q3: 10 }, total: 20, max: 20 },
  { id: "S3", name: "王五", scores: { Q1: 3, Q2: 5, Q3: 6 }, total: 14, max: 20 },
];

export default function ScoreReview() {
  const { id } = useParams<{ id: string }>();

  return (
    <div className="max-w-4xl mx-auto">
      <Link to={`/projects/${id}`} className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]">← 返回项目</Link>
      <h1 className="text-lg font-bold text-[var(--color-text)] mt-2 mb-6">评分审查</h1>

      {/* Summary */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        {[
          { label: "学生数", value: MOCK_STUDENTS.length },
          { label: "平均分", value: `${Math.round(MOCK_STUDENTS.reduce((s, st) => s + st.total, 0) / MOCK_STUDENTS.length * 10) / 10}/${MOCK_STUDENTS[0].max}` },
          { label: "最高分", value: `${Math.max(...MOCK_STUDENTS.map((s) => s.total))}/${MOCK_STUDENTS[0].max}` },
        ].map((s) => (
          <div key={s.label} className="bg-white border border-[var(--color-border)] rounded-card p-4">
            <div className="text-2xl font-bold text-primary">{s.value}</div>
            <div className="text-xs text-[var(--color-text-muted)] mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Student scores table */}
      <div className="bg-white border border-[var(--color-border)] rounded-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-[var(--color-border)]">
            <tr>
              <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">学生</th>
              <th className="text-center px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">Q1</th>
              <th className="text-center px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">Q2</th>
              <th className="text-center px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">Q3</th>
              <th className="text-right px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">总分</th>
            </tr>
          </thead>
          <tbody>
            {MOCK_STUDENTS.map((st) => (
              <tr key={st.id} className="border-b border-[var(--color-border)] last:border-0">
                <td className="px-4 py-3 font-medium text-[var(--color-text)]">{st.name}</td>
                <td className="text-center px-4 py-3 text-[var(--color-text-secondary)]">{st.scores.Q1}</td>
                <td className="text-center px-4 py-3 text-[var(--color-text-secondary)]">{st.scores.Q2}</td>
                <td className="text-center px-4 py-3 text-[var(--color-text-secondary)]">{st.scores.Q3}</td>
                <td className="text-right px-4 py-3 font-semibold text-[var(--color-text)]">{st.total}/{st.max}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex justify-end gap-2 mt-6">
        <Button variant="secondary">📥 导出 JSON</Button>
        <Button variant="secondary">📥 导出 PDF</Button>
        <Button variant="primary">✓ 确认评分</Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify**

```bash
cd frontend && npx tsc --noEmit
```

---

## Phase 5: Secondary pages

### Task 13: TaskCenter, ReportCenter, MasteryPage

**Files:**
- Create: `frontend/src/pages/TaskCenter.tsx`
- Create: `frontend/src/pages/ReportCenter.tsx`
- Create: `frontend/src/pages/MasteryPage.tsx`

- [ ] **Step 1: Write TaskCenter**

Write `frontend/src/pages/TaskCenter.tsx`:

```tsx
import { useMockStore } from "../mock/data";
import Badge from "../components/ui/Badge";
import EmptyState from "../components/layout/EmptyState";

export default function TaskCenter() {
  const tasks = useMockStore((s) => s.tasks);

  return (
    <div>
      <h1 className="text-lg font-bold text-[var(--color-text)] mb-6">任务中心</h1>
      {tasks.length === 0 ? (
        <EmptyState icon="📝" title="暂无任务" description="分析任务将在提交答题卡后自动创建" />
      ) : (
        <div className="space-y-2">
          {tasks.map((t) => (
            <div key={t.job_id} className="bg-white border border-[var(--color-border)] rounded-card p-4 flex items-center justify-between">
              <div>
                <div className="text-sm font-medium text-[var(--color-text)]">学生 {t.student_id}</div>
                <div className="text-xs text-[var(--color-text-muted)] mt-0.5">{t.job_id} · {t.created_at.slice(0, 16)}</div>
              </div>
              <div className="flex items-center gap-3">
                {t.result_summary && <span className="text-sm font-semibold text-primary">{t.result_summary}</span>}
                <Badge color={t.status === "completed" ? "green" : "purple"}>{t.status === "completed" ? "已完成" : "处理中"}</Badge>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Write ReportCenter**

Write `frontend/src/pages/ReportCenter.tsx`:

```tsx
import { useMockStore } from "../mock/data";
import Button from "../components/ui/Button";
import EmptyState from "../components/layout/EmptyState";

export default function ReportCenter() {
  const projects = useMockStore((s) => s.projects.filter((p) => p.status === "completed"));

  return (
    <div>
      <h1 className="text-lg font-bold text-[var(--color-text)] mb-6">报告中心</h1>
      {projects.length === 0 ? (
        <EmptyState icon="📋" title="暂无报告" description="完成项目评分后将自动生成报告" />
      ) : (
        <div className="space-y-3">
          {projects.map((p) => (
            <div key={p.project_id} className="bg-white border border-[var(--color-border)] rounded-card p-4 flex items-center justify-between">
              <div>
                <div className="text-sm font-medium text-[var(--color-text)]">{p.title}</div>
                <div className="text-xs text-[var(--color-text-muted)] mt-0.5">
                  {p.subject} · {p.grade} · {p.question_count} 题 · {p.student_count} 名学生
                </div>
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm">📥 JSON</Button>
                <Button variant="secondary" size="sm">📥 PDF</Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Write MasteryPage**

Write `frontend/src/pages/MasteryPage.tsx`:

```tsx
import { useParams } from "react-router-dom";
import EmptyState from "../components/layout/EmptyState";

const MOCK_SKILLS = [
  { name: "三角函数", level: 0.85, trend: "up" },
  { name: "函数求值", level: 0.72, trend: "stable" },
  { name: "解方程", level: 0.60, trend: "up" },
  { name: "几何证明", level: 0.45, trend: "down" },
];

export default function MasteryPage() {
  const { studentId } = useParams<{ studentId?: string }>();

  return (
    <div>
      <h1 className="text-lg font-bold text-[var(--color-text)] mb-6">{studentId ? `${studentId} · 学情详情` : "学情追踪"}</h1>
      {!studentId ? (
        <EmptyState icon="📈" title="学情追踪" description="选择一个学生查看掌握度详情" />
      ) : (
        <div className="space-y-3">
          {MOCK_SKILLS.map((skill) => (
            <div key={skill.name} className="bg-white border border-[var(--color-border)] rounded-card p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-[var(--color-text)]">{skill.name}</span>
                <span className="text-xs font-semibold text-primary">{Math.round(skill.level * 100)}%</span>
              </div>
              <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
                <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${skill.level * 100}%` }} />
              </div>
              <span className="text-[10px] text-[var(--color-text-muted)] mt-1 inline-block">
                {skill.trend === "up" ? "📈 上升" : skill.trend === "down" ? "📉 下降" : "➡️ 稳定"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Verify**

```bash
cd frontend && npx tsc --noEmit
```

---

## Phase 6: Final cleanup & build

### Task 14: Clean up old files, verify build

- [ ] **Step 1: Remove old Antd-dependent files**

```bash
cd frontend
rm -rf src/components/common
rm -f src/components/layout/AppLayout.tsx
rm -rf src/hooks
rm -f src/stores/uiStore.ts
rm -f src/api/auth.ts src/api/mastery.ts
rm -f src/pages/LoginPage.tsx src/pages/TaskListPage.tsx src/pages/TaskDetailPage.tsx src/pages/ProjectDetailPage.tsx
rm -f src/pages/DashboardPage.tsx src/pages/ProjectListPage.tsx src/pages/ReportCenterPage.tsx src/pages/MasteryPage.tsx
```

- [ ] **Step 2: Update index.html title**

Modify `frontend/index.html`: change `<title>` to `<title>PaperFlow</title>`

- [ ] **Step 3: Full build check**

```bash
cd frontend
npm run build
```

Expected: Build succeeds with no errors.

- [ ] **Step 4: Start dev server and verify**

```bash
cd frontend
npm run dev
```

Open http://localhost:5173, verify:
- Dashboard loads with stats and project list
- Project list shows 3 seed projects
- Project create (two-step) works
- Project workspace shows phase cards
- Question review works
- Navigation between pages works
