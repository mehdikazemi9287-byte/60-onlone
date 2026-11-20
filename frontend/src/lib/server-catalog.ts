import "server-only";
import { normalizeProduct } from "./api";
const origin = process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000";
export const site = "https://60online.ir";
export async function serverStorefrontProduct(slug: string): Promise<import("./storefront").ProductPage | null> {
  const res = await fetch(origin + "/api/v1/storefront/products/" + encodeURIComponent(slug), { cache: "no-store", signal: AbortSignal.timeout(10000) });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("دریافت اطلاعات کالا ناموفق بود");
  return res.json();
}
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
/** Every non-empty node of the real taxonomy (department → category → subcategory → product type), flattened. */
export async function serverCategories() {
  const res = await fetch(origin + "/api/v1/storefront/taxonomy", { cache: "no-store", signal: AbortSignal.timeout(10000) });
  if (!res.ok) throw new Error("دریافت دسته‌ها ناموفق بود");
  const data = (await res.json()) as { items: import("./storefront").TaxNode[] };
  const out: { slug: string; name_fa: string; product_count: number; level: string }[] = [];
  const walk = (n: import("./storefront").TaxNode) => { out.push({ slug: n.slug, name_fa: n.name_fa, product_count: n.product_count, level: n.level }); n.children.forEach(walk); };
  data.items.forEach(walk);
  return out;
}
export async function allPublicProducts() {
  const items: { slug: string }[] = [];
  for (let page = 1; page <= 1000; page++) {
    const res = await fetch(
      origin + "/api/v1/storefront/products?group=sku&page_size=48&page=" + page,
      { cache: "no-store", signal: AbortSignal.timeout(10000) },
    );
    if (!res.ok) throw new Error("دریافت کاتالوگ ناموفق بود");
    const data = await res.json();
    items.push(...data.items);
    if (page >= data.total_pages) return items;
  }
  throw new Error("Catalog exceeds sitemap page limit");
}
export async function serverShop(slug: string): Promise<{ shop: import("./shops").Shop } | null> {
  const res = await fetch(origin + "/api/v1/shops/" + encodeURIComponent(slug), { cache: "no-store", signal: AbortSignal.timeout(10000) });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("دریافت اطلاعات غرفه ناموفق بود");
  return res.json();
}
export async function serverPack(slug: string): Promise<import("./storefront").PackDetail | null> {
  const res = await fetch(origin + "/api/v1/storefront/packs/" + encodeURIComponent(slug), { cache: "no-store", signal: AbortSignal.timeout(10000) });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("دریافت اطلاعات پک ناموفق بود");
  return ((await res.json()) as { pack: import("./storefront").PackDetail }).pack;
}
/** Published packs (public list). */
export async function serverPacks(): Promise<{ slug: string }[]> {
  const res = await fetch(origin + "/api/v1/storefront/packs", { cache: "no-store", signal: AbortSignal.timeout(10000) });
  if (!res.ok) throw new Error("دریافت پک‌ها ناموفق بود");
  return ((await res.json()) as { items: { slug: string }[] }).items;
}
/** Active, approved public shops (the API returns at most 200). */
export async function serverShops(): Promise<{ slug: string | null }[]> {
  const res = await fetch(origin + "/api/v1/shops", { cache: "no-store", signal: AbortSignal.timeout(10000) });
  if (!res.ok) throw new Error("دریافت غرفه‌ها ناموفق بود");
  return ((await res.json()) as { items: { slug: string | null }[] }).items;
}
