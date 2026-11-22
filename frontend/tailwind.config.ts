import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#05080F",
          900: "#070B14",
          850: "#0A101C",
          800: "#0C1424",
          700: "#111C30",
          600: "#1B2942",
          500: "#2A3B58",
        },
        mist: {
          100: "#EDF2F9",
          200: "#D8E1EE",
          300: "#AEBCD0",
          400: "#8194AC",
          500: "#64758C",
        },
        accent: {
          DEFAULT: "#38BDF8",
          soft: "#7DD3FC",
          deep: "#0EA5E9",
        },
        good: "#34D399",
        warn: "#FBBF24",
        bad: "#FB7185",
        violet: "#A78BFA",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      borderRadius: {
        xl2: "18px",
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(56,189,248,0.14), 0 18px 50px -30px rgba(56,189,248,0.55)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulseSoft: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.45" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.35s ease-out both",
        "pulse-soft": "pulseSoft 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
