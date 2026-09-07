import { notFound } from "next/navigation";
import type { Metadata } from "next";
import ProductDetail from "./ProductDetail";
import { serverProduct, site } from "@/lib/server-catalog";
export const dynamic = "force-dynamic";
export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const p = await serverProduct((await params).id);
  if (!p) return { title: "کالا یافت نشد", robots: { index: false } };
  return {
    title: p.name + " | شصت‌آنلاین",
    description: p.description || "مشخصات و استعلام شرایط تأمین " + p.name,
    alternates: { canonical: site + "/products/" + encodeURIComponent(p.slug) },
  };
}
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const p = await serverProduct((await params).id);
  if (!p) notFound();
  const structured = {
    "@context": "https://schema.org",
    "@type": "Product",
    name: p.name,
    description: p.description || undefined,
    url: site + "/products/" + encodeURIComponent(p.slug),
    image: p.image_url ? new URL(p.image_url, site).href : undefined,
    sku: p.sku || undefined,
    brand: p.brand ? { "@type": "Brand", name: p.brand } : undefined,
  };
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(structured).replace(/</g, "\\u003c"),
        }}
      />
      <ProductDetail initialProduct={p} />
    </>
  );
}
