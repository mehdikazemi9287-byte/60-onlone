"use client";

// Side-by-side supplier quote comparison. Indicators are factual (lowest
// total, fastest delivery, full coverage); the decision stays with the user
// and the selection is recorded with its reason in the audit trail.

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, Award, ChevronDown, Clock, Lock, Scale, ShieldCheck, Truck } from "lucide-react";
import type React from "react";
import { useAuth } from "@/lib/auth-context";
import { ApiError, apiRequest } from "@/lib/api";
import { money, proc, type Comparison, type Workspace } from "@/lib/procurement/api";
import { addDaysIso, formatJalali, formatJalaliDateTime } from "@/lib/procurement/jalali";
import { Chip, Drawer, Empty, Notice, cx, n } from "./ui";
import s from "./proc.module.css";

type Q = Comparison["quotes"][number];

export default function QuoteComparison({ requestId, rfqId }: { requestId: string; rfqId: string }) {
  const { token, user, loading } = useAuth();
  const params = useSearchParams();
  const org = params.get("org") ?? "";
  const [data, setData] = useState<Comparison | null>(null);
  const [ws, setWs] = useState<Workspace | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pick, setPick] = useState<Q | null>(null);
  const [reason, setReason] = useState("");
  const [detail, setDetail] = useState(false);

  const load = useCallback(async () => {
    if (!token || !org) return;
    try {
      const [c, w] = await Promise.all([proc.comparison(token, org, rfqId), proc.workspace(token, org, requestId)]);
      setData(c); setWs(w); setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "دریافت مقایسه ناموفق بود"); }
  }, [token, org, rfqId, requestId]);
  useEffect(() => { void load(); }, [load]);

  const facts = useMemo(() => {
    if (!data?.quotes.length) return null;
    const need = new Map(data.rfq_items.map((i) => [i.id, i.quantity]));
    const coverage = (q: Q) => {
      const total = [...need.values()].reduce((a, b) => a + b, 0) || 1;
      const got = q.items.reduce((a, it) => a + Math.min(it.quantity, need.get(it.rfq_item_id) ?? 0), 0);
      return Math.round((got / total) * 100);
    };
    const deliveryDays = (q: Q) => {
      const dates = q.items.map((i) => i.delivery_date).filter(Boolean) as string[];
      if (dates.length) return Math.max(...dates.map((d) => Math.round((Date.parse(d) - Date.now()) / 86_400_000)));
      return q.delivery_lead_days;
    };
    const cov = new Map(data.quotes.map((q) => [q.quote_id, coverage(q)]));
    const days = new Map(data.quotes.map((q) => [q.quote_id, deliveryDays(q)]));
    const minTotal = Math.min(...data.quotes.map((q) => q.computed_grand_total_minor));
    const dayVals = [...days.values()].filter((d): d is number => d != null);
    const minDays = dayVals.length ? Math.min(...dayVals) : null;
    return { cov, days, minTotal, minDays, maxCov: Math.max(...cov.values()) };
  }, [data]);

  async function award() {
    if (!token || !pick || busy) return;
    setBusy(true); setError("");
    try {
      if (data?.rfq_status === "open") await proc.post(token, `${proc.base(org)}/rfqs/${rfqId}/close`);
      await apiRequest(`${proc.base(org)}/rfqs/${rfqId}/award`, { token, method: "POST", body: JSON.stringify({ winning_quote_id: pick.quote_id, reason: reason.trim() }) });
      setPick(null); setReason("");
      await load();
    } catch (e) { setError(e instanceof ApiError || e instanceof Error ? e.message : "انتخاب پیشنهاد ناموفق بود"); }
    finally { setBusy(false); }
  }

  if (loading || (!data && !error)) return <div className={s.root}><div className={s.skeleton} style={{ height: 420 }} /></div>;
  if (!user) return <div className={s.root}><Empty icon={<Lock />} title="برای مشاهده مقایسه وارد شوید" /></div>;
  if (!data || !ws) return <div className={s.root}><Notice tone="bad" icon={<AlertTriangle />}>{error}</Notice></div>;

  const cur = ws.organization.currency;
  const canAward = ws.permissions.can_procure && ["open", "closed"].includes(data.rfq_status);
  const awarded = ws.rfqs.find((r) => r.id === Number(rfqId))?.suppliers.find((sp) => sp.quote?.status === "awarded");
  const itemName = (id: number) => {
    const it = data.rfq_items.find((i) => i.id === id);
    return it?.product_name_fa || it?.free_text_description || `ردیف ${id}`;
  };
  const row = (label: string, render: (q: Q) => React.ReactNode, cls?: string) => (
    <tr className={cls}><th scope="row">{label}</th>{data.quotes.map((q) => <td key={q.quote_id} className={s.num}>{render(q)}</td>)}</tr>
  );

  return (
    <div className={s.root}>
      <header className={s.head}>
        <div className={s.headRow}>
          <div>
            <div className={s.eyebrow}><Link href="/org">میز کار</Link> / <Link href={`/organization/requests/${requestId}?org=${org}`}>{ws.request.request_number}</Link> / مقایسه پیشنهادها</div>
            <h1 className={s.title}>مقایسه پیشنهادهای {data.rfq_number}</h1>
            <div className={s.meta}>
              <span>{ws.request.title}</span>
              <Chip tone={data.rfq_status === "awarded" ? "ok" : "info"} dot>{{ open: "دریافت پیشنهاد باز است", closed: "دریافت پیشنهاد بسته شد", awarded: "برنده انتخاب شد" }[data.rfq_status] ?? data.rfq_status}</Chip>
              <span>{n(data.total_quotes)} پیشنهاد، {n(data.rfq_items.length)} قلم</span>
            </div>
          </div>
          <Link className={s.btn} href={`/organization/requests/${requestId}?org=${org}`}>بازگشت به پرونده</Link>
        </div>
      </header>
      {error && <div style={{ marginBottom: 12 }}><Notice tone="bad" icon={<AlertTriangle />}>{error}</Notice></div>}
      {awarded && <div style={{ marginBottom: 12 }}><Notice tone="info" icon={<Award />}>پیشنهاد «{awarded.name}» انتخاب شده است. صدور سفارش از صفحه پرونده انجام می‌شود.</Notice></div>}
      {!data.quotes.length ? (
        <Empty icon={<Scale />} title="هنوز پیشنهادی دریافت نشده">پس از ارسال پیشنهاد توسط تأمین‌کنندگان دعوت‌شده، مقایسه در این صفحه نمایش داده می‌شود.</Empty>
      ) : (
        <>
          <MobileCards data={data} cur={cur} facts={facts} canAward={canAward && !awarded} onPick={setPick} itemName={itemName} />
          <div className={cx(s.compareWrap, s.desktopOnly)}>
            <table className={s.compare}>
              <thead>
                <tr>
                  <th scope="col" style={{ right: 0, position: "sticky", zIndex: 3, background: "#f8fafc" }}>شاخص</th>
                  {data.quotes.map((q) => (
                    <th key={q.quote_id} scope="col">
                      <div className={s.supHead}>
                        <b>{q.supplier_name}</b>
                        <span className={s.small} style={{ color: "var(--muted)" }}>{q.quote_number} · نسخه {n(q.revision)}</span>
                        <div className={s.row} style={{ justifyContent: "center", gap: 4 }}>
                          {facts && q.computed_grand_total_minor === facts.minTotal && <Chip tone="ok">کمترین قیمت نهایی</Chip>}
                          {facts && facts.minDays != null && facts.days.get(q.quote_id) === facts.minDays && <Chip tone="info"><Clock /> سریع‌ترین تحویل</Chip>}
                          {facts && facts.cov.get(q.quote_id) === 100 && <Chip tone="violet"><ShieldCheck /> پوشش کامل</Chip>}
                          {q.status === "awarded" && <Chip tone="ok"><Award /> منتخب</Chip>}
                        </div>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {row("قیمت کالا", (q) => money(q.computed_items_total_minor, cur))}
                {row("مالیات", (q) => money(q.vat_amount_minor, cur))}
                {row("حمل", (q) => (q.shipping_cost_minor ? money(q.shipping_cost_minor, cur) : "رایگان/لحاظ‌شده"))}
                {row("تخفیف", (q) => (q.discount_minor ? `− ${money(q.discount_minor, cur)}` : "—"))}
                {row("قیمت نهایی", (q) => <span className={cx(facts && q.computed_grand_total_minor === facts.minTotal && s.best)}>{money(q.computed_grand_total_minor, cur)}</span>, s.grand)}
                {row("موجودی", (q) => {
                  const short = q.items.filter((it) => it.quantity < (data.rfq_items.find((r) => r.id === it.rfq_item_id)?.quantity ?? 0));
                  return short.length ? <Chip tone="warn">{n(short.length)} قلم کمتر از نیاز</Chip> : <Chip tone="ok">کامل</Chip>;
                })}
                {row("درصد تأمین", (q) => { const c = facts?.cov.get(q.quote_id) ?? 0; return <><b>{n(c)}٪</b><div className={s.bar}><i style={{ width: `${c}%` }} /></div></>; })}
                {row("زمان تحویل", (q) => {
                  const dates = q.items.map((i) => i.delivery_date).filter(Boolean) as string[];
                  if (dates.length) return formatJalali(dates.sort()[dates.length - 1]);
                  return q.delivery_lead_days != null ? `${n(q.delivery_lead_days)} روز` : "—";
                })}
                {row("شرایط پرداخت", (q) => q.payment_terms || "—")}
                {row("اعتبار پیشنهاد", (q) => (q.validity_days != null ? <>{n(q.validity_days)} روز<div className={s.small} style={{ color: "var(--muted)" }}>تا {formatJalali(addDaysIso(q.validity_days, new Date(q.submitted_at)))}</div></> : "—"))}
                {row("گارانتی", (q) => q.warranty_terms || "—")}
                {row("جایگزین‌ها", (q) => {
                  const alts = q.items.filter((i) => i.alternative_description);
                  return alts.length ? alts.map((a) => <div key={a.rfq_item_id} className={s.small}>{itemName(a.rfq_item_id)}: {a.alternative_description}</div>) : "—";
                })}
                {row("ارسال", (q) => <span className={s.small}>{formatJalaliDateTime(q.submitted_at)}</span>)}
                {canAward && !awarded && (
                  <tr><th scope="row">تصمیم</th>{data.quotes.map((q) => (
                    <td key={q.quote_id}><button className={cx(s.btn, s.primary, s.sm)} onClick={() => setPick(q)}><Award /> انتخاب پیشنهاد</button></td>
                  ))}</tr>
                )}
              </tbody>
            </table>
          </div>
          <div className={s.card} style={{ marginTop: 16 }}>
            <button className={cx(s.btn, s.ghost)} onClick={() => setDetail((v) => !v)} aria-expanded={detail}><ChevronDown style={{ transform: detail ? "rotate(180deg)" : undefined }} /> جزئیات قیمت به تفکیک قلم</button>
            {detail && (
              <div className={s.compareWrap} style={{ marginTop: 10 }}>
                <table className={s.compare}>
                  <thead><tr><th style={{ right: 0, position: "sticky", zIndex: 3, background: "#f8fafc" }}>قلم (نیاز)</th>{data.quotes.map((q) => <th key={q.quote_id}>{q.supplier_name}</th>)}</tr></thead>
                  <tbody>
                    {data.rfq_items.map((it) => (
                      <tr key={it.id}>
                        <th scope="row">{itemName(it.id)} <span className={s.muted}>({n(it.quantity)} {it.unit})</span></th>
                        {data.quotes.map((q) => {
                          const qi = q.items.find((x) => x.rfq_item_id === it.id);
                          return <td key={q.quote_id} className={s.num}>{qi ? <>
                            <b>{money(qi.unit_price_minor, cur)}</b><div className={s.small}>× {n(qi.quantity)} = {money(qi.total_price_minor, cur)}</div>
                            {qi.discount_minor ? <div className={s.small} style={{ color: "var(--green)" }}>تخفیف {money(qi.discount_minor, cur)}</div> : null}
                            {qi.delivery_date && <div className={s.small}><Truck size={11} /> {formatJalali(qi.delivery_date)}</div>}
                          </> : <Chip tone="bad">پیشنهاد نشده</Chip>}</td>;
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          <p className={s.small} style={{ color: "var(--muted)", marginTop: 10 }}>شاخص‌ها صرفاً واقعیت‌های ثبت‌شده در پیشنهادها هستند و توصیه خرید محسوب نمی‌شوند. مبالغ مالیات بر اساس نرخ رسمی زمان ارسال پیشنهاد محاسبه شده است.</p>
        </>
      )}
      <Drawer open={!!pick} title={`انتخاب پیشنهاد ${pick?.supplier_name ?? ""}`} onClose={() => setPick(null)}
        footer={<><button className={s.btn} onClick={() => setPick(null)}>انصراف</button><button className={cx(s.btn, s.primary)} disabled={busy || reason.trim().length < 3} onClick={award}>{busy ? "در حال ثبت…" : "ثبت انتخاب"}</button></>}>
        {pick && <Notice tone="info" icon={<Award />}>قیمت نهایی {money(pick.computed_grand_total_minor, cur)} · {pick.quote_number} نسخه {n(pick.revision)}. سایر پیشنهادها رد می‌شوند و این تصمیم با نام شما در رویدادهای پرونده ثبت می‌شود.</Notice>}
        {data.rfq_status === "open" && <Notice icon={<Lock />}>دریافت پیشنهاد هنوز باز است؛ با ثبت انتخاب، استعلام بسته می‌شود.</Notice>}
        <label className={s.field}>علت انتخاب (الزامی)<textarea className={s.textarea} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="مثلاً کمترین قیمت نهایی با پوشش کامل و گارانتی ۱۸ ماهه" maxLength={1000} autoFocus /></label>
      </Drawer>
    </div>
  );
}

type Facts = { cov: Map<number, number>; days: Map<number, number | null>; minTotal: number; minDays: number | null } | null;

function MobileCards({ data, cur, facts, canAward, onPick, itemName }: {
  data: Comparison; cur: string; facts: Facts; canAward: boolean; onPick: (q: Q) => void; itemName: (id: number) => string;
}) {
  return (
    <div className={s.mobileCards}>
      {data.quotes.map((q) => {
        const rows: [string, React.ReactNode][] = [
          ["قیمت کالا", money(q.computed_items_total_minor, cur)], ["مالیات", money(q.vat_amount_minor, cur)],
          ["حمل", q.shipping_cost_minor ? money(q.shipping_cost_minor, cur) : "لحاظ‌شده"], ["تخفیف", q.discount_minor ? `− ${money(q.discount_minor, cur)}` : "—"],
          ["درصد تأمین", `${n(facts?.cov.get(q.quote_id) ?? 0)}٪`],
          ["زمان تحویل", q.items.some((i) => i.delivery_date) ? formatJalali((q.items.map((i) => i.delivery_date).filter(Boolean) as string[]).sort().pop()) : q.delivery_lead_days != null ? `${n(q.delivery_lead_days)} روز` : "—"],
          ["شرایط پرداخت", q.payment_terms || "—"], ["اعتبار پیشنهاد", q.validity_days != null ? `${n(q.validity_days)} روز` : "—"],
          ["گارانتی", q.warranty_terms || "—"],
          ["جایگزین‌ها", q.items.filter((i) => i.alternative_description).map((a) => `${itemName(a.rfq_item_id)}: ${a.alternative_description}`).join("، ") || "—"],
        ];
        return (
          <div key={q.quote_id} className={s.card}>
            <div className={s.spread}><b>{q.supplier_name}</b><span className={s.small} style={{ color: "var(--muted)" }}>نسخه {n(q.revision)}</span></div>
            <div className={s.row} style={{ gap: 4, margin: "6px 0" }}>
              {facts && q.computed_grand_total_minor === facts.minTotal && <Chip tone="ok">کمترین قیمت نهایی</Chip>}
              {facts && facts.minDays != null && facts.days.get(q.quote_id) === facts.minDays && <Chip tone="info">سریع‌ترین تحویل</Chip>}
              {facts && facts.cov.get(q.quote_id) === 100 && <Chip tone="violet">پوشش کامل</Chip>}
              {q.status === "awarded" && <Chip tone="ok">منتخب</Chip>}
            </div>
            <div className={s.spread} style={{ padding: "8px 0", borderBottom: "1px solid var(--line)" }}><span>قیمت نهایی</span><b className={s.num} style={{ fontSize: 17 }}>{money(q.computed_grand_total_minor, cur)}</b></div>
            {rows.map(([k, v]) => <div key={k} className={s.spread} style={{ padding: "6px 0", borderBottom: "1px dashed var(--line2)", fontSize: 13 }}><span className={s.muted}>{k}</span><span className={s.num} style={{ textAlign: "left" }}>{v}</span></div>)}
            {canAward && <button className={cx(s.btn, s.primary)} style={{ width: "100%", marginTop: 10 }} onClick={() => onPick(q)}><Award /> انتخاب پیشنهاد</button>}
          </div>
        );
      })}
    </div>
  );
}
