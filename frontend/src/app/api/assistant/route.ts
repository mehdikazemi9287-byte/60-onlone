import { NextRequest, NextResponse } from "next/server";
import { runAssistant, buildPackDraft, type RawProduct } from "@/lib/assistant";
import { detectAccountIntent, fetchAccountContext } from "@/lib/assistantAccount";

export const dynamic = "force-dynamic";

const origin = process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000";

type StorefrontCard = {
  id: number; slug: string; title_fa: string; brand_fa: string | null; category_slug: string; category_name_fa: string;
  price_minor: number | null; currency?: string; in_stock: boolean; availability: string; image_url: string | null;
};

// Only what the public storefront shows: the same visibility, price and availability rules as the store itself.
// (The legacy /products listing also returns hidden placeholder rows, which must never surface here.)
async function fetchAllProducts(): Promise<RawProduct[]> {
  const out: RawProduct[] = [];
  for (let page = 1; page <= 50; page++) {
    const res = await fetch(`${origin}/api/v1/storefront/products?group=sku&page_size=48&page=${page}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) throw new Error("catalog fetch failed");
    const data = await res.json();
    for (const c of data.items as StorefrontCard[]) {
      out.push({
        id: c.id, slug: c.slug, title_fa: c.title_fa, brand_fa: c.brand_fa, category_slug: c.category_slug, category_name_fa: c.category_name_fa,
        price: c.price_minor, price_minor: c.price_minor, currency: c.currency || "IRR", in_stock: !!c.in_stock,
        purchasable: c.availability === "purchasable", quantity_available: null, image_url: c.image_url,
      });
    }
    if (page >= (data.total_pages ?? 1)) break;
  }
  return out;
}

async function fetchCategories(): Promise<{ slug: string; name_fa: string }[]> {
  const res = await fetch(`${origin}/api/v1/categories`, {
    cache: "no-store",
    signal: AbortSignal.timeout(10000),
  });
  if (!res.ok) throw new Error("categories fetch failed");
  const data = await res.json();
  return data.items as { slug: string; name_fa: string }[];
}

export async function GET(req: NextRequest) {
  const q = (req.nextUrl.searchParams.get("q") || "").slice(0, 300);
  if (!q.trim()) {
    return NextResponse.json({ error: "پرسش خالی است" }, { status: 400 });
  }
  const auth = req.headers.get("authorization");
  const token = auth?.startsWith("Bearer ") ? auth.slice(7) : null;
  try {
    // Status questions are answered only from the caller's own records, with the caller's own token:
    // the backend's authorization decides what is visible. Read-only; the assistant never changes anything.
    const intent = detectAccountIntent(q);
    if (intent) {
      const account = await fetchAccountContext(origin, token, intent);
      return NextResponse.json({ intent: "account", account }, { headers: { "cache-control": "no-store" } });
    }
    const [products, categories] = await Promise.all([fetchAllProducts(), fetchCategories()]);
    const result = runAssistant(q, products, categories);
    const packDraft = buildPackDraft(q, products, categories);
    return NextResponse.json({ intent: "catalog", ...result, packDraft }, { headers: { "cache-control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "دریافت اطلاعات فروشگاه ناموفق بود" }, { status: 502 });
  }
}
