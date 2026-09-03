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
        primary: {
          50:  "#EAF3FF",
          100: "#D8E9FF",
          200: "#B7D7FF",
          300: "#83B9FF",
          400: "#4C9CFF",
          500: "#1677FF",
          600: "#125FCC",   // 60Online action blue
          700: "#164E7A",
          800: "#153E5C",
          900: "#102A43",
          950: "#0C2233",
        },
        accent: {
          50:  "#fffbeb",
          100: "#fef3c7",
          200: "#fde68a",
          300: "#fcd34d",
          400: "#fbbf24",
          500: "#f59e0b",   // ← main accent (CTA)
          600: "#d97706",
          700: "#b45309",
          800: "#92400e",
          900: "#78350f",
        },
        success: {
          50:  "#ecfdf5",
          500: "#10b981",
          600: "#059669",
          700: "#047857",
        },
        danger: {
          50:  "#fef2f2",
          500: "#ef4444",
          600: "#dc2626",
          700: "#b91c1c",
        },
        warning: {
          50:  "#fffbeb",
          500: "#f59e0b",
          600: "#d97706",
        },
        // Neutral (same as Tailwind gray but aliased for brand docs)
        neutral: {
          0:   "#ffffff",
          50:  "#f9fafb",
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
          navy:      "#102A43",
          navyLight: "#1A3D5B",
          blue:      "#1677FF",
          blueDark:  "#125FCC",
          blueLight: "#EAF3FF",
          gray:      "#F5F7FA",
          coral:     "#E8483C",
        },
      },

      // ── Typography ─────────────────────────────────────────────────────────
      fontFamily: {
        sans: ["var(--font-vazirmatn)", "Vazirmatn", "system-ui", "sans-serif"],
        display: ["var(--font-vazirmatn)", "Vazirmatn", "system-ui", "sans-serif"],
        mono: ["Fira Code", "monospace"],
      },
      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "0.875rem" }],
        xs:   ["0.75rem",  { lineHeight: "1rem" }],
        sm:   ["0.875rem", { lineHeight: "1.25rem" }],
        base: ["1rem",     { lineHeight: "1.625rem" }],
        lg:   ["1.125rem", { lineHeight: "1.75rem" }],
        xl:   ["1.25rem",  { lineHeight: "1.875rem" }],
        "2xl":["1.5rem",   { lineHeight: "2rem" }],
        "3xl":["1.875rem", { lineHeight: "2.25rem" }],
        "4xl":["2.25rem",  { lineHeight: "2.5rem" }],
        "5xl":["3rem",     { lineHeight: "1" }],
        "6xl":["3.75rem",  { lineHeight: "1" }],
      },

      // ── Spacing / layout ───────────────────────────────────────────────────
      borderRadius: {
        "2xs": "2px",
        xs:    "4px",
        sm:    "6px",
        DEFAULT:"8px",
        md:    "10px",
        lg:    "12px",
        xl:    "16px",
        "2xl": "20px",
        "3xl": "24px",
        full:  "9999px",
      },

      // ── Shadows ────────────────────────────────────────────────────────────
      boxShadow: {
        xs:  "0 1px 2px 0 rgb(0 0 0 / 0.05)",
        sm:  "0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)",
        md:  "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
        lg:  "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)",
        xl:  "0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)",
        card:"0 1px 4px 0 rgb(0 0 0 / 0.06), 0 2px 12px 0 rgb(0 0 0 / 0.06)",
        "card-hover": "0 4px 16px 0 rgb(79 70 229 / 0.12), 0 2px 8px 0 rgb(0 0 0 / 0.08)",
        "primary-glow": "0 0 0 3px rgb(99 102 241 / 0.15)",
        "brand-card": "0 18px 45px -28px rgb(16 42 67 / 0.35), 0 8px 20px -16px rgb(16 42 67 / 0.18)",
      },

      // ── Animation ──────────────────────────────────────────────────────────
      animation: {
        "fade-in":  "fadeIn 0.2s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
        "shimmer":  "shimmer 1.5s infinite",
        "spin-slow":"spin 2s linear infinite",
      },
      keyframes: {
        fadeIn:  { from: { opacity: "0" }, to: { opacity: "1" } },
        slideUp: { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        shimmer: { "0%": { backgroundPosition: "-200% 0" }, "100%": { backgroundPosition: "200% 0" } },
      },

      // ── Screens ────────────────────────────────────────────────────────────
      screens: {
        xs:  "375px",
        sm:  "640px",
        md:  "768px",
        lg:  "1024px",
        xl:  "1280px",
        "2xl": "1440px",
      },
    },
  },
  plugins: [],
};

export default config;
