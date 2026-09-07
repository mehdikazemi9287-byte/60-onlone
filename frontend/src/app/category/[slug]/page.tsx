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
  return (
    <Suspense fallback={<p>در حال دریافت…</p>}>
      <CatalogBrowser categorySlug={slug} />
    </Suspense>
  );
}
