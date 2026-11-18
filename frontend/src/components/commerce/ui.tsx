"use client";

import type { ReactNode } from "react";

export const inputCls = "mt-1 min-h-11 w-full rounded-xl border border-line-strong bg-white px-3 py-2 text-sm font-normal text-ink focus:border-ink focus:outline-none";
export const btnCls = "min-h-11 rounded-full bg-ink px-5 py-2 text-sm font-bold text-white transition hover:bg-primary-700 disabled:opacity-40";
export const btnGhost = "min-h-11 rounded-full border border-line-strong bg-white px-4 py-2 text-sm font-bold text-ink transition hover:border-ink disabled:opacity-40";

/** Loading / error / empty switch for a list that is `null` while loading. */
export function ListState({ items, error, empty, onRetry }: { items: unknown[] | null | undefined; error: string | null; empty: string; onRetry?: () => void }) {
  if (error) return (
    <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}
      {onRetry && <button type="button" onClick={onRetry} className="mr-2 font-bold underline">تلاش دوباره</button>}</p>
  );
  if (items == null) return <p role="status" className="py-6 text-center text-sm text-neutral-400">در حال بارگذاری…</p>;
  if (!items.length) return <p className="rounded-2xl border border-dashed border-line-strong p-6 text-center text-sm text-ink-muted">{empty}</p>;
  return null;
}

export function Card({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="space-y-4 rounded-2xl border border-line bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-[15px] font-bold text-ink">{title}</h2>{action}
      </div>
      {children}
    </section>
  );
}

export function Flash({ msg }: { msg: { ok: boolean; text: string } | null }) {
  if (!msg) return null;
  return <p role={msg.ok ? "status" : "alert"} className={`rounded-xl p-3 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700"}`}>{msg.text}</p>;
}

export const n = (v: number) => v.toLocaleString("fa-IR");
