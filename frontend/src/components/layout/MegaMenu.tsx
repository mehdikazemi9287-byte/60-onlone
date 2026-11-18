"use client";

// Category mega menu — Google Stitch screen 15 (light) / 22 (dark; same st- tokens switch with the theme).
// Right column: real top-level taxonomy nodes; left: the active node's sub-categories, each as a group with
// its own children and real product counts. No sample groups or counts from Stitch are shown.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { categories } from "@/lib/api";
import type { TaxNode } from "@/lib/storefront";
import { cn, toPersianNum } from "@/lib/utils";
import { categorySymbol } from "./categoryIcon";

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

const Icon = ({ name, className = "" }: { name: string; className?: string }) => <span aria-hidden className={cn("material-symbols-outlined", className)}>{name}</span>;
const count = (n: number) => `${toPersianNum(n)} کالا`;

function ItemRow({ n }: { n: TaxNode }) {
  return (
    <Link href={`/category/${n.slug}`} className="flex items-center justify-between gap-st-space-sm py-1 text-st-on-surface-variant transition-colors hover:text-st-secondary">
      <span className="truncate">{n.name_fa}</span>
      <span className="shrink-0 rounded-full bg-st-surface-container-low px-2 py-0.5 text-st-outline">{count(n.product_count)}</span>
    </Link>
  );
}

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
  // Groups: sub-categories that have their own children; leaf sub-categories are gathered in one group.
  const groups = current ? current.children.filter((c) => c.product_count > 0 && c.children.some((g) => g.product_count > 0)) : [];
  const leaves = current ? current.children.filter((c) => c.product_count > 0 && !c.children.some((g) => g.product_count > 0)) : [];

  return (
    <div ref={root} className="relative flex h-full items-center" onMouseEnter={() => hover(true)} onMouseLeave={() => hover(false)}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-controls="mega-menu"
        className="flex h-8 cursor-pointer items-center gap-1 whitespace-nowrap rounded-full bg-st-accent px-3 text-st-label-lg font-bold text-white shadow-[0_6px_16px_-8px_rgb(255_122_0/0.9)] transition-colors hover:bg-st-on-tertiary-container">
        <Icon name="menu" className="text-[18px]" /><span>دسته‌بندی کالاها</span>
        <Icon name="expand_more" className={cn("text-[16px] transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div id="mega-menu" role="region" aria-label="دسته‌بندی کالاها"
          className="absolute right-0 top-full z-50 mt-1 grid w-[820px] max-w-[calc(100vw-4rem)] grid-cols-12 gap-st-gutter rounded-2xl border border-st-surface-container bg-st-surface-container-lowest p-st-space-md text-st-on-surface shadow-xl">
          {tree === null ? <p role="status" className="col-span-12 p-st-space-lg text-st-on-surface-variant">در حال بارگذاری دسته‌ها…</p>
            : !tree.length ? <p className="col-span-12 p-st-space-lg text-st-on-surface-variant">هنوز دسته‌ای با کالای واقعی ثبت نشده است.</p>
            : <>
              <div className="col-span-4 flex max-h-[420px] flex-col gap-1 overflow-y-auto border-l border-st-surface-container-low pl-st-space-md">
                {tree.map((n, i) => (
                  <Link key={n.slug} href={`/category/${n.slug}`} onMouseEnter={() => setActive(i)} onFocus={() => setActive(i)}
                    className={cn("flex items-center justify-between rounded-xl p-st-space-sm transition-colors",
                      i === active ? "bg-st-surface-container-low font-bold text-st-secondary" : "text-st-on-surface-variant hover:bg-st-surface-container-low hover:text-st-on-surface")}>
                    <span className="flex min-w-0 items-center gap-st-space-xs"><Icon name={categorySymbol(n.slug, n.name_fa)} className="text-[20px]" /><span className="truncate">{n.name_fa}</span></span>
                    <Icon name="chevron_left" className={cn("text-[16px] -scale-x-100", i !== active && "opacity-40")} />
                  </Link>
                ))}
              </div>
              {current && <div className="col-span-8 grid grid-cols-2 content-start gap-st-gutter pr-st-space-xs">
                {[...groups.slice(0, 3).map((g) => ({ head: g, items: g.children.filter((x) => x.product_count > 0).slice(0, 5) })),
                  ...(leaves.length || !groups.length ? [{ head: null as TaxNode | null, items: (leaves.length ? leaves : []).slice(0, 6) }] : [])]
                  .slice(0, 4).map((col, i) => (
                  <div key={col.head?.slug ?? `leaf-${i}`} className="flex flex-col gap-st-space-sm">
                    <Link href={`/category/${(col.head ?? current).slug}`} className="border-b border-st-surface-container-low pb-st-space-xs font-bold text-st-primary hover:text-st-secondary">
                      {col.head ? col.head.name_fa : `زیردسته‌های ${current.name_fa}`}</Link>
                    <div className="flex flex-col gap-2">
                      {col.items.length ? col.items.map((s) => <ItemRow key={s.slug} n={s} />)
                        : <p className="py-1 text-st-on-surface-variant">این دسته زیرشاخه ندارد.</p>}
                    </div>
                  </div>
                ))}
                <div className="col-span-2 flex flex-wrap items-center gap-st-gutter">
                  <Link href={`/category/${current.slug}`} className="flex flex-1 items-center justify-between rounded-xl bg-st-surface-container-low p-st-space-sm transition-colors hover:bg-st-surface-container">
                    <span className="font-bold text-st-on-surface">همهٔ کالاهای {current.name_fa}<span className="mr-st-space-xs font-normal text-st-outline">({count(current.product_count)})</span></span>
                    <Icon name="arrow_forward" className="text-[16px] -scale-x-100 text-st-secondary" />
                  </Link>
                  <Link href="/pack-builder" className="flex flex-1 items-center justify-between rounded-xl bg-st-secondary-fixed/25 p-st-space-sm transition-colors hover:bg-st-secondary-fixed/40">
                    <span className="font-bold text-st-on-secondary-container">طراحی پک اختصاصی با پک‌ساز</span>
                    <Icon name="arrow_forward" className="text-[16px] -scale-x-100 text-st-secondary" />
                  </Link>
                </div>
              </div>}
            </>}
        </div>
      )}
    </div>
  );
}
