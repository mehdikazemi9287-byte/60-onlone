"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { shops, KIND_LABEL, safeLogo, type Shop, type ShopItem } from "@/lib/shops";
import { ApiError } from "@/lib/api";
import { formatPrice } from "@/lib/utils";

export default function ShopPage() {
  const { slug } = useParams<{ slug: string }>();
  const [shop, setShop] = useState<Shop | null>(null);
  const [items, setItems] = useState<ShopItem[]>([]);
  const [missing, setMissing] = useState(false);
  const [failed, setFailed] = useState(false);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    let cancelled = false;
    shops.page(slug, page)
      .then((r) => { if (cancelled) return; setShop(r.shop); setTotal(r.total); setItems((prev) => (page === 1 ? r.items : [...prev, ...r.items])); })
      .catch((e) => { if (!cancelled) (e instanceof ApiError && e.status === 404 ? setMissing : setFailed)(true); });
    return () => { cancelled = true; };
  }, [slug, page]);

  if (missing) {
    return <div className="internal-page container-page py-20 text-center text-neutral-500">این غرفه پیدا نشد یا هنوز فعال نیست.</div>;
  }
  if (failed && !shop) {
    return <div className="internal-page container-page py-20 text-center text-neutral-500">بارگذاری غرفه ناموفق بود. دوباره تلاش کن.</div>;
  }
  if (!shop) {
    return <div className="internal-page container-page py-20 text-center text-neutral-400">در حال بارگذاری غرفه…</div>;
  }
  return (
    <div className="internal-page container-page py-6 md:py-8">
      <header className="flex items-center gap-4 mb-6">
        {safeLogo(shop.logo_url) ? <img src={safeLogo(shop.logo_url)!} alt="" referrerPolicy="no-referrer" className="h-16 w-16 rounded-2xl object-cover" />
          : <span className="grid h-16 w-16 place-items-center rounded-2xl bg-neutral-100 text-2xl font-black">{shop.title.slice(0, 1)}</span>}
        <div>
          <h1 className="text-xl md:text-2xl font-black text-neutral-900">{shop.title}</h1>
          <p className="text-sm text-neutral-500">
            {shop.official ? <><span aria-hidden="true">✓ </span>برند رسمی تأییدشده</> : KIND_LABEL[shop.kind]}{shop.city ? ` · ${shop.city}` : ""}
          </p>
        </div>
      </header>
      {shop.bio && <p className="mb-6 max-w-2xl leading-8 text-neutral-700">{shop.bio}</p>}
      {items.length === 0 ? <p className="text-neutral-500">این غرفه هنوز کالایی برای فروش ندارد.</p> : (
        <ul className="grid gap-4 grid-cols-2 md:grid-cols-4">
          {items.map((it) => (
            <li key={it.slug}>
              <Link href={`/products/${it.slug}`} className="block rounded-2xl border border-neutral-200 p-3 hover:border-neutral-400">
                <span className="block min-h-[3rem] text-sm font-bold text-neutral-900">{it.title}</span>
                <span className="mt-2 block text-sm">
                  {it.price_minor !== null ? formatPrice(it.price_minor) : "استعلام قیمت"}
                </span>
                {!it.in_stock && <span className="text-xs text-red-600">ناموجود</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {items.length < total && (
        <button type="button" onClick={() => setPage((p) => p + 1)} className="mx-auto mt-6 block rounded-xl border px-6 py-2 text-sm font-bold">
          کالاهای بیشتر
        </button>
      )}
    </div>
  );
}
