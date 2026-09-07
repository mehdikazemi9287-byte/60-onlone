import type { MetadataRoute } from "next";
import { site } from "@/lib/server-catalog";
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
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
    },
    sitemap: site + "/sitemap.xml",
  };
}
