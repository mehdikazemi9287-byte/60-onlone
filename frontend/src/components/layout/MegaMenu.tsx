"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { ArrowLeft, ChevronDown, LayoutGrid } from "lucide-react";
import { categories } from "@/lib/api";
import type { TaxNode } from "@/lib/storefront";
import { cn, toPersianNum } from "@/lib/utils";
import { categoryIcon } from "./categoryIcon";

let treeRequest: Promise<TaxNode[]> | null = null;
export function useTaxonomy() {
  const [tree, setTree] = useState<TaxNode[] | null>(null);
  useEffect(() => {
    let off = false;
    treeRequest ??= categories.tree().catch(() => { treeRequest = null; return []; });
    treeRequest.then((t) => !off && setTree(t.filter((n) => n.product_count > 0)));
    return () => { off = true; };
  }, []);
  return tree;
}

/** Desktop mega-menu: main categories on the right, the hovered one's children in columns. Real taxonomy only. */
export function MegaMenu() {
  const tree = useTaxonomy();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const path = usePathname();
  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const out = (e: MouseEvent) => root.current && !root.current.contains(e.target as Node) && setOpen(false);
    window.addEventListener("keydown", esc); window.addEventListener("mousedown", out);
    return () => { window.removeEventListener("keydown", esc); window.removeEventListener("mousedown", out); };
  }, [open]);
  const hover = (v: boolean) => { if (timer.current) clearTimeout(timer.current); timer.current = setTimeout(() => setOpen(v), v ? 120 : 180); };
  const current = tree?.[active];

  return (
    <div ref={root} className="relative" onMouseEnter={() => hover(true)} onMouseLeave={() => hover(false)}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-controls="mega-menu"
        className={cn("flex h-8 flex-shrink-0 items-center gap-2 rounded-full px-3.5 text-[13px] font-bold text-ink transition",
          open ? "bg-ink text-white" : "bg-canvas-sunken hover:bg-line")}>
        <LayoutGrid className="h-4 w-4" strokeWidth={1.75} />دسته‌بندی کالاها<ChevronDown className={cn("h-3.5 w-3.5 transition", open && "rotate-180")} />
      </button>
      {open && (
        <div id="mega-menu" role="region" aria-label="دسته‌بندی کالاها"
          className="absolute right-0 top-[calc(100%+10px)] z-[70] flex w-[min(92vw,960px)] overflow-hidden rounded-2xl border border-line bg-white shadow-soft">
          {tree === null ? <p role="status" className="p-8 text-sm text-ink-muted">در حال بارگذاری دسته‌ها…</p>
            : !tree.length ? <p className="p-8 text-sm text-ink-muted">هنوز دسته‌ای با کالای واقعی ثبت نشده است.</p>
            : <>
              <ul className="w-64 shrink-0 border-l border-line bg-canvas p-2">
                {tree.map((n, i) => {
                  const Icon = categoryIcon(n.slug, n.name_fa);
                  return <li key={n.slug}>
                    <Link href={`/category/${n.slug}`} onMouseEnter={() => setActive(i)} onFocus={() => setActive(i)}
                      className={cn("flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm transition",
                        i === active ? "bg-white font-bold text-ink ring-1 ring-line" : "text-ink-soft hover:text-ink")}>
                      <Icon className="h-[18px] w-[18px] shrink-0" strokeWidth={1.6} /><span className="flex-1 truncate">{n.name_fa}</span>
                      <span className="text-[11px] text-ink-faint tabular-nums">{toPersianNum(n.product_count)}</span>
                    </Link></li>;
                })}
              </ul>
              {current && <div className="min-h-[300px] flex-1 p-6">
                <div className="mb-5 flex items-center justify-between">
                  <Link href={`/category/${current.slug}`} className="flex items-center gap-1.5 text-sm font-bold text-ink hover:text-petrol">
                    همهٔ کالاهای {current.name_fa}<ArrowLeft className="h-4 w-4" /></Link>
                  <span className="text-xs text-ink-faint">{toPersianNum(current.product_count)} کالا</span>
                </div>
                {current.children.length ? (
                  <div className="columns-3 gap-8">
                    {current.children.map((c) => <div key={c.slug} className="mb-6 break-inside-avoid">
                      <Link href={`/category/${c.slug}`} className="mb-2 flex items-center gap-2 border-r-2 border-ink pr-2 text-[13px] font-bold text-ink hover:text-petrol">
                        {c.name_fa}<span className="text-[11px] font-normal text-ink-faint">{toPersianNum(c.product_count)}</span></Link>
                      <ul className="space-y-1.5 pr-2.5">{c.children.map((s) => <li key={s.slug}>
                        <Link href={`/category/${s.slug}`} className="text-[13px] text-ink-muted hover:text-ink">{s.name_fa}</Link></li>)}</ul>
                    </div>)}
                  </div>
                ) : <p className="text-sm text-ink-muted">این دسته زیرشاخه ندارد؛ همهٔ کالاهای آن را از پیوند بالا ببینید.</p>}
              </div>}
            </>}
        </div>
      )}
    </div>
  );
}
