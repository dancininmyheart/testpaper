import { Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAuthStore } from "./stores/authStore";
import AppShell from "./components/layout/AppShell";
import LoginPage from "./pages/LoginPage";
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
import StudentListPage from "./pages/StudentListPage";
import StudentDetailPage from "./pages/StudentDetailPage";
import StudentProjectReportPage from "./pages/StudentProjectReportPage";
import ProjectReportPage from "./pages/ProjectReportPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 10_000, refetchOnWindowFocus: false },
  },
});

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  const initialized = useAuthStore((s) => s.initialized);

  if (!initialized) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-sm text-[var(--color-text-muted)]">加载中...</div>
      </div>
    );
  }
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute><AppShell /></ProtectedRoute>}>
        <Route index element={<Dashboard />} />
        <Route path="projects" element={<ProjectList />} />
        <Route path="projects/new" element={<ProjectCreate />} />
        <Route path="projects/:id" element={<ProjectWorkspace />} />
        <Route path="projects/:id/review" element={<QuestionReview />} />
        <Route path="projects/:id/answers" element={<AnswerReview />} />
        <Route path="projects/:id/scoring" element={<ScoreReview />} />
        <Route path="projects/:id/scoring/:jobId" element={<ScoreReview />} />
        <Route path="students" element={<StudentListPage />} />
        <Route path="students/:studentId" element={<StudentDetailPage />} />
        <Route path="students/:studentId/projects/:projectId" element={<StudentProjectReportPage />} />
        <Route path="tasks" element={<TaskCenter />} />
        <Route path="mastery" element={<MasteryPage />} />
        <Route path="mastery/:studentId" element={<MasteryPage />} />
        <Route path="reports" element={<ReportCenter />} />
        <Route path="reports/:projectId" element={<ProjectReportPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppRoutes />
    </QueryClientProvider>
  );
}
