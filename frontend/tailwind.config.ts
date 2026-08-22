import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      // These map Tailwind color utilities (e.g. bg-primary, border-input)
      // to the HSL CSS variables defined in globals.css. Changing a variable
      // there re-themes the whole app.
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // ArivuPro brand green scale + vibrant accents (from the design system).
        brand: {
          50: "#f0faf7",
          100: "#d0f0e6",
          200: "#a8e4d3",
          300: "#7dd8c0",
          400: "#52ccad",
          500: "#1a6942",
          600: "#15603d",
          700: "#125738",
          800: "#0f4e33",
          900: "#0a422b",
          950: "#052420",
        },
        "accent-green": "#00a651",
        "accent-orange": "#f5a623",
        "accent-pink": "#ff6b7a",
        "accent-lime": "#2ecc71",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        // --font-sans is set by next/font (Plus Jakarta Sans) in app/layout.tsx.
        sans: ["var(--font-sans)", "sans-serif"],
      },
      // Soft, green-tinted elevation from the ArivuPro design system.
      boxShadow: {
        sm: "0 1px 2px 0 rgb(26 46 34 / 0.04), 0 1px 3px 0 rgb(26 46 34 / 0.06)",
        DEFAULT:
          "0 2px 4px -1px rgb(26 46 34 / 0.05), 0 6px 16px -4px rgb(26 46 34 / 0.08)",
        md: "0 2px 4px -1px rgb(26 46 34 / 0.05), 0 6px 16px -4px rgb(26 46 34 / 0.08)",
        lg: "0 8px 24px -6px rgb(26 46 34 / 0.10), 0 16px 40px -12px rgb(26 46 34 / 0.10)",
        glow: "0 4px 14px -3px rgb(26 122 74 / 0.35)",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
