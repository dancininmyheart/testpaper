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
