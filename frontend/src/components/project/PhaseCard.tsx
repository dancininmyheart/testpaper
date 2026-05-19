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
        <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${
          isDone ? "bg-emerald-500 text-white" :
          isActive ? "bg-primary text-white" :
          "bg-gray-200 text-gray-400"
        }`}>
          {isDone ? "✓" : phase.phase}
        </div>
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
        <span className={`text-[10px] font-medium px-2.5 py-0.5 rounded-pill ${
          isDone ? "bg-emerald-50 text-emerald-600" :
          isActive ? "bg-primary-light text-primary" :
          "bg-gray-100 text-[var(--color-text-muted)]"
        }`}>
          {isDone ? "已完成" : isActive ? "进行中" : "待开始"}
        </span>
      </div>
      {(isActive || isDone) && children && (
        <div className="mt-4 pl-10">{children}</div>
      )}
    </div>
  );
}
