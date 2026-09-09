"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { catalog, categories } from "@/lib/api";
import { ProductGrid } from "@/components/product/ProductCard";
import type { Product, Category } from "@/lib/types";
export function CatalogBrowser({ categorySlug }: { categorySlug?: string }) {
  const params = useSearchParams(),
    router = useRouter(),
    path = usePathname();
  const q = params.get("q") || "",
    cat = categorySlug || params.get("cat") || "";
  const page = Math.max(1, Number(params.get("page")) || 1),
    sort = params.get("sort") || "newest";
  const [items, setItems] = useState<Product[]>([]),
    [cats, setCats] = useState<Category[]>([]),
    [pages, setPages] = useState(1),
    [total, setTotal] = useState(0),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [query, setQuery] = useState(q);
  function change(values: Record<string, string>) {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(values)) {
      v ? next.set(k, v) : next.delete(k);
    }
    router.push(path + "?" + next.toString());
  }
  useEffect(() => {
    setQuery(q);
  }, [q]);
  useEffect(() => {
    let active = true;
    categories
      .list()
      .then((x) => active && setCats(x))
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    catalog
      .list({
        q: q || undefined,
        category: cat || undefined,
        page,
        page_size: 24,
        sort,
      })
      .then((x) => {
        if (active) {
          setItems(
            x.items.map((p) => ({
              ...p,
              stock: p.purchasable ? p.stock : undefined,
            })),
          );
          setTotal(x.total);
          setPages(Math.max(1, x.pages));
        }
      })
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [q, cat, page, sort]);
  const name = cats.find((c) => c.slug === cat)?.name;
  return (
    <div className="internal-page container-page py-8">
      <nav className="mb-5 flex flex-wrap gap-4 text-sm">
        <Link href="/">خانه</Link>
        <Link href="/category">دسته‌بندی‌ها</Link>
        <Link href="/requests">درخواست‌های من</Link>
        <Link href="/account">حساب و خدمات</Link>
      </nav>
      <h1 className="mb-5 text-2xl font-bold text-brand-navy">
        {name || "جستجوی کالا"}
      </h1>
      <form
        className="mb-6 flex flex-wrap gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          change({ q: query, page: "1" });
        }}
      >
        <input
          aria-label="جستجوی کالا"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="نام، برند یا مدل کالا"
          className="min-h-12 min-w-0 flex-1 rounded-xl border p-3"
        />
        <button className="rounded-xl bg-primary-600 px-5 text-white">
          جستجو
        </button>
        {!categorySlug && (
          <select
            aria-label="دسته‌بندی"
            value={cat}
            onChange={(e) => change({ cat: e.target.value, page: "1" })}
            className="min-h-12 max-w-full rounded-xl border p-3"
          >
            <option value="">همه دسته‌ها</option>
            {cats.map((c) => (
              <option key={c.slug} value={c.slug}>
                {c.name}
              </option>
            ))}
          </select>
        )}
        <select
          aria-label="مرتب‌سازی"
          value={sort}
          onChange={(e) => change({ sort: e.target.value, page: "1" })}
          className="min-h-12 rounded-xl border p-3"
        >
          <option value="newest">ترتیب پیش‌فرض</option>
          <option value="price_asc">قیمت کمتر</option>
          <option value="price_desc">قیمت بیشتر</option>
        </select>
      </form>
      <p className="mb-4 text-sm" aria-live="polite">
        {loading ? "در حال دریافت…" : total.toLocaleString("fa-IR") + " کالا"}
      </p>
      {error ? (
        <p role="alert" className="rounded-xl bg-red-50 p-5 text-red-800">
          {error}
        </p>
      ) : loading ? (
        <div className="min-h-64 animate-pulse rounded-xl bg-neutral-100" />
      ) : items.length ? (
        <ProductGrid products={items} cols={3} />
      ) : (
        <div className="card p-8 text-center text-neutral-600">{categorySlug && !q ? "این دسته در حال تکمیل محصولات است." : "کالایی برای این جستجو یافت نشد."}</div>
      )}
      {!loading && !error && pages > 1 && (
        <nav
          aria-label="صفحه‌بندی"
          className="mt-8 flex items-center justify-center gap-4"
        >
          <button
            disabled={page <= 1}
            onClick={() => change({ page: String(page - 1) })}
            className="min-h-11 rounded-xl border px-4 disabled:opacity-40"
          >
            قبلی
          </button>
          <span>
            صفحه {page.toLocaleString("fa-IR")} از{" "}
            {pages.toLocaleString("fa-IR")}
          </span>
          <button
            disabled={page >= pages}
            onClick={() => change({ page: String(page + 1) })}
            className="min-h-11 rounded-xl border px-4 disabled:opacity-40"
          >
            بعدی
          </button>
        </nav>
      )}
    </div>
  );
}
