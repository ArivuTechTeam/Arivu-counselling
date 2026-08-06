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
        glow: "0 4px 14px -3px rgb(26 122 74 / 0.35)",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
