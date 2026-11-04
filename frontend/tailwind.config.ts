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
        vinyl: {
          gold: "#D4A017",
          silver: "#6F675E",
          obsidian: "#1C1917",
        },
        // Placeholders that were near-black zinc now sit on the warm paper scale.
        zinc: {
          700: "#5A3A28",
          800: "#E6E0D6",
          900: "#D9D2C6",
          950: "#CFC6B8",
        },
        amber: {
          400: "#8A5A12",
          500: "#C8962A",
          600: "#6B2D3C",
          900: "#4A3228",
        },
        green: {
          400: "#2F4A32",
          500: "#3E4A2E",
        },
        red: {
          400: "#B91C1C",
        },
        border: "#E7E2D9",
        input: "#F7F4EF",
        ring: "#D4A017",
        primary: {
          DEFAULT: "#D4A017",
          foreground: "#1C1917",
        },
        secondary: {
          DEFAULT: "#FFFFFF",
          foreground: "#1C1917",
        },
        muted: {
          DEFAULT: "#EFEBE4",
          foreground: "#6F675E",
        },
        accent: {
          DEFAULT: "#EFEBE4",
          foreground: "#1C1917",
        },
        destructive: {
          DEFAULT: "#B42318",
          foreground: "#FFFFFF",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        serif: ["var(--font-serif)", "Georgia", "ui-serif", "serif"],
      },
      borderRadius: {
        lg: "0.75rem",
        md: "0.5rem",
        sm: "0.375rem",
      },
      backdropBlur: {
        glass: "24px",
      },
    },
  },
  plugins: [],
};

export default config;
