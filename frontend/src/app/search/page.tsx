"use client";

import { Suspense, useState, useMemo, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { catalog, categories as categoriesApi } from "@/lib/api";
import { ProductGrid } from "@/components/product/ProductCard";
import type { Category, Product } from "@/lib/types";

// Free-text search over the real catalog. Deliberately kept as its own page/
// component, separate from /category/[slug] (category browsing) — this page
// only ever narrows by an optional category slug, it does not own category
// routing or a category's canonical URL.

type SortKey = "relevant" | "price_asc" | "price_desc" | "rating" | "newest";

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "relevant",   label: "مرتبط‌ترین" },
  { value: "price_asc",  label: "ارزان‌ترین" },
  { value: "price_desc", label: "گران‌ترین" },
  { value: "rating",     label: "بهترین امتیاز" },
  { value: "newest",     label: "جدیدترین" },
];

// ── Filters sidebar ───────────────────────────────────────────────────────────

function FilterSidebar({
  cats,
  categorySlug,
  onCategory,
  priceMax,
  onPriceMax,
}: {
  cats: Category[];
  categorySlug: string | null;
  onCategory: (slug: string | null) => void;
  priceMax: number;
  onPriceMax: (n: number) => void;
}) {
  return (
    <aside className="w-full lg:w-60 xl:w-64 flex-shrink-0 space-y-6">
      {/* Categories */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold text-neutral-900 mb-3">دسته‌بندی</h3>
        <div className="space-y-1">
          <button
            onClick={() => onCategory(null)}
            className={cn(
              "w-full text-right px-3 py-2 rounded-lg text-sm transition-colors",
              categorySlug === null
                ? "bg-primary-50 text-primary-700 font-semibold"
                : "text-neutral-600 hover:bg-neutral-50"
            )}
          >
            همه
          </button>
          {cats.map((c) => (
            <button
              key={c.slug}
              onClick={() => onCategory(c.slug)}
              className={cn(
                "w-full text-right px-3 py-2 rounded-lg text-sm transition-colors",
                categorySlug === c.slug
                  ? "bg-primary-50 text-primary-700 font-semibold"
                  : "text-neutral-600 hover:bg-neutral-50"
              )}
            >
              {c.name}
            </button>
          ))}
        </div>
      </div>

      {/* Price range */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold text-neutral-900 mb-3">حداکثر قیمت</h3>
        <input
          type="range"
          min={0}
          max={300}
          step={10}
          value={priceMax}
          onChange={(e) => onPriceMax(+e.target.value)}
          className="w-full accent-primary-600"
        />
        <div className="flex justify-between text-2xs text-neutral-400 mt-2">
          <span>رایگان</span>
          <span className="font-medium text-primary-600">{priceMax === 300 ? "همه" : `${priceMax} میلیون`}</span>
        </div>
      </div>
    </aside>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SearchPage() {
  return (
    <Suspense fallback={<div className="internal-page container-page py-10"><div className="card p-6"><div className="h-12 rounded-xl skeleton" /><div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-3">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="aspect-square rounded-2xl skeleton" />)}</div></div></div>}>
      <SearchPageInner />
    </Suspense>
  );
}

function SearchPageInner() {
  const searchParams = useSearchParams();
  const initialCat = searchParams.get("cat");
  const initialQ = searchParams.get("q") ?? "";

  const [query, setQuery]             = useState(initialQ);
  const [categorySlug, setCategorySlug] = useState<string | null>(initialCat);
  const [sort, setSort]               = useState<SortKey>("relevant");
  const [priceMax, setPriceMax]       = useState(300);
  const [showFilters, setShowFilters] = useState(false);

  const [cats, setCats] = useState<Category[]>([]);
  const [products, setProducts] = useState<Product[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    categoriesApi.list().then(setCats).catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    setProducts(null);
    setError(null);
    catalog
      .list({ category: categorySlug ?? undefined, q: query.trim() || undefined, page_size: 48 })
      .then((res) => {
        if (!cancelled) {
          setProducts(res.items);
          setTotal(res.total);
        }
      })
      .catch((e) => {
        if (!cancelled) { setError(e instanceof Error ? e.message : "خطا در جست‌وجو"); setProducts([]); setTotal(0); }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categorySlug, query]);

  const results = useMemo(() => {
    let list = [...(products ?? [])];

    if (priceMax < 300) {
      list = list.filter((p) => p.price_minor != null && p.price_minor / 1e7 <= priceMax);
    }

    switch (sort) {
      case "price_asc":  list.sort((a, b) => (a.price_minor ?? Infinity) - (b.price_minor ?? Infinity)); break;
      case "price_desc": list.sort((a, b) => (b.price_minor ?? -1) - (a.price_minor ?? -1)); break;
      case "rating":     list.sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0)); break;
      case "newest":     list.sort((a, b) => b.id - a.id); break;
    }

    return list;
  }, [products, sort, priceMax]);

  return (
    <div className="internal-page container-page py-6 md:py-10">
      {/* Top bar */}
      <div className="flex items-center gap-3 mb-6">
        {/* Mobile filter toggle */}
        <button
          onClick={() => setShowFilters(!showFilters)}
          className="lg:hidden flex items-center gap-1.5 px-3 py-2 rounded-lg border border-neutral-200 text-sm text-neutral-700 hover:bg-neutral-50"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2a1 1 0 01-.293.707l-6.414 6.414A1 1 0 0014 13.828v5.172a1 1 0 01-.553.894l-4 2A1 1 0 018 21v-7.172a1 1 0 00-.293-.707L1.293 6.707A1 1 0 011 6V4z" />
          </svg>
          فیلترها
        </button>

        {/* Search box */}
        <div className="flex-1 relative">
          <input
            type="search"
            placeholder="دنبال چه کالایی هستید؟"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full h-12 pr-4 pl-11 rounded-xl border-2 border-neutral-200 text-sm focus:outline-none focus:border-amber-400 focus:ring-4 focus:ring-amber-100 bg-white shadow-sm"
          />
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-amber-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35m0 0A7.5 7.5 0 104.5 4.5a7.5 7.5 0 0012.15 12.15z" />
          </svg>
        </div>

        {/* Sort */}
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          className="h-12 pr-3 pl-8 rounded-xl border border-neutral-200 text-sm bg-white text-neutral-700 focus:outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100 cursor-pointer"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-6 lg:flex-row">
        {/* Sidebar — desktop always, mobile conditional */}
        <div className={cn("lg:block", showFilters ? "block" : "hidden")}>
          <FilterSidebar
            cats={cats}
            categorySlug={categorySlug}
            onCategory={(slug) => { setCategorySlug(slug); setShowFilters(false); }}
            priceMax={priceMax}
            onPriceMax={setPriceMax}
          />
        </div>

        {/* Results */}
        <div className="flex-1 min-w-0">
          {error && <div role="alert" className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"><b className="block mb-1">جستجو در دسترس نیست</b>{error}</div>}
          <p className="text-sm text-neutral-500 mb-4">
            {products === null
              ? "در حال جست‌وجو…"
              : priceMax < 300
                ? `${results.length} محصول مطابق فیلتر قیمت یافت شد`
                : `${total} محصول یافت شد`}
          </p>
          {products === null ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 md:gap-5">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="card aspect-[4/3] animate-pulse bg-neutral-100" />
              ))}
            </div>
          ) : results.length > 0 ? (
            <ProductGrid products={results} cols={3} />
          ) : (
            <div className="card py-16 text-center text-neutral-400">
              <svg className="w-12 h-12 mx-auto mb-3 opacity-40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-4.35-4.35m0 0A7.5 7.5 0 104.5 4.5a7.5 7.5 0 0012.15 12.15z" />
              </svg>
              <p className="font-medium">محصولی یافت نشد</p>
              <p className="text-sm mt-1">فیلترها را تغییر دهید</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
