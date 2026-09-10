import { Suspense } from "react";
import { notFound } from "next/navigation";
import { CatalogBrowser } from "@/components/catalog/CatalogBrowser";
import { serverCategories, site } from "@/lib/server-catalog";
export const dynamic = "force-dynamic";
export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const c = (await serverCategories()).find((c) => c.slug === slug);
  return c
    ? {
        title: c.name_fa + " | شصت‌آنلاین",
        alternates: {
          canonical: site + "/category/" + encodeURIComponent(c.slug),
        },
      }
    : { title: "دسته یافت نشد", robots: { index: false } };
}
export default async function Page({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  if (!(await serverCategories()).some((c) => c.slug === slug))
    notFound();
  const cat = (await serverCategories()).find((c) => c.slug === slug)!;
  const bc = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "خانه", item: site },
      { "@type": "ListItem", position: 2, name: "دسته‌بندی‌ها", item: site + "/category" },
      { "@type": "ListItem", position: 3, name: cat.name_fa, item: site + "/category/" + encodeURIComponent(slug) },
    ],
  };
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(bc).replace(/</g, "\\u003c") }} />
      <Suspense fallback={<p>در حال دریافت…</p>}>
        <CatalogBrowser categorySlug={slug} />
      </Suspense>
    </>
  );
}
