"use client";

// «هشدارهای من»: watched items at the buyer's OWN level. Prices shown here are only the ones the server
// computed for this account (retail, the buyer's organization price, or wholesale) — never another level's.
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { errText } from "@/lib/commerce";
import { latinDigits } from "@/lib/shops";
import { ALERT_FA, priceWatch, type AlertType, type LevelInfo, type PriceWatch, type WatchHistory } from "@/lib/priceWatch";
import { faDate, formatPrice } from "@/lib/utils";
import { Card, Flash, ListState, btnCls, btnGhost, inputCls, n } from "@/components/commerce/ui";

export default function PriceAlertsPage() {
  const { token, loading } = useAuth();
  const [items, setItems] = useState<PriceWatch[] | null>(null);
  const [level, setLevel] = useState<LevelInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [flash, setFlash] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setItems(null); setError(null);
    priceWatch.list(token)
      .then((r) => { if (!cancelled) { setItems(r.items); setLevel(r.level); } })
      .catch((e) => { if (!cancelled) setError(errText(e, "بارگذاری هشدارها ناموفق بود")); });
    return () => { cancelled = true; };
  }, [token, retry]);

  const replace = (w: PriceWatch) => setItems((cur) => cur && cur.map((x) => (x.id === w.id ? w : x)));

  if (loading) return <div className="internal-page container-page py-20 text-center text-neutral-400">در حال بارگذاری…</div>;
  if (!token) return (
    <div className="internal-page container-page py-16 text-center">
      <h1 className="mb-3 text-xl font-black">هشدارهای من</h1>
      <p className="mb-6 text-neutral-600">برای دیدن کالاهای زیر نظر وارد حساب شو.</p>
      <Link href="/login?next=/me/price-alerts" className="rounded-xl bg-neutral-900 px-5 py-2 font-bold text-white">ورود</Link>
    </div>
  );

  return (
    <div className="internal-page container-page max-w-3xl space-y-5 py-6 md:py-8" dir="rtl">
      <div>
        <h1 className="text-xl font-black text-neutral-900 md:text-2xl">هشدارهای من</h1>
        <p className="mt-1 text-sm leading-7 text-neutral-600">
          هر کالا را با دکمهٔ «زیر نظر بگیر» در وامبی یا صفحهٔ کالا اضافه کن. هشدارها همیشه در اعلان‌های سایت می‌آید؛
          اگر شمارهٔ همراهت تأیید شده باشد، چند هشدار هم‌زمان در یک پیامک خلاصه جمع می‌شود (برای هر کالا حداکثر یک پیامک در روز).
        </p>
        {level && (
          <p className="mt-2 rounded-xl bg-[#F5F7FD] p-3 text-sm text-[#102B7A]">
            سطح شما: <b>{level.level_fa}</b> · هشدارها: {level.alert_types.map((t) => ALERT_FA[t]).join("، ") || "—"}
            {!level.price_visible && <span className="block text-xs text-[#6B4A00]">قیمت فعلاً فقط برای مشتریان سازمانی نمایش داده می‌شود؛ هشدار «موجود شد» فعال است.</span>}
          </p>
        )}
      </div>
      <Flash msg={flash} />
      <Card title="کالاهای زیر نظر">
        <ListState items={items} error={error} empty="هنوز کالایی را زیر نظر نگرفته‌ای." onRetry={() => setRetry((x) => x + 1)} />
        <ul className="space-y-3">
          {items?.map((w) => (
            <WatchRow key={w.id} w={w} token={token} onChange={replace} onFlash={setFlash}
              onDelete={() => setItems((cur) => cur && cur.filter((x) => x.id !== w.id))} />
          ))}
        </ul>
      </Card>
    </div>
  );
}

