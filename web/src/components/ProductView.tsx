"use client";

// Vambi product page: one product, every in-ecosystem seller side by side. Buying happens on 60Online.
import { useEffect, useState } from "react";
import { apiRequest, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { startLogin } from "@/lib/sso";
import { buyUrl, countClick, imageSrc, MAIN, type Offer, type Summary } from "@/lib/catalog";
import { formatPrice, toPersianNum } from "@/lib/ui";
import { OfferTable } from "@/components/OfferTable";
import { WatchButton } from "@/components/WatchButton";

type Product = { slug: string; title: string; brand: string | null; description: string | null; images: string[];
  specs: { label: string; value: string }[]; category: string | null; breadcrumbs: string[];
  summary: Summary; offers: Offer[]; price_hidden?: boolean };

export function ProductView({ slug }: { slug: string }) {
  const { token, loading } = useAuth();
  const [p, setP] = useState<Product | null>(null);
  const [error, setError] = useState<{ text: string; missing: boolean } | null>(null);

  useEffect(() => {
    if (loading) return; // wait for the session, so members see their own price on first paint
    let alive = true;
    setError(null);
    apiRequest<Product>(`/vambi/products/${encodeURIComponent(slug)}`, token ? { token } : {})
      .then((d) => { if (alive) setP(d); })
      .catch((e) => { if (alive) setError(e instanceof ApiError && e.status === 404
        ? { text: "این کالا در وامبی پیدا نشد.", missing: true } : { text: "بارگذاری نشد. دوباره امتحان کن.", missing: false }); });
    return () => { alive = false; };
  }, [slug, token, loading]);

  if (error) return (
    <div className="mx-auto max-w-3xl px-4 py-10 text-center">
      <p role="alert" className="text-neutral-700">{error.text}</p>
      <a href="/" className="mt-4 inline-block font-bold text-[#1748C9]">بازگشت به جستجو</a>
    </div>
  );
  if (!p) return <p role="status" className="py-16 text-center text-neutral-600">در حال بارگذاری…</p>;

  const s = p.summary;
  const best = p.offers.find((o) => o.best) ?? null;
  return (
    <article className="mx-auto max-w-5xl px-4 py-6">
      <nav aria-label="مسیر" className="mb-3 text-xs text-neutral-600">
        <a href="/" className="hover:text-[#1748C9]">وامبی</a>
        {p.breadcrumbs.map((b) => <span key={b}> / {b}</span>)}
      </nav>

      <div className="grid gap-6 md:grid-cols-[18rem_1fr]">
        <div className="aspect-square overflow-hidden rounded-2xl bg-white ring-1 ring-[#E6EBF8]">
          {p.images[0] ? <img src={imageSrc(p.images[0])} alt={p.title} className="h-full w-full object-contain" /> :
            <div className="flex h-full items-center justify-center text-sm text-neutral-500">بدون عکس</div>}
        </div>
        <div className="min-w-0">
          <h1 className="text-xl font-black leading-9 text-neutral-900 md:text-2xl">{p.title}</h1>
          {p.brand && <p className="mt-1 text-sm text-neutral-600">برند: {p.brand}</p>}

          <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
            <div className="rounded-xl bg-white p-3 ring-1 ring-[#E6EBF8]"><dt className="text-xs text-neutral-600">فروشنده</dt><dd className="mt-1 font-black text-[#102B7A]">{toPersianNum(s.seller_count)}</dd></div>
            <div className="rounded-xl bg-white p-3 ring-1 ring-[#E6EBF8]"><dt className="text-xs text-neutral-600">کمترین قیمت</dt><dd className="mt-1 font-black tabular-nums text-[#1748C9]">{s.min_price_minor != null ? formatPrice(s.min_price_minor) : "—"}</dd></div>
            <div className="rounded-xl bg-white p-3 ring-1 ring-[#E6EBF8]"><dt className="text-xs text-neutral-600">سریع‌ترین تحویل</dt><dd className="mt-1 font-black text-[#102B7A]">{s.fastest_lead_days != null ? `${toPersianNum(s.fastest_lead_days)} روز` : "—"}</dd></div>
          </dl>

          {p.price_hidden && (
            <p className="mt-4 rounded-2xl bg-[#FFF6DD] p-4 text-sm text-[#6B4A00]">
              قیمت فقط برای مشتریان سازمانی طرف قرارداد است. <button type="button" onClick={() => startLogin()} className="font-bold underline">ورود</button> · <a href={`${MAIN}/business`} className="font-bold underline">درخواست حساب سازمانی</a>
            </p>
          )}

          <div className="mt-4 flex flex-col gap-2 sm:flex-row">
            <a href={buyUrl(p.slug)} onClick={countClick} className="flex min-h-11 flex-1 items-center justify-center rounded-xl bg-[#1748C9] px-4 font-bold text-white hover:bg-[#0B2A80]">
              {best?.price_incl_vat_minor != null ? `خرید از ${formatPrice(best.price_incl_vat_minor)} در شصت آنلاین` : "خرید در شصت آنلاین"}
            </a>
            <WatchButton slug={p.slug} variant="vambi" />
          </div>
        </div>
      </div>

      <section className="mt-8 rounded-2xl bg-white p-4 ring-1 ring-[#E6EBF8]" aria-labelledby="sellers-h">
        <h2 id="sellers-h" className="mb-2 font-black text-[#102B7A]">همهٔ فروشنده‌ها</h2>
        {p.offers.length ? <OfferTable offers={p.offers} caption={`فروشنده‌های ${p.title}`} /> :
          <p className="text-sm text-neutral-600">فعلاً فروشنده‌ای برای این کالا نیست. زیر نظرش بگیر تا وقتی موجود شد خبرت کنیم.</p>}
      </section>

      {(p.specs.length > 0 || p.description) && (
        <section className="mt-6 rounded-2xl bg-white p-4 ring-1 ring-[#E6EBF8]" aria-labelledby="specs-h">
          <h2 id="specs-h" className="mb-2 font-black text-[#102B7A]">مشخصات</h2>
          {p.specs.length > 0 && (
            <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
              {p.specs.map((x) => <div key={x.label} className="flex justify-between gap-3 border-b border-[#F0F3FB] py-1"><dt className="text-neutral-600">{x.label}</dt><dd className="font-medium">{String(x.value)}</dd></div>)}
            </dl>
          )}
          {p.description && <p className="mt-3 whitespace-pre-line text-sm leading-7 text-neutral-700">{p.description}</p>}
        </section>
      )}
    </article>
  );
}
