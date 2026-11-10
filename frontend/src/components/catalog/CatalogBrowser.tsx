"use client";
// Search & category browsing over the marketplace storefront: REAL products grouped by family, typed
// results (products first, packs as a secondary section), brand/sub-category/size/price/availability facets.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { CatalogSkeleton } from "./CatalogSkeleton";
import { catalog, categories } from "@/lib/api";
import { ProductGrid } from "@/components/product/ProductCard";
import type { Product } from "@/lib/types";
import type { AttributeFacet, Facets, PackSummary, TaxNode } from "@/lib/storefront";
import { toPersianNum } from "@/lib/utils";
import { ActiveFilterChips, FilterPanel, readAttrParams, type FilterState } from "./AttributeFilters";

type Flat = { slug: string; name: string; depth: number };
const flatten = (nodes: TaxNode[], depth = 0, out: Flat[] = []) => {
  for (const n of nodes) { out.push({ slug: n.slug, name: n.name_fa, depth }); flatten(n.children, depth + 1, out); }
  return out;
};

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
  function change(values: Record<string, string>) {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(values)) v ? next.set(k, v) : next.delete(k);
    router.push(path + "?" + next.toString());
  }
  useEffect(() => { setQuery(q); }, [q]);
  useEffect(() => { let on = true; categories.tree().then((t) => on && setTree(t)).catch(() => {}); return () => { on = false; }; }, []);
  useEffect(() => {
    let on = true;
    setLoading(true); setError("");
    catalog.list({ q: q || undefined, category: cat || undefined, brand: brand || undefined, availability: avail || undefined,
                   size: size || undefined, min_price: minPrice ? Number(minPrice) : undefined, max_price: maxPrice ? Number(maxPrice) : undefined,
                   page, page_size: 24, sort, group: "family",
                   in_stock: inStock ? "1" : undefined, official: official ? "1" : undefined,
                   attrs: Object.fromEntries(Object.entries(attrs).map(([c, t]) => ["attr." + c, t.join(",")])) })
      .then((x) => { if (!on) return; setItems(x.items); setPacks(x.packs); setFacets(x.facets ?? null); setAttrFacets(x.attribute_facets); setTotal(x.total); setPages(Math.max(1, x.pages)); })
      .catch((e) => on && setError(e.message))
      .finally(() => on && setLoading(false));
    return () => { on = false; };
  }, [q, cat, brand, avail, size, minPrice, maxPrice, page, sort, inStock, official, attrs]);
  const filterState: FilterState = { attrs, brand, minPrice, maxPrice, inStock, official, purchasable: avail === "purchasable" };
  const flat = useMemo(() => flatten(tree), [tree]);
  const name = flat.find((c) => c.slug === cat)?.name;
  const subNodes = useMemo(() => {
    const find = (nodes: TaxNode[]): TaxNode | undefined => { for (const n of nodes) { if (n.slug === cat) return n; const f = find(n.children); if (f) return f; } };
    return cat ? find(tree)?.children ?? [] : tree;
  }, [tree, cat]);
  const chip = "rounded-full border px-3 py-1.5 text-xs font-bold whitespace-nowrap";

  return (
    <div className="internal-page container-page py-8" dir="rtl">
      <nav className="mb-5 flex flex-wrap gap-4 text-sm">
        <Link href="/">خانه</Link><Link href="/category">دسته‌بندی‌ها</Link><Link href="/pack-builder">پک‌ها</Link><Link href="/requests">درخواست‌های من</Link>
      </nav>
      <h1 className="mb-5 text-2xl font-bold text-brand-navy">{name || (q ? `نتایج «${q}»` : "جستجوی کالا")}</h1>
      <form className="mb-4 flex flex-wrap gap-3" onSubmit={(e) => { e.preventDefault(); change({ q: query, page: "1", sort: "" }); }}>
        <input aria-label="جستجوی کالا" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="نام کالا، برند، مدل، وزن یا کد کالا"
          className="min-h-12 min-w-0 flex-1 rounded-xl border p-3" />
        <button className="rounded-xl bg-primary-600 px-5 text-white">جستجو</button>
        {!categorySlug && (
          <select aria-label="دسته‌بندی" value={cat} onChange={(e) => change({ cat: e.target.value, page: "1" })} className="min-h-12 max-w-full rounded-xl border p-3">
            <option value="">همه دسته‌ها</option>
            {flat.map((c) => <option key={c.slug} value={c.slug}>{"— ".repeat(c.depth)}{c.name}</option>)}
          </select>
        )}
        <select aria-label="مرتب‌سازی" value={sort} onChange={(e) => change({ sort: e.target.value, page: "1" })} className="min-h-12 rounded-xl border p-3">
          <option value="relevance">{q ? "مرتبط‌ترین" : "پیشنهادی"}</option>
          <option value="newest">جدیدترین</option><option value="name">نام</option><option value="price_asc">قیمت کمتر</option><option value="price_desc">قیمت بیشتر</option>
        </select>
      </form>

      {subNodes.length > 0 && <div className="mb-3 flex gap-2 overflow-x-auto pb-1" aria-label="زیردسته‌ها">
        {subNodes.map((n) => <Link key={n.slug} href={`/category/${n.slug}${q ? `?q=${encodeURIComponent(q)}` : ""}`} className={`${chip} border-neutral-200 bg-white text-neutral-700 hover:border-brand-blue`}>{n.name_fa} ({toPersianNum(n.product_count)})</Link>)}
      </div>}
      {facets && (facets.brands.length > 1 || brand) && <div className="mb-3 flex gap-2 overflow-x-auto pb-1" aria-label="برندها">
        <button type="button" onClick={() => change({ brand: "", page: "1" })} className={`${chip} ${!brand ? "border-brand-navy bg-brand-navy text-white" : "border-neutral-200 bg-white"}`}>همه برندها</button>
        {facets.brands.map((b) => <button key={b.value} type="button" onClick={() => change({ brand: b.value, page: "1" })}
          className={`${chip} ${brand === b.value ? "border-brand-navy bg-brand-navy text-white" : "border-neutral-200 bg-white text-neutral-700"}`}>{b.value} ({toPersianNum(b.count)})</button>)}
      </div>}
      {facets?.sizes && (facets.sizes.length > 1 || size) && <div className="mb-3 flex gap-2 overflow-x-auto pb-1" aria-label="اندازه و وزن">
        <button type="button" onClick={() => change({ size: "", page: "1" })} className={`${chip} ${!size ? "border-brand-navy bg-brand-navy text-white" : "border-neutral-200 bg-white"}`}>همه اندازه‌ها</button>
        {facets.sizes.map((s) => <button key={s.value} type="button" onClick={() => change({ size: s.value, page: "1" })}
          className={`${chip} ${size === s.value ? "border-brand-navy bg-brand-navy text-white" : "border-neutral-200 bg-white text-neutral-700"}`}>{s.value} ({toPersianNum(s.count)})</button>)}
      </div>}
      <ActiveFilterChips attrFacets={attrFacets} state={filterState} change={change} />
      <div className="md:grid md:grid-cols-[15rem_minmax(0,1fr)] md:items-start md:gap-6">
      <FilterPanel facets={facets} attrFacets={attrFacets} state={filterState} change={change} loading={loading} total={total} />
      <div className="min-w-0">
      <p className="mb-4 text-sm" aria-live="polite">{loading ? "در حال دریافت…" : toPersianNum(total) + " محصول"}</p>
      {error ? <p role="alert" className="rounded-xl bg-red-50 p-5 text-red-800">{error}</p>
        : loading ? <CatalogSkeleton />
        : items.length ? <ProductGrid products={items} cols={3} />
        : <div className="card p-8 text-center text-neutral-600">{avail ? "در حال حاضر کالای قابل خرید آنلاین در این بخش نیست؛ فیلتر را بردارید تا کالاهای قابل استعلام را ببینید." : "کالایی برای این جستجو یافت نشد. املای دیگری را امتحان کنید یا درخواست تأمین ثبت کنید."}
            <div className="mt-3"><Link href={`/requests/new${q ? `?q=${encodeURIComponent(q)}` : ""}`} className="font-bold text-brand-blue">ثبت درخواست تأمین کالا</Link></div></div>}
      {!loading && !error && pages > 1 && (
        <nav aria-label="صفحه‌بندی" className="mt-8 flex items-center justify-center gap-4">
          <button disabled={page <= 1} onClick={() => change({ page: String(page - 1) })} className="min-h-11 rounded-xl border px-4 disabled:opacity-40">قبلی</button>
          <span>صفحه {toPersianNum(page)} از {toPersianNum(pages)}</span>
          <button disabled={page >= pages} onClick={() => change({ page: String(page + 1) })} className="min-h-11 rounded-xl border px-4 disabled:opacity-40">بعدی</button>
        </nav>
      )}
      {!loading && packs.length > 0 && (
        <section className="mt-10" aria-label="پک‌های مرتبط">
          <h2 className="mb-3 text-lg font-black text-brand-navy">پک‌هایی که این کالا را دارند</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{packs.map((p) => (
            <Link key={p.slug} href={`/packs/${p.slug}`} className="card p-4 hover:border-brand-blue">
              <span className="text-[11px] font-bold text-neutral-500">{p.kind_fa}{p.tier_fa ? ` · ${p.tier_fa}` : ""}</span>
              <p className="mt-1 font-bold text-brand-navy">{p.title_fa}</p>
              <p className="mt-1 text-xs text-neutral-600">{toPersianNum(p.item_count)} قلم · {p.availability === "quote_only" ? "قیمت با استعلام" : "قابل سفارش"}</p>
            </Link>))}</div>
        </section>
      )}
      </div>
      </div>
    </div>
  );
}
