"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { shops, KIND_LABEL, type Shop, type ShopItem } from "@/lib/shops";
import { formatPrice } from "@/lib/utils";

export default function ShopPage() {
  const { slug } = useParams<{ slug: string }>();
  const [shop, setShop] = useState<Shop | null>(null);
  const [items, setItems] = useState<ShopItem[]>([]);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    shops.page(slug).then((r) => { setShop(r.shop); setItems(r.items); }).catch(() => setMissing(true));
  }, [slug]);

  if (missing) {
    return <div className="internal-page container-page py-20 text-center text-neutral-500">این غرفه پیدا نشد یا هنوز فعال نیست.</div>;
  }
  if (!shop) {
    return <div className="internal-page container-page py-20 text-center text-neutral-400">در حال بارگذاری غرفه…</div>;
  }
  return (
    <div className="internal-page container-page py-6 md:py-8">
      <header className="flex items-center gap-4 mb-6">
        {shop.logo_url ? <img src={shop.logo_url} alt="" className="h-16 w-16 rounded-2xl object-cover" />
          : <span className="grid h-16 w-16 place-items-center rounded-2xl bg-neutral-100 text-2xl font-black">{shop.title.slice(0, 1)}</span>}
        <div>
          <h1 className="text-xl md:text-2xl font-black text-neutral-900">{shop.title}</h1>
          <p className="text-sm text-neutral-500">
            {shop.official ? "✓ برند رسمی تأییدشده" : KIND_LABEL[shop.kind]}{shop.city ? ` · ${shop.city}` : ""}
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
    </div>
  );
}
