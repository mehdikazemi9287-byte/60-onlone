import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes safely */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Format Rial amounts (stored as minor units = ریال) */
export function formatPrice(minor: number, currency = "IRR"): string {
  if (currency === "IRR") {
    // Display in Tomans (÷ 10)
    const toman = Math.round(minor / 10);
    // One customer-facing format everywhere: exact grouped Persian digits.
    // The stored Rial-to-Toman conversion remains unchanged.
    return toman.toLocaleString("fa-IR", { maximumFractionDigits: 0 }) + " تومان";
  }
  return minor.toLocaleString("fa-IR");
}

/** Format a number with Persian numerals */
export function toPersianNum(n: number | string): string {
  return String(n).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[+d]);
}

/** Format an exact Toman amount with thousands separators and Persian numerals (no rounding to میلیون) */
export function formatTomanExact(toman: number): string {
  const rounded = Math.round(toman);
  const sign = rounded < 0 ? "−" : "";
  return sign + toPersianNum(Math.abs(rounded).toLocaleString("en-US")) + " تومان";
}

/** Truncate text */
export function truncate(str: string, max: number): string {
  return str.length > max ? str.slice(0, max).trimEnd() + "…" : str;
}

/** Relative time in Persian */
export function relativeTime(date: Date): string {
  const diff = Date.now() - date.getTime();
  const m = Math.floor(diff / 60_000);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  if (d > 0) return `${toPersianNum(d)} روز پیش`;
  if (h > 0) return `${toPersianNum(h)} ساعت پیش`;
  if (m > 0) return `${toPersianNum(m)} دقیقه پیش`;
  return "لحظاتی پیش";
}

/** Clamp a number */
export function clamp(val: number, min: number, max: number): number {
  return Math.min(Math.max(val, min), max);
}

/** Jalali date (fa-IR) of an ISO/SQL timestamp, e.g. «۱۴۰۵/۷/۱۲»; empty when missing/invalid. */
export function faDate(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value.includes("T") ? value : value.replace(" ", "T") + "Z");
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("fa-IR-u-ca-persian");
}
