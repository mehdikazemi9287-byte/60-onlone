import { NextResponse, type NextRequest } from "next/server";

// Closed ecosystem: refuse known price-aggregator / marketplace crawlers (robots.txt alone is advisory).
const AGGREGATOR = /torob|emalls|basalam|digikala|snappshop|snapp\s*market|pricebot|price-?compar/i;

export function middleware(req: NextRequest) {
  if (AGGREGATOR.test(req.headers.get("user-agent") ?? "")) return new NextResponse("Forbidden", { status: 403 });
  return NextResponse.next();
}

export const config = { matcher: ["/((?!_next/static|_next/image|icon.svg|manifest.webmanifest).*)"] };
