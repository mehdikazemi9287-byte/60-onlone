"use client";

// Supplier portal: invited RFQs and the versioned quote builder. Submitting
// again creates a new revision; earlier revisions stay in the history.

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Check, ClipboardList, History, Lock, MapPin, Send, X } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { ApiError, apiRequest, newIdempotencyKey } from "@/lib/api";
import { DELIVERY_STATUS, RFQ_STATUS, money } from "@/lib/procurement/api";
import { formatJalali, formatJalaliDateTime } from "@/lib/procurement/jalali";
import { Chip, Drawer, Empty, Notice, cx, n } from "./ui";
import { OrderDocuments, type OrderDoc } from "./OrderDocuments";
import s from "./proc.module.css";

type RfqItem = { id: number; product_name_fa?: string | null; free_text_description: string | null; quantity: number; unit: string; notes: string | null; target_specification?: string | null; acceptable_alternative?: string | null };
type Rfq = { id: number; rfq_number: string; title: string; status: string; deadline_at: string | null; notes: string | null; supplier_status: string; invited_at: string; items: RfqItem[] };
type Quote = {
  id: number; quote_number: string; status: string; revision: number; grand_total_minor: number; total_items_minor: number; vat_amount_minor: number;
  shipping_cost_minor: number; payment_terms: string | null; delivery_lead_days: number | null; validity_days: number | null; warranty_terms: string | null; notes: string | null;
  submitted_at: string; items: { rfq_item_id: number; unit_price_minor: number; quantity: number; discount_minor: number; alternative_description: string | null; delivery_date: string | null; notes: string | null }[];
  revisions: { revision: number; created_at: string; quote: { grand_total_minor: number } }[];
};
type Line = { unit: string; qty: string; discount: string; date: string; alt: string; notes: string };

const itemName = (i: RfqItem) => i.product_name_fa || i.free_text_description || `ردیف ${i.id}`;
const toman = (v: string) => (v.trim() ? Math.round(Number(v)) * 10 : 0);

type Overview = {
  supplier: { id: number; name: string; status: string; is_demo: boolean; provenance?: string; onboarding_stage?: string };
  accounts?: { id: number; display_name: string; provenance: string; role: string }[];
  readiness?: { key: string; label: string; ok: boolean }[];
  offers?: { total: number; confirmed: number };
  rfqs: { id: number; rfq_number: string; title: string; rfq_status: string; deadline_at: string | null; invitation: string; quote_status: string | null; revision: number | null; grand_total_minor: number | null }[];
  orders: { id: number; po_number: string; status: string; organization: string | null; grand_total_minor: number | null;
    deliveries: { destination_index: number; label: string | null; city: string | null; status: string | null; tracking_reference: string | null }[];
    receivable: { settled: boolean; amount_minor: number | null; reference?: string; environment?: string; created_at?: string };
    documents?: OrderDoc[]; receipts?: { destination_index: number; kind: string; receiver_name: string; created_at: string }[];
    disputes?: { id: number; kind: string; reason: string; status: string; resolution: string | null; created_at: string }[] }[];
};
const RECEIPT_FA: Record<string, string> = { full: "کامل", partial: "ناقص", shortage: "کسری", damaged: "آسیب‌دیده", mismatch: "مغایرت" };
const QUOTE_FA: Record<string, string> = { submitted: "ارسال‌شده", awarded: "انتخاب شد", rejected: "انتخاب نشد", draft: "پیش‌نویس", expired: "منقضی" };
const NEXT_STEP: Record<string, [string, string]> = { confirmed: ["preparing", "آماده‌سازی"], preparing: ["ready", "آماده ارسال"], ready: ["shipped", "ارسال"] };

