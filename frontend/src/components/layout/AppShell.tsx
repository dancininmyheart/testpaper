import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { Users, LayoutDashboard, FolderOpen, ClipboardList, LogOut } from "lucide-react";
import { useAuthStore } from "../../stores/authStore";

const NAV_ITEMS = [
  { to: "/", label: "工作台", icon: LayoutDashboard },
  { to: "/projects", label: "项目", icon: FolderOpen },
  { to: "/students", label: "学生管理", icon: Users },
  { to: "/tasks", label: "任务", icon: ClipboardList },
];

export default function AppShell() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const displayName = user?.username || "用户";
  const roleLabel = user?.role === "admin" ? "管理员" : "教师";
  const initials = displayName.slice(0, 2).toUpperCase();

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="flex h-screen bg-[#f8fafc]">
      {/* Sidebar */}
      <aside className="w-[240px] flex-shrink-0 bg-white border-r border-slate-100 flex flex-col p-5 justify-between shadow-premium">
        <div>
          {/* Logo */}
          <div className="flex items-center gap-3 mb-8 px-2.5">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-primary to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-200">
              <span className="text-white font-extrabold text-sm tracking-wider">P</span>
            </div>
            <div>
              <span className="font-extrabold text-sm text-slate-800 tracking-tight">PaperFlow</span>
              <span className="text-[10px] ml-1.5 px-1.5 py-0.2 bg-indigo-50 text-primary font-bold rounded-md">Pro</span>
            </div>
          </div>

          {/* Nav Items */}
          <nav className="flex flex-col gap-1.5">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-3 rounded-btn text-sm font-semibold transition-all duration-200 group ${
                      isActive
                        ? "bg-primary text-white shadow-md shadow-indigo-100"
                        : "text-slate-500 hover:text-slate-800 hover:bg-slate-50"
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon className={`w-4 h-4 transition-colors ${isActive ? "text-white" : "text-slate-400 group-hover:text-slate-600"}`} />
                      <span>{item.label}</span>
                    </>
                  )}
                </NavLink>
              );
            })}
          </nav>
        </div>

        {/* User Card */}
        <div className="border-t border-slate-100 pt-4 mt-auto">
          <div className="flex items-center justify-between p-2 rounded-btn hover:bg-slate-50 transition-colors">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-indigo-100 to-purple-100 flex items-center justify-center text-primary text-xs font-bold font-mono">
                {initials}
              </div>
              <div className="min-w-0">
                <div className="text-xs font-bold text-slate-800 truncate">{displayName}</div>
                <div className="text-[10px] text-slate-400 truncate">{roleLabel}</div>
              </div>
            </div>
            <button
              type="button"
              onClick={handleLogout}
              className="text-slate-400 hover:text-slate-600 transition-colors p-1"
              title="退出"
            >
              <LogOut className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 overflow-auto bg-[#f8fafc]/50 relative">
        <div className="w-full max-w-6xl p-8 mx-auto">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
