import type { MetadataRoute } from "next";
import {
  allPublicProducts,
  serverCategories,
  site,
} from "@/lib/server-catalog";
export const dynamic = "force-dynamic";
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [products, categories] = await Promise.all([
    allPublicProducts(),
    serverCategories(),
  ]);
  return [
    { url: site },
    { url: site + "/category" },
    ...categories
      .filter((c) => c.product_count > 0)
      .map((c) => ({ url: site + "/category/" + encodeURIComponent(c.slug) })),
    ...products.map((p) => ({
      url: site + "/products/" + encodeURIComponent(p.slug),
    })),
  ];
}
