"use client";
// Search & category listing — faithful to Stitch 23 (desktop 1440) and 14 (mobile 390).
// REAL storefront products grouped by family; typed results (products first, packs as a secondary section);
// brand / sub-category / price / availability / attribute facets. URL is the single source of truth.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { catalog, categories } from "@/lib/api";
import { ProductGrid } from "@/components/product/ProductCard";
import type { Product } from "@/lib/types";
import type { AttributeFacet, Facets, PackSummary, TaxNode } from "@/lib/storefront";
import { cn, toPersianNum } from "@/lib/utils";
import { ActiveFilterChips, FilterSheet, FilterSidebar, SORTS, activeCount, readAttrParams, type CategoryLink, type FilterState } from "./AttributeFilters";
import dark from "./stitchDark.module.css";

const PAGE_SIZE = 24;
const Icon = ({ name, className, fill }: { name: string; className?: string; fill?: boolean }) =>
  <span aria-hidden className={cn("material-symbols-outlined", fill && "icon-fill", className)}>{name}</span>;

type Flat = { slug: string; name: string; depth: number };
const flatten = (nodes: TaxNode[], depth = 0, out: Flat[] = []) => {
  for (const n of nodes) { out.push({ slug: n.slug, name: n.name_fa, depth }); flatten(n.children, depth + 1, out); }
  return out;
};
const findPath = (nodes: TaxNode[], slug: string, trail: TaxNode[] = []): TaxNode[] | null => {
  for (const n of nodes) {
    if (n.slug === slug) return [...trail, n];
    const f = findPath(n.children, slug, [...trail, n]);
    if (f) return f;
  }
  return null;
};

/** Page numbers with gaps: 1 … p-1 p p+1 … last. */
function pageList(page: number, pages: number): (number | "…")[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
  const set = new Set([1, pages, page - 1, page, page + 1].filter((n) => n >= 1 && n <= pages));
  const sorted = [...set].sort((a, b) => a - b);
  const out: (number | "…")[] = [];
  sorted.forEach((n, i) => { if (i && n - sorted[i - 1] > 1) out.push("…"); out.push(n); });
  return out;
}

