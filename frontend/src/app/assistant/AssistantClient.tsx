"use client";
import { useState } from "react";
import Link from "next/link";
import { Search, Sparkles, Info } from "lucide-react";
import type { AssistantResult } from "@/lib/assistant";

const EXAMPLES = [
  "لپ‌تاپ زیر ۵۰ میلیون تومان",
  "روتر میکروتیک",
  "آجیل تواضع برای هدیه",
  "ماهی قزل آلا",
  "برنج طبیعت ۱۰ کیلویی",
];

function priceLabel(status: string) {
  return status === "verified"
    ? { t: "قیمت‌دار", c: "bg-emerald-50 text-emerald-700 border-emerald-200" }
    : { t: "بدون قیمت (استعلامی)", c: "bg-amber-50 text-amber-700 border-amber-200" };
}
function buyLabel(status: string) {
  if (status === "purchasable") return { t: "قابل خرید", c: "bg-emerald-50 text-emerald-700 border-emerald-200" };
  if (status === "inquiry-only") return { t: "استعلامی", c: "bg-amber-50 text-amber-700 border-amber-200" };
  return { t: "ناموجود", c: "bg-neutral-100 text-neutral-500 border-neutral-200" };
}

export function AssistantClient() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<AssistantResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function ask(query: string) {
    const term = query.trim();
    if (!term) return;
    setLoading(true); setErr(null); setRes(null);
    try {
      const r = await fetch("/api/assistant?q=" + encodeURIComponent(term), { cache: "no-store" });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "خطا در دستیار");
      setRes(data as AssistantResult);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "خطا در دستیار");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <form
        onSubmit={(e) => { e.preventDefault(); ask(q); }}
        className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center"
      >
        <div className="flex flex-1 items-center gap-2 rounded-xl border border-neutral-200 bg-white px-3">
          <Sparkles className="h-5 w-5 shrink-0 text-amber-500" aria-hidden="true" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="مثلاً: لپ‌تاپ زیر ۵۰ میلیون تومان"
            aria-label="پرسش خرید"
            className="min-h-12 w-full bg-transparent py-3 text-sm outline-none"
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-primary-700 px-5 text-sm font-bold text-white hover:bg-primary-800 disabled:opacity-60"
        >
          <Search className="h-4 w-4" aria-hidden="true" />
          {loading ? "در حال جستجو…" : "پیشنهاد بده"}
        </button>
      </form>

      <div className="flex flex-wrap gap-2">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            onClick={() => { setQ(ex); ask(ex); }}
            className="rounded-full border border-neutral-200 bg-white px-3 py-1.5 text-xs text-neutral-600 hover:border-primary-300 hover:text-primary-700"
          >
            {ex}
          </button>
        ))}
      </div>

      {err && (
        <div role="alert" className="card border-red-200 bg-red-50 p-4 text-sm text-red-700">{err}</div>
      )}

      {res && (
        <div className="space-y-4">
          <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4 text-xs leading-6 text-neutral-600">
            <p className="mb-1 font-bold text-neutral-800">دستیار این شرایط را از جمله شما استخراج کرد:</p>
            <ul className="flex flex-wrap gap-x-4 gap-y-1">
              {res.parsed.categoryName && <li>دسته: <b>{res.parsed.categoryName}</b></li>}
              {res.parsed.brand && <li>برند: <b>{res.parsed.brand}</b></li>}
              {res.parsed.budgetMin != null && <li>حداقل بودجه: <b>{res.parsed.budgetMin.toLocaleString("fa-IR")}</b> تومان</li>}
              {res.parsed.budgetMax != null && <li>حداکثر بودجه: <b>{res.parsed.budgetMax.toLocaleString("fa-IR")}</b> تومان</li>}
              {res.parsed.inStockOnly && <li>فقط کالاهای موجود</li>}
              {res.parsed.keywords.length > 0 && <li>کلیدواژه: <b>{res.parsed.keywords.join("، ")}</b></li>}
              {!res.parsed.categoryName && !res.parsed.brand && res.parsed.budgetMin == null && res.parsed.budgetMax == null && res.parsed.keywords.length === 0 && <li>شرط مشخصی تشخیص داده نشد</li>}
            </ul>
          </div>

          {res.note ? (
            <div className="card p-8 text-center text-neutral-600">{res.note}</div>
          ) : (
            <>
              <p className="text-sm text-neutral-500">{res.total.toLocaleString("fa-IR")} کالای واقعی مطابق شرایط شما</p>
              <ul className="space-y-3">
                {res.matches.map((m) => {
                  const pl = priceLabel(m.product.priceStatus);
                  const bl = buyLabel(m.product.purchaseStatus);
                  return (
                    <li key={m.product.id} className="card p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <Link href={"/products/" + m.product.slug} className="font-bold text-neutral-900 hover:text-primary-700">
                            {m.product.title}
                          </Link>
                          <p className="mt-0.5 text-xs text-neutral-500">
                            {m.product.categoryName}{m.product.brand ? " · " + m.product.brand : ""}
                          </p>
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-1">
                          <span className={"rounded-md border px-2 py-0.5 text-2xs font-medium " + pl.c}>{pl.t}</span>
                          <span className={"rounded-md border px-2 py-0.5 text-2xs font-medium " + bl.c}>{bl.t}</span>
                        </div>
                      </div>
                      {m.product.price != null && (
                        <p className="mt-2 text-sm font-bold text-primary-800">
                          {m.product.price.toLocaleString("fa-IR")} تومان
                        </p>
                      )}
                      <ul className="mt-2 flex flex-wrap gap-1.5">
                        {m.reasons.map((r, i) => (
                          <li key={i} className="rounded-md bg-neutral-100 px-2 py-0.5 text-2xs text-neutral-600">{r}</li>
                        ))}
                      </ul>
                    </li>
                  );
                })}
              </ul>
            </>
          )}

          <div className="rounded-xl border border-neutral-200 bg-white p-4">
            {res.disclaimers.map((d, i) => (
              <p key={i} className="flex items-start gap-2 text-xs leading-6 text-neutral-500">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />{d}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
