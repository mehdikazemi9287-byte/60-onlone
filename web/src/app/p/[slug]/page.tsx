import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ProductView } from "@/components/ProductView";

type Props = { params: Promise<{ slug: string }> };

// Title for sharing/search engines only — never a price (prices depend on who is viewing).
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const origin = (process.env.VAMBI_API_ORIGIN ?? "").replace(/\/+$/, "");
  try {
    if (!origin) throw new Error("no api");
    const r = await fetch(`${origin}/api/v1/vambi/products/${encodeURIComponent(slug)}`, { next: { revalidate: 3600 } });
    if (!r.ok) throw new Error(String(r.status));
    const d: { title: string; brand: string | null; summary: { seller_count: number } } = await r.json();
    const sellers = d.summary.seller_count.toLocaleString("fa-IR");
    return { title: d.title, description: `مقایسهٔ ${sellers} فروشندهٔ معتبر ${d.title}${d.brand ? ` (${d.brand})` : ""} در وامبی.`,
      alternates: { canonical: `/p/${encodeURIComponent(slug)}` } };
  } catch {
    return { title: "مقایسهٔ فروشنده‌ها" };
  }
}

export default async function ProductPage({ params }: Props) {
  const { slug } = await params;
  // Real 404 for search engines when the product doesn't exist (prices still load client-side, per viewer).
  const origin = (process.env.VAMBI_API_ORIGIN ?? "").replace(/\/+$/, "");
  if (origin) {
    const r = await fetch(`${origin}/api/v1/vambi/products/${encodeURIComponent(slug)}`, { next: { revalidate: 3600 } }).catch(() => null);
    if (r?.status === 404) notFound();
  }
  return <ProductView slug={slug} />;
}
