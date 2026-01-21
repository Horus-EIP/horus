import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class", ":root"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./contexts/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
    "./ui/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif",
        ],
      },
      colors: {
        background: "rgb(var(--background))",
        foreground: "rgb(var(--foreground))",
        muted: "rgb(var(--background-muted))",
        "muted-foreground": "rgb(var(--foreground-muted))",
      },
      keyframes: {
        "attention-bounce": {
          "0%": { transform: "translateY(0)" },
          "30%": { transform: "translateY(-8px)" },
          "60%": { transform: "translateY(4px)" },
          "100%": { transform: "translateY(0)" },
        },
      },
      animation: {
        "attention-bounce": "attention-bounce 0.6s ease",
      },
      backgroundImage: {
        "brand-gradient":
          "linear-gradient(135deg, rgba(var(--brand-start) / 0.85), rgba(var(--brand-end) / 0.9))",
      },
    },
  },
  plugins: [],
};

export default config;
