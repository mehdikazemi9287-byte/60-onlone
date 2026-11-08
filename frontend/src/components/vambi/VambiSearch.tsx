"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiRequest, ApiError } from "@/lib/api";
import { formatPrice, toPersianNum } from "@/lib/utils";
import { VambiHeroLogo } from "./VambiShell";
import { WatchButton } from "@/components/price-watch/WatchButton";

type Offer = { seller: string; city: string | null; price_incl_vat_minor: number | null; lead_time_days: number | null;
  stock_state: string; best: boolean };
type Item = { slug: string; title: string; brand: string | null; image_url: string | null; category: string | null;
  summary: { seller_count: number; min_price_minor: number | null; max_price_minor: number | null;
    fastest_lead_days: number | null; in_stock_count: number }; offers: Offer[] };
type Res = { items: Item[]; total: number; total_pages: number; price_hidden?: boolean };

const MAIN = process.env.NEXT_PUBLIC_MAIN_SITE ?? "";
const STOCK_FA: Record<string, string> = { in_stock: "موجود", out_of_stock: "ناموجود", unknown: "نامشخص" };
const SORTS = [["relevance", "مرتبط‌ترین"], ["sellers", "بیشترین فروشنده"], ["price_asc", "ارزان‌ترین"]] as const;

export function VambiSearch() {
  const router = useRouter();
  const params = useSearchParams();
  const q = params.get("q") ?? "";
  const sort = params.get("sort") ?? "relevance";
  const page = Number(params.get("page") ?? "1") || 1;
  const [text, setText] = useState(q);
  const [res, setRes] = useState<Res | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setRes(null); setError(null);
    const qs = new URLSearchParams({ ...(q ? { q } : {}), sort, page: String(page) });
    apiRequest<Res>(`/vambi/search?${qs}`)
      .then((r) => { if (alive) setRes(r); })
      .catch((e) => { if (alive) setError(e instanceof ApiError ? e.message : "جستجو ناموفق بود"); });
    return () => { alive = false; };
  }, [q, sort, page]);

  const go = (next: Record<string, string>) => {
    const p = new URLSearchParams(params.toString());
    Object.entries(next).forEach(([k, v]) => (v ? p.set(k, v) : p.delete(k)));
    router.push(`/vambi?${p}`);
  };

  return (
    <div className="mx-auto max-w-5xl px-4 pb-12">
      <section className="py-8 text-center">
        <VambiHeroLogo />
        <h1 className="mt-4 text-lg font-bold text-[#102B7A] [text-wrap:balance] md:text-2xl">کشف کن، مقایسه کن، هوشمندانه انتخاب کن.</h1>
        <p className="mt-2 text-sm text-neutral-600">یک کالا، همهٔ فروشنده‌های معتبر کنار هم: قیمت، زمان تحویل و موجودی.</p>
        <form className="mx-auto mt-6 flex max-w-2xl gap-2" role="search" onSubmit={(e) => { e.preventDefault(); go({ q: text.trim(), page: "" }); }}>
          <label htmlFor="vambi-q" className="sr-only">جستجوی کالا</label>
          <input id="vambi-q" value={text} onChange={(e) => setText(e.target.value)} placeholder="نام کالا، برند یا مدل…"
            className="min-h-14 flex-1 rounded-2xl border-2 border-[#DCE3F7] bg-white px-5 text-base outline-none focus:border-[#1748C9]" />
          <button className="min-h-14 rounded-2xl bg-[#1748C9] px-6 font-bold text-white hover:bg-[#0B2A80]">بگرد</button>
        </form>
      </section>

      <div className="mb-4 flex flex-wrap items-center gap-2" role="group" aria-label="مرتب‌سازی">
        {SORTS.map(([k, label]) => (
          <button key={k} onClick={() => go({ sort: k === "relevance" ? "" : k, page: "" })} aria-pressed={sort === k}
            disabled={k === "price_asc" && res?.price_hidden}
            className={`rounded-full px-4 py-1.5 text-sm font-bold disabled:opacity-40 ${sort === k ? "bg-[#102B7A] text-white" : "bg-white text-[#102B7A] ring-1 ring-[#DCE3F7]"}`}>
            {label}
          </button>
        ))}
      </div>

      {res?.price_hidden && (
        <p className="mb-4 rounded-2xl bg-[#FFF6DD] p-4 text-sm text-[#6B4A00]">
          قیمت و خرید فقط برای مشتریان سازمانی طرف قرارداد است. <a href="/login" className="font-bold underline">ورود</a> · <a href="/business" className="font-bold underline">درخواست حساب سازمانی</a>
        </p>
      )}
      {error && <p role="alert" className="rounded-2xl bg-red-50 p-4 text-sm text-red-700">{error}</p>}
      {!res && !error && <p className="py-10 text-center text-neutral-500">در حال جستجو…</p>}
      {res && res.items.length === 0 && <p className="py-10 text-center text-neutral-500">کالایی پیدا نشد. عبارت دیگری امتحان کن.</p>}

      <ul className="space-y-3">
        {res?.items.map((it) => {
          const s = it.summary;
          const expanded = open === it.slug;
          return (
            <li key={it.slug} className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-[#E6EBF8]">
              <div className="flex gap-4">
                <div className="h-20 w-20 shrink-0 overflow-hidden rounded-xl bg-[#F5F7FD]">
                  {it.image_url && <img src={it.image_url} alt="" className="h-full w-full object-contain" loading="lazy" />}
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="font-bold leading-7 text-neutral-900">{it.title}</h2>
                  <p className="text-xs text-neutral-500">{[it.brand, it.category].filter(Boolean).join(" · ")}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                    <span className="font-black text-[#1748C9]">
                      {s.min_price_minor != null ? <>از {formatPrice(s.min_price_minor)}</> : res.price_hidden ? "قیمت فقط برای مشتریان سازمانی" : "استعلام قیمت"}
                    </span>
                    <span className="text-neutral-600">{toPersianNum(s.seller_count)} فروشنده</span>
                    {s.fastest_lead_days != null && <span className="text-neutral-600">تحویل از {toPersianNum(s.fastest_lead_days)} روز</span>}
                  </div>
                </div>
              </div>
              {s.seller_count > 0 && (
                <button onClick={() => setOpen(expanded ? null : it.slug)} aria-expanded={expanded}
                  className="mt-3 w-full rounded-xl bg-[#F5F7FD] py-2 text-sm font-bold text-[#102B7A]">
                  {expanded ? "بستن مقایسه" : "مقایسهٔ فروشنده‌ها"}
                </button>
              )}
              {expanded && (
                <table className="mt-3 w-full text-sm">
                  <thead><tr className="text-right text-xs text-neutral-500"><th className="py-1 font-medium">فروشنده</th><th className="font-medium">قیمت (با مالیات)</th><th className="font-medium">تحویل</th><th className="font-medium">موجودی</th></tr></thead>
                  <tbody>
                    {it.offers.map((o, i) => (
                      <tr key={i} className="border-t border-[#E6EBF8]">
                        <td className="py-2">{o.seller}{o.city ? <span className="text-xs text-neutral-500"> · {o.city}</span> : null}{o.best && <span className="mr-2 inline-block whitespace-nowrap rounded-full bg-[#FFB21E] px-2 text-[11px] font-bold text-[#102B7A]">پیشنهاد برتر</span>}</td>
                        <td className="tabular-nums">{o.price_incl_vat_minor != null ? formatPrice(o.price_incl_vat_minor) : "—"}</td>
                        <td>{o.lead_time_days != null ? `${toPersianNum(o.lead_time_days)} روز` : "—"}</td>
                        <td>{STOCK_FA[o.stock_state] ?? o.stock_state}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                <a href={`${MAIN}/products/${encodeURIComponent(it.slug)}`} className="inline-block text-sm font-bold text-[#1748C9]">مشاهده و خرید ←</a>
                <WatchButton slug={it.slug} />
              </div>
            </li>
          );
        })}
      </ul>

      {res && res.total_pages > 1 && (
        <nav className="mt-6 flex justify-center gap-2" aria-label="صفحه‌ها">
          <button disabled={page <= 1} onClick={() => go({ page: String(page - 1) })} className="rounded-xl bg-white px-4 py-2 ring-1 ring-[#DCE3F7] disabled:opacity-40">قبلی</button>
          <span className="px-3 py-2 text-sm">{toPersianNum(page)} از {toPersianNum(res.total_pages)}</span>
          <button disabled={page >= res.total_pages} onClick={() => go({ page: String(page + 1) })} className="rounded-xl bg-white px-4 py-2 ring-1 ring-[#DCE3F7] disabled:opacity-40">بعدی</button>
        </nav>
      )}
    </div>
  );
}
