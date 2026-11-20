import type { MetadataRoute } from "next";
import {
  allPublicProducts,
  serverCategories,
  serverPacks,
  serverShops,
  site,
} from "@/lib/server-catalog";
import { publishedContent } from "@/lib/published-content";
import { LEGAL_PAGES } from "@/lib/legal-pages";
export const dynamic = "force-dynamic";
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [products, categories, packs, shops, legal] = await Promise.all([
    allPublicProducts(),
    serverCategories(),
    // Newer sections must not take the whole sitemap down if their API fails.
    serverPacks().catch(() => []),
    serverShops().catch(() => []),
    // Legal/contact pages are listed only once their CMS text is published.
    Promise.all(LEGAL_PAGES.map(async (p) => ((await publishedContent(p.cmsSlug)) ? p.path : null))),
  ]);
  return [
    { url: site },
    { url: site + "/category" },
    ...categories.map((c) => ({ url: site + "/category/" + encodeURIComponent(c.slug) })),
    { url: site + "/assistant" },
    { url: site + "/pack-builder" },
    { url: site + "/help/buying" },
    { url: site + "/help/faq" },
    { url: site + "/shops" },
    { url: site + "/brands" },
    ...shops.flatMap((s) => (s.slug ? [{ url: site + "/shops/" + encodeURIComponent(s.slug) }] : [])),
    ...packs.map((p) => ({ url: site + "/packs/" + encodeURIComponent(p.slug) })),
    ...legal.filter((u): u is string => Boolean(u)).map((u) => ({ url: site + u })),
    ...products.map((p) => ({
      url: site + "/products/" + encodeURIComponent(p.slug),
    })),
  ];
}
