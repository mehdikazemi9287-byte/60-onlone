import { notFound } from "next/navigation";
import type { Metadata } from "next";
import ProductDetail from "./ProductDetail";
import { serverStorefrontProduct, site } from "@/lib/server-catalog";
export const dynamic = "force-dynamic";
export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const d = await serverStorefrontProduct((await params).id);
  if (!d) return { title: "کالا یافت نشد", robots: { index: false } };
  const p = d.product;
  return {
    title: p.title_fa + " | شصت‌آنلاین",
    description: p.description_fa || d.seo?.meta_description || "مشخصات، فروشندگان و استعلام شرایط تأمین " + p.title_fa,
    alternates: { canonical: site + "/products/" + encodeURIComponent(p.slug) },
  };
}
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const d = await serverStorefrontProduct((await params).id);
  if (!d) notFound();
  const p = d.product;
  const breadcrumb = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "خانه", item: site },
      ...d.breadcrumbs.map((b, i) => ({ "@type": "ListItem", position: i + 2, name: b.name_fa, item: site + "/category/" + encodeURIComponent(b.slug) })),
      { "@type": "ListItem", position: d.breadcrumbs.length + 2, name: p.title_fa, item: site + "/products/" + encodeURIComponent(p.slug) },
    ],
  };
  // Offers/price only when a verified offer exists; never an estimated price in structured data.
  const additionalProperty = d.seo?.product_jsonld?.additionalProperty
    ?? (d.spec_groups ?? []).flatMap((g) => g.items.map((i) => ({ "@type": "PropertyValue" as const, name: i.label_fa, value: i.value_fa })));
  const priced = d.offers.filter((o) => o.price_minor != null);
  const structured = {
    "@context": "https://schema.org",
    "@type": "Product",
    name: p.title_fa,
    description: p.description_fa || undefined,
    url: site + "/products/" + encodeURIComponent(p.slug),
    image: p.images[0] ? new URL(p.images[0], site).href : undefined,
    sku: p.sku,
    brand: p.brand_fa ? { "@type": "Brand", name: p.brand_fa } : undefined,
    category: d.breadcrumbs.length ? d.breadcrumbs.map((b) => b.name_fa).join(" > ") : undefined,
    // Typed attributes (Phase 6) as schema.org PropertyValue pairs.
    additionalProperty: additionalProperty.length ? additionalProperty : undefined,
    offers: priced.length ? priced.map((o) => ({ "@type": "Offer", priceCurrency: "IRR", price: o.price_minor! / 10, seller: { "@type": "Organization", name: o.seller },
      availability: o.stock_state === "in_stock" ? "https://schema.org/InStock" : "https://schema.org/OutOfStock" })) : undefined,
  };
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(structured).replace(/</g, "\\u003c") }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumb).replace(/</g, "\\u003c") }} />
      <ProductDetail key={p.slug} initial={d} />
    </>
  );
}
