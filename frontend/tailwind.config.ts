import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      // ── Brand palette ─────────────────────────────────────────────────────
      colors: {
        white: "#F9F9F9",
        amber: {
          50: "#fff5f1",
          100: "#ffede6",
          200: "#ffd7c9",
          300: "#ffb59e",
          400: "#ff906f",
          500: "#FF6D41",
          600: "#FF6D41",
          700: "#004E72",
          800: "#0A2735",
          900: "#0A2735",
          950: "#0A2735",
        },
        primary: {
          50: "rgb(0 78 114 / 0.04)",
          100: "rgb(0 78 114 / 0.08)",
          200: "rgb(0 78 114 / 0.16)",
          300: "rgb(0 78 114 / 0.35)",
          400: "rgb(0 78 114 / 0.7)",
          500: "#004E72",
          600: "#004E72",
          700: "#004E72",
          800: "#0A2735",
          900: "#0A2735",
          950: "#0A2735",
        },
        accent: {
          50: "rgb(255 109 65 / 0.05)",
          100: "rgb(255 109 65 / 0.1)",
          200: "rgb(255 109 65 / 0.2)",
          300: "rgb(255 109 65 / 0.4)",
          400: "rgb(255 109 65 / 0.7)",
          500: "#FF6D41",
          600: "#FF6D41",
          700: "#004E72",
          800: "#0A2735",
          900: "#0A2735",
        },
        success: {
          50: "#ecfdf5",
          500: "#10b981",
          600: "#059669",
          700: "#047857",
        },
        danger: {
          50: "#fef2f2",
          500: "#ef4444",
          600: "#dc2626",
          700: "#b91c1c",
        },
        warning: {
          50: "rgb(255 109 65 / 0.05)",
          500: "#FF6D41",
          600: "#FF6D41",
        },
        // Neutral (same as Tailwind gray but aliased for brand docs)
        neutral: {
          0: "#F9F9F9",
          50: "#F9F9F9",
          100: "#f3f4f6",
          150: "#eaecf0",
          200: "#e5e7eb",
          300: "#d1d5db",
          400: "#9ca3af",
          500: "#6b7280",
          600: "#4b5563",
          700: "#374151",
          800: "#1f2937",
          900: "#111827",
          950: "#030712",
        },
        // ── 60Online brand system (navy / action-blue) ──────────────────────
        // This is the approved homepage identity — used by Header, Footer,
        // Hero, and every home-page section. Keep separate from `primary`
        // (still used by inner app pages: cart/checkout/login/etc.) so those
        // routes are unaffected by this pass.
        brand: {
          navy: "#0A2735",
          navyLight: "#004E72",
          blue: "#004E72",
          blueDark: "#004E72",
          blueLight: "rgb(0 78 114 / 0.08)",
          gray: "#F9F9F9",
          coral: "#FF6D41",
        },
      },

      // ── Typography ─────────────────────────────────────────────────────────
      fontFamily: {
        sans: ["var(--font-vazirmatn)", "Vazirmatn", "system-ui", "sans-serif"],
        display: [
          "var(--font-vazirmatn)",
          "Vazirmatn",
          "system-ui",
          "sans-serif",
        ],
        mono: ["Fira Code", "monospace"],
      },
      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "0.875rem" }],
        xs: ["0.75rem", { lineHeight: "1rem" }],
        sm: ["0.875rem", { lineHeight: "1.25rem" }],
        base: ["1rem", { lineHeight: "1.625rem" }],
        lg: ["1.125rem", { lineHeight: "1.75rem" }],
        xl: ["1.25rem", { lineHeight: "1.875rem" }],
        "2xl": ["1.5rem", { lineHeight: "2rem" }],
        "3xl": ["1.875rem", { lineHeight: "2.25rem" }],
        "4xl": ["2.25rem", { lineHeight: "2.5rem" }],
        "5xl": ["3rem", { lineHeight: "1" }],
        "6xl": ["3.75rem", { lineHeight: "1" }],
      },

      // ── Spacing / layout ───────────────────────────────────────────────────
      borderRadius: {
        "2xs": "2px",
        xs: "4px",
        sm: "6px",
        DEFAULT: "8px",
        md: "10px",
        lg: "12px",
        xl: "16px",
        "2xl": "20px",
        "3xl": "24px",
        full: "9999px",
      },

      // ── Shadows ────────────────────────────────────────────────────────────
      boxShadow: {
        xs: "0 1px 2px 0 rgb(0 0 0 / 0.05)",
        sm: "0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)",
        md: "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
        lg: "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)",
        xl: "0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)",
        card: "0 1px 4px 0 rgb(0 0 0 / 0.06), 0 2px 12px 0 rgb(0 0 0 / 0.06)",
        "card-hover":
          "0 4px 16px 0 rgb(0 78 114 / 0.12), 0 2px 8px 0 rgb(0 0 0 / 0.08)",
        "primary-glow": "0 0 0 3px rgb(0 78 114 / 0.15)",
        "brand-card":
          "0 18px 45px -28px rgb(10 39 53 / 0.35), 0 8px 20px -16px rgb(10 39 53 / 0.18)",
      },

      // ── Animation ──────────────────────────────────────────────────────────
      animation: {
        "fade-in": "fadeIn 0.2s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
        shimmer: "shimmer 1.5s infinite",
        "spin-slow": "spin 2s linear infinite",
      },
      keyframes: {
        fadeIn: { from: { opacity: "0" }, to: { opacity: "1" } },
        slideUp: {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },

      // ── Screens ────────────────────────────────────────────────────────────
      screens: {
        xs: "375px",
        sm: "640px",
        md: "768px",
        lg: "1024px",
        xl: "1280px",
        "2xl": "1440px",
      },
    },
  },
  plugins: [],
};

export default config;
