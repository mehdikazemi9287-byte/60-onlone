// Visual tokens for the redesigned /pack-builder page (Stitch screens 62/63, approved 2026-11-17).
// Kept separate from `UI` in PackCard.tsx on purpose: that object is imported by the protected homepage
// (HomeSections, PackBuilderInteractive) and must not change as a side effect of this page's redesign.
export const S = {
  blue: "#034EA2", // brand blue: links, active filter, focus
  navy: "#112D46", // primary buttons, active step
  navyHover: "#0A1C2C",
  mint: "#EDF3EE", // hero background
  mintLine: "#E0EBE2",
  bg: "#F9F9F9",
  line: "#E5E7EB", // thin gray borders
  text: "#111827",
  muted: "#6B7280",
  orange: "#F26B1D", // only for the «قیمت سازمانی» badge
} as const;

/** Card surface: white, 12px radius, thin border, soft shadow. */
export const card = "rounded-xl border border-[#E5E7EB] bg-white shadow-[0_1px_2px_rgba(17,24,39,0.04),0_4px_16px_rgba(17,24,39,0.04)]";
export const btnPrimary = "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-[#112D46] px-4 text-sm font-bold text-white transition hover:bg-[#0A1C2C] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#034EA2]/20 disabled:cursor-not-allowed disabled:opacity-50";
export const btnSecondary = "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-[#E5E7EB] bg-white px-4 text-sm font-bold text-[#112D46] transition hover:border-[#034EA2] hover:text-[#034EA2] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#034EA2]/20 disabled:cursor-not-allowed disabled:opacity-50";
export const input = "h-11 w-full rounded-xl border border-[#E5E7EB] bg-white px-3 text-sm text-[#111827] placeholder:text-[#9CA3AF] focus:border-[#034EA2] focus:outline-none focus:ring-4 focus:ring-[#034EA2]/10";
export const sectionTitle = "text-base font-extrabold text-[#112D46] md:text-lg";
export const sectionSub = "mt-1 line-clamp-1 text-xs text-[#6B7280] md:text-sm";
