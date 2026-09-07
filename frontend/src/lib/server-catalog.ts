import "server-only";
import { normalizeProduct } from "./api";
const origin = process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000";
export const site = "https://60online.ir";
export async function serverProduct(slug: string) {
  const res = await fetch(
    origin + "/api/v1/products/" + encodeURIComponent(slug),
    { cache: "no-store", signal: AbortSignal.timeout(10000) },
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("دریافت اطلاعات کالا ناموفق بود");
  const data = await res.json();
  return normalizeProduct(data.product);
}
export async function serverCategories() {
  const res = await fetch(origin + "/api/v1/categories", {
    cache: "no-store",
    signal: AbortSignal.timeout(10000),
  });
  if (!res.ok) throw new Error("دریافت دسته‌ها ناموفق بود");
  const data = await res.json();
  return data.items as {
    slug: string;
    name_fa: string;
    product_count: number;
  }[];
}
export async function allPublicProducts() {
  const items: { slug: string }[] = [];
  for (let page = 1; page <= 1000; page++) {
    const res = await fetch(
      origin + "/api/v1/products?page_size=48&page=" + page,
      { cache: "no-store", signal: AbortSignal.timeout(10000) },
    );
    if (!res.ok) throw new Error("دریافت کاتالوگ ناموفق بود");
    const data = await res.json();
    items.push(...data.items);
    if (page >= data.total_pages) return items;
  }
  throw new Error("Catalog exceeds sitemap page limit");
}
