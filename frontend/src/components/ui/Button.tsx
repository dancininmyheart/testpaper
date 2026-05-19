import { type ButtonHTMLAttributes } from "react";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
}

const variants: Record<string, string> = {
  primary: "bg-primary text-white hover:bg-indigo-600",
  secondary: "bg-white text-primary border border-primary hover:bg-primary-light",
  ghost: "text-[var(--color-text-secondary)] hover:bg-gray-100",
  danger: "bg-danger text-white hover:bg-red-600",
};

const sizes: Record<string, string> = {
  sm: "px-3 py-1.5 text-xs", md: "px-4 py-2 text-sm", lg: "px-6 py-3 text-sm",
};

export default function Button({ variant = "primary", size = "md", className = "", children, ...props }: Props) {
  return (
    <button
      className={`inline-flex items-center gap-1.5 font-medium rounded-btn transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
