import { NextRequest, NextResponse } from "next/server";
import { runAssistant, type RawProduct } from "@/lib/assistant";

export const dynamic = "force-dynamic";

const origin = process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000";

async function fetchAllProducts(): Promise<RawProduct[]> {
  const out: RawProduct[] = [];
  for (let page = 1; page <= 100; page++) {
    const res = await fetch(`${origin}/api/v1/products?page_size=48&page=${page}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) throw new Error("catalog fetch failed");
    const data = await res.json();
    out.push(...(data.items as RawProduct[]));
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
  try {
    const [products, categories] = await Promise.all([fetchAllProducts(), fetchCategories()]);
    const result = runAssistant(q, products, categories);
    return NextResponse.json(result, { headers: { "cache-control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "دریافت کاتالوگ ناموفق بود" }, { status: 502 });
  }
}
