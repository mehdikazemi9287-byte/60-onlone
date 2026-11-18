"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { apiRequest, errText, FREQ_FA, RECUR_FA, type DraftQuote, type RecurringList } from "@/lib/commerce";
import { faDate } from "@/lib/utils";
import { Card, Flash, ListState, btnGhost, n } from "@/components/commerce/ui";
import { NewList, QuoteView, ReadyRun } from "@/components/commerce/Recurring";

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
      <Link href="/login?next=/me/recurring" className="rounded-full bg-ink px-5 py-2 font-bold text-white">ورود</Link>
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
