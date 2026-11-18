"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTaxonomy } from "@/components/layout/MegaMenu";
import { stIcon } from "@/components/catalog/stIcon";
import { catalog } from "@/lib/api";
import type { Product } from "@/lib/types";
import { toman } from "@/components/product/ProductCard";
import { cn, toPersianNum } from "@/lib/utils";
import dark from "@/components/catalog/stitchDark.module.css";

// Category explorer — faithful to Stitch 27 (light, mobile 390) and 05 (dark, via the site theme switch).
// Real taxonomy only: a node appears when at least one REAL product sits under it. Desktop reuses the same
// two-column explorer inside the page container (no desktop Stitch screen exists for this route).
const Icon = ({ name, className }: { name: string; className?: string }) => <span aria-hidden className={cn("material-symbols-outlined", className)}>{name}</span>;
const tile = "flex flex-col rounded-xl border border-st-surface-container bg-st-surface-container-lowest p-st-space-sm shadow-[0_1px_3px_rgba(0,0,0,0.02)] transition-all hover:shadow-md";

function ProductTiles({ slug }: { slug: string }) {
  const [items, setItems] = useState<Product[] | null>(null);
  useEffect(() => {
    let on = true; setItems(null);
    catalog.list({ category: slug, page_size: 8, group: "family" }).then((x) => on && setItems(x.items)).catch(() => on && setItems([]));
    return () => { on = false; };
  }, [slug]);
  if (items === null) return <div className="grid grid-cols-2 gap-st-space-xs md:grid-cols-3 xl:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-40 animate-pulse rounded-xl bg-st-surface-container" />)}</div>;
  if (!items.length) return null;
  return (
    <div className="grid grid-cols-2 gap-st-space-xs md:grid-cols-3 md:gap-st-space-sm xl:grid-cols-4">
      {items.map((p) => (
        <Link key={p.id} href={`/products/${p.slug}`} className={tile}>
          <div className="relative mb-2 flex h-24 w-full items-center justify-center overflow-hidden rounded-lg bg-st-surface-container-low">
            {p.image_url ? <img alt={p.name} src={p.image_url} className="h-full w-full object-contain p-1" loading="lazy" /> : <Icon name="inventory_2" className="text-[32px] text-st-outline" />}
            {(p.variant_count ?? 1) > 1 && <span className="absolute right-1 top-1 rounded-full bg-st-surface-container-lowest/90 px-1.5 py-0.5 text-[10px] font-bold text-st-primary-container backdrop-blur-sm">{toPersianNum(p.variant_count!)} مدل</span>}
          </div>
          <span className="truncate text-[13px] font-semibold leading-snug text-st-primary-container">{p.name}</span>
          <span className="mt-0.5 truncate text-[11px] text-st-on-surface-variant">
            {p.price_minor != null ? `${toman(p.price_minor)} تومان` : p.list_price_minor ? `آخرین قیمت اعلامی ${toman(p.list_price_minor)}` : p.brand || "قیمت با استعلام"}
          </span>
        </Link>
      ))}
    </div>
  );
}

