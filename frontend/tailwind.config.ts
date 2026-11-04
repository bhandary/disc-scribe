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
        background: "#F3F1EC",
        foreground: "#1C1917",
        card: "#FFFFFF",
        border: "#E7E2D9",
        input: "#FFFFFF",
        ring: "#C9C0B2",
        primary: {
          DEFAULT: "#2C241C",
          foreground: "#F7F4EF",
        },
        secondary: {
          DEFAULT: "#FFFFFF",
          foreground: "#1C1917",
        },
        muted: {
          DEFAULT: "#E9E4DB",
          foreground: "#8A847A",
        },
        accent: {
          DEFAULT: "#F7F4EF",
          foreground: "#1C1917",
        },
        destructive: {
          DEFAULT: "#B42318",
          foreground: "#FFFFFF",
        },
        gold: "#D4A017",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        serif: ["var(--font-serif)", "Georgia", "ui-serif", "serif"],
      },
      borderRadius: {
        lg: "1rem",
        md: "0.75rem",
        sm: "0.5rem",
      },
      boxShadow: {
        card: "0 1px 2px rgba(28, 25, 23, 0.04), 0 8px 24px rgba(28, 25, 23, 0.04)",
      },
    },
  },
  plugins: [],
};

export default config;
