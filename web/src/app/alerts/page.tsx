"use client";

// «کالاهای زیر نظر»: watched items at the buyer's OWN level. Prices shown here are only the ones the server
// computed for this account (retail, the buyer's organization price, or wholesale) — never another level's.
// Alert types and their labels come from the API per watch; this page keeps no copy of that table.
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { errText } from "@/lib/ui";
import { latinDigits } from "@/lib/ui";
import { priceWatch, type AlertType, type LevelInfo, type PriceWatch, type WatchHistory } from "@/lib/priceWatch";
import { faDate, formatPrice } from "@/lib/ui";
import { MAIN_SITE, startLogin } from "@/lib/sso";
import { Card, ListState, btnCls, btnGhost, inputCls, n } from "@/lib/ui";

const PRICE_TYPES: AlertType[] = ["price_target", "price_drop", "new_tier", "contract_expiring"];
type Msg = { ok: boolean; text: string } | null;

export default function PriceAlertsPage() {
  const { token, loading } = useAuth();
  const [items, setItems] = useState<PriceWatch[] | null>(null);
  const [level, setLevel] = useState<LevelInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setItems(null); setError(null);
    priceWatch.list(token)
      .then((r) => { if (!cancelled) { setItems(r.items); setLevel(r.level); } })
      .catch((e) => { if (!cancelled) setError(errText(e, "بارگذاری کالاهای زیر نظر ناموفق بود")); });
    return () => { cancelled = true; };
  }, [token, retry]);

  const replace = (w: PriceWatch) => setItems((cur) => cur && cur.map((x) => (x.id === w.id ? w : x)));

  if (loading) return <div className="internal-page container-page py-20 text-center text-neutral-400">در حال بارگذاری…</div>;
  if (!token) return (
    <div className="internal-page container-page py-16 text-center">
      <h1 className="mb-3 text-xl font-black">کالاهای زیر نظر</h1>
      <p className="mb-6 text-neutral-600">برای دیدن کالاهای زیر نظر وارد حساب شو.</p>
      <button type="button" onClick={() => startLogin("/alerts")} className="rounded-xl bg-brand-navy px-5 py-2 font-bold text-white">ورود با حساب شصت آنلاین</button>
    </div>
  );

  return (
    <div className="internal-page container-page max-w-3xl space-y-5 py-6 md:py-8" dir="rtl">
      <div>
        <h1 className="text-xl font-black text-neutral-900 md:text-2xl">کالاهای زیر نظر</h1>
        <p className="mt-1 text-sm leading-7 text-neutral-600">
          کالاهایی که زیر نظر گرفته‌ای. هشدارها در اعلان‌ها می‌آیند و اگر شماره‌ات تأیید شده باشد، پیامک خلاصه هم می‌گیری:
          روزی حداکثر دو پیامک و برای هر کالا حداکثر یکی، و نه بین ساعت ۲۲ تا ۸.
        </p>
        {level && (
          <p className="mt-2 rounded-xl bg-neutral-50 p-3 text-sm text-brand-navy">
            سطح: <b>{level.level_fa}</b> · هشدارها: {level.alert_types.map((t) => level.alert_fa[t] ?? t).join("، ") || "—"}
            {!level.price_visible && <span className="block text-xs text-amber-800">قیمت فعلاً فقط برای مشتریان سازمانی نمایش داده می‌شود؛ هشدار «موجود شد» فعال است.</span>}
          </p>
        )}
        {level?.is_seller && level.level === "consumer" && (
          <p className="mt-2 rounded-xl bg-neutral-50 p-3 text-sm text-neutral-700">
            هشدار فروشنده‌ها خودکار است. <a href={`${MAIN_SITE}/sell#price-alerts`} className="font-bold text-brand-blue">پنل فروشنده</a>
          </p>
        )}
      </div>
      <Card title="فهرست">
        <ListState items={items} error={error} empty="هنوز کالایی را زیر نظر نگرفته‌ای. در صفحهٔ کالا یا وامبی «زیر نظر بگیر» را بزن." onRetry={() => setRetry((x) => x + 1)} />
        <ul className="space-y-3">
          {items?.map((w) => (
            <WatchRow key={w.id} w={w} token={token} onChange={replace}
              onDelete={() => setItems((cur) => cur && cur.filter((x) => x.id !== w.id))} />
          ))}
        </ul>
      </Card>
    </div>
  );
}

