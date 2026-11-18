// Visual tokens for /pack-builder, copied from the approved Google Stitch screens 62 (desktop 1440) and
// 63 (mobile 390) — rebuilt faithfully 2026-11-18. Pack-builder screens 55–63 use their own palette, so it
// lives here (not in tailwind.config.ts / globals.css, which belong to the shared foundation).
// Kept separate from `UI` in PackCard.tsx on purpose: that object is imported by the protected homepage.
export const S = {
  blue: "#034EA2", // brand blue: active step, active filter, links, selected method
  navy: "#112D46", // action navy: primary buttons, headings
  navyHover: "#0A1C2C",
  orange: "#FF7A00", // accent: card badge, PDF icon
  mint: "#EDF3EE", // hero + tier box
  mintLine: "#E0EBE2",
  bg: "#F9F9F9",
} as const;

/** Stitch card surface: white, rounded-xl, gray-200 border, shadow-sm. */
export const card = "rounded-xl border border-gray-200 bg-white shadow-sm";
export const btnPrimary = "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-[#112D46] px-4 text-xs font-bold text-white shadow-sm transition hover:bg-[#0A1C2C] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#034EA2]/20 disabled:cursor-not-allowed disabled:opacity-50";
export const btnSecondary = "inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white px-4 text-xs font-semibold text-gray-700 transition hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#034EA2]/20 disabled:cursor-not-allowed disabled:opacity-50";
export const input = "h-11 w-full rounded-xl border border-gray-200 bg-white px-3 text-xs text-gray-900 placeholder:text-gray-400 focus:border-[#034EA2] focus:outline-none focus:ring-4 focus:ring-[#034EA2]/10";
export const sectionTitle = "text-sm font-bold text-gray-900 md:text-base";
export const sectionSub = "mt-1 text-xs text-gray-500";

/** Material Symbols icon (self-hosted subset; see tools/stitch/icons-included.txt). */
export function Icon({ name, className = "", fill = false }: { name: string; className?: string; fill?: boolean }) {
  return <span aria-hidden className={`material-symbols-outlined ${fill ? "icon-fill " : ""}${className}`}>{name}</span>;
}

/** Honest marker for a Stitch feature that has no backend yet. */
export function Soon({ className = "" }: { className?: string }) {
  return <span className={`inline-flex shrink-0 items-center rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-bold text-gray-500 ${className}`}>به‌زودی</span>;
}
