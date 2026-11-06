import type { MetadataRoute } from "next";
import { site } from "@/lib/server-catalog";
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      // Closed ecosystem: price-comparison and marketplace crawlers may not index our prices.
      { userAgent: ["TorobBot", "Torob", "EmallsBot", "Emalls", "Basalam", "DigikalaBot", "SnappShop"], disallow: "/" },
      {
      userAgent: "*",
      allow: "/",
      disallow: [
        "/api/",
        "/admin",
        "/crm",
        "/account",
        "/wallet",
        "/60coin",
        "/60club",
        "/requests",
        "/orders",
        "/checkout",
        "/cart",
        "/supplier",
        "/org",
        "/search",
      ],
    }],
    sitemap: site + "/sitemap.xml",
  };
}
