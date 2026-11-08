"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { shops, KIND_LABEL, safeLogo, type Shop } from "@/lib/shops";

export default function ShopsPage() {
  const [kind, setKind] = useState<string>("");
  const [items, setItems] = useState<Shop[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    setError(null);
    shops.list(kind || undefined)
      .then((r) => { if (!cancelled) setItems(r.items.filter((s) => s.slug)); })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [kind]);

  return (
    <div className="internal-page container-page py-6 md:py-8">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <h1 className="text-xl md:text-2xl font-black text-neutral-900">غرفه‌ها و برندها</h1>
        <Link href="/sell" className="rounded-xl bg-neutral-900 px-4 py-2 text-sm font-bold text-white">
          غرفه‌ات را بساز
        </Link>
      </div>
      <div className="flex gap-2 mb-6 overflow-x-auto pb-1">
        {[["", "همه"], ["brand", "برندهای رسمی"], ["shop", "غرفه‌دارها"], ["partner", "شرکا"]].map(([k, label]) => (
          <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}
            className={`shrink-0 rounded-full px-4 py-1.5 text-sm ${kind === k ? "bg-neutral-900 text-white" : "bg-neutral-100 text-neutral-700"}`}>
            {label}
          </button>
        ))}
      </div>
      {error && <p className="text-red-600">{error}</p>}
      {items === null && !error && <p className="text-neutral-400">در حال بارگذاری…</p>}
      {items?.length === 0 && <p className="text-neutral-500">هنوز غرفهٔ فعالی در این بخش نیست.</p>}
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {items?.map((s) => (
          <li key={s.id}>
            <Link href={`/shops/${encodeURIComponent(s.slug!)}`} className="flex items-center gap-3 rounded-2xl border border-neutral-200 p-4 hover:border-neutral-400">
              {safeLogo(s.logo_url) ? <img src={safeLogo(s.logo_url)!} alt="" referrerPolicy="no-referrer" loading="lazy" className="h-12 w-12 rounded-xl object-cover" />
                : <span className="grid h-12 w-12 place-items-center rounded-xl bg-neutral-100 text-lg font-black">{s.title.slice(0, 1)}</span>}
              <span className="min-w-0">
                <span className="block truncate font-bold text-neutral-900">{s.title}</span>
                <span className="block text-xs text-neutral-500">
                  {s.official ? <><span aria-hidden="true">✓ </span>برند رسمی</> : KIND_LABEL[s.kind]} {s.city ? `· ${s.city}` : ""}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
