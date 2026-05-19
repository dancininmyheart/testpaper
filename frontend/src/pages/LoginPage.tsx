import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "../stores/authStore";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const login = useAuthStore((s) => s.login);
  const navigate = useNavigate();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) return;
    setError("");
    setLoading(true);
    try {
      await login(username, password);
      navigate("/");
    } catch (err: any) {
      setError(err?.message || "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)]">
      <div className="bg-white border border-[var(--color-border)] rounded-card p-8 w-full max-w-sm">
        <div className="flex items-center gap-2.5 mb-8 justify-center">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-primary to-purple-500" />
          <span className="font-bold text-sm text-[var(--color-text)]">PaperFlow</span>
        </div>
        <h2 className="text-base font-bold text-[var(--color-text)] mb-6 text-center">登录</h2>
        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">用户名</label>
            <input value={username} onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2.5 border border-[var(--color-border)] rounded-btn text-sm outline-none focus:border-primary"
              placeholder="admin" autoFocus />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">密码</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2.5 border border-[var(--color-border)] rounded-btn text-sm outline-none focus:border-primary"
              placeholder="••••••" />
          </div>
          {error && <p className="text-xs text-danger">{error}</p>}
          <button type="submit" disabled={loading}
            className="w-full bg-primary text-white font-medium rounded-btn py-2.5 text-sm hover:bg-indigo-600 transition-colors disabled:opacity-50">
            {loading ? "登录中..." : "登录"}
          </button>
        </form>
      </div>
    </div>
  );
}
