/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: "#5f5dec",
          hover: "#4846d1",
          light: "rgba(95, 93, 236, 0.07)",
        },
        success: {
          DEFAULT: "#10b981",
          light: "rgba(16, 185, 129, 0.08)",
        },
        warning: {
          DEFAULT: "#f59e0b",
          light: "rgba(245, 158, 11, 0.08)",
        },
        danger: {
          DEFAULT: "#ef4444",
          light: "rgba(239, 68, 68, 0.08)",
        },
      },
      borderRadius: {
        card: "16px",
        btn: "10px",
        pill: "9999px",
      },
      boxShadow: {
        premium: "0 8px 30px rgba(0, 0, 0, 0.03)",
        glass: "0 8px 32px 0 rgba(95, 93, 236, 0.04)",
        cardHover: "0 20px 25px -5px rgba(95, 93, 236, 0.06), 0 8px 10px -6px rgba(95, 93, 236, 0.04)",
      },
    },
  },
  plugins: [],
};
