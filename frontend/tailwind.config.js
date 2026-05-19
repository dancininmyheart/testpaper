/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: "#6366f1", light: "#f0f0ff" },
        success: "#10b981",
        warning: "#f59e0b",
        danger: "#ef4444",
      },
      borderRadius: { card: "10px", btn: "8px", pill: "20px" },
    },
  },
  plugins: [],
};
