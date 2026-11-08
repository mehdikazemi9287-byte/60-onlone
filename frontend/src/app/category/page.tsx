"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { LayoutGrid } from "lucide-react";
import { categories } from "@/lib/api";
import type { TaxNode } from "@/lib/storefront";
import { toPersianNum } from "@/lib/utils";

// Real taxonomy only: a node appears when at least one REAL product sits under it.
export default function CategoryIndexPage() {
  const [tree, setTree] = useState<TaxNode[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let off = false;
    categories.tree().then((t) => !off && setTree(t)).catch((e) => !off && (setError(e instanceof Error ? e.message : "خطا"), setTree([])));
    return () => { off = true; };
  }, []);
  return (
    <div className="internal-page container-page py-6 md:py-10" dir="rtl">
      <div className="internal-hero mb-6">
        <div className="internal-hero-icon"><LayoutGrid className="h-7 w-7" /></div>
        <div>
          <span className="section-kicker">دسترسی سریع</span>
          <h1>دسته‌بندی کالاها</h1>
          <p>ساختار دسته‌ها از کالاهای واقعی کاتالوگ ساخته شده است؛ دسته‌ی بدون کالا نمایش داده نمی‌شود.</p>
        </div>
      </div>
      {error ? <div role="alert" className="card border-red-200 bg-red-50 p-6 text-center text-sm text-red-700">{error}</div>
        : tree === null ? <div className="grid gap-4 md:grid-cols-2">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="card h-40 skeleton" />)}</div>
        : !tree.length ? <div className="card p-8 text-center text-neutral-600">هنوز دسته‌ای با کالای واقعی ثبت نشده است.</div>
        : <div className="grid gap-4 md:grid-cols-2">{tree.map((d) => (
          <section key={d.slug} className="card p-5">
            <h2 className="mb-3 flex items-center justify-between text-lg font-black text-brand-navy">
              <Link href={`/category/${d.slug}`} className="hover:text-brand-blue">{d.name_fa}</Link>
              <span className="text-xs font-bold text-neutral-500">{toPersianNum(d.product_count)} محصول</span></h2>
            <div className="space-y-3">{d.children.map((c) => (
              <div key={c.slug}>
                <Link href={`/category/${c.slug}`} className="text-sm font-bold text-neutral-900 hover:text-brand-blue">{c.name_fa} <span className="text-xs font-normal text-neutral-500">({toPersianNum(c.product_count)})</span></Link>
                {c.children.length > 0 && <div className="mt-1.5 flex flex-wrap gap-1.5">{c.children.map((s) => (
                  <Link key={s.slug} href={`/category/${s.slug}`} className="rounded-full bg-neutral-100 px-2.5 py-1 text-xs text-neutral-700 hover:bg-sky-50 hover:text-brand-blue">{s.name_fa} ({toPersianNum(s.product_count)})</Link>))}</div>}
              </div>))}</div>
          </section>))}</div>}
    </div>
  );
}
