"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { apiRequest, errText, FREQ_FA, RECUR_FA, type DraftQuote, type RecurringList } from "@/lib/commerce";
import { latinDigits } from "@/lib/shops";
import { formatPrice, faDate } from "@/lib/utils";
import { Card, Flash, ListState, btnCls, btnGhost, inputCls, n } from "@/components/commerce/ui";

type Pick = { product_id: number; title_fa: string; quantity: number };
type Hit = { id: number; title_fa: string };

export default function RecurringPage() {
  const { token, loading } = useAuth();
  const [items, setItems] = useState<RecurringList[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [flash, setFlash] = useState<{ ok: boolean; text: string } | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [quote, setQuote] = useState<{ id: number; q: DraftQuote | null; err?: string } | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setItems(null); setError(null);
    apiRequest<{ items: RecurringList[] }>("/me/recurring", { token })
      .then((r) => { if (!cancelled) setItems(r.items); })
      .catch((e) => { if (!cancelled) setError(errText(e, "بارگذاری فهرست‌ها ناموفق بود")); });
    return () => { cancelled = true; };
  }, [token, retry]);

  const act = async (l: RecurringList, action: "pause" | "resume" | "cancel") => {
    if (!token) return;
    if (action === "cancel" && !window.confirm(`فهرست «${l.title}» لغو شود؟ این کار برگشت ندارد.`)) return;
    setBusyId(l.id); setFlash(null);
    try {
      const { list } = await apiRequest<{ list: RecurringList }>(`/me/recurring/${l.id}/${action}`, { token, method: "POST" });
      setItems((cur) => cur && (list.status === "cancelled" ? cur.filter((x) => x.id !== l.id) : cur.map((x) => (x.id === l.id ? list : x))));
      setFlash({ ok: true, text: action === "pause" ? "فهرست متوقف شد." : action === "resume" ? "فهرست دوباره فعال شد." : "فهرست لغو شد." });
    } catch (e) { setFlash({ ok: false, text: errText(e) }); } finally { setBusyId(null); }
  };

  const showQuote = async (id: number) => {
    if (!token) return;
    if (quote?.id === id) { setQuote(null); return; }
    setQuote({ id, q: null });
    try {
      const r = await apiRequest<{ quote: DraftQuote }>(`/me/recurring/${id}/quote`, { token });
      setQuote((cur) => (cur?.id === id ? { id, q: r.quote } : cur));
    } catch (e) { setQuote((cur) => (cur?.id === id ? { id, q: null, err: errText(e) } : cur)); }
  };

  if (loading) return <div className="internal-page container-page py-20 text-center text-neutral-400">در حال بارگذاری…</div>;
  if (!token) return (
    <div className="internal-page container-page py-16 text-center">
      <h1 className="mb-3 text-xl font-black">خرید دوره‌ای</h1>
      <p className="mb-6 text-neutral-600">برای ساخت فهرست خرید دوره‌ای وارد حساب شو.</p>
      <Link href="/login?next=/me/recurring" className="rounded-xl bg-neutral-900 px-5 py-2 font-bold text-white">ورود</Link>
    </div>
  );

  return (
    <div className="internal-page container-page max-w-3xl space-y-5 py-6 md:py-8">
      <div>
        <h1 className="text-xl font-black text-neutral-900 md:text-2xl">خرید دوره‌ای</h1>
        <p className="mt-1 text-sm text-neutral-600">کالاهای تکراری را یک‌بار فهرست کن؛ در هر دوره پیش‌فاکتور آماده می‌شود و تا تأیید تو پرداختی انجام نمی‌شود.</p>
      </div>
      <Flash msg={flash} />
      <NewList token={token} onCreated={(l) => { setItems((cur) => [l, ...(cur ?? [])]); setFlash({ ok: true, text: "فهرست ساخته شد." }); }} />
      <Card title="فهرست‌های من">
        <ListState items={items} error={error} empty="هنوز فهرستی نساخته‌ای." onRetry={() => setRetry((x) => x + 1)} />
        <ul className="space-y-3">
          {items?.map((l) => (
            <li key={l.id} className="rounded-xl border border-neutral-200 p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-bold text-neutral-900">{l.title}</p>
                  <p className="text-xs text-neutral-500">{FREQ_FA[l.frequency]} · {RECUR_FA[l.status]} · {n(l.items.length)} قلم
                    {l.status === "active" && ` · نوبت بعد: ${faDate(l.next_run_on)}`}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={btnGhost} aria-expanded={quote?.id === l.id} onClick={() => showQuote(l.id)}>پیش‌فاکتور</button>
                  {l.status === "active" && <button type="button" className={btnGhost} disabled={busyId === l.id} onClick={() => act(l, "pause")}>توقف</button>}
                  {l.status === "paused" && <button type="button" className={btnGhost} disabled={busyId === l.id} onClick={() => act(l, "resume")}>ادامه</button>}
                  <button type="button" className={`${btnGhost} text-red-700`} disabled={busyId === l.id} onClick={() => act(l, "cancel")}>لغو</button>
                </div>
              </div>
              <ul className="mt-2 text-xs text-neutral-600">
                {l.items.map((it) => <li key={it.product_id}>{it.title_fa} × {n(it.quantity)}</li>)}
              </ul>
              {quote?.id === l.id && <QuoteView q={quote.q} err={quote.err} />}
              {l.status === "active" && token && <ReadyRun token={token} listId={l.id} />}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function QuoteView({ q, err }: { q: DraftQuote | null; err?: string }) {
  if (err) return <p role="alert" className="mt-3 rounded-xl bg-red-50 p-3 text-sm text-red-700">{err}</p>;
  if (!q) return <p role="status" className="mt-3 text-sm text-neutral-400">در حال محاسبه…</p>;
  return (
    <div className="mt-3 rounded-xl bg-neutral-50 p-3 text-sm">
      <p className="mb-2 text-xs text-neutral-500">پیش‌نویس قیمت با قیمت امروز؛ پرداختی انجام نمی‌شود.</p>
      {!q.lines.length ? <p className="text-neutral-600">فعلاً هیچ قلمی قابل فروش نیست.</p> : (
        <ul className="space-y-1">
          {q.lines.map((ln) => (
            <li key={ln.product_id} className="flex justify-between gap-2"><span className="min-w-0 truncate">{ln.title_fa} × {n(ln.quantity)}</span><span className="tabular-nums">{formatPrice(ln.line_after_discounts_minor)}</span></li>
          ))}
        </ul>
      )}
      {q.totals.discount_total_minor > 0 && <p className="mt-2 flex justify-between text-emerald-700"><span>تخفیف دوره‌ای</span><span>{formatPrice(q.totals.discount_total_minor)}</span></p>}
      <p className="mt-2 flex justify-between border-t border-neutral-200 pt-2 font-black"><span>قابل پرداخت</span><span>{formatPrice(q.totals.payable_minor)}</span></p>
    </div>
  );
}

function NewList({ token, onCreated }: { token: string; onCreated: (l: RecurringList) => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [frequency, setFrequency] = useState<RecurringList["frequency"]>("weekly");
  const [startOn, setStartOn] = useState("");
  const [picks, setPicks] = useState<Pick[]>([]);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) { setHits(null); return; }
    let cancelled = false;
    const t = setTimeout(() => {
      apiRequest<{ items: Hit[] }>(`/storefront/products?q=${encodeURIComponent(term)}&group=sku&page_size=6`)
        .then((r) => { if (!cancelled) setHits(r.items); }).catch(() => { if (!cancelled) setHits([]); });
    }, 300);
    return () => { cancelled = true; clearTimeout(t); };
  }, [q]);

  const add = useCallback((h: Hit) => {
    setPicks((cur) => (cur.some((p) => p.product_id === h.id) ? cur : [...cur, { product_id: h.id, title_fa: h.title_fa, quantity: 1 }]));
    setQ(""); setHits(null);
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!picks.length) { setErr("حداقل یک کالا اضافه کن."); return; }
    setBusy(true); setErr(null);
    try {
      const { list } = await apiRequest<{ list: RecurringList }>("/me/recurring", { token, method: "POST", body: JSON.stringify({
        title: title.trim(), frequency, ...(startOn ? { start_on: startOn } : {}),
        items: picks.map((p) => ({ product_id: p.product_id, quantity: p.quantity })) }) });
      onCreated(list);
      setTitle(""); setPicks([]); setStartOn(""); setOpen(false);
    } catch (e2) { setErr(errText(e2, "ساخت فهرست ناموفق بود")); } finally { setBusy(false); }
  };

  if (!open) return <button type="button" className={btnCls} onClick={() => setOpen(true)}>ساخت فهرست جدید</button>;
  return (
    <form onSubmit={submit} className="space-y-3 rounded-2xl border border-neutral-200 bg-white p-4">
      <h2 className="text-base font-black">فهرست جدید</h2>
      <label className="block text-sm font-bold">عنوان
        <input className={inputCls} required maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="مثلاً خرید هفتگی دفتر" />
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm font-bold">دورهٔ ارسال
          <select className={inputCls} value={frequency} onChange={(e) => setFrequency(e.target.value as RecurringList["frequency"])}>
            {Object.entries(FREQ_FA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="block text-sm font-bold">شروع از <span className="font-normal text-neutral-500">(اختیاری)</span>
          <input type="date" dir="ltr" className={inputCls} value={startOn} onChange={(e) => setStartOn(e.target.value)} />
        </label>
      </div>
      <div>
        <label htmlFor="rec-search" className="block text-sm font-bold">افزودن کالا</label>
        <input id="rec-search" type="search" className={inputCls} value={q} onChange={(e) => setQ(e.target.value)} placeholder="نام کالا را بنویس" autoComplete="off" />
        {hits && (hits.length ? (
          <ul className="mt-1 divide-y divide-neutral-100 rounded-xl border border-neutral-200">
            {hits.map((h) => <li key={h.id}><button type="button" className="w-full p-2 text-right text-sm hover:bg-neutral-50" onClick={() => add(h)}>{h.title_fa}</button></li>)}
          </ul>
        ) : <p className="mt-1 text-xs text-neutral-500">کالایی پیدا نشد.</p>)}
      </div>
      {picks.length > 0 && (
        <ul className="space-y-2">
          {picks.map((p) => (
            <li key={p.product_id} className="flex items-center gap-2 text-sm">
              <span className="min-w-0 flex-1 truncate">{p.title_fa}</span>
              <label className="sr-only" htmlFor={`qty-${p.product_id}`}>تعداد {p.title_fa}</label>
              <input id={`qty-${p.product_id}`} inputMode="numeric" dir="ltr" className="w-16 rounded-lg border border-neutral-300 p-1 text-center"
                value={String(p.quantity)} onChange={(e) => {
                  const v = Math.max(1, Math.min(100000, parseInt(latinDigits(e.target.value), 10) || 1));
                  setPicks((cur) => cur.map((x) => (x.product_id === p.product_id ? { ...x, quantity: v } : x)));
                }} />
              <button type="button" className="text-xs font-bold text-red-700" aria-label={`حذف ${p.title_fa}`}
                onClick={() => setPicks((cur) => cur.filter((x) => x.product_id !== p.product_id))}>حذف</button>
            </li>
          ))}
        </ul>
      )}
      {err && <p role="alert" className="text-sm text-red-600">{err}</p>}
      <div className="flex gap-2">
        <button type="submit" className={btnCls} disabled={busy}>{busy ? "در حال ثبت…" : "ساخت فهرست"}</button>
        <button type="button" className={btnGhost} onClick={() => setOpen(false)}>انصراف</button>
      </div>
    </form>
  );
}

type Run = { id: number; status: string; scheduled_for: string; payable_minor: number | null };

// A quoted pre-invoice can be confirmed: the cart becomes this list and checkout applies the subscription discount.
function ReadyRun({ token, listId }: { token: string; listId: number }) {
  const [run, setRun] = useState<Run | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    apiRequest<{ items: Run[] }>(`/me/recurring/${listId}/runs`, { token })
      .then((d) => setRun(d.items.find((r) => r.status === "quoted") ?? null)).catch(() => {});
  }, [token, listId]);
  if (!run) return null;
  const confirm = async () => {
    setBusy(true); setErr(null);
    try {
      await apiRequest(`/me/recurring/${listId}/runs/${run.id}/to-cart`, { token, method: "POST" });
      window.location.href = "/checkout";
    } catch (e) { setErr(e instanceof Error ? e.message : "تأیید ناموفق بود"); setBusy(false); }
  };
  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">
      <span>پیش‌فاکتور نوبت {faDate(run.scheduled_for)} آماده است{run.payable_minor ? ` (${formatPrice(run.payable_minor)})` : ""}.</span>
      <button type="button" disabled={busy} onClick={confirm} className="rounded-lg bg-emerald-700 px-3 py-1.5 font-bold text-white disabled:opacity-60">تأیید و پرداخت</button>
      {err && <p role="alert" className="w-full text-red-700">{err}</p>}
    </div>
  );
}