function WatchRow({ w, token, onChange, onDelete }: { w: PriceWatch; token: string; onChange: (w: PriceWatch) => void; onDelete: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsgState] = useState<Msg>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [target, setTarget] = useState(w.target_price_minor ? String(Math.round(w.target_price_minor / 10)) : "");
  const [qty, setQty] = useState(String(w.quantity));
  const [chart, setChart] = useState<WatchHistory | null | { error: string } | "closed">("closed");
  const orgLevel = w.level === "org_buyer" || w.level === "shop";

  const setMsg = useCallback((m: Msg) => {
    if (timer.current) clearTimeout(timer.current);
    setMsgState(m);
    if (m) timer.current = setTimeout(() => setMsgState(null), 4000);
  }, []);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const save = async (body: Parameters<typeof priceWatch.update>[2], ok: string) => {
    setBusy(true);
    try { const r = await priceWatch.update(token, w.id, body); onChange(r.watch); setMsg({ ok: true, text: ok }); }
    catch (e) { setMsg({ ok: false, text: errText(e) }); } finally { setBusy(false); }
  };
  const remove = async () => {
    if (!window.confirm(`«${w.product.title_fa}» از فهرست زیر نظر حذف شود؟`)) return;
    setBusy(true);
    try { await priceWatch.remove(token, w.id); onDelete(); }
    catch (e) { setMsg({ ok: false, text: errText(e) }); setBusy(false); }
  };
  const toggleChart = () => {
    if (chart !== "closed") { setChart("closed"); return; }
    setChart(null);
    priceWatch.history(token, w.id).then(setChart).catch((e) => setChart({ error: errText(e, "نمودار در دسترس نیست.") }));
  };
  const saveTarget = () => {
    if (!target) { save({ target_price_minor: null }, "قیمت هدف برداشته شد؛ هر کاهش قیمت خبر داده می‌شود."); return; }
    const toman = Number(target);
    if (!(toman > 0)) { setMsg({ ok: false, text: "قیمت هدف باید بیشتر از صفر باشد" }); return; }
    save({ target_price_minor: toman * 10 }, "قیمت هدف ذخیره شد.");
  };
  const saveQty = () => {
    const q = Number(qty);
    if (!(q >= 1 && q <= 100000)) { setMsg({ ok: false, text: "تعداد باید بین ۱ و ۱۰۰٬۰۰۰ باشد" }); return; }
    save({ quantity: Math.floor(q) }, "تعداد ذخیره شد.");
  };

  const chips = w.allowed_alert_types.filter((t) => !(w.price_hidden && PRICE_TYPES.includes(t)));
  const toggleType = (t: AlertType) => {
    const on = w.alert_types.includes(t);
    if (on && w.alert_types.length === 1) return;
    save({ alert_types: on ? w.alert_types.filter((x) => x !== t) : [...w.alert_types, t] }, "نوع هشدارها ذخیره شد.");
  };

  const c = w.current;
  return (
    <li className={`rounded-xl border p-3 ${w.active ? "border-neutral-200" : "border-dashed border-neutral-300 opacity-80"}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <a href={`/p/${encodeURIComponent(w.product.slug)}`} className="font-bold text-neutral-900 hover:text-brand-blue">{w.product.title_fa}</a>
          <p className="text-xs text-neutral-500">سطح: {w.level_fa}{orgLevel && ` · برای ${n(w.quantity)} عدد`} · از {faDate(w.created_at)}{!w.active && " · متوقف"}</p>
        </div>
        <div className="text-left text-sm">
          {c.level_changed ? <span className="text-xs text-amber-800">سطح حسابت تغییر کرده؛ در بررسی بعدی به‌روز می‌شود</span> : (
            <>
              <p className="font-black tabular-nums text-brand-blue">{c.price_minor != null ? formatPrice(c.price_minor) : w.price_hidden ? "قیمت پنهان" : "—"}</p>
              <p className="text-xs text-neutral-500">{c.in_stock == null ? "" : c.in_stock ? "موجود" : "ناموجود"}</p>
            </>
          )}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5" role="group" aria-label="نوع هشدارها">
        {chips.map((t) => {
          const on = w.alert_types.includes(t);
          const last = on && w.alert_types.length === 1;
          return (
            <button key={t} type="button" disabled={busy || last} aria-pressed={on} onClick={() => toggleType(t)}
              title={last ? "حداقل یک نوع هشدار لازم است" : undefined}
              className={`rounded-full px-3 py-1 text-xs font-bold disabled:cursor-not-allowed ${on ? "bg-brand-navy text-white" : "bg-neutral-100 text-neutral-700"}`}>
              {w.alert_fa[t] ?? t}
            </button>
          );
        })}
      </div>
      {w.alert_types.length === 1 && <p className="mt-1 text-[11px] text-neutral-500">حداقل یک نوع هشدار لازم است</p>}

      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto]">
        {!orgLevel && !w.price_hidden && w.allowed_alert_types.includes("price_target") && (
          <>
            <label className="text-xs font-bold text-neutral-700">قیمت هدف (تومان؛ خالی = هر کاهش قیمت)
              <input className={inputCls} inputMode="numeric" dir="ltr" value={target} onChange={(e) => setTarget(latinDigits(e.target.value).replace(/\D/g, ""))} />
            </label>
            <button type="button" className={`${btnCls} self-end`} disabled={busy} onClick={saveTarget}>ذخیره</button>
          </>
        )}
        {orgLevel && (
          <>
            <label className="text-xs font-bold text-neutral-700">تعداد معمول خرید
              <input className={inputCls} inputMode="numeric" dir="ltr" value={qty} onChange={(e) => setQty(latinDigits(e.target.value).replace(/\D/g, ""))} />
            </label>
            <button type="button" className={`${btnCls} self-end`} disabled={busy} onClick={saveQty}>ذخیره</button>
          </>
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className={btnGhost} disabled={busy} aria-pressed={!w.active}
          onClick={() => save({ active: !w.active }, w.active ? "هشدار متوقف شد." : "هشدار دوباره فعال شد.")}>
          {w.active ? "توقف" : "فعال‌سازی"}</button>
        <button type="button" className={btnGhost} disabled={busy} aria-pressed={w.sms_enabled}
          onClick={() => save({ sms_enabled: !w.sms_enabled }, w.sms_enabled ? "پیامک این کالا خاموش شد." : "پیامک این کالا روشن شد.")}>
          پیامک: {w.sms_enabled ? "روشن" : "خاموش"}</button>
        {!w.price_hidden && !c.level_changed && (
          <button type="button" className={btnGhost} aria-expanded={chart !== "closed"} onClick={toggleChart}>
            {chart === "closed" ? "نمودار ۹۰ روزه" : "بستن نمودار"}</button>
        )}
        <button type="button" className={`${btnGhost} text-red-700`} disabled={busy} onClick={remove}>حذف</button>
      </div>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`mt-2 rounded-lg px-3 py-2 text-xs ${msg.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700"}`}>{msg.text}</p>}
      {chart === null && <p role="status" className="mt-2 text-xs text-neutral-400">در حال بارگذاری نمودار…</p>}
      {chart && typeof chart === "object" && "error" in chart && <p role="alert" className="mt-2 text-xs text-red-700">{chart.error}</p>}
      {chart && typeof chart === "object" && "points" in chart && <PriceChart h={chart} />}
    </li>
  );
}

function PriceChart({ h }: { h: WatchHistory }) {
  const pts = h.points.filter((p) => p.price_minor != null) as { day: string; price_minor: number }[];
  if (pts.length < 2) return <p className="mt-2 rounded-xl bg-neutral-50 p-3 text-xs text-neutral-500">برای نمودار هنوز دادهٔ کافی ثبت نشده (ثبت روزانه از زمان زیر نظر گرفتن).</p>;
  const W = 600, H = 120, P = 8;
  const vals = pts.map((p) => p.price_minor), lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  // RTL: oldest day on the right, matching the caption order.
  const x = (i: number) => W - P - (i * (W - 2 * P)) / (pts.length - 1);
  const y = (v: number) => H - P - ((v - lo) * (H - 2 * P)) / span;
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.price_minor).toFixed(1)}`).join(" ");
  return (
    <figure className="mt-3">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-28 w-full text-brand-blue" role="img" aria-label={`نمودار قیمت ${n(h.days)} روزه در سطح ${h.level_fa}`}>
        <path d={d} fill="none" stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
      <figcaption className="flex justify-between text-[11px] text-neutral-500">
        <span>{faDate(pts[0].day)}</span><span>کمترین {formatPrice(lo)} · بیشترین {formatPrice(hi)}</span><span>{faDate(pts[pts.length - 1].day)}</span>
      </figcaption>
    </figure>
  );
}
