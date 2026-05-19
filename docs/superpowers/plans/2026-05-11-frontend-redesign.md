# Frontend Redesign Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task.

**Goal:** Restructure frontend to hybrid sidebar/wizard layout with bottom task bar, refactor ProjectDetailPage into focused sub-components

**Architecture:** Keep React + Ant Design + React Query + Zustand. Extract project workflow components from monolithic ProjectDetailPage into `components/project/`. Add BottomTaskBar for real-time progress.

**Tech Stack:** React 18, TypeScript, Ant Design 6, TanStack React Query 5, Zustand 5, Vite 5

---

### Task 1: Refactor AppLayout (compact sidebar + top bar)

**Files:**
- Modify: `frontend/src/components/layout/AppLayout.tsx`

Rewrite to narrow 56px dark sidebar + 48px top bar + placeholder for BottomTaskBar.

```tsx
import { useMemo } from "react";
import { Layout, Tooltip } from "antd";
import {
  DashboardOutlined, FileTextOutlined, BarChartOutlined,
  CheckSquareOutlined, RadarChartOutlined,
} from "@ant-design/icons";
import { Outlet, useNavigate, useLocation } from "react-router-dom";
import { useAuthStore } from "../../stores/authStore";
import BottomTaskBar from "./BottomTaskBar";

const { Content } = Layout;

const NAV_ITEMS = [
  { key: "/", icon: <DashboardOutlined />, label: "仪表盘" },
  { key: "/projects", icon: <FileTextOutlined />, label: "试卷项目" },
  { key: "/tasks", icon: <CheckSquareOutlined />, label: "任务中心" },
  { key: "/reports", icon: <BarChartOutlined />, label: "报告中心" },
  { key: "/mastery", icon: <RadarChartOutlined />, label: "掌握度" },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuthStore();

  const selectedKey = useMemo(() => {
    const path = location.pathname;
    if (path.startsWith("/projects")) return "/projects";
    if (path.startsWith("/tasks")) return "/tasks";
    if (path.startsWith("/reports")) return "/reports";
    if (path.startsWith("/mastery")) return "/mastery";
    return "/";
  }, [location.pathname]);

  return (
    <Layout style={{ minHeight: "100vh", background: "#f5f5f5" }}>
      <div style={{ height: 48, background: "#fff", display: "flex", alignItems: "center", padding: "0 16px", borderBottom: "1px solid #e8e8e8", position: "fixed", top: 0, left: 0, right: 0, zIndex: 100 }}>
        <div style={{ width: 28, height: 28, background: "#115f63", borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 700, fontSize: 12, marginRight: 10 }}>T</div>
        <span style={{ fontWeight: 600, fontSize: 14, color: "#115f63" }}>Testpaper</span>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 13, color: "#666", marginRight: 8 }}>{user?.username}</span>
        <span style={{ fontSize: 11, padding: "1px 6px", borderRadius: 3, background: "#e6f7ff", color: "#115f63", marginRight: 12 }}>{user?.role}</span>
        <div style={{ width: 28, height: 28, borderRadius: "50%", background: "#115f63", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, cursor: "pointer" }} onClick={logout}>
          {user?.username?.charAt(0)?.toUpperCase() || "U"}
        </div>
      </div>

      <div style={{ display: "flex", paddingTop: 48, minHeight: "100vh" }}>
        <div style={{ width: 56, background: "#1a1a2e", position: "fixed", top: 48, left: 0, bottom: 0, zIndex: 99, display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 8 }}>
          {NAV_ITEMS.map((item) => (
            <Tooltip key={item.key} title={item.label} placement="right">
              <div onClick={() => navigate(item.key)} style={{ width: 40, height: 40, borderRadius: 8, marginBottom: 4, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", fontSize: 18, background: selectedKey === item.key ? "rgba(255,255,255,0.15)" : "transparent", color: selectedKey === item.key ? "#fff" : "rgba(255,255,255,0.55)" }}>
                {item.icon}
              </div>
            </Tooltip>
          ))}
          <div style={{ flex: 1 }} />
        </div>

        <div style={{ marginLeft: 56, flex: 1, display: "flex", flexDirection: "column", minHeight: "calc(100vh - 48px)" }}>
          <Content style={{ padding: "20px 24px", flex: 1, maxWidth: 1200 }}>
            <Outlet />
          </Content>
          <BottomTaskBar />
        </div>
      </div>
    </Layout>
  );
}
```

Commit: `git add frontend/src/components/layout/AppLayout.tsx && git commit -m "refactor: redesign AppLayout to hybrid sidebar/topbar layout"`

---

### Task 2: Create BottomTaskBar component

**Files:**
- Create: `frontend/src/components/layout/BottomTaskBar.tsx`