export function CatalogBrowser({ categorySlug }: { categorySlug?: string }) {
  const params = useSearchParams(), router = useRouter(), path = usePathname();
  const q = params.get("q") || "", cat = categorySlug || params.get("cat") || "";
  const brand = params.get("brand") || "", avail = params.get("availability") || "", size = params.get("size") || "";
  const minPrice = params.get("min_price") || "", maxPrice = params.get("max_price") || "";
  const inStock = params.get("in_stock") === "1", official = params.get("official") === "1";
  const attrKey = [...params.entries()].filter(([k]) => k.startsWith("attr.")).map(([k, v]) => k + "=" + v).sort().join("&");
  const attrs = useMemo(() => readAttrParams(new URLSearchParams(attrKey)), [attrKey]);
  const page = Math.max(1, Number(params.get("page")) || 1);
  const sort = params.get("sort") || "relevance"; // without a query the backend ranks by merchandising (buyable, photo, price)
  const [items, setItems] = useState<Product[]>([]), [packs, setPacks] = useState<PackSummary[]>([]), [facets, setFacets] = useState<Facets | null>(null);
  const [tree, setTree] = useState<TaxNode[]>([]), [pages, setPages] = useState(1), [total, setTotal] = useState(0);
  const [attrFacets, setAttrFacets] = useState<AttributeFacet[]>([]);
  const [loading, setLoading] = useState(true), [error, setError] = useState(""), [query, setQuery] = useState(q);
  const [sheet, setSheet] = useState(false);
  const [view, setView] = useState<"grid" | "list">("grid"); // desktop grid/list (Stitch 23 switcher)
  const [mView, setMView] = useState<"list" | "grid">("list"); // mobile list/grid (Stitch 14 switcher)
  // Mobile «نمایش موارد بیشتر»: appends the following pages without touching the URL.
  const [more, setMore] = useState<Product[]>([]), [morePage, setMorePage] = useState(page), [moreBusy, setMoreBusy] = useState(false);

  function change(values: Record<string, string>) {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(values)) v ? next.set(k, v) : next.delete(k);
    router.push(path + "?" + next.toString());
  }
  const listParams = (p: number) => ({ q: q || undefined, category: cat || undefined, brand: brand || undefined, availability: avail || undefined,
    size: size || undefined, min_price: minPrice ? Number(minPrice) : undefined, max_price: maxPrice ? Number(maxPrice) : undefined,
    page: p, page_size: PAGE_SIZE, sort, group: "family" as const, in_stock: inStock ? "1" : undefined, official: official ? "1" : undefined,
    attrs: Object.fromEntries(Object.entries(attrs).map(([c, t]) => ["attr." + c, t.join(",")])) });
  useEffect(() => { setQuery(q); }, [q]);
  useEffect(() => { let on = true; categories.tree().then((t) => on && setTree(t)).catch(() => {}); return () => { on = false; }; }, []);
  useEffect(() => {
    let on = true;
    setLoading(true); setError(""); setMore([]); setMorePage(page);
    catalog.list(listParams(page))
      .then((x) => { if (!on) return; setItems(x.items); setPacks(x.packs); setFacets(x.facets ?? null); setAttrFacets(x.attribute_facets); setTotal(x.total); setPages(Math.max(1, x.pages)); })
      .catch((e) => on && setError(e.message))
      .finally(() => on && setLoading(false));
    return () => { on = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, cat, brand, avail, size, minPrice, maxPrice, page, sort, inStock, official, attrs]);
  const loadMore = () => {
    if (moreBusy || morePage >= pages) return;
    setMoreBusy(true);
    catalog.list(listParams(morePage + 1)).then((x) => { setMore((m) => [...m, ...x.items]); setMorePage(morePage + 1); })
      .catch(() => {}).finally(() => setMoreBusy(false));
  };

  const filterState: FilterState = { attrs, brand, minPrice, maxPrice, inStock, official, purchasable: avail === "purchasable" };
  const flat = useMemo(() => flatten(tree), [tree]);
  const trail = useMemo(() => (cat ? findPath(tree, cat) ?? [] : []), [tree, cat]);
  const name = flat.find((c) => c.slug === cat)?.name;
  // Sidebar tree: children of the current node, or its siblings when it is a leaf; the top level otherwise.
  const catLinks: CategoryLink[] = useMemo(() => {
    const cur = trail[trail.length - 1];
    const list = !cat ? tree : cur?.children.length ? cur.children : (trail[trail.length - 2]?.children ?? tree);
    const qs = q ? `?q=${encodeURIComponent(q)}` : "";
    return list.map((n) => ({ slug: n.slug, name: n.name_fa, count: n.product_count, active: n.slug === cat, href: `/category/${n.slug}${qs}` }));
  }, [tree, trail, cat, q]);
  const shown = page === 1 ? 0 : (page - 1) * PAGE_SIZE;
  const from = total ? shown + 1 : 0, to = Math.min(total, shown + items.length);
  const sortLabel = SORTS.find((s) => s.value === sort)?.label ?? "پیشنهادی";
  const title = name || (q ? `نتایج «${q}»` : "همهٔ کالاها");
  const empty = (
    <div className="rounded-xl bg-st-surface-container-lowest p-st-space-xl text-center text-st-on-surface-variant shadow-sm">
      <Icon name="search" className="mb-2 text-[40px] text-st-outline" />
      <p>{avail ? "در حال حاضر کالای قابل خرید آنلاین در این بخش نیست؛ فیلتر را بردارید تا کالاهای قابل استعلام را ببینید." : "کالایی برای این جستجو یافت نشد. املای دیگری را امتحان کنید یا درخواست تأمین ثبت کنید."}</p>
      <Link href={`/requests/new${q ? `?q=${encodeURIComponent(q)}` : ""}`} className="mt-3 inline-flex font-bold text-st-secondary hover:underline">ثبت درخواست تأمین کالا</Link>
    </div>
  );

  return (
    <div className={cn(dark.root, "w-full bg-st-background text-st-on-surface")} dir="rtl">
      {/* ── Breadcrumb + meta bar (Stitch 23) ─────────────────────────── */}
      <section className="hidden w-full bg-st-surface-container-lowest shadow-sm md:block">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center justify-between gap-st-space-md px-st-margin-md py-st-space-md xl:px-8">
          <nav aria-label="مسیر راهنما" className="flex flex-wrap items-center gap-st-space-xs text-st-on-surface-variant">
            <Link className="flex items-center gap-1 transition-colors hover:text-st-primary" href="/"><Icon name="home" className="text-[18px]" /><span>خانه</span></Link>
            <Icon name="chevron_left" className="text-[16px] text-st-outline" />
            <Link className="transition-colors hover:text-st-primary" href="/category">دسته‌بندی‌ها</Link>
            {trail.slice(0, -1).map((n) => <span key={n.slug} className="flex items-center gap-st-space-xs">
              <Icon name="chevron_left" className="text-[16px] text-st-outline" />
              <Link className="transition-colors hover:text-st-primary" href={`/category/${n.slug}`}>{n.name_fa}</Link></span>)}
            <Icon name="chevron_left" className="text-[16px] text-st-outline" />
            <h1 className="font-bold text-st-primary">{title}</h1>
            {!loading && <>
              <span className="mx-st-space-xs text-st-outline">/</span>
              <span className="rounded-full bg-st-surface-container px-st-space-sm py-0.5 font-bold text-st-secondary">{toPersianNum(total)} قلم کالا فعال</span>
            </>}
          </nav>
          <div className="hidden items-center gap-st-space-lg text-st-on-surface-variant lg:flex">
            <div className="flex items-center gap-1.5"><Icon name="verified" fill className="text-[16px] text-st-secondary" /><span>فقط قیمت‌های تأییدشدهٔ فروشنده</span></div>
            <div className="h-1 w-1 rounded-full bg-st-outline-variant" />
            <div className="flex items-center gap-1.5"><Icon name="domain" className="text-[16px] text-st-secondary" /><span>خرید سازمانی و استعلام تیراژ</span></div>
          </div>
        </div>
      </section>

      {/* ── Mobile search context header (Stitch 14) ───────────────────── */}
      <div className="flex w-full flex-col px-st-margin pt-st-space-sm md:hidden">
        <h1 className="sr-only">{title}</h1>
        <div className="mb-st-space-sm flex flex-col gap-st-space-sm pt-st-space-xs">
          <form role="search" onSubmit={(e) => { e.preventDefault(); change({ q: query, page: "1", sort: "" }); }}
            className="relative flex w-full items-center rounded-xl bg-st-surface-container-lowest px-st-space-md py-2.5 shadow-[0_1px_4px_rgba(0,0,0,0.03)]">
            <button type="submit" aria-label="جستجو" className="ml-st-space-sm flex"><Icon name="search" className="text-[22px] text-st-secondary" /></button>
            <input aria-label="جستجوی کالا" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={name ? `جستجو در ${name}...` : "جستجوی کالا، برند یا کد کالا..."}
              className="min-w-0 flex-1 border-0 bg-transparent p-0 text-st-title-md text-st-primary-container outline-none placeholder:text-st-outline" />
            {query && <button aria-label="پاک کردن جستجو" type="button" onClick={() => { setQuery(""); if (q) change({ q: "", page: "1" }); }}
              className="flex h-7 w-7 items-center justify-center rounded-full bg-st-surface-container text-st-on-surface-variant transition-colors hover:text-st-primary"><Icon name="close" className="text-[16px]" /></button>}
          </form>
          <div className="[scrollbar-width:none] [&::-webkit-scrollbar]:hidden -mx-st-margin flex items-center gap-st-space-xs overflow-x-auto px-st-margin py-1">
            <button type="button" onClick={() => setSheet(true)} aria-haspopup="dialog" aria-expanded={sheet}
              className="flex shrink-0 items-center gap-1.5 rounded-full bg-st-primary-container px-3.5 py-1.5 text-st-label-md text-st-on-primary shadow-sm transition-transform active:scale-95">
              <Icon name="tune" className="text-[16px]" /><span>فیلتر و ترتیب</span>
              {activeCount(filterState) > 0 && <span className="h-1.5 w-1.5 rounded-full bg-st-tertiary-fixed" aria-label={`${toPersianNum(activeCount(filterState))} فیلتر فعال`} />}
            </button>
            <button type="button" onClick={() => setSheet(true)} className="flex shrink-0 items-center gap-1 rounded-full bg-st-surface-container-lowest px-3 py-1.5 text-st-label-md text-st-on-surface shadow-[0_1px_3px_rgba(0,0,0,0.02)]">
              <span className="text-st-on-surface-variant">مرتب‌سازی:</span><span className="font-semibold text-st-secondary">{sortLabel}</span>
            </button>
            <button type="button" aria-pressed={inStock} onClick={() => change({ in_stock: inStock ? "" : "1", page: "1" })}
              className={cn("flex shrink-0 items-center gap-1 rounded-full px-3 py-1.5 text-st-label-md shadow-[0_1px_3px_rgba(0,0,0,0.02)]", inStock ? "bg-st-secondary-fixed text-st-on-secondary-fixed" : "bg-st-surface-container-lowest text-st-on-surface")}>
              <span className="h-2 w-2 rounded-full bg-st-secondary" /><span>فقط موجود</span>
            </button>
            <button type="button" aria-pressed={avail === "purchasable"} onClick={() => change({ availability: avail === "purchasable" ? "" : "purchasable", page: "1" })}
              className={cn("flex shrink-0 items-center gap-1 rounded-full px-3 py-1.5 text-st-label-md shadow-[0_1px_3px_rgba(0,0,0,0.02)]", avail === "purchasable" ? "bg-st-secondary-fixed text-st-on-secondary-fixed" : "bg-st-surface-container-lowest text-st-on-surface")}>
              <Icon name="bolt" className="text-[15px] text-st-secondary" /><span>خرید آنلاین</span>
            </button>
            {catLinks.filter((c) => !c.active).map((c) => <Link key={c.slug} href={c.href}
              className="flex shrink-0 items-center gap-1 rounded-full bg-st-surface-container-lowest px-3 py-1.5 text-st-label-md text-st-on-surface shadow-[0_1px_3px_rgba(0,0,0,0.02)]">
              {c.name}<span className="text-st-outline">{toPersianNum(c.count)}</span></Link>)}
          </div>
        </div>
        <div className="mb-st-space-sm flex items-center justify-between py-st-space-xs">
          <div className="flex items-center gap-1.5" aria-live="polite">
            <span className="text-st-headline-md text-st-primary-container">{loading ? "…" : toPersianNum(total)}</span>
            <span className="text-st-body-sm text-st-on-surface-variant">{name ? `کالا در ${name}` : "کالا در دسترس"}</span>
          </div>
          <div className="flex items-center rounded-lg bg-st-surface-container p-0.5">
            <button type="button" aria-label="نمایش لیستی" aria-pressed={mView === "list"} onClick={() => setMView("list")}
              className={cn("rounded p-1", mView === "list" ? "bg-st-surface-container-lowest text-st-primary-container shadow-sm" : "text-st-outline")}><Icon name="view_list" className="text-[20px]" /></button>
            <button type="button" aria-label="نمایش شبکه‌ای" aria-pressed={mView === "grid"} onClick={() => setMView("grid")}
              className={cn("rounded p-1", mView === "grid" ? "bg-st-surface-container-lowest text-st-primary-container shadow-sm" : "text-st-outline")}><Icon name="grid_view" className="text-[20px]" /></button>
          </div>
        </div>
        {(activeCount(filterState) > 0) && <div className="mb-st-space-sm text-st-label-md"><ActiveFilterChips attrFacets={attrFacets} state={filterState} change={change} /></div>}
        <div className="pb-st-space-lg">
          {error ? <p role="alert" className="rounded-xl bg-st-error-container p-st-space-md text-st-on-error-container">{error}</p>
            : loading ? <div className="flex flex-col gap-st-space-sm">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-32 animate-pulse rounded-xl bg-st-surface-container" />)}</div>
            : items.length ? <>
              <ProductGrid products={[...items, ...more]} view={mView} cols={2} />
              {morePage < pages && <button type="button" onClick={loadMore} disabled={moreBusy}
                className="mt-st-space-md flex w-full items-center justify-center gap-st-space-sm rounded-xl bg-st-surface-container-lowest py-3 text-st-label-lg text-st-primary-container shadow-sm disabled:opacity-60">
                <span>{moreBusy ? "در حال دریافت…" : `نمایش موارد بیشتر (${toPersianNum(total - to - more.length)} کالای دیگر)`}</span><Icon name="expand_more" className="text-[20px]" />
              </button>}
              <p className="mt-st-space-sm text-center text-st-label-sm text-st-outline">نمایش {toPersianNum(from)} تا {toPersianNum(to + more.length)} از {toPersianNum(total)} کالای واجد شرایط</p>
            </> : empty}
        </div>
      </div>
      <FilterSheet open={sheet} onClose={() => setSheet(false)} facets={facets} attrFacets={attrFacets} state={filterState} change={change}
        loading={loading} total={total} sort={sort} onSort={(v) => change({ sort: v, page: "1" })} categories={catLinks} />

      {/* ── Desktop body: sidebar + catalog (Stitch 23) ───────────────── */}
      <section className="mx-auto hidden w-full max-w-[1280px] px-st-margin-md py-st-space-xl md:block xl:px-8">
        <div className="flex items-start gap-st-gutter-lg">
          <aside className="sticky top-32 z-10 flex w-72 shrink-0 flex-col gap-st-space-md lg:w-80" aria-label="فیلترها">
            <FilterSidebar facets={facets} attrFacets={attrFacets} state={filterState} change={change} loading={loading} total={total} categories={catLinks} />
            <div className="relative overflow-hidden rounded-xl bg-st-primary-container p-st-space-md text-st-on-primary shadow-sm">
              <div className="relative z-10 flex flex-col gap-st-space-xs">
                <div className="flex items-center gap-2 text-st-on-tertiary-container"><Icon name="support_agent" className="text-[20px]" /><span className="font-bold">خرید عمده و سازمانی</span></div>
                <p className="text-st-outline-variant">برای تأمین در تیراژ بالا یا کالایی که در فهرست نیست، درخواست استعلام ثبت کنید تا قیمت و زمان تحویل از تأمین‌کنندگان دریافت شود.</p>
                <Link className="mt-st-space-xs inline-flex items-center gap-1 text-st-secondary-fixed hover:underline" href="/requests/new">
                  <span>ثبت درخواست استعلام سازمانی</span><Icon name="arrow_back" className="text-[14px]" /></Link>
              </div>
            </div>
          </aside>

          <main className="flex min-w-0 flex-1 flex-col gap-st-space-lg">
            <div className="flex flex-col gap-st-space-md rounded-xl bg-st-surface-container-lowest p-st-space-md shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-st-space-md">
                <div className="flex flex-wrap items-center gap-st-space-xs" role="group" aria-label="مرتب‌سازی">
                  <span className="ml-st-space-xs flex items-center gap-1 text-st-outline"><Icon name="sort" className="text-[18px]" /><span>مرتب‌سازی:</span></span>
                  {SORTS.map((s) => <button key={s.value} type="button" aria-pressed={sort === s.value} onClick={() => change({ sort: s.value, page: "1" })}
                    className={cn("rounded-full px-st-space-md py-1.5 transition-colors", sort === s.value ? "bg-st-primary-container font-bold text-st-on-primary shadow-sm" : "bg-st-surface-container-low text-st-on-surface-variant hover:text-st-primary")}>
                    {s.value === "relevance" && q ? "مرتبط‌ترین" : s.label}</button>)}
                </div>
                <div className="flex items-center gap-st-space-md">
                  <span className="text-st-outline" aria-live="polite">{loading ? "در حال دریافت…" : `نمایش ${toPersianNum(from)}-${toPersianNum(to)} از ${toPersianNum(total)}`}</span>
                  <div className="flex items-center gap-1 rounded-lg bg-st-surface-container-low p-1">
                    <button type="button" aria-label="نمایش شبکه‌ای" aria-pressed={view === "grid"} onClick={() => setView("grid")}
                      className={cn("flex h-8 w-8 items-center justify-center rounded", view === "grid" ? "bg-st-surface-container-lowest text-st-primary shadow-sm" : "text-st-outline hover:text-st-primary")}><Icon name="grid_view" className="text-[18px]" /></button>
                    <button type="button" aria-label="نمایش لیستی" aria-pressed={view === "list"} onClick={() => setView("list")}
                      className={cn("flex h-8 w-8 items-center justify-center rounded", view === "list" ? "bg-st-surface-container-lowest text-st-primary shadow-sm" : "text-st-outline hover:text-st-primary")}><Icon name="format_list_bulleted" className="text-[18px]" /></button>
                  </div>
                </div>
              </div>
              <ActiveFilterChips attrFacets={attrFacets} state={filterState} change={change} />
            </div>

            {error ? <p role="alert" className="rounded-xl bg-st-error-container p-st-space-md text-st-on-error-container">{error}</p>
              : loading ? <div className="grid gap-st-gutter-md md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-[30rem] animate-pulse rounded-xl bg-st-surface-container" />)}</div>
              : items.length ? <ProductGrid products={items} cols={3} view={view} /> : empty}

            {!loading && !error && pages > 1 && (
              <nav aria-label="صفحه‌بندی نتایج" className="mt-st-space-md flex w-full flex-col items-center justify-between gap-st-space-md rounded-xl bg-st-surface-container-lowest p-st-space-md shadow-sm lg:flex-row">
                <div className="flex items-center gap-st-space-xs text-st-on-surface-variant">
                  <span>صفحه</span><span className="font-bold text-st-primary">{toPersianNum(page)}</span><span>از</span><span className="font-bold text-st-primary">{toPersianNum(pages)}</span>
                  <span className="mx-2 text-st-outline">|</span><span>نمایش {toPersianNum(from)} تا {toPersianNum(to)} از {toPersianNum(total)} قلم کالا</span>
                </div>
                <div className="flex items-center gap-st-space-xs">
                  <button type="button" disabled={page <= 1} onClick={() => change({ page: String(page - 1) })}
                    className="flex h-10 items-center gap-1 rounded-xl bg-st-surface-container-low px-st-space-md text-st-primary transition-colors hover:bg-st-surface-container disabled:cursor-not-allowed disabled:bg-st-surface-container disabled:text-st-outline">
                    <Icon name="arrow_forward" className="text-[18px]" /><span>صفحه قبل</span></button>
                  {pageList(page, pages).map((n, i) => n === "…" ? <span key={"g" + i} className="px-1 text-st-outline">…</span>
                    : <button key={n} type="button" aria-current={n === page ? "page" : undefined} onClick={() => change({ page: String(n) })}
                        className={cn("h-10 w-10 rounded-xl transition-colors", n === page ? "bg-st-primary font-bold text-st-on-primary shadow-sm" : "bg-st-surface-container-low text-st-on-surface hover:bg-st-surface-container")}>{toPersianNum(n)}</button>)}
                  <button type="button" disabled={page >= pages} onClick={() => change({ page: String(page + 1) })}
                    className="flex h-10 items-center gap-1 rounded-xl bg-st-surface-container-low px-st-space-md text-st-primary transition-colors hover:bg-st-surface-container disabled:cursor-not-allowed disabled:bg-st-surface-container disabled:text-st-outline">
                    <span>صفحه بعد</span><Icon name="arrow_back" className="text-[18px]" /></button>
                </div>
              </nav>
            )}

            <div className="flex flex-col items-center justify-between gap-st-space-md rounded-xl bg-st-surface-container-low p-st-space-lg lg:flex-row">
              <div className="flex items-start gap-st-space-md">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-st-secondary-fixed text-st-on-secondary-fixed"><Icon name="receipt_long" className="text-[24px]" /></div>
                <div className="flex flex-col gap-1">
                  <h2 className="font-bold text-st-primary">خرید سازمانی با پیش‌فاکتور</h2>
                  <p className="max-w-2xl leading-relaxed text-st-on-surface-variant">برای خرید سازمانی، کالاها را به میز سفارش سازمان اضافه کنید یا درخواست استعلام ثبت کنید؛ پیش‌فاکتورهای صادرشده در پنل شما قابل مشاهده و پیگیری است.</p>
                </div>
              </div>
              <Link href="/org" className="flex h-11 items-center gap-2 whitespace-nowrap rounded-xl bg-st-surface-container-lowest px-st-space-lg font-bold text-st-primary shadow-sm transition-all hover:bg-st-primary hover:text-st-on-primary">
                <span>آشنایی با خرید سازمانی</span><Icon name="arrow_back" className="text-[16px]" /></Link>
            </div>
          </main>
        </div>
      </section>

      {!loading && packs.length > 0 && (
        <section className="mx-auto w-full max-w-[1280px] px-st-margin pb-st-space-xl md:px-st-margin-md xl:px-8" aria-label="پک‌های مرتبط">
          <h2 className="mb-st-space-sm text-st-title-lg text-st-primary-container">پک‌هایی که این کالا را دارند</h2>
          <div className="grid gap-st-space-sm sm:grid-cols-2 lg:grid-cols-4">{packs.map((p) => (
            <Link key={p.slug} href={`/packs/${p.slug}`} className="flex flex-col gap-1 rounded-xl bg-st-surface-container-lowest p-st-space-md shadow-sm transition-shadow hover:shadow-md">
              <span className="text-st-label-sm text-st-secondary">{p.kind_fa}{p.tier_fa ? ` · ${p.tier_fa}` : ""}</span>
              <p className="font-bold text-st-primary">{p.title_fa}</p>
              <p className="text-st-body-sm text-st-on-surface-variant">{toPersianNum(p.item_count)} قلم · {p.availability === "quote_only" ? "قیمت با استعلام" : "قابل سفارش"}</p>
            </Link>))}</div>
        </section>
      )}
    </div>
  );
}
