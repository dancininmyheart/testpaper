interface Props { icon?: string; title: string; description?: string; action?: React.ReactNode; }

export default function EmptyState({ icon = "📭", title, description, action }: Props) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="text-4xl mb-4">{icon}</div>
      <h3 className="text-sm font-semibold text-[var(--color-text)] mb-1">{title}</h3>
      {description && <p className="text-xs text-[var(--color-text-muted)] mb-4 max-w-xs">{description}</p>}
      {action}
    </div>
  );
}