export default function CategoryIndexPage() {
  const tree = useTaxonomy();
  const router = useRouter();
  const [active, setActive] = useState(0);
  const [q, setQ] = useState("");
  const current = tree?.[active];
  return (
    <div className={cn(dark.root, "flex min-h-[calc(100vh-4rem)] w-full flex-col bg-st-background text-st-body-md text-st-on-surface")} dir="rtl">
      <h1 className="sr-only">دسته‌بندی کالاها</h1>
      <div className="shrink-0 border-b border-st-surface-container-high bg-st-surface/85 px-st-margin pb-2 pt-3 backdrop-blur-xl md:px-st-margin-md xl:px-8">
        <form role="search" onSubmit={(e) => { e.preventDefault(); router.push(`/search${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`); }}
          className="relative mx-auto flex w-full max-w-[1280px] items-center rounded-xl bg-st-surface-container-lowest px-st-space-md py-2 shadow-[0_1px_4px_rgba(0,0,0,0.03)]">
          <button type="submit" aria-label="جستجو" className="ml-st-space-sm flex"><Icon name="search" className="text-[20px] text-st-secondary" /></button>
          <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="جستجو در دسته‌بندی‌ها و کالاها" placeholder="جستجو در دسته‌بندی‌ها و کالاها..."
            className="min-w-0 flex-1 border-0 bg-transparent p-0 text-st-body-md text-st-primary-container outline-none placeholder:text-st-outline" />
        </form>
      </div>

      {tree === null ? (
        <div className="flex flex-1">
          <div className="w-24 shrink-0 space-y-2 bg-st-surface-container-low p-2 md:w-60">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-16 animate-pulse rounded-xl bg-st-surface-container" />)}</div>
          <div className="grid flex-1 grid-cols-2 gap-2 p-st-space-md">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-32 animate-pulse rounded-xl bg-st-surface-container" />)}</div>
        </div>
      ) : !tree.length ? (
        <p className="m-st-space-md rounded-xl bg-st-surface-container-lowest p-st-space-lg text-center text-st-on-surface-variant">هنوز دسته‌ای با کالای واقعی ثبت نشده است.</p>
      ) : (
        <div className="mx-auto flex w-full max-w-[1280px] flex-1 md:px-st-margin-md md:py-st-space-lg xl:px-8">
          <aside aria-label="دسته‌های اصلی"
            className="sticky top-16 flex h-[calc(100vh-8rem)] w-24 shrink-0 flex-col overflow-y-auto border-l border-st-surface-container-high bg-st-surface-container-low py-1 [scrollbar-width:none] md:top-28 md:h-auto md:max-h-[calc(100vh-9rem)] md:w-60 md:self-start md:rounded-xl md:border-l-0">
            {tree.map((n, i) => {
              const on = i === active;
              return (
                <button key={n.slug} type="button" onClick={() => setActive(i)} aria-pressed={on}
                  className={cn("relative flex flex-col items-center justify-center px-1 py-3 text-center transition-colors md:flex-row md:justify-start md:gap-3 md:px-3 md:text-right",
                    on ? "border-r-4 border-st-secondary bg-st-surface-container-lowest font-semibold text-st-secondary shadow-sm" : "text-st-on-surface-variant hover:bg-st-surface-container hover:text-st-primary")}>
                  <span className={cn("mb-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-full md:mb-0", on ? "bg-st-secondary-fixed text-st-on-secondary-fixed-variant" : "bg-st-surface-container text-st-on-surface-variant")}>
                    <Icon name={stIcon(n.slug, n.name_fa)} className="text-[20px]" />
                  </span>
                  <span className={cn("text-[11px] leading-tight md:flex-1 md:text-st-label-lg", on && "font-bold text-st-primary-container")}>{n.name_fa}</span>
                  <span className="hidden text-st-label-sm text-st-outline md:inline">{toPersianNum(n.product_count)}</span>
                </button>
              );
            })}
          </aside>

          {current && (
            <section aria-labelledby="cat-current" className="flex min-w-0 flex-1 flex-col gap-st-space-md bg-st-background p-st-space-md md:pr-st-gutter-md md:pt-0">
              <div className="relative flex min-h-[96px] flex-col justify-between overflow-hidden rounded-xl bg-st-primary-container p-st-space-md text-st-on-primary shadow-sm md:min-h-[140px] md:p-st-space-lg">
                <div className="relative z-10">
                  <span className="text-[11px] font-semibold text-st-tertiary-fixed md:text-st-label-md">{toPersianNum(current.product_count)} کالای واقعی{current.children.length ? ` · ${toPersianNum(current.children.length)} زیردسته` : ""}</span>
                  <h2 id="cat-current" className="mt-0.5 text-st-headline-md font-bold text-st-on-primary md:text-st-headline-lg">{current.name_fa}</h2>
                  <p className="mt-0.5 text-[11px] text-st-outline-variant md:text-st-body-md">قیمت و موجودی از پیشنهادهای تأییدشدهٔ فروشندگان؛ کالای بدون قیمت قابل استعلام است.</p>
                </div>
                <div className="pointer-events-none absolute -bottom-4 -left-3 opacity-15"><Icon name={stIcon(current.slug, current.name_fa)} className="text-[100px] md:text-[140px]" /></div>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-st-title-md font-bold text-st-primary-container">{current.children.length ? "زیردسته‌ها" : "کالاهای این دسته"}</span>
                <Link className="flex items-center gap-0.5 text-st-label-sm text-st-secondary hover:underline md:text-st-label-md" href={`/category/${current.slug}`}>
                  <span>مشاهده همه {toPersianNum(current.product_count)} کالا</span><Icon name="arrow_back" className="text-[14px]" />
                </Link>
              </div>

              {current.children.length ? (
                <div className="grid grid-cols-2 gap-st-space-xs md:grid-cols-3 md:gap-st-space-sm xl:grid-cols-4">
                  {current.children.map((c) => (
                    <Link key={c.slug} href={`/category/${c.slug}`} className={tile}>
                      <div className="relative mb-2 flex h-24 w-full items-center justify-center overflow-hidden rounded-lg bg-st-surface-container-low">
                        <Icon name={stIcon(c.slug, c.name_fa)} className="text-[36px] text-st-secondary" />
                        <span className="absolute right-1 top-1 rounded-full bg-st-surface-container-lowest/90 px-1.5 py-0.5 text-[10px] font-bold text-st-primary-container backdrop-blur-sm">{toPersianNum(c.product_count)} کالا</span>
                      </div>
                      <span className="truncate text-[13px] font-semibold leading-snug text-st-primary-container">{c.name_fa}</span>
                      <span className="mt-0.5 truncate text-[11px] text-st-on-surface-variant">{c.children.length ? c.children.slice(0, 2).map((s) => s.name_fa).join("، ") : "مشاهدهٔ کالاها"}</span>
                    </Link>
                  ))}
                </div>
              ) : <ProductTiles slug={current.slug} />}
            </section>
          )}
        </div>
      )}
    </div>
  );
}
