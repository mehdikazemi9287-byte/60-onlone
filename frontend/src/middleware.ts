import { NextResponse, type NextRequest } from "next/server";

// Closed ecosystem: refuse known price-aggregator / marketplace crawlers (robots.txt alone is advisory).
const AGGREGATOR = /torob|emalls|basalam|digikala|snappshop|snapp\s*market|pricebot|price-?compar/i;

const VAMBI_HOSTS = (process.env.VAMBI_HOSTS ?? "vambi.ir,www.vambi.ir").split(",").map((h) => h.trim().toLowerCase());

export function middleware(req: NextRequest) {
  if (AGGREGATOR.test(req.headers.get("user-agent") ?? "")) return new NextResponse("Forbidden", { status: 403 });
  // vambi.ir serves the Vambi search front; other paths (login, products) stay shared with the ecosystem.
  const host = (req.headers.get("host") ?? "").toLowerCase().split(":")[0];
  if (VAMBI_HOSTS.includes(host) && req.nextUrl.pathname === "/") {
    const url = req.nextUrl.clone();
    url.pathname = "/vambi";
    return NextResponse.rewrite(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/((?!_next/static|_next/image|icon.svg|manifest.webmanifest).*)"] };
