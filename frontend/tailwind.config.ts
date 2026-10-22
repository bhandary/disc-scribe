import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#F3F6F2",
        foreground: "#1A211C",
        vinyl: {
          gold: "#1F2A24",
          silver: "#6B7A72",
          obsidian: "#F7FAF6",
        },
        border: "rgba(31, 42, 36, 0.10)",
        input: "#FFFFFF",
        ring: "#1B4D3E",
        primary: {
          DEFAULT: "#1F2A24",
          foreground: "#F7FAF6",
        },
        secondary: {
          DEFAULT: "#FFFFFF",
          foreground: "#1A211C",
        },
        muted: {
          DEFAULT: "#E6EBE6",
          foreground: "#6B7A72",
        },
        accent: {
          DEFAULT: "#1B4D3E",
          foreground: "#F7FAF6",
        },
        destructive: {
          DEFAULT: "#B42318",
          foreground: "#FFFFFF",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "ui-serif", "Georgia", "serif"],
      },
      borderRadius: {
        lg: "1rem",
        md: "0.75rem",
        sm: "0.5rem",
      },
      backdropBlur: {
        glass: "24px",
      },
    },
  },
  plugins: [],
};

export default config;