export function SupplierRfqList() {
  const { token, user, loading } = useAuth();
  const [d, setD] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [track, setTrack] = useState<Record<string, string>>({});
  const load = useCallback(() => { if (token) apiRequest<Overview>("/supplier/overview", { token }).then(setD).catch((e) => setError(e.message)); }, [token]);
  useEffect(() => { load(); }, [load]);
  async function step(po: number, idx: number, status: string) {
    if (!token || busy) return;
    setBusy(true); setError("");
    try { setD(await apiRequest<Overview>(`/supplier/orders/${po}/deliveries/${idx}`, { token, method: "POST", body: JSON.stringify({ status, tracking_reference: track[`${po}-${idx}`] || null }) })); }
    catch (e) { setError(e instanceof Error ? e.message : "ثبت ناموفق بود"); } finally { setBusy(false); }
  }
  if (loading) return <div className={s.root}><div className={s.skeleton} style={{ height: 200 }} /></div>;
  if (!user) return <div className={s.root}><Empty icon={<Lock />} title="برای مشاهده استعلام‌ها وارد حساب تأمین‌کننده شوید" action={<Link className={cx(s.btn, s.primary)} href="/login?next=/supplier/rfqs">ورود</Link>} /></div>;
  if (error && !d) return <div className={s.root}><Notice tone="bad" icon={<AlertTriangle />}>{error}</Notice></div>;
  if (!d) return <div className={s.root}><div className={s.skeleton} style={{ height: 240 }} /></div>;
  return (
    <div className={s.root}>
      <header className={s.head}>
        <div className={s.eyebrow}><Link href="/supplier">پنل تأمین‌کننده</Link> / میز کار</div>
        <h1 className={s.title}>{d.supplier.name}</h1>
        <div className={s.row} style={{ marginTop: 6 }}><Link className={cx(s.btn, s.sm)} href="/supplier/offers">کالاها و پیشنهادهای فروش</Link></div>
        <div className={s.meta}><Chip tone={d.supplier.status === "active" ? "ok" : "warn"} dot>{d.supplier.status === "active" ? "فعال" : d.supplier.status}</Chip>{d.supplier.is_demo && <Chip tone="warn">{d.supplier.provenance === "test" ? "TEST" : "DEMO/SEED"}</Chip>}
          {(d.accounts?.length ?? 0) > 1 && <label className={s.row}>حساب:
            <select className={s.select} style={{ width: "auto", height: 32 }} value={d.supplier.id} onChange={(e) => { try { localStorage.setItem("60online_supplier", e.target.value); } catch {} setD(null); load(); }}>
              {d.accounts!.map((a) => <option key={a.id} value={a.id}>{a.display_name}{a.provenance !== "real" ? " (DEMO)" : ""}</option>)}</select></label>}</div>
      </header>
      {d.supplier.is_demo && <div style={{ marginBottom: 12 }}><Notice icon={<AlertTriangle />}>این حساب تأمین‌کنندهٔ نمایشی/آزمایشی است و برای خرید واقعی استفاده نمی‌شود.</Notice></div>}
      {error && <div style={{ marginBottom: 12 }}><Notice tone="bad" icon={<AlertTriangle />}>{error}</Notice></div>}
      <div className={s.stack}>
        {d.readiness && <section className={s.card}>
          <div className={s.sectionHead}><div><h2>آمادگی عملیاتی</h2><p>پیشنهاد کالا: {n(d.offers?.total ?? 0)} · با قیمت/موجودی تأییدشده: {n(d.offers?.confirmed ?? 0)}</p></div></div>
          <div className={s.row}>{d.readiness.map((r) => <Chip key={r.key} tone={r.ok ? "ok" : "warn"} dot>{r.label}{r.ok ? "" : " — ناقص"}</Chip>)}</div>
        </section>}
        <section className={s.card}>
          <div className={s.sectionHead}><div><h2><ClipboardList /> استعلام‌ها و نتیجه پیشنهاد</h2></div></div>
          {!d.rfqs.length ? <Empty icon={<ClipboardList />} title="استعلامی برای شما ارسال نشده">وقتی سازمانی شما را به استعلام دعوت کند، اینجا نمایش داده می‌شود.</Empty> : (
            <div className={s.tableWrap}><table className={cx(s.table, s.cards)}>
              <thead><tr><th>استعلام</th><th>مهلت</th><th>پیشنهاد شما</th><th /></tr></thead>
              <tbody>{d.rfqs.map((r) => (
                <tr key={r.id}><td className={s.full}><b>{r.title}</b><div className={s.small} style={{ color: "var(--muted)" }}>{r.rfq_number} · {RFQ_STATUS[r.rfq_status] ?? r.rfq_status}</div></td>
                  <td data-label="مهلت">{formatJalaliDateTime(r.deadline_at)}</td>
                  <td data-label="پیشنهاد">{r.quote_status ? <><Chip tone={r.quote_status === "awarded" ? "ok" : r.quote_status === "rejected" ? "bad" : "info"} dot>{QUOTE_FA[r.quote_status] ?? r.quote_status}</Chip> <span className={s.small}>{money(r.grand_total_minor)} · نسخه {n(r.revision ?? 1)}</span></> : r.invitation === "declined" ? <Chip tone="bad">انصراف</Chip> : <Chip>بدون پیشنهاد</Chip>}</td>
                  <td><Link className={cx(s.btn, s.sm, s.primary)} href={`/supplier/rfqs/${r.id}`}>مشاهده</Link></td></tr>
              ))}</tbody>
            </table></div>
          )}
        </section>
        <section className={s.card}>
          <div className={s.sectionHead}><div><h2><Send /> سفارش‌ها، ارسال و تسویه</h2><p>تحویل و رسید را خریدار ثبت می‌کند؛ تأمین‌کننده آماده‌سازی و ارسال را اعلام می‌کند.</p></div></div>
          {!d.orders.length ? <Empty icon={<Send />} title="سفارشی برای شما صادر نشده">پس از انتخاب پیشنهادتان، سفارش اینجا نمایش داده می‌شود.</Empty> : d.orders.map((o) => (
            <div key={o.id} className={s.cardFlat} style={{ marginBottom: 10 }}>
              <div className={s.spread}><b>{o.po_number} · {o.organization}</b>
                <div className={s.row}><span className={s.num}>{money(o.grand_total_minor)}</span>
                  {o.receivable.settled ? <Chip tone="ok" dot>تسویه شد · {o.receivable.reference}{o.receivable.environment === "test" ? " · TEST" : ""}</Chip> : <Chip tone="warn" dot>در انتظار تسویه</Chip>}</div></div>
              {o.deliveries.map((dv) => { const nx = NEXT_STEP[dv.status ?? ""]; const k = `${o.id}-${dv.destination_index}`; return (
                <div key={k} className={s.spread} style={{ marginTop: 8, paddingTop: 8, borderTop: "1px dashed var(--line)" }}>
                  <span className={s.small}>{dv.label || dv.city || `مقصد ${n(dv.destination_index + 1)}`} · <b>{DELIVERY_STATUS[dv.status ?? ""] ?? "در انتظار ارسال سفارش"}</b>{dv.tracking_reference ? ` · ${dv.tracking_reference}` : ""}</span>
                  {nx && ["sent", "partially_received"].includes(o.status) && (
                    <span className={s.row}>
                      {nx[0] === "shipped" && <input className={cx(s.input, s.inputSm)} style={{ width: 150 }} placeholder="کد رهگیری" value={track[k] ?? ""} onChange={(e) => setTrack({ ...track, [k]: e.target.value })} />}
                      <button className={cx(s.btn, s.sm, s.primary)} disabled={busy || (nx[0] === "shipped" && !track[k]?.trim())} onClick={() => step(o.id, dv.destination_index, nx[0])}>ثبت «{nx[1]}»</button>
                    </span>
                  )}
                </div>); })}
              {!!o.receipts?.length && <p className={s.small} style={{ marginTop: 6 }}>رسید خریدار: {o.receipts.map((r) => `${RECEIPT_FA[r.kind] ?? r.kind} (${r.receiver_name})`).join("، ")}</p>}
              {!!o.disputes?.length && <div style={{ marginTop: 6 }}>{o.disputes.map((x) => (
                <Notice key={x.id} tone={x.status === "open" ? "bad" : "info"} icon={<AlertTriangle />}>{x.kind === "return" ? "مرجوعی" : "اصلاحیه"} · {x.status === "open" ? "باز" : "حل‌شده"}: {x.reason}{x.resolution ? ` — ${x.resolution}` : ""}</Notice>))}</div>}
              <OrderDocuments token={token!} docs={o.documents ?? []} uploadPath={`/supplier/orders/${o.id}/documents`}
                destinations={o.deliveries.map((dv) => ({ index: dv.destination_index, label: dv.label || dv.city || `مقصد ${n(dv.destination_index + 1)}` }))} onUploaded={load} />
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}

export function SupplierQuoteBuilder({ rfqId }: { rfqId: string }) {
  const { token, user, loading } = useAuth();
  const [data, setData] = useState<{ rfq: Rfq; destinations: { label: string | null; province: string; city: string; delivery_window: string | null; allocations: { item_index: number; quantity: number }[] }[]; needed_by_date: string | null; quotes: Quote[] } | null>(null);
  const [lines, setLines] = useState<Record<number, Line>>({});
  const [head, setHead] = useState({ shipping: "", terms: "", lead: "", validity: "7", warranty: "", notes: "" });
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);
  const [decline, setDecline] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const r = await apiRequest<NonNullable<typeof data>>(`/supplier/rfqs/${rfqId}`, { token });
      setData(r);
      const q = r.quotes[0];
      setLines(Object.fromEntries(r.rfq.items.map((i) => {
        const qi = q?.items.find((x) => x.rfq_item_id === i.id);
        return [i.id, { unit: qi ? String(qi.unit_price_minor / 10) : "", qty: String(qi?.quantity ?? i.quantity), discount: qi?.discount_minor ? String(qi.discount_minor / 10) : "", date: qi?.delivery_date ?? "", alt: qi?.alternative_description ?? "", notes: qi?.notes ?? "" }];
      })));
      if (q) setHead({ shipping: q.shipping_cost_minor ? String(q.shipping_cost_minor / 10) : "", terms: q.payment_terms ?? "", lead: q.delivery_lead_days != null ? String(q.delivery_lead_days) : "", validity: q.validity_days != null ? String(q.validity_days) : "7", warranty: q.warranty_terms ?? "", notes: q.notes ?? "" });
    } catch (e) { setError(e instanceof Error ? e.message : "دریافت استعلام ناموفق بود"); }
  }, [token, rfqId]);
  useEffect(() => { void load(); }, [load]);

  const totals = useMemo(() => {
    let items = 0;
    for (const [, l] of Object.entries(lines)) {
      if (!l.unit.trim()) continue;
      items += Number(l.unit) * Number(l.qty || 0) - Number(l.discount || 0);
    }
    return { items, shipping: Number(head.shipping || 0) };
  }, [lines, head.shipping]);

  if (loading || (!data && !error)) return <div className={s.root}><div className={s.skeleton} style={{ height: 320 }} /></div>;
  if (!user) return <div className={s.root}><Empty icon={<Lock />} title="برای ارسال پیشنهاد وارد شوید" /></div>;
  if (!data) return <div className={s.root}><Notice tone="bad" icon={<AlertTriangle />}>{error}</Notice></div>;

  const rfq = data.rfq, current = data.quotes[0];
  const editable = rfq.status === "open" && rfq.supplier_status !== "declined" && (!current || current.status === "submitted");
  const set = (id: number, patch: Partial<Line>) => setLines((l) => ({ ...l, [id]: { ...l[id], ...patch } }));

  async function submit() {
    if (!token || busy) return;
    const items = rfq.items.filter((i) => lines[i.id]?.unit.trim()).map((i) => {
      const l = lines[i.id];
      return {
        rfq_item_id: i.id, unit_price_minor: toman(l.unit), quantity: Math.max(1, Math.floor(Number(l.qty) || 1)), discount_minor: toman(l.discount),
        delivery_date: l.date || null, alternative_description: l.alt.trim() || null, notes: l.notes.trim() || null,
      };
    });
    if (!items.length) { setError("حداقل برای یک قلم قیمت وارد کنید."); return; }
    setBusy(true); setError(""); setOk("");
    try {
      await apiRequest(`/supplier/rfqs/${rfqId}/quotes`, {
        token, method: "POST", headers: { "Idempotency-Key": newIdempotencyKey() },
        body: JSON.stringify({
          items, shipping_cost_minor: toman(head.shipping), payment_terms: head.terms.trim() || null, warranty_terms: head.warranty.trim() || null,
          delivery_lead_days: head.lead ? Number(head.lead) : null, validity_days: head.validity ? Number(head.validity) : null, notes: head.notes.trim() || null,
        }),
      });
      setOk(current ? "نسخه جدید پیشنهاد ثبت شد؛ نسخه قبلی در تاریخچه باقی است." : "پیشنهاد ثبت شد.");
      await load();
    } catch (e) { setError(e instanceof ApiError || e instanceof Error ? e.message : "ثبت پیشنهاد ناموفق بود"); }
    finally { setBusy(false); }
  }

  async function sendDecline() {
    if (!token || !decline?.trim()) return;
    setBusy(true);
    try { await apiRequest(`/supplier/rfqs/${rfqId}/decline`, { token, method: "POST", body: JSON.stringify({ reason: decline.trim() }) }); setDecline(null); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "ثبت انصراف ناموفق بود"); }
    finally { setBusy(false); }
  }

  return (
    <div className={s.root}>
      <header className={s.head}>
        <div className={s.headRow}>
          <div>
            <div className={s.eyebrow}><Link href="/supplier/rfqs">استعلام‌ها</Link> / {rfq.rfq_number}</div>
            <h1 className={s.title}>{rfq.title}</h1>
            <div className={s.meta}>
              <Chip tone={rfq.status === "open" ? "info" : "muted"} dot>{RFQ_STATUS[rfq.status] ?? rfq.status}</Chip>
              <span>مهلت پاسخ: <b>{formatJalaliDateTime(rfq.deadline_at)}</b></span>
              <span>تاریخ موردنیاز سازمان: <b>{formatJalali(data.needed_by_date)}</b></span>
              {current && <span>پیشنهاد فعلی: <b>نسخه {n(current.revision)}</b> · {money(current.grand_total_minor)}</span>}
            </div>
          </div>
          {editable && rfq.supplier_status !== "responded" && <button className={cx(s.btn, s.danger)} onClick={() => setDecline("")}><X /> انصراف از پیشنهاد</button>}
        </div>
      </header>
      {error && <div style={{ marginBottom: 12 }}><Notice tone="bad" icon={<AlertTriangle />}>{error}</Notice></div>}
      {ok && <div style={{ marginBottom: 12 }}><Notice tone="info" icon={<Check />}>{ok}</Notice></div>}
      {rfq.supplier_status === "declined" && <div style={{ marginBottom: 12 }}><Notice icon={<X />}>شما از ارائه پیشنهاد برای این استعلام انصراف داده‌اید.</Notice></div>}
      <div className={s.stack}>
        {data.destinations.length > 0 && (
          <section className={s.card}>
            <div className={s.sectionHead}><div><h2><MapPin /> مقصدهای تحویل</h2><p>نشانی دقیق پس از صدور سفارش ارسال می‌شود</p></div></div>
            <div className={s.grid3}>{data.destinations.map((d, i) => (
              <div key={i} className={s.cardFlat}><b>{d.label || d.city}</b> <span className={s.muted}>· {d.province}</span>
                {d.delivery_window && <div className={s.small}>بازه تحویل: {d.delivery_window}</div>}
                <div className={s.row} style={{ marginTop: 6, gap: 4 }}>{d.allocations.map((a) => <Chip key={a.item_index} tone="info">{itemName(rfq.items[a.item_index] ?? rfq.items[0])}: {n(a.quantity)}</Chip>)}</div>
              </div>
            ))}</div>
          </section>
        )}
        <section className={s.card}>
          <div className={s.sectionHead}><div><h2><ClipboardList /> اقلام و قیمت</h2><p>مبالغ به تومان؛ مالیات بر اساس نرخ رسمی توسط سامانه محاسبه می‌شود</p></div></div>
          <div className={s.stack} style={{ gap: 10 }}>
            {rfq.items.map((i) => {
              const l = lines[i.id] ?? { unit: "", qty: "", discount: "", date: "", alt: "", notes: "" };
              return (
                <div key={i.id} className={s.lineCard}>
                  <div className={s.spread}><b>{itemName(i)}</b><Chip>نیاز: {n(i.quantity)} {i.unit}</Chip></div>
                  {(i.target_specification || i.acceptable_alternative || i.notes) && (
                    <div className={s.small} style={{ color: "var(--ink2)", display: "grid", gap: 2 }}>
                      {i.target_specification && <span>مشخصات موردنیاز: <b>{i.target_specification}</b></span>}
                      {i.acceptable_alternative && <span>جایگزین قابل قبول: {i.acceptable_alternative}</span>}
                      {i.notes && <span>{i.notes}</span>}
                    </div>
                  )}
                  <div className={s.grid4}>
                    <label className={s.field}>قیمت واحد (تومان)<input className={cx(s.input, s.inputSm)} type="number" min={0} disabled={!editable} value={l.unit} onChange={(e) => set(i.id, { unit: e.target.value })} /></label>
                    <label className={s.field}>تعداد قابل تأمین<input className={cx(s.input, s.inputSm)} type="number" min={1} disabled={!editable} value={l.qty} onChange={(e) => set(i.id, { qty: e.target.value })} /></label>
                    <label className={s.field}>تخفیف ردیف (تومان)<input className={cx(s.input, s.inputSm)} type="number" min={0} disabled={!editable} value={l.discount} onChange={(e) => set(i.id, { discount: e.target.value })} /></label>
                    <label className={s.field}>تاریخ تحویل<input className={cx(s.input, s.inputSm)} type="date" disabled={!editable} value={l.date} onChange={(e) => set(i.id, { date: e.target.value })} /></label>
                  </div>
                  <div className={s.grid2}>
                    <label className={s.field}>کالای جایگزین (در صورت وجود)<input className={cx(s.input, s.inputSm)} disabled={!editable} value={l.alt} onChange={(e) => set(i.id, { alt: e.target.value })} /></label>
                    <label className={s.field}>توضیح<input className={cx(s.input, s.inputSm)} disabled={!editable} value={l.notes} onChange={(e) => set(i.id, { notes: e.target.value })} /></label>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
        <section className={s.card}>
          <div className={s.sectionHead}><div><h2><Send /> شرایط پیشنهاد</h2></div></div>
          <div className={s.grid3}>
            <label className={s.field}>هزینه حمل (تومان)<input className={cx(s.input, s.inputSm)} type="number" min={0} disabled={!editable} value={head.shipping} onChange={(e) => setHead({ ...head, shipping: e.target.value })} /></label>
            <label className={s.field}>مدت تحویل (روز)<input className={cx(s.input, s.inputSm)} type="number" min={0} disabled={!editable} value={head.lead} onChange={(e) => setHead({ ...head, lead: e.target.value })} /></label>
            <label className={s.field}>اعتبار پیشنهاد (روز)<input className={cx(s.input, s.inputSm)} type="number" min={1} disabled={!editable} value={head.validity} onChange={(e) => setHead({ ...head, validity: e.target.value })} /></label>
            <label className={s.field}>شرایط پرداخت<input className={cx(s.input, s.inputSm)} disabled={!editable} value={head.terms} placeholder="مثلاً نقدی پس از تحویل" onChange={(e) => setHead({ ...head, terms: e.target.value })} /></label>
            <label className={s.field}>گارانتی<input className={cx(s.input, s.inputSm)} disabled={!editable} value={head.warranty} placeholder="مثلاً ۱۸ ماه" onChange={(e) => setHead({ ...head, warranty: e.target.value })} /></label>
            <label className={s.field}>توضیحات<input className={cx(s.input, s.inputSm)} disabled={!editable} value={head.notes} onChange={(e) => setHead({ ...head, notes: e.target.value })} /></label>
          </div>
          <div className={s.stickyBar}>
            <div className={s.row} style={{ gap: 18 }}>
              <span className={s.stat}>جمع اقلام (پیش از مالیات)<b className={s.num}>{money(totals.items * 10)}</b></span>
              <span className={s.stat}>حمل<b className={s.num}>{money(totals.shipping * 10)}</b></span>
              <span className={s.stat}>مالیات<b>محاسبه در سامانه</b></span>
            </div>
            {editable && <button className={cx(s.btn, s.primary)} disabled={busy} onClick={submit}><Send /> {busy ? "در حال ثبت…" : current ? `ثبت نسخه ${n(current.revision + 1)}` : "ارسال پیشنهاد"}</button>}
          </div>
        </section>
        {current && (
          <section className={s.card}>
            <div className={s.sectionHead}><div><h2><History /> تاریخچه نسخه‌ها</h2><p>نسخه‌های قبلی حذف یا ویرایش نمی‌شوند</p></div></div>
            <div className={s.timeline}>
              {current.revisions.slice().reverse().map((r) => (
                <div key={r.revision} className={s.tItem}><span className={s.tDot} /><div><b>نسخه {n(r.revision)}</b> · {money(r.quote.grand_total_minor)}</div><time>{formatJalaliDateTime(r.created_at)}</time></div>
              ))}
            </div>
          </section>
        )}
      </div>
      <Drawer open={decline !== null} title="انصراف از ارائه پیشنهاد" onClose={() => setDecline(null)}
        footer={<><button className={s.btn} onClick={() => setDecline(null)}>بازگشت</button><button className={cx(s.btn, s.primary)} disabled={busy || !decline?.trim()} onClick={sendDecline}>ثبت انصراف</button></>}>
        <label className={s.field}>علت انصراف<textarea className={s.textarea} value={decline ?? ""} onChange={(e) => setDecline(e.target.value)} maxLength={1000} autoFocus /></label>
      </Drawer>
    </div>
  );
}
