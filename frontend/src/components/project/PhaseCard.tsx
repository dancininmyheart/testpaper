import type { PhaseState } from "../../mock/types";
import { Check, Play, Lock } from "lucide-react";

interface Props {
  phase: PhaseState;
  children?: React.ReactNode;
}

export default function PhaseCard({ phase, children }: Props) {
  const isDone = phase.status === "done";
  const isActive = phase.status === "active";
  const isPending = phase.status === "pending";

  return (
    <div className={`border rounded-card p-6 transition-all duration-300 ${
      isActive
        ? "border-primary bg-indigo-50/10 shadow-md ring-1 ring-primary/10"
        : isDone
        ? "border-slate-100 bg-white/60 shadow-premium"
        : "border-slate-100 bg-slate-50/50 opacity-70"
    }`}>
      <div className="flex items-center gap-4">
        {/* Status Indicator */}
        <div className={`w-8 h-8 rounded-xl flex items-center justify-center text-xs font-bold flex-shrink-0 transition-colors duration-300 shadow-sm ${
          isDone
            ? "bg-emerald-500 text-white"
            : isActive
            ? "bg-primary text-white animate-pulse"
            : "bg-slate-200 text-slate-400"
        }`}>
          {isDone ? <Check className="w-4 h-4" /> : isActive ? <Play className="w-3.5 h-3.5 fill-current ml-0.5" /> : <Lock className="w-3.5 h-3.5" />}
        </div>

        {/* Phase Info */}
        <div className="flex-1 min-w-0">
          <div className={`text-sm font-extrabold tracking-tight ${isDone ? "text-slate-400" : "text-slate-700"}`}>
            {phase.label}
          </div>
          {!isDone && !isPending && (
            <div className="text-[11px] text-slate-400 font-semibold mt-0.5 flex items-center gap-2">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary animate-ping" />
              <span>有 {phase.subActions.filter((a) => !a.done).length} 项待处理操作</span>
            </div>
          )}
        </div>

        {/* Badge */}
        <span className={`text-[10px] font-extrabold uppercase tracking-wider px-3 py-1 rounded-pill border ${
          isDone
            ? "bg-emerald-50 text-emerald-600 border-emerald-100"
            : isActive
            ? "bg-indigo-50 text-primary border-indigo-100"
            : "bg-slate-100 text-slate-400 border-slate-200"
        }`}>
          {isDone ? "已完成" : isActive ? "进行中" : "待开始"}
        </span>
      </div>

      {(isActive || isDone) && children && (
        <div className="mt-5 pl-12 border-l-2 border-slate-100/80 ml-4 animate-fadeIn">
          {children}
        </div>
      )}
    </div>
  );
}