```tsx
import { useTasks } from "../../hooks/useTasks";
import { SyncOutlined } from "@ant-design/icons";
import { Progress } from "antd";

export default function BottomTaskBar() {
  const { data: tasks } = useTasks();
  const activeTasks = (tasks || []).filter(
    (t: { status: string }) => t.status === "queued" || t.status === "running"
  );
  if (activeTasks.length === 0) return null;

  const total = (tasks || []).length;
  const succeeded = (tasks || []).filter(
    (t: { status: string }) => t.status === "succeeded"
  ).length;
  const pct = total > 0 ? Math.round((succeeded / total) * 100) : 0;

  return (
    <div style={{ height: 40, background: "#115f63", color: "#fff", display: "flex", alignItems: "center", gap: 10, padding: "0 20px", fontSize: 13, position: "sticky", bottom: 0, zIndex: 90 }}>
      <SyncOutlined spin style={{ fontSize: 14 }} />
      <span>正在处理中...</span>
      <div style={{ width: 160 }}>
        <Progress percent={pct} showInfo={false} strokeColor="#fff" trailColor="rgba(255,255,255,0.2)" size="small" />
      </div>
      <span style={{ fontSize: 12, opacity: 0.9 }}>{pct}%</span>
      <span style={{ flex: 1 }} />
      <span style={{ fontSize: 12, opacity: 0.9 }}>{activeTasks.length} 个任务进行中</span>
    </div>
  );
}
```

Commit: `git add frontend/src/components/layout/BottomTaskBar.tsx && git commit -m "feat: add BottomTaskBar with real-time progress"`

---

### Task 3: Extract ProcessingProgress component

**Files:**
- Create: `frontend/src/components/project/ProcessingProgress.tsx`

Props: `{ title: string; description: string; stageLogs?: StageLog[] }`

Renders: spinning icon + title + description + indeterminate progress + stage logs table (columns: 阶段名, 状态 Tag, 耗时). Stage names mapped to Chinese labels.

Commit: `git add frontend/src/components/project/ProcessingProgress.tsx && git commit -m "feat: add ProcessingProgress for real-time stage logs"`

---

### Task 4: Extract workflow sub-components from ProjectDetailPage

**Files:**
- Create: `frontend/src/components/project/UploadSection.tsx`
- Create: `frontend/src/components/project/QuestionReview.tsx`
- Create: `frontend/src/components/project/AnswerReview.tsx`
- Create: `frontend/src/components/project/ScoreReview.tsx`
- Create: `frontend/src/components/project/CompletionView.tsx`
- Create: `frontend/src/components/project/AnswerSheetUpload.tsx`

Each component extracts existing code from ProjectDetailPage with its own props interface:
- **UploadSection**: paper/key file Draggers + upload/extract buttons
- **QuestionReview**: editable table + view image + approve
- **AnswerReview**: read-only table with reference answers + approve
- **ScoreReview**: stats cards + score table + approve
- **CompletionView**: completion stats + action buttons
- **AnswerSheetUpload**: single/batch answer sheet upload

Commit: `git add frontend/src/components/project/ && git commit -m "refactor: extract project workflow sub-components"`

---

### Task 5: Simplify ProjectDetailPage with sub-components + new hooks

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Modify: `frontend/src/hooks/useProjects.ts`

**ProjectDetailPage changes:**
- Replace monolithic step rendering with switch on `project.status` importing sub-components
- Steps bar changed to compact pill-style (matching spec)
- New statuses: `generating_answers` → ProcessingProgress, `review_answers` → AnswerReview, `recognizing` → ProcessingProgress, `review_recognition` → AnswerSheetUpload
- STATUS_STEP_MAP and WORKFLOW_STEPS updated to 7 steps

**useProjects.ts additions:**
```ts
export function useTriggerGenerateAnswers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) =>
      fetch(`/api/v1/paper-projects/${projectId}/stage/generate-answers`, { method: "POST" })
        .then(r => { if (!r.ok) throw new Error(); return r.json(); }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useApproveReferenceAnswers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) =>
      fetch(`/api/v1/paper-projects/${projectId}/stage/approve-answers`, { method: "POST" })
        .then(r => { if (!r.ok) throw new Error(); return r.json(); }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["projects"] }); qc.invalidateQueries({ queryKey: ["project-review"] }); },
  });
}
```

Also update `useProject` refetchInterval for new processing statuses:
```ts
refetchInterval: (query) => {
  const p = query.state.data;
  if (!p) return false;
  return ["extracting", "generating_answers", "recognizing", "analyzing"].includes(p.status) ? 2000 : false;
},
```

Commit: `git add frontend/src/pages/ProjectDetailPage.tsx frontend/src/hooks/useProjects.ts && git commit -m "refactor: use sub-components in ProjectDetailPage, add stage hooks"`

---

### Task 6: Redesign ProjectListPage with filter tabs

**Files:**
- Modify: `frontend/src/pages/ProjectListPage.tsx`

Add `Segmented` filter component (全部/进行中/已完成) + `useMemo` for filtered list. Update `STEP_PROGRESS` and `STEP_LABELS` for new statuses.

STEP_PROGRESS additions: generating_answers=45, review_answers=55, recognizing=65, review_recognition=75.

Commit: `git add frontend/src/pages/ProjectListPage.tsx && git commit -m "feat: add status filter to ProjectListPage, update progress map"`

---

### Task 7: Build verification

- [ ] `cd frontend && npx tsc --noEmit --pretty` — clean compile
- [ ] `cd frontend && npm run build` — build succeeds
- [ ] Manual walkthrough of full project workflow on http://localhost:8020
