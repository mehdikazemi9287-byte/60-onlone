// Shared catalog bits for search cards and the product page.
export type Offer = { seller: string; city: string | null; price_incl_vat_minor: number | null; lead_time_days: number | null;
  stock_state: string; best: boolean };
export type Summary = { seller_count: number; min_price_minor: number | null; max_price_minor: number | null;
  fastest_lead_days: number | null; in_stock_count: number };

export const MAIN = (process.env.NEXT_PUBLIC_MAIN_SITE ?? "").replace(/\/+$/, "");
export const STOCK_FA: Record<string, string> = { in_stock: "موجود", out_of_stock: "ناموجود", unknown: "نامشخص" };
/** Catalog photos live on the main site; a relative path would 404 on vambi.ir. */
export const imageSrc = (u: string) => (u.startsWith("/") && !u.startsWith("//") ? `${MAIN}${u}` : u);
/** Buy happens on 60Online; ?ref=vambi credits a later order to Vambi (first-party only). */
export const buyUrl = (slug: string) => `${MAIN}/products/${encodeURIComponent(slug)}?ref=vambi`;
/** One «خرید» click adds one to today's counter (no token, no body). */
export const countClick = () => { fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/vambi/click`, { method: "POST", keepalive: true }).catch(() => {}); };
