"use client";
import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, ChevronLeft } from "lucide-react";
import { useTaxonomy } from "@/components/layout/MegaMenu";
import { categoryIcon } from "@/components/layout/categoryIcon";
import { cn, toPersianNum } from "@/lib/utils";

// Real taxonomy only: a node appears when at least one REAL product sits under it.
// Layout (Stitch 2026-11): right rail of main categories, subcategory tiles beside it — same on app and desktop.
export default function CategoryIndexPage() {
  const tree = useTaxonomy();
  const [active, setActive] = useState(0);
  const current = tree?.[active];
  return (
    <div className="container-page py-5 md:py-10" dir="rtl">
      <div className="mb-5 flex items-end justify-between gap-3 md:mb-8">
        <div>
          <nav aria-label="مسیر" className="page-breadcrumb"><Link href="/">خانه</Link><ChevronLeft className="h-3 w-3" /><span>دسته‌بندی‌ها</span></nav>
          <h1 className="text-2xl font-extrabold text-ink md:text-3xl">دسته‌بندی کالاها</h1>
          <p className="mt-1 text-xs text-ink-muted md:text-sm">ساختار دسته‌ها از کالاهای واقعی کاتالوگ ساخته شده است؛ دستهٔ بدون کالا نمایش داده نمی‌شود.</p>
        </div>
        {tree && tree.length > 0 && <span className="hidden shrink-0 text-xs text-ink-faint md:block">{toPersianNum(tree.length)} دستهٔ اصلی</span>}
      </div>

      {tree === null ? (
        <div className="grid grid-cols-[96px_1fr] gap-3 md:grid-cols-[240px_1fr] md:gap-6">
          <div className="space-y-2">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="skeleton h-20 rounded-2xl md:h-12" />)}</div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{Array.from({ length: 8 }).map((_, i) => <div key={i} className="skeleton h-28 rounded-2xl" />)}</div>
        </div>
      ) : !tree.length ? (
        <div className="card p-8 text-center text-ink-muted">هنوز دسته‌ای با کالای واقعی ثبت نشده است.</div>
      ) : (
        <div className="grid grid-cols-[92px_1fr] gap-3 md:grid-cols-[240px_1fr] md:gap-6">
          <ul className="sticky top-24 self-start space-y-1.5" aria-label="دسته‌های اصلی">
            {tree.map((n, i) => {
              const Icon = categoryIcon(n.slug, n.name_fa);
              const on = i === active;
              return <li key={n.slug}>
                <button type="button" onClick={() => setActive(i)} aria-pressed={on}
                  className={cn("flex w-full flex-col items-center gap-1.5 rounded-2xl border px-1.5 py-3 text-center text-[11px] leading-5 transition md:min-h-12 md:flex-row md:gap-3 md:px-3.5 md:py-2 md:text-right md:text-sm",
                    on ? "border-ink bg-ink font-bold text-white" : "border-line bg-white text-ink-soft hover:border-line-strong hover:text-ink")}>
                  <Icon className="h-5 w-5 shrink-0" strokeWidth={1.6} />
                  <span className="md:flex-1">{n.name_fa}</span>
                  <span className={cn("hidden text-[11px] tabular-nums md:inline", on ? "text-white/70" : "text-ink-faint")}>{toPersianNum(n.product_count)}</span>
                </button></li>;
            })}
          </ul>

          {current && <section aria-labelledby="cat-current" className="min-w-0 rounded-2xl border border-line bg-white p-4 md:p-6">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 id="cat-current" className="text-base font-extrabold text-ink md:text-lg">{current.name_fa}</h2>
              <Link href={`/category/${current.slug}`} className="inline-flex min-h-10 items-center gap-1 rounded-full border border-line-strong px-3.5 text-xs font-bold text-ink hover:border-ink">
                همهٔ {toPersianNum(current.product_count)} کالا<ArrowLeft className="h-3.5 w-3.5" /></Link>
            </div>
            {current.children.length ? (
              <div className="space-y-6">
                {current.children.map((c) => {
                  const Icon = categoryIcon(c.slug, c.name_fa);
                  return <div key={c.slug}>
                    <Link href={`/category/${c.slug}`} className="group mb-3 flex items-center gap-3 rounded-2xl bg-canvas p-3 hover:bg-canvas-sunken">
                      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white text-ink"><Icon className="h-5 w-5" strokeWidth={1.6} /></span>
                      <span className="flex-1"><b className="block text-sm text-ink">{c.name_fa}</b><small className="text-[11px] text-ink-faint">{toPersianNum(c.product_count)} کالا</small></span>
                      <ArrowLeft className="h-4 w-4 text-ink-faint transition group-hover:-translate-x-0.5 group-hover:text-ink" />
                    </Link>
                    {c.children.length > 0 && <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                      {c.children.map((s) => <Link key={s.slug} href={`/category/${s.slug}`}
                        className="flex min-h-12 items-center justify-between gap-2 rounded-xl border border-line px-3 py-2 text-xs text-ink-soft hover:border-ink hover:text-ink">
                        <span className="line-clamp-2">{s.name_fa}</span><span className="text-[10px] text-ink-faint tabular-nums">{toPersianNum(s.product_count)}</span></Link>)}
                    </div>}
                  </div>;
                })}
              </div>
            ) : (
              <Link href={`/category/${current.slug}`} className="flex flex-col items-center gap-3 rounded-2xl bg-canvas px-4 py-10 text-center hover:bg-canvas-sunken">
                {(() => { const Icon = categoryIcon(current.slug, current.name_fa); return <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-white text-ink"><Icon className="h-8 w-8" strokeWidth={1.4} /></span>; })()}
                <b className="text-sm text-ink">مشاهدهٔ همهٔ کالاهای {current.name_fa}</b>
                <small className="text-xs text-ink-muted">{toPersianNum(current.product_count)} کالای واقعی در این دسته</small>
              </Link>
            )}
          </section>}
        </div>
      )}
    </div>
  );
}
