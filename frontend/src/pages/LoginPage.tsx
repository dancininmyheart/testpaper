import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "../stores/authStore";
import { User, Lock, ArrowRight, Loader2, Sparkles } from "lucide-react";

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
      setError(err?.message || "登录失败，请检查用户名或密码");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 via-indigo-50/20 to-purple-50/30 relative overflow-hidden px-4">
      {/* 科技感大光晕背景装饰 */}
      <div className="absolute -top-40 -left-40 w-96 h-96 bg-primary/10 rounded-full blur-3xl pointer-events-none"></div>
      <div className="absolute -bottom-40 -right-40 w-96 h-96 bg-purple-500/10 rounded-full blur-3xl pointer-events-none"></div>
      
      {/* 磨砂玻璃登录卡片 */}
      <div className="bg-white/80 backdrop-blur-xl border border-white/60 rounded-3xl p-8 w-full max-w-[400px] shadow-premium relative z-10 transition-all duration-300 hover:shadow-2xl">
        <div className="flex flex-col items-center mb-8">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-9 h-9 rounded-2xl bg-gradient-to-br from-primary to-indigo-600 flex items-center justify-center shadow-[0_4px_12px_rgba(95,93,236,0.3)]">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <span className="font-extrabold text-base tracking-tight bg-gradient-to-r from-primary to-indigo-700 bg-clip-text text-transparent font-sans">
              PaperFlow
            </span>
          </div>
          <p className="text-xs text-[var(--color-text-muted)] font-medium">大模型试卷智能分析与评分平台</p>
        </div>

        <h2 className="text-base font-bold text-slate-800 mb-6 text-center tracking-tight">教师登录</h2>
        
        <form onSubmit={handleLogin} className="space-y-5">
          {/* 用户名 */}
          <div className="space-y-1.5">
            <label className="block text-xs font-bold text-slate-500 tracking-wider">用户名</label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                <User className="w-4 h-4" />
              </div>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full pl-10 pr-4 py-3 border border-slate-200 rounded-xl text-xs outline-none focus:border-primary focus:ring-4 focus:ring-primary/5 transition-all bg-slate-50/30"
                placeholder="请输入用户名 (如 admin)"
                autoFocus
              />
            </div>
          </div>

          {/* 密码 */}
          <div className="space-y-1.5">
            <label className="block text-xs font-bold text-slate-500 tracking-wider">密码</label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                <Lock className="w-4 h-4" />
              </div>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full pl-10 pr-4 py-3 border border-slate-200 rounded-xl text-xs outline-none focus:border-primary focus:ring-4 focus:ring-primary/5 transition-all bg-slate-50/30"
                placeholder="请输入登录密码"
              />
            </div>
          </div>

          {/* 错误提示 */}
          {error && (
            <div className="text-[11px] bg-rose-50 border border-rose-100 text-rose-700 px-3 py-2 rounded-lg flex items-center gap-1.5 animate-fadeIn">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-500 shrink-0"></span>
              <span>{error}</span>
            </div>
          )}

          {/* 登录按钮 */}
          <button
            type="submit"
            disabled={loading || !username || !password}
            className="w-full bg-gradient-to-r from-primary to-indigo-600 hover:from-indigo-600 hover:to-primary text-white font-semibold rounded-xl py-3 text-xs tracking-wider transition-all duration-300 shadow-premium hover:shadow-[0_8px_20px_rgba(95,93,236,0.25)] hover:-translate-y-0.5 disabled:opacity-50 disabled:pointer-events-none flex items-center justify-center gap-1.5"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>验证登录中...</span>
              </>
            ) : (
              <>
                <span>立即登录</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
