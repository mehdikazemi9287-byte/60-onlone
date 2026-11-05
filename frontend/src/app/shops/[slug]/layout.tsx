import type { Metadata } from "next";
import { serverShop, site } from "@/lib/server-catalog";

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const data = await serverShop(slug).catch(() => null);
  if (!data) return { title: "غرفه پیدا نشد | شصت‌آنلاین", robots: { index: false } };
  const { shop } = data;
  return {
    title: `${shop.title} | شصت‌آنلاین`,
    description: shop.bio?.slice(0, 160) ?? `غرفهٔ ${shop.title} در شصت‌آنلاین`,
    alternates: { canonical: `${site}/shops/${encodeURIComponent(slug)}` },
  };
}

export default function ShopLayout({ children }: { children: React.ReactNode }) {
  return children;
}
