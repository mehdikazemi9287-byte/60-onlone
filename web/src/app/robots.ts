import type { MetadataRoute } from "next";

// Closed ecosystem: outside price-comparison crawlers stay out; general search engines may index the public pages.
const BLOCKED = ["TorobBot", "Torob", "EmallsBot", "Emalls", "BasalamBot", "DigikalaBot"];
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      ...BLOCKED.map((userAgent) => ({ userAgent, disallow: "/" })),
      { userAgent: "*", allow: "/", disallow: ["/alerts", "/sso/", "/api/"] },
    ],
  };
}
