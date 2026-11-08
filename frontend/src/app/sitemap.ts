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
    ...categories.map((c) => ({ url: site + "/category/" + encodeURIComponent(c.slug) })),
    { url: site + "/assistant" },
    { url: site + "/pack-builder" },
    { url: site + "/help/buying" },
    { url: site + "/help/faq" },
    ...products.map((p) => ({
      url: site + "/products/" + encodeURIComponent(p.slug),
    })),
  ];
}
