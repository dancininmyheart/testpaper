interface Props { children: React.ReactNode; color?: "green" | "purple" | "gray" | "yellow" | "red"; }

const colors: Record<string, string> = {
  green: "bg-emerald-50 text-emerald-600",
  purple: "bg-primary-light text-primary",
  gray: "bg-gray-100 text-[var(--color-text-muted)]",
  yellow: "bg-amber-50 text-amber-600",
  red: "bg-red-50 text-red-600",
};

export default function Badge({ children, color = "gray" }: Props) {
  return (
    <span className={`inline-block px-2.5 py-0.5 text-[10px] font-medium rounded-pill ${colors[color]}`}>
      {children}
    </span>
  );
}
