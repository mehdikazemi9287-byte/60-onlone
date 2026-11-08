"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { BadgeCheck } from "lucide-react";
import { apiRequest, errText, type Brand } from "@/lib/commerce";
import { safeLogo } from "@/lib/shops";
import { ListState } from "@/components/commerce/ui";

export default function BrandsPage() {
  const [items, setItems] = useState<Brand[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setItems(null); setError(null);
    apiRequest<{ items: Brand[] }>("/brands")
      .then((r) => { if (!cancelled) setItems(r.items); })
      .catch((e) => { if (!cancelled) setError(errText(e, "بارگذاری برندها ناموفق بود")); });
    return () => { cancelled = true; };
  }, [retry]);

  return (
    <div className="internal-page container-page py-6 md:py-8">
      <h1 className="mb-2 text-xl font-black text-neutral-900 md:text-2xl">برندهای رسمی</h1>
      <p className="mb-6 text-sm text-neutral-600">علامت تجاری این برندها بررسی و تأیید شده و مستقیم از خود برند می‌خرید.</p>
      <ListState items={items} error={error} empty="هنوز برند رسمی تأییدشده‌ای نداریم." onRetry={() => setRetry((x) => x + 1)} />
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {items?.map((b) => {
          const logo = safeLogo(b.shop_logo_url);
          const body = (
            <>
              {logo ? <img src={logo} alt="" referrerPolicy="no-referrer" loading="lazy" className="h-12 w-12 flex-none rounded-xl object-cover" />
                : <span aria-hidden="true" className="grid h-12 w-12 flex-none place-items-center rounded-xl bg-neutral-100 text-lg font-black">{b.title.slice(0, 1)}</span>}
              <span className="min-w-0">
                <span className="block truncate font-bold text-neutral-900">{b.title}</span>
                <span className="flex items-center gap-1 text-xs text-emerald-700"><BadgeCheck className="h-4 w-4" aria-hidden="true" />برند رسمی · {b.brand_name}</span>
              </span>
            </>
          );
          return (
            <li key={b.id}>
              {b.shop_slug
                ? <Link href={`/shops/${encodeURIComponent(b.shop_slug)}`} className="flex items-center gap-3 rounded-2xl border border-neutral-200 bg-white p-4 hover:border-neutral-400">{body}</Link>
                : <div className="flex items-center gap-3 rounded-2xl border border-neutral-200 bg-white p-4">{body}</div>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
