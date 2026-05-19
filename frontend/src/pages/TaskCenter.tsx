import EmptyState from "../components/layout/EmptyState";

export default function TaskCenter() {
  return (
    <div>
      <h1 className="text-lg font-bold text-[var(--color-text)] mb-6">任务中心</h1>
      <EmptyState icon="📝" title="暂无任务" description="分析任务将在提交答题卡后自动创建" />
    </div>
  );
}
