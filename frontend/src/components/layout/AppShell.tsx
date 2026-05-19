import { NavLink, Outlet } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/students", label: "学生管理", icon: "👥" },
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
        <div className="w-full max-w-6xl p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
