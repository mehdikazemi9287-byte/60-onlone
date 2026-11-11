import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";

export const inputCls = "mt-1 w-full rounded-xl border border-neutral-300 bg-white p-2 text-sm font-normal";
export const btnCls = "min-h-10 rounded-xl bg-brand-navy px-4 py-2 text-sm font-bold text-white disabled:opacity-50";
export const btnGhost = "min-h-10 rounded-xl border border-neutral-300 px-3 py-2 text-sm font-bold text-neutral-800 disabled:opacity-50";

/** Loading / error / empty switch for a list that is `null` while loading. */
export function ListState({ items, error, empty, onRetry }: { items: unknown[] | null | undefined; error: string | null; empty: string; onRetry?: () => void }) {
  if (error) return (
    <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}
      {onRetry && <button type="button" onClick={onRetry} className="mr-2 font-bold underline">تلاش دوباره</button>}</p>
  );
  if (items == null) return <p role="status" className="py-6 text-center text-sm text-neutral-500">در حال بارگذاری…</p>;
  if (!items.length) return <p className="rounded-xl bg-neutral-50 p-4 text-center text-sm text-neutral-600">{empty}</p>;
  return null;
}

export function Card({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="space-y-3 rounded-2xl border border-[#DCE3F7] bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-black text-neutral-900">{title}</h2>{action}
      </div>
      {children}
    </section>
  );
}

export const n = (v: number) => v.toLocaleString("fa-IR");

/** Prices arrive in rial (minor units); shown in toman. */
export const formatPrice = (minor: number) => Math.round(minor / 10).toLocaleString("fa-IR", { maximumFractionDigits: 0 }) + " تومان";
export const toPersianNum = (v: number | string) => String(v).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[+d]);
export const latinDigits = (v: string) =>
  v.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))).replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)));

/** Jalali date of an ISO/SQL timestamp; empty when missing or invalid. */
export function faDate(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value.includes("T") ? value : value.replace(" ", "T") + "Z");
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("fa-IR-u-ca-persian");
}

export function errText(e: unknown, fallback = "خطا در ارتباط با سرور"): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return e.message || "دسترسی این بخش را ندارید.";
    return e.message || fallback;
  }
  return fallback;
}