function WatchRow({ w, token, onChange, onDelete, onFlash }: { w: PriceWatch; token: string; onChange: (w: PriceWatch) => void;
  onDelete: () => void; onFlash: (m: { ok: boolean; text: string }) => void }) {
  const [busy, setBusy] = useState(false);
  const [target, setTarget] = useState(w.target_price_minor ? String(Math.round(w.target_price_minor / 10)) : "");
  const [qty, setQty] = useState(String(w.quantity));
  const [chart, setChart] = useState<WatchHistory | null | "error" | "closed">("closed");
  const orgLevel = w.level === "org_buyer" || w.level === "shop";

  const save = async (body: Parameters<typeof priceWatch.update>[2], ok: string) => {
    setBusy(true);
    try { const r = await priceWatch.update(token, w.id, body); onChange(r.watch); onFlash({ ok: true, text: ok }); }
    catch (e) { onFlash({ ok: false, text: errText(e) }); } finally { setBusy(false); }
  };
  const remove = async () => {
    if (!window.confirm(`«${w.product.title_fa}» از فهرست زیر نظر حذف شود؟`)) return;
    setBusy(true);
    try { await priceWatch.remove(token, w.id); onDelete(); onFlash({ ok: true, text: "حذف شد." }); }
    catch (e) { onFlash({ ok: false, text: errText(e) }); } finally { setBusy(false); }
  };
  const toggleChart = useCallback(() => {
    if (chart !== "closed") { setChart("closed"); return; }
    setChart(null);
    priceWatch.history(token, w.id).then(setChart).catch(() => setChart("error"));
  }, [chart, token, w.id]);
  const toggleType = (t: AlertType) => {
    const next = w.alert_types.includes(t) ? w.alert_types.filter((x) => x !== t) : [...w.alert_types, t];
    if (next.length) save({ alert_types: next }, "نوع هشدارها ذخیره شد.");
  };

  const c = w.current;
  return (
    <li className={`rounded-xl border p-3 ${w.active ? "border-neutral-200" : "border-dashed border-neutral-300 opacity-70"}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <Link href={`/products/${encodeURIComponent(w.product.slug)}`} className="font-bold text-neutral-900 hover:text-[#1748C9]">{w.product.title_fa}</Link>
          <p className="text-xs text-neutral-500">سطح {w.level_fa}{orgLevel && ` · برای ${n(w.quantity)} عدد`} · از {faDate(w.created_at)}</p>
        </div>
        <div className="text-left text-sm">
          {c.level_changed ? <span className="text-xs text-[#6B4A00]">سطح حسابت تغییر کرده؛ در بررسی بعدی به‌روز می‌شود</span> : (
            <>
              <p className="font-black tabular-nums text-[#1748C9]">{c.price_minor != null ? formatPrice(c.price_minor) : w.price_hidden ? "قیمت پنهان" : "—"}</p>
              <p className="text-xs text-neutral-500">{c.in_stock == null ? "" : c.in_stock ? "موجود" : "ناموجود"}</p>
            </>
          )}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5" role="group" aria-label="نوع هشدارها">
        {(Object.keys(ALERT_FA) as AlertType[]).filter((t) => w.alert_types.includes(t) || levelTypes(w.level).includes(t)).map((t) => (
          <button key={t} type="button" disabled={busy} aria-pressed={w.alert_types.includes(t)} onClick={() => toggleType(t)}
            className={`rounded-full px-3 py-1 text-xs font-bold ${w.alert_types.includes(t) ? "bg-[#102B7A] text-white" : "bg-neutral-100 text-neutral-700"}`}>
            {ALERT_FA[t]}
          </button>
        ))}
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto]">
        {!orgLevel && !w.price_hidden && (
          <label className="text-xs font-bold text-neutral-700">قیمت هدف (تومان، خالی = هر کاهش قیمت)
            <input className={inputCls} inputMode="numeric" dir="ltr" value={target} onChange={(e) => setTarget(latinDigits(e.target.value).replace(/\D/g, ""))} />
          </label>
        )}
        {orgLevel && (
          <label className="text-xs font-bold text-neutral-700">تعداد معمول خرید
            <input className={inputCls} inputMode="numeric" dir="ltr" value={qty} onChange={(e) => setQty(latinDigits(e.target.value).replace(/\D/g, ""))} />
          </label>
        )}
        <button type="button" className={`${btnCls} self-end`} disabled={busy} onClick={() => orgLevel
          ? save({ quantity: Math.max(1, Math.min(100000, Number(qty) || 1)) }, "تعداد ذخیره شد.")
          : save({ target_price_minor: target ? Number(target) * 10 : null }, "قیمت هدف ذخیره شد.")}>ذخیره</button>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className={btnGhost} disabled={busy} onClick={() => save({ active: !w.active }, w.active ? "هشدار متوقف شد." : "هشدار فعال شد.")}>
          {w.active ? "توقف" : "فعال‌سازی"}</button>
        <button type="button" className={btnGhost} disabled={busy} onClick={() => save({ sms_enabled: !w.sms_enabled }, "تنظیم پیامک ذخیره شد.")}>
          پیامک: {w.sms_enabled ? "روشن" : "خاموش"}</button>
        {!w.price_hidden && <button type="button" className={btnGhost} onClick={toggleChart}>{chart === "closed" ? "نمودار ۹۰ روزه" : "بستن نمودار"}</button>}
        <button type="button" className={`${btnGhost} text-red-700`} disabled={busy} onClick={remove}>حذف</button>
      </div>
      {chart === null && <p className="mt-2 text-xs text-neutral-400">در حال بارگذاری نمودار…</p>}
      {chart === "error" && <p className="mt-2 text-xs text-red-700">نمودار در دسترس نیست.</p>}
      {chart && typeof chart === "object" && <PriceChart h={chart} />}
    </li>
  );
}

function levelTypes(level: PriceWatch["level"]): AlertType[] {
  return { consumer: ["price_target", "back_in_stock"], employee: ["price_target", "back_in_stock", "welfare_added"],
    org_buyer: ["price_drop", "new_seller", "contract_expiring"], shop: ["price_drop", "new_tier", "back_in_stock"] }[level] as AlertType[];
}

function PriceChart({ h }: { h: WatchHistory }) {
  const pts = h.points.filter((p) => p.price_minor != null) as { day: string; price_minor: number }[];
  if (pts.length < 2) return <p className="mt-2 rounded-xl bg-neutral-50 p-3 text-xs text-neutral-500">برای نمودار هنوز دادهٔ کافی ثبت نشده است (ثبت روزانه از زمان زیر نظر گرفتن).</p>;
  const W = 600, H = 120, P = 8;
  const vals = pts.map((p) => p.price_minor), lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  // RTL: oldest day on the right, matching the caption order.
  const x = (i: number) => W - P - (i * (W - 2 * P)) / (pts.length - 1);
  const y = (v: number) => H - P - ((v - lo) * (H - 2 * P)) / span;
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.price_minor).toFixed(1)}`).join(" ");
  return (
    <figure className="mt-3">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-28 w-full" role="img" aria-label={`نمودار قیمت ${n(h.days)} روزه در سطح ${h.level_fa}`}>
        <path d={d} fill="none" stroke="#1748C9" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
      <figcaption className="flex justify-between text-[11px] text-neutral-500">
        <span>{faDate(pts[0].day)}</span><span>کمترین {formatPrice(lo)} · بیشترین {formatPrice(hi)}</span><span>{faDate(pts[pts.length - 1].day)}</span>
      </figcaption>
    </figure>
  );
}
