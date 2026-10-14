"use client";
// Pack card from the Figma library component (171:223): real item photos (quality-gated),
// kind, title, contents, item count, real price or "استعلام قیمت", one CTA.
import Link from "next/link";
import { Package } from "lucide-react";
import { storefront, type PackDetail } from "@/lib/storefront";
import { formatPrice, toPersianNum } from "@/lib/utils";

export const UI = { ink: "#112D46", mint: "#EDF3EE", warm: "#F8F7F4", line: "#DFE5E9", muted: "#526778" };

export function packImages(p: PackDetail, good: Set<string> | null, max = 3, used?: Set<string>): string[] {
  if (!good) return [];
  const out: string[] = [];
  for (const i of p.items) if (i.image_url && good.has(i.image_url) && !out.includes(i.image_url) && !used?.has(i.image_url) && out.length < max) out.push(i.image_url);
  out.forEach((u) => used?.add(u));
  return out;
}

export function PackCard({ p, good, compare, used }: { p: PackDetail; good: Set<string> | null; compare?: { picked: boolean; onPick: () => void }; used?: Set<string> }) {
  // `used` (shared across a row of cards) keeps the same photo from appearing on two cards.
  const pics = packImages(p, good, 3, used);
  const href = `/packs/${p.slug}`;
  return (
    <article className="flex min-w-0 flex-col rounded-2xl border bg-white p-4" style={{ borderColor: UI.line }}>
      <Link href={href} aria-label={p.title_fa} className="flex aspect-[16/9] items-center justify-center gap-2 overflow-hidden rounded-xl p-2" style={{ background: UI.warm }}>
        {good === null ? <span className="h-full w-full animate-pulse rounded-lg bg-white/70" />
          : pics.length ? pics.map((src) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={src} src={src} alt="" loading="lazy" className="aspect-square h-full max-w-[32%] rounded-lg bg-white object-contain p-1.5" />))
          : <span className="flex h-full items-center justify-center"><Package className="h-10 w-10" style={{ color: UI.muted }} strokeWidth={1.4} /></span>}
      </Link>
      <p className="mt-3 text-xs" style={{ color: UI.muted }}>{p.kind_fa}{p.tier_fa ? ` · ${p.tier_fa}` : ""}{p.occasion ? ` · ${p.occasion}` : ""}</p>
      <h3 className="mt-1 text-lg font-black leading-8" style={{ color: UI.ink }}><Link href={href}>{p.title_fa}</Link></h3>
      <p className="mt-1 line-clamp-2 min-h-[48px] text-sm leading-6" style={{ color: UI.ink }}>{p.purpose_fa}</p>
      <p className="mt-2 text-xs" style={{ color: UI.muted }}>{toPersianNum(p.item_count)} نوع کالا{p.customizable ? " · قابل شخصی‌سازی" : ""}</p>
      <p className="mt-2 text-[11px]" style={{color:UI.muted}}>حداقل تعداد: {toPersianNum(p.min_order_qty)} پک</p>
      <div className="mt-3 flex items-center justify-between gap-2">
        <b className="text-base font-black" style={{ color: UI.ink }}>{p.price_minor != null ? (p.availability==="quote_only" ? "برآورد "+formatPrice(p.price_minor) : formatPrice(p.price_minor)) : "استعلام قیمت"}</b>
        {compare && <label className="flex min-h-11 items-center gap-1.5 text-xs" style={{ color: UI.muted }}><input type="checkbox" checked={compare.picked} onChange={compare.onPick} className="h-4 w-4" /> مقایسه</label>}
      </div>
      <Link href={href} className="mt-3 flex h-11 items-center justify-center rounded-xl border text-sm font-bold" style={{ color: UI.ink, borderColor: UI.line }}>مشاهده و شخصی‌سازی</Link>
    </article>
  );
}

let detailsRequest: Promise<PackDetail[]> | null = null;
/** All published packs with their items (cached per page view). */
export function loadPackDetails(): Promise<PackDetail[]> {
  detailsRequest ??= storefront.packs()
    .then((r) => Promise.all(r.items.map((p) => storefront.pack(p.slug).then((x) => x.pack))))
    .catch((e) => { detailsRequest = null; throw e; });
  return detailsRequest;
}
