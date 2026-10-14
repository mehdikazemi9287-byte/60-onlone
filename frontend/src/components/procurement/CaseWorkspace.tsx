"use client";

// Procurement Case command center: one purchase request followed from
// submission through approval, supplier RFQ, quotes, order, per-destination
// fulfillment, receipt/return and closure. Every action calls an existing
// backend endpoint; permissions come from the server's workspace projection.

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  AlertTriangle, ArrowLeft, Building2, CalendarClock, Check, CircleDot, ClipboardList, FileText, FolderLock, GitCompare,
  History, Landmark, Lock, MapPin, NotebookPen, Package, PackageCheck, RotateCcw, Scale, Send, ShieldCheck, Truck, User, Users, X,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { apiRequest } from "@/lib/api";
import { ApiError } from "@/lib/api";
import {
  DELIVERY_FLOW, DELIVERY_STATUS, EVENT_LABEL, PO_STATUS, PR_STATUS, RECEIPT_KIND, RFQ_STATUS, SUPPLIER_STATE, URGENCY,
  money, proc, type Order, type Rfq, type Workspace,
} from "@/lib/procurement/api";
import { daysUntil, formatJalali, formatJalaliDateTime } from "@/lib/procurement/jalali";
import { toPersianNum } from "@/lib/utils";
import { normalizedDigits } from "@/lib/pack-input";
import { Chip, Drawer, Empty, Journey, Notice, cx, n, type Tone } from "./ui";
import { OrderDocuments } from "./OrderDocuments";
import CaseFinance from "./CaseFinance";
import s from "./proc.module.css";

const JOURNEY = ["درخواست", "تأیید", "استعلام", "پیشنهادها", "انتخاب", "سفارش", "تحویل", "رسید", "بستن"];
const SECTIONS: [string, string][] = [
  ["items", "اقلام"], ["destinations", "مقصدها"], ["approvals", "تأییدها"], ["rfq", "استعلام تأمین‌کنندگان"], ["quotes", "پیشنهادها"],
  ["orders", "سفارش و تحویل"], ["finance", "مالی"], ["documents", "اسناد"], ["notes", "یادداشت‌ها"], ["timeline", "رویدادها"],
];

function stage(ws: Workspace): number {
  const st = ws.request.status;
  if (st === "draft") return 0;
  if (["submitted", "under_review", "rejected"].includes(st)) return 1;
  if (st === "approved") return 2;
  if (["sourcing", "quoted"].includes(st)) return ws.rfqs.some((r) => r.quotes_received) ? 3 : 2;
  if (st === "completed") return JOURNEY.length;
  if (st === "awarded") {
    const po = ws.orders.find((o) => o.status !== "cancelled");
    if (!po) return 4;
    if (["draft", "confirmed"].includes(po.status)) return 5;
    const ds = ws.orders.filter(o=>o.status!=="cancelled").flatMap(o=>o.deliveries);
    if (ds.every((d) => d.status === "delivered")) return 8; // ready to close
    if (ds.some((d) => d.receipts.length)) return 7;
    return 6;
  }
  return 0;
}

const statusTone = (st: string): Tone =>
  ["completed", "approved", "awarded", "received", "delivered"].includes(st) ? "ok"
    : ["rejected", "cancelled"].includes(st) ? "bad"
      : ["draft"].includes(st) ? "muted" : "info";
const supplierTone = (st: string): Tone =>
  st === "quoted" ? "ok" : st === "partially_quoted" ? "warn" : st === "declined" || st === "expired" ? "bad" : st === "viewed" ? "info" : "muted";

function slaChip(date: string | null) {
  const d = daysUntil(date);
  if (d == null) return <Chip>بدون موعد</Chip>;
  if (d < 0) return <Chip tone="bad" dot>{n(-d)} روز تأخیر</Chip>;
  if (d <= 3) return <Chip tone="warn" dot>{d === 0 ? "امروز" : `${n(d)} روز مانده`}</Chip>;
  return <Chip tone="ok" dot>{n(d)} روز مانده</Chip>;
}

export default function CaseWorkspace({ id }: { id: string }) {
  const { token, user, loading } = useAuth();
  const params = useSearchParams();
  const [org, setOrg] = useState(params.get("org") ?? "");
  const [ws, setWs] = useState<Workspace | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [flash, setFlash] = useState(params.get("submit_error") ? `پیش‌نویس ذخیره شد، اما ارسال انجام نشد: ${params.get("submit_error")}` : "");
  const [active, setActive] = useState("items");
  const [drawer, setDrawer] = useState<null | { kind: "rfq" } | { kind: "invite"; rfq: Rfq } | { kind: "receipt"; po: Order; idx: number } | { kind: "correction"; po: Order } | { kind: "reject" } | {kind:"order";qid:number}>(null);

  useEffect(() => {
    if (org || !token) return;
    import("@/lib/api").then(({ apiRequest }) => apiRequest<{ items: { id: number; membership: { status: string } }[] }>("/organizations", { token }))
      .then((r) => { const a = r.items.find((o) => o.membership.status === "active"); if (a) setOrg(String(a.id)); else setError("عضویت فعال سازمانی ندارید."); })
      .catch((e) => setError(e.message));
  }, [org, token]);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!token || !org) return;
    try { setWs(await proc.workspace(token, org, id, signal)); setError(""); }
    catch (e) { if (!signal?.aborted) setError(e instanceof Error ? e.message : "دریافت پرونده ناموفق بود"); }
  }, [token, org, id]);
  useEffect(() => { const c = new AbortController(); void load(c.signal); return () => c.abort(); }, [load]);

  const act = useCallback(async (label: string, path: string, body?: unknown, idem = false) => {
    if (!token || busy) return false;
    setBusy(label); setFlash("");
    try {
      const r = await proc.post<Workspace | Record<string, unknown>>(token, path, body, idem);
      if (r && typeof r === "object" && "request" in r && "timeline" in r) setWs(r as Workspace); else await load();
      return true;
    } catch (e) {
      setFlash(e instanceof ApiError || e instanceof Error ? e.message : "عملیات ناموفق بود");
      return false;
    } finally { setBusy(""); }
  }, [token, busy, load]);

  if (loading || (!ws && !error)) return <div className={s.root}><div className={s.skeleton} style={{ height: 120 }} /><div className={s.skeleton} style={{ height: 320, marginTop: 16 }} /></div>;
  if (!user) return <div className={s.root}><Empty icon={<Lock />} title="برای مشاهده پرونده وارد شوید" action={<Link className={cx(s.btn, s.primary)} href={`/login?next=/organization/requests/${id}`}>ورود</Link>} /></div>;
  if (!ws) return <div className={s.root}><Notice tone="bad" icon={<AlertTriangle />}>{error}</Notice></div>;

  const r = ws.request, p = ws.permissions, base = proc.base(org), cur = stage(ws);
  const liveOrder = ws.orders.find((o) => o.status !== "cancelled");
  const awarded = ws.rfqs.flatMap((x) => x.suppliers.map((sp) => ({ rfq: x, sp }))).find((x) => x.sp.quote?.status === "awarded" && !ws.orders.some(o=>o.rfq_id===x.rfq.id));
  const openRfq = ws.rfqs.find((x) => x.status === "draft" || x.status === "open");
  const go = (key: string) => { setActive(key); document.getElementById(key)?.scrollIntoView({ behavior: "smooth", block: "start" }); };

  const primary: Record<string, ReactNode> = {
    submit: p.can_submit && <button className={cx(s.btn, s.primary)} disabled={!!busy} onClick={() => act("submit", `${base}/requests/${r.id}/submit`)}><Send /> ارسال برای بررسی</button>,
    approve: p.can_approve && <button className={cx(s.btn, s.primary)} disabled={!!busy} onClick={() => go("approvals")}><ShieldCheck /> بررسی و تأیید</button>,
    create_rfq: p.can_procure && <button className={cx(s.btn, s.primary)} onClick={() => setDrawer({ kind: "rfq" })}><ClipboardList /> ایجاد استعلام</button>,
    invite: p.can_procure && openRfq && <button className={cx(s.btn, s.primary)} onClick={() => setDrawer({ kind: "invite", rfq: openRfq })}><Users /> دعوت از تأمین‌کنندگان</button>,
    compare: ws.rfqs[0] && <Link className={cx(s.btn, s.primary)} href={`/organization/requests/${r.id}/compare/${(ws.rfqs.find((x) => x.quotes_received) ?? ws.rfqs[0]).id}?org=${org}`}><GitCompare /> مقایسه پیشنهادها</Link>,
    create_order: p.can_procure && awarded && <button className={cx(s.btn, s.primary)} disabled={!!busy} onClick={() => setDrawer({kind:"order",qid:awarded.sp.quote!.id})}><PackageCheck /> صدور سفارش</button>,
    confirm_order: p.can_procure && liveOrder && <button className={cx(s.btn, s.primary)} disabled={!!busy} onClick={() => act("confirm", `${base}/purchase-orders/${liveOrder.id}/confirm`)}><Check /> تأیید سفارش</button>,
    send_order: p.can_procure && liveOrder && <button className={cx(s.btn, s.primary)} disabled={!!busy} onClick={() => act("send", `${base}/purchase-orders/${liveOrder.id}/send`)}><Send /> ارسال به تأمین‌کننده</button>,
    fulfillment: <button className={cx(s.btn, s.primary)} onClick={() => go("orders")}><Truck /> پیگیری تحویل</button>,
    resolve_correction: <button className={cx(s.btn, s.primary)} onClick={() => go("orders")}><RotateCcw /> رسیدگی به مرجوعی</button>,
    close: p.can_procure && <button className={cx(s.btn, s.primary)} disabled={!!busy} onClick={() => act("close", `${base}/requests/${r.id}/close`)}><FolderLock /> بستن پرونده</button>,
    payment_plan: <button className={cx(s.btn, s.primary)} onClick={() => go("finance")}><Landmark /> برنامه پرداخت</button>,
    finance_approval: <button className={cx(s.btn, s.primary)} onClick={() => go("finance")}><Landmark /> تأیید مالی</button>,
    collection: <button className={cx(s.btn, s.primary)} onClick={() => go("finance")}><Landmark /> ثبت وصول</button>,
    settlement: <button className={cx(s.btn, s.primary)} onClick={() => go("finance")}><Landmark /> تسویه</button>,
  };

  return (
    <div className={s.root}>
      <header className={s.head}>
        <div className={s.headRow}>
          <div style={{ minWidth: 0 }}>
            <div className={s.eyebrow}>
              <Link href="/org">میز کار</Link> / <Link href="/organization/requests">درخواست‌ها</Link> / <span className={s.num}>{r.request_number}</span>
            </div>
            <h1 className={s.title}>{r.title}</h1>
            <div className={s.meta}>
              <Chip tone={statusTone(r.status)} dot>{PR_STATUS[r.status] ?? r.status}</Chip>
              <span><Building2 size={14} /> <b>{ws.organization.name}</b></span>
              <span><User size={14} /> مالک: <b>{ws.owner ?? "—"}</b></span>
              <span><CalendarClock size={14} /> موردنیاز: <b>{formatJalali(ws.sla.needed_by_date)}</b> {!["completed", "cancelled", "rejected"].includes(r.status) && slaChip(ws.sla.needed_by_date)}</span>
              {ws.sla.rfq_deadline && <span>مهلت پیشنهاد: <b>{formatJalaliDateTime(ws.sla.rfq_deadline)}</b></span>}
              <span>اولویت: <b>{URGENCY[r.urgency] ?? r.urgency}</b></span>
            </div>
          </div>
          <div className={s.headActions}>
            {p.can_cancel && r.status === "draft" && <button className={cx(s.btn, s.sm, s.danger)} disabled={!!busy} onClick={() => act("cancel", `${base}/requests/${r.id}/cancel`)}><X /> لغو</button>}
            {primary[ws.next_action.key] || null}
          </div>
        </div>
        <div className={s.next} style={{ marginTop: 12 }}>
          <div>
            <small>اقدام بعدی</small>
            <strong>{ws.next_action.label}</strong>
            {ws.next_action.owner && <small>مسئول: {ws.next_action.owner}</small>}
          </div>
          <div style={{ flex: 1, minWidth: 260 }}><Journey steps={JOURNEY} current={cur} /></div>
        </div>
        <nav className={s.tabs} aria-label="بخش‌های پرونده">
          {SECTIONS.map(([k, label]) => (
            <button key={k} type="button" className={cx(s.tab, active === k && s.tabOn)} onClick={() => go(k)}>
              {label}{k === "quotes" && ws.rfqs.reduce((a, x) => a + x.quotes_received, 0) > 0 && <em>{n(ws.rfqs.reduce((a, x) => a + x.quotes_received, 0))}</em>}
            </button>
          ))}
        </nav>
      </header>

      <StatusBoard ws={ws} go={go} />
      <AllocationPanel token={token!} org={org} ws={ws} onDone={() => load()} />
      {flash && <div style={{ marginBottom: 12 }}><Notice tone="bad" icon={<AlertTriangle />}>{flash}</Notice></div>}
      {busy && <div className={s.small} role="status" style={{ marginBottom: 8, color: "var(--muted)" }}>در حال انجام…</div>}

      <div className={s.stack}>
        <ItemsCard ws={ws} />
        <DestinationsCard ws={ws} />
        <ApprovalsCard ws={ws} busy={!!busy} onApprove={(reason) => act("approve", `${base}/requests/${r.id}/approve`, { action: "approve", reason: reason || null })} onReject={() => setDrawer({ kind: "reject" })} />
        <RfqCard ws={ws} org={org} onCreate={() => setDrawer({ kind: "rfq" })} onInvite={(rfq) => setDrawer({ kind: "invite", rfq })}
          onOpen={(rfq) => act("open", `${base}/rfqs/${rfq.id}/open`)} onClose={(rfq) => act("closeRfq", `${base}/rfqs/${rfq.id}/close`)} busy={!!busy} />
        <QuotesCard ws={ws} org={org} />
        <OrdersCard ws={ws} busy={!!busy} awardedQuoteId={awarded?.sp.quote?.id ?? null}
          onCreate={(qid) => setDrawer({kind:"order",qid})}
          onPo={(po, step) => act(step, `${base}/purchase-orders/${po.id}/${step}`)}
          onDelivery={(po, idx, status) => act("delivery", `${base}/purchase-orders/${po.id}/deliveries/${idx}`, { status })}
          onReceipt={(po, idx) => setDrawer({ kind: "receipt", po, idx })}
          onCorrection={(po) => setDrawer({ kind: "correction", po })}
          onResolve={(po, cid, resolution) => act("resolve", `${base}/purchase-orders/${po.id}/corrections/${cid}/resolve`, { resolution })}
          onClose={() => act("close", `${base}/requests/${r.id}/close`)} onReload={() => load()} base={base} />
        <FinanceCard ws={ws} base={base} act={(l, pth, b, idem) => act(l, pth, b, idem)} busy={!!busy} />
        <section className={cx(s.card, s.section)} id="documents">
          <div className={s.sectionHead}><div><h2><FileText /> اسناد</h2><p>پیش‌فاکتور، رسید و مدارک تحویل</p></div></div>
          {!ws.orders.some((o) => o.documents?.length) ? <Empty icon={<FileText />} title="هنوز سندی پیوست نشده">مدارک تحویل، بارنامه و صورت‌حساب تأمین‌کننده در بخش «سفارش، ارسال و تحویل» هر سفارش بارگذاری می‌شوند ({ws.documents.reason}).</Empty>
            : ws.orders.map((o) => <div key={o.id}><b className={s.small}>{o.po_number}</b><OrderDocuments token={token!} docs={o.documents ?? []} /></div>)}
        </section>
        <NotesCard ws={ws} busy={!!busy} onAdd={(text) => act("note", `${base}/requests/${r.id}/notes`, { text })} />
        <TimelineCard ws={ws} />
      </div>

      <RfqDrawer open={drawer?.kind === "rfq"} ws={ws} onClose={() => setDrawer(null)}
        onCreate={async (body) => { if (await act("rfq", `${base}/rfqs`, body, true)) setDrawer(null); }} />
      {drawer?.kind === "order" && <OrderAllocationDrawer qid={drawer.qid} org={org} token={token!} busy={!!busy} onClose={()=>setDrawer(null)} onCreate={async body=>{if(await act("po",`${base}/purchase-orders`,body,true))setDrawer(null)}}/>}
      {drawer?.kind === "invite" && (
        <InviteDrawer rfq={drawer.rfq} cities={ws.request.destinations.map((d) => d.city)} org={org} token={token!} onClose={() => setDrawer(null)}
          onInvite={async (ids) => {
            for (const sid of ids) if (!(await act("invite", `${base}/rfqs/${drawer.rfq.id}/invite`, { supplier_id: sid }))) return;
            setDrawer(null);
          }} />
      )}
      {drawer?.kind === "receipt" && (
        <ReceiptDrawer ws={ws} po={drawer.po} idx={drawer.idx} onClose={() => setDrawer(null)}
          onSave={async (body) => { if (await act("receipt", `${base}/purchase-orders/${drawer.po.id}/receipts`, body)) setDrawer(null); }} />
      )}
      {drawer?.kind === "correction" && (
        <CorrectionDrawer po={drawer.po} onClose={() => setDrawer(null)}
          onSave={async (body) => { if (await act("correction", `${base}/purchase-orders/${drawer.po.id}/corrections`, body)) setDrawer(null); }} />
      )}
      {drawer?.kind === "reject" && (
        <ReasonDrawer title="رد درخواست" label="علت رد" cta="ثبت رد درخواست" onClose={() => setDrawer(null)}
          onSave={async (reason) => { if (await act("reject", `${base}/requests/${r.id}/approve`, { action: "reject", reason })) setDrawer(null); }} />
      )}
    </div>
  );
}

// ── Status board ───────────────────────────────────────────────────────────

function StatusBoard({ ws, go }: { ws: Workspace; go: (k: string) => void }) {
  const steps = ws.approval.steps, done = steps.filter((x) => x.state === "approved").length;
  const sups = ws.rfqs.flatMap((r) => r.suppliers);
  const quotes = sups.filter((x) => x.quote).map((x) => x.quote!.grand_total_minor);
  const po = ws.orders.find((o) => o.status !== "cancelled");
  const delivered = po ? po.deliveries.filter((d) => d.status === "delivered").length : 0;
  const openCorr = po ? po.corrections.filter((c) => c.status === "open").length : 0;
  const tiles: [string, string, ReactNode, ReactNode][] = [
    ["approvals", "تأیید", `${n(done)} از ${n(steps.length)}`, steps.some((x) => x.state === "rejected") ? <Chip tone="bad">رد شده</Chip> : steps.find((x) => x.state === "pending")?.label ?? (done === steps.length ? "تکمیل" : "پس از ارسال")],
    ["rfq", "تأمین‌کنندگان", sups.length ? `${n(sups.length)} دعوت` : "—", sups.length ? `${n(sups.filter((x) => x.viewed_at).length)} مشاهده · ${n(sups.filter((x) => x.quote).length)} پیشنهاد` : "هنوز استعلام نشده"],
    ["quotes", "بهترین پیشنهاد", quotes.length ? money(Math.min(...quotes), ws.organization.currency) : "—", quotes.length ? `${n(quotes.length)} پیشنهاد فعال` : "در انتظار پیشنهاد"],
    ["orders", "تحویل", po ? `${n(delivered)} از ${n(po.deliveries.length)} مقصد` : "—", po ? (openCorr ? <Chip tone="warn">{n(openCorr)} مرجوعی باز</Chip> : PO_STATUS[po.status]) : "پس از صدور سفارش"],
    ["finance", "مالی", ws.finance.policy_status === "approved" ? "سیاست مصوب" : "تصویب نشده", ws.finance.order_total_minor ? money(ws.finance.order_total_minor, ws.organization.currency) : "بدون تراکنش"],
    ["documents", "اسناد", "—", ws.documents.uploads_enabled ? "بارگذاری فعال" : "بارگذاری غیرفعال"],
  ];
  return (
    <section className={s.summary} style={{ gridTemplateColumns: undefined, marginBottom: 16 }} aria-label="وضعیت پرونده">
      {tiles.map(([k, label, v, sub]) => (
        <button key={k} type="button" className={s.sumTile} onClick={() => go(k)}><span>{label}</span><b className={s.num}>{v}</b><small>{sub}</small></button>
      ))}
    </section>
  );
}

// ── Sections ───────────────────────────────────────────────────────────────

function Section({ id, icon, title, sub, action, children }: { id: string; icon: ReactNode; title: string; sub?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className={cx(s.card, s.section)} id={id}>
      <div className={s.sectionHead}><div><h2>{icon} {title}</h2>{sub && <p>{sub}</p>}</div>{action}</div>
      {children}
    </section>
  );
}

function ItemsCard({ ws }: { ws: Workspace }) {
  const cur = ws.organization.currency;
  return (
    <Section id="items" icon={<Package />} title="اقلام درخواستی" sub={`${n(ws.items.length)} قلم، ${n(ws.items.reduce((a, i) => a + i.quantity, 0))} واحد`}>
      <div className={s.tableWrap}>
        <table className={cx(s.table, s.cards)}>
          <thead><tr><th>کالا</th><th>تعداد</th><th>مشخصات هدف</th><th>جایگزین قابل قبول</th><th>قیمت هدف</th><th>وضعیت قیمت</th></tr></thead>
          <tbody>
            {ws.items.map((i) => {
              const quoted = ws.rfqs.some((x) => x.quotes_received > 0);
              return (
                <tr key={i.id}>
                  <td className={s.full}><div className={s.prod}><span className={s.thumb}>{i.image_url ? <img src={i.image_url} alt="" /> : <Package />}</span><div><b>{i.name}</b><small>{i.master_product_id ? `کالای کاتالوگ${i.sku ? ` · ${i.sku}` : ""}` : "شرح آزاد"}{i.brand ? ` · ${i.brand}` : ""}</small></div></div></td>
                  <td data-label="تعداد" className={s.num}>{n(i.quantity)} {i.unit}</td>
                  <td data-label="مشخصات هدف">{i.target_specification || <span className={s.muted}>—</span>}</td>
                  <td data-label="جایگزین">{i.acceptable_alternative || <span className={s.muted}>—</span>}</td>
                  <td data-label="قیمت هدف" className={s.num}>{i.target_unit_price_minor ? money(i.target_unit_price_minor, cur) : <span className={s.muted}>—</span>}</td>
                  <td data-label="وضعیت قیمت">{quoted ? <Chip tone="info">پیشنهاد دریافت شده</Chip> : <Chip tone="warn">نیازمند استعلام</Chip>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {ws.request.description && <p className={s.small} style={{ whiteSpace: "pre-line", marginTop: 10, color: "var(--ink2)" }}>{toPersianNum(ws.request.description)}</p>}
      {ws.request.notes && <p className={s.small} style={{ whiteSpace: "pre-line", color: "var(--ink2)" }}>{ws.request.notes}</p>}
    </Section>
  );
}

function DestinationsCard({ ws }: { ws: Workspace }) {
  const ds = ws.request.destinations;
  return (
    <Section id="destinations" icon={<MapPin />} title="مقصدها" sub={ds.length ? `${n(ds.length)} مقصد با تخصیص مستقل` : undefined}>
      {!ds.length ? <Empty icon={<MapPin />} title="مقصدی ثبت نشده">این درخواست پیش از قابلیت چندمقصدی ثبت شده یا نشانی تحویل ندارد.</Empty> : (
        <div className={s.grid3}>
          {ds.map((d, i) => (
            <div key={i} className={s.cardFlat}>
              <div className={s.spread}><b>{d.label || d.city}</b><Chip>{d.province} · {d.city}</Chip></div>
              <p className={s.small} style={{ margin: "6px 0", color: "var(--ink2)" }}>{d.address}</p>
              <div className={s.small} style={{ display: "grid", gap: 2 }}>
                {d.recipient_name && <span>گیرنده: <b>{d.recipient_name}</b>{d.recipient_phone ? ` · ${d.recipient_phone}` : ""}</span>}
                {d.delivery_window && <span>بازه تحویل: {d.delivery_window}</span>}
                {d.notes && <span className={s.muted}>{d.notes}</span>}
              </div>
              <hr className={s.divider} style={{ margin: "10px 0" }} />
              <div className={s.row} style={{ gap: 6 }}>
                {d.allocations.map((a) => <Chip key={a.item_index} tone="info">{ws.items[a.item_index]?.name ?? `ردیف ${a.item_index + 1}`}: {n(a.quantity)}</Chip>)}
              </div>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

function ApprovalsCard({ ws, busy, onApprove, onReject }: { ws: Workspace; busy: boolean; onApprove: (reason: string) => void; onReject: () => void }) {
  const [comment, setComment] = useState("");
  const steps = ws.approval.steps;
  return (
    <Section id="approvals" icon={<ShieldCheck />} title="زنجیره تأیید" sub={ws.approval.configured ? "طبق سیاست خرید سازمان" : "تأیید یک‌مرحله‌ای (سیاست پیش‌فرض)"}
      action={<Link className={cx(s.btn, s.sm, s.ghost)} href="/organization/policy">سیاست تأیید</Link>}>
      <div className={s.chain}>
        {steps.map((st, i) => (
          <div key={st.key} className={s.chainStep}>
            <span className={cx(s.chainIcon, st.state === "approved" && s.cApproved, st.state === "pending" && s.cPending, st.state === "rejected" && s.cRejected)}>
              {st.state === "approved" ? "✓" : st.state === "rejected" ? "✕" : st.state === "pending" ? "●" : "○"}
            </span>
            <div>
              <div className={s.spread}>
                <b>{n(i + 1)}. {st.label}</b>
                <Chip tone={st.state === "approved" ? "ok" : st.state === "pending" ? "info" : st.state === "rejected" ? "bad" : "muted"}>
                  {{ approved: "تأییدشده", pending: "در انتظار", rejected: "ردشده", upcoming: "مرحله بعد" }[st.state]}
                </Chip>
              </div>
              {st.actor && <div className={s.small}>{st.actor} · {formatJalaliDateTime(st.at)}</div>}
              {st.comment && <div className={s.small} style={{ color: "var(--ink2)" }}>«{st.comment}»</div>}
              {st.state === "pending" && ws.permissions.can_approve && (
                <div className={s.row} style={{ marginTop: 8 }}>
                  <input className={cx(s.input, s.inputSm)} style={{ flex: 1, minWidth: 180 }} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="توضیح (اختیاری)" />
                  <button className={cx(s.btn, s.sm, s.primary)} disabled={busy} onClick={() => onApprove(comment)}><Check /> تأیید</button>
                  <button className={cx(s.btn, s.sm, s.danger)} disabled={busy} onClick={onReject}><X /> رد</button>
                </div>
              )}
              {st.state === "pending" && !ws.permissions.can_approve && <div className={s.small} style={{ color: "var(--muted)" }}>این مرحله با نقش شما قابل انجام نیست.</div>}
            </div>
          </div>
        ))}
      </div>
      {ws.request.status === "draft" && <Notice tone="info" icon={<CircleDot />}>زنجیره تأیید پس از ارسال درخواست آغاز می‌شود.</Notice>}
    </Section>
  );
}

function RfqCard({ ws, org, onCreate, onInvite, onOpen, onClose, busy }: {
  ws: Workspace; org: string; onCreate: () => void; onInvite: (r: Rfq) => void; onOpen: (r: Rfq) => void; onClose: (r: Rfq) => void; busy: boolean;
}) {
  const p = ws.permissions;
  const canCreate = p.can_procure && ["approved", "sourcing", "quoted"].includes(ws.request.status);
  return (
    <Section id="rfq" icon={<ClipboardList />} title="استعلام از تأمین‌کنندگان" sub="هر استعلام می‌تواند به چند تأمین‌کننده ارسال شود"
      action={canCreate && <button className={cx(s.btn, s.sm)} onClick={onCreate}><ClipboardList /> استعلام جدید</button>}>
      {!ws.rfqs.length ? (
        <Empty icon={<ClipboardList />} title="هنوز استعلامی ایجاد نشده"
          action={canCreate ? <button className={cx(s.btn, s.primary)} onClick={onCreate}>ایجاد استعلام</button> : undefined}>
          {ws.request.status === "approved" ? "درخواست تأیید شده و آماده استعلام از تأمین‌کنندگان است." : "استعلام پس از تأیید درخواست توسط تدارکات ایجاد می‌شود."}
        </Empty>
      ) : ws.rfqs.map((x) => (
        <div key={x.id} className={s.cardFlat} style={{ marginBottom: 10 }}>
          <div className={s.spread}>
            <div className={s.row}>
              <b className={s.num}>{x.rfq_number}</b><span>{x.title}</span>
              <Chip tone={x.status === "open" ? "info" : x.status === "awarded" ? "ok" : "muted"} dot>{RFQ_STATUS[x.status] ?? x.status}</Chip>
            </div>
            <div className={s.row}>
              <span className={s.small}>مهلت پاسخ: <b>{formatJalaliDateTime(x.deadline_at)}</b></span>
              {p.can_procure && ["draft", "open"].includes(x.status) && <button className={cx(s.btn, s.sm)} onClick={() => onInvite(x)}><Users /> دعوت</button>}
              {p.can_procure && x.status === "draft" && <button className={cx(s.btn, s.sm, s.primary)} disabled={busy || !x.suppliers.length} onClick={() => onOpen(x)}><Send /> ارسال به تأمین‌کنندگان</button>}
              {p.can_procure && x.status === "open" && <button className={cx(s.btn, s.sm)} disabled={busy} onClick={() => onClose(x)}><Lock /> بستن دریافت پیشنهاد</button>}
              {x.quotes_received > 0 && <Link className={cx(s.btn, s.sm, s.primary)} href={`/organization/requests/${ws.request.id}/compare/${x.id}?org=${org}`}><GitCompare /> مقایسه</Link>}
            </div>
          </div>
          {!x.suppliers.length ? (
            <p className={s.small} style={{ color: "var(--muted)", margin: "8px 0 0" }}>هنوز تأمین‌کننده‌ای دعوت نشده است.</p>
          ) : (
            <div className={s.tableWrap} style={{ marginTop: 10 }}>
              <table className={cx(s.table, s.cards)}>
                <thead><tr><th>تأمین‌کننده</th><th>وضعیت</th><th>دعوت</th><th>مشاهده</th><th>پیشنهاد</th></tr></thead>
                <tbody>
                  {x.suppliers.map((sp) => (
                    <tr key={sp.supplier_id}>
                      <td className={s.full}><b>{sp.name}</b>{sp.decline_reason && <div className={s.small} style={{ color: "var(--red)" }}>علت انصراف: {sp.decline_reason}</div>}</td>
                      <td data-label="وضعیت"><Chip tone={supplierTone(sp.state)} dot>{SUPPLIER_STATE[sp.state]}</Chip></td>
                      <td data-label="دعوت" className={s.small}>{formatJalaliDateTime(sp.invited_at)}</td>
                      <td data-label="مشاهده" className={s.small}>{sp.viewed_at ? formatJalaliDateTime(sp.viewed_at) : "—"}</td>
                      <td data-label="پیشنهاد" className={s.num}>{sp.quote ? <>{money(sp.quote.grand_total_minor, ws.organization.currency)} <span className={s.muted}>· نسخه {n(sp.quote.revision)}</span></> : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
    </Section>
  );
}

function QuotesCard({ ws, org }: { ws: Workspace; org: string }) {
  const quotes = ws.rfqs.flatMap((x) => x.suppliers.filter((sp) => sp.quote).map((sp) => ({ rfq: x, sp })));
  const invited = ws.rfqs.reduce((a, x) => a + x.suppliers.length, 0);
  const deadline = ws.sla.rfq_deadline;
  return (
    <Section id="quotes" icon={<Scale />} title="پیشنهادها و مقایسه" sub="انتخاب نهایی با شماست؛ سامانه فقط شاخص‌های واقعی را نمایش می‌دهد">
      {!quotes.length ? (
        <Empty icon={<Scale />} title="هنوز پیشنهادی دریافت نشده">
          {invited ? `${n(invited)} تأمین‌کننده دعوت شده‌اند${deadline ? ` · مهلت پاسخ ${formatJalaliDateTime(deadline)}` : ""}.` : "ابتدا باید از تأمین‌کنندگان استعلام شود."}
        </Empty>
      ) : (
        <>
          <div className={s.grid3}>
            {quotes.map(({ rfq, sp }) => (
              <div key={sp.quote!.id} className={s.cardFlat}>
                <div className={s.spread}><b>{sp.name}</b><Chip tone={sp.quote!.status === "awarded" ? "ok" : supplierTone(sp.state)} dot>{sp.quote!.status === "awarded" ? "انتخاب‌شده" : SUPPLIER_STATE[sp.state]}</Chip></div>
                <div style={{ fontSize: 20, fontWeight: 800, margin: "6px 0" }} className={s.num}>{money(sp.quote!.grand_total_minor, ws.organization.currency)}</div>
                <div className={s.small} style={{ color: "var(--muted)" }}>{sp.quote!.quote_number} · نسخه {n(sp.quote!.revision)} · {rfq.rfq_number}</div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 12 }}>
            <Link className={cx(s.btn, s.primary)} href={`/organization/requests/${ws.request.id}/compare/${quotes[0].rfq.id}?org=${org}`}><GitCompare /> مقایسه کامل پیشنهادها</Link>
          </div>
        </>
      )}
    </Section>
  );
}

function OrdersCard({ ws, busy, awardedQuoteId, onCreate, onPo, onDelivery, onReceipt, onCorrection, onResolve, onClose, onReload, base }: {
  ws: Workspace; busy: boolean; awardedQuoteId: number | null; onCreate: (qid: number) => void; onPo: (po: Order, step: "confirm" | "send") => void;
  onDelivery: (po: Order, idx: number, status: string) => void; onReceipt: (po: Order, idx: number) => void; onCorrection: (po: Order) => void;
  onResolve: (po: Order, cid: number, resolution: string) => void; onClose: () => void; onReload: () => void; base: string;
}) {
  const { token } = useAuth();
  const p = ws.permissions, cur = ws.organization.currency;
  const [resolution, setResolution] = useState<Record<number, string>>({});
  return (
    <Section id="orders" icon={<Truck />} title="سفارش، ارسال و تحویل" sub="قیمت و شرایط سفارش هنگام صدور ثابت (snapshot) می‌شود">
      {!ws.orders.length ? (
        <Empty icon={<PackageCheck />} title="هنوز سفارشی صادر نشده"
          action={p.can_procure && awardedQuoteId ? <button className={cx(s.btn, s.primary)} disabled={busy} onClick={() => onCreate(awardedQuoteId)}>صدور سفارش از پیشنهاد منتخب</button> : undefined}>
          {awardedQuoteId ? "پیشنهاد منتخب آماده تبدیل به سفارش است." : "سفارش پس از انتخاب پیشنهاد صادر می‌شود."}
        </Empty>
      ) : ws.orders.map((po) => {
        const allDelivered = po.deliveries.every((d) => d.status === "delivered");
        const openCorr = po.corrections.some((c) => c.status === "open");
        return (
          <div key={po.id} className={s.stack} style={{ gap: 12 }}>
            <div className={s.cardFlat}>
              <div className={s.spread}>
                <div className={s.row}><b className={s.num}>{po.po_number}</b><Chip tone={statusTone(po.status)} dot>{PO_STATUS[po.status] ?? po.status}</Chip><span className={s.small}>تأمین‌کننده: <b>{po.supplier ?? "—"}</b></span>
                  <Link className={cx(s.btn, s.sm)} href={`/organization/requests/${ws.request.id}/proforma?org=${ws.organization.id}`}><FileText /> پیش‌فاکتور</Link>
                  {po.status !== "draft" && <Link className={cx(s.btn, s.sm)} href={`/organization/requests/${ws.request.id}/proforma?org=${ws.organization.id}&doc=statement`}><FileText /> صورت‌حساب داخلی</Link>}</div>
                <div className={s.row}>
                  <span className={s.num} style={{ fontWeight: 800 }}>{money(po.grand_total_minor, cur)}</span>
                  {p.can_procure && po.status === "draft" && <button className={cx(s.btn, s.sm, s.primary)} disabled={busy} onClick={() => onPo(po, "confirm")}><Check /> تأیید سفارش</button>}
                  {p.can_procure && po.status === "confirmed" && <button className={cx(s.btn, s.sm, s.primary)} disabled={busy} onClick={() => onPo(po, "send")}><Send /> ارسال به تأمین‌کننده</button>}
                </div>
              </div>
              <div className={s.tableWrap} style={{ marginTop: 10 }}>
                <table className={cx(s.table, s.cards)}>
                  <thead><tr><th>قلم</th><th>تعداد</th><th>قیمت واحد (ثابت)</th><th>جمع</th></tr></thead>
                  <tbody>
                    {po.items.map((it, k) => (
                      <tr key={it.id}>
                        <td className={s.full}><b>{ws.items[k]?.name ?? it.free_text_description ?? `ردیف ${k + 1}`}</b></td>
                        <td data-label="تعداد" className={s.num}>{n(it.quantity)} {it.unit}</td>
                        <td data-label="قیمت واحد" className={s.num}>{money(it.unit_price_minor_snapshot, cur)}</td>
                        <td data-label="جمع" className={s.num}>{money(it.total_minor_snapshot, cur)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            {po.status !== "draft" && (
              <div className={s.grid2}>
                {po.deliveries.map((d) => {
                  const idx = DELIVERY_FLOW.indexOf(d.status ?? "confirmed");
                  const canReceive = p.can_receive && ["shipped", "partially_delivered", "delivered"].includes(d.status ?? "") && d.status !== "delivered";
                  return (
                    <div key={d.destination_index} className={s.cardFlat}>
                      <div className={s.spread}>
                        <b className={s.row} style={{ gap: 6 }}><MapPin size={15} /> {d.label || d.city || `مقصد ${n(d.destination_index + 1)}`}</b>
                        <Chip tone={d.status === "delivered" ? "ok" : d.status === "partially_delivered" ? "warn" : "info"} dot>{DELIVERY_STATUS[d.status ?? "confirmed"]}</Chip>
                      </div>
                      <div style={{ margin: "10px 0 6px" }}><Journey compact steps={DELIVERY_FLOW.map((x) => DELIVERY_STATUS[x])} current={d.status === "delivered" ? DELIVERY_FLOW.length : idx} /></div>
                      {d.tracking_reference && <div className={s.small}>کد رهگیری: <b dir="ltr">{d.tracking_reference}</b></div>}
                      <div className={s.row} style={{ marginTop: 8 }}>
                        {p.can_procure && idx < DELIVERY_FLOW.indexOf("shipped") && (
                          <button className={cx(s.btn, s.sm)} disabled={busy} onClick={() => onDelivery(po, d.destination_index, DELIVERY_FLOW[idx + 1])}>
                            ثبت «{DELIVERY_STATUS[DELIVERY_FLOW[idx + 1]]}»
                          </button>
                        )}
                        {canReceive && <button className={cx(s.btn, s.sm, s.primary)} onClick={() => onReceipt(po, d.destination_index)}><PackageCheck /> ثبت رسید تحویل</button>}
                      </div>
                      {d.receipts.map((rc) => (
                        <div key={rc.id} className={s.small} style={{ marginTop: 8, paddingTop: 8, borderTop: "1px dashed var(--line)" }}>
                          <Chip tone={rc.kind === "full" ? "ok" : "warn"}>{RECEIPT_KIND[rc.kind]}</Chip> {rc.receiver_name} · {formatJalaliDateTime(rc.created_at)}
                          {rc.notes && <div style={{ color: "var(--ink2)" }}>{rc.notes}</div>}
                        </div>
                      ))}
                    </div>
                  );
                })}
              </div>
            )}
            {(po.corrections.length > 0 || (p.can_receive && po.status !== "draft")) && (
              <div className={s.cardFlat}>
                <div className={s.spread}>
                  <b className={s.row} style={{ gap: 6 }}><RotateCcw size={15} /> مرجوعی و اصلاحیه</b>
                  {p.can_receive && po.status !== "draft" && <button className={cx(s.btn, s.sm)} onClick={() => onCorrection(po)}>ثبت مرجوعی/اصلاحیه</button>}
                </div>
                {!po.corrections.length ? <p className={s.small} style={{ color: "var(--muted)", margin: "6px 0 0" }}>موردی ثبت نشده است.</p> : po.corrections.map((c) => (
                  <div key={c.id} style={{ marginTop: 8, paddingTop: 8, borderTop: "1px dashed var(--line)" }} className={s.small}>
                    <div className={s.row}><Chip tone={c.status === "open" ? "warn" : "ok"} dot>{c.kind === "return" ? "مرجوعی" : "اصلاحیه"} · {c.status === "open" ? "باز" : "رسیدگی‌شده"}</Chip><span>{c.reason}</span></div>
                    {c.resolution && <div style={{ color: "var(--ink2)" }}>نتیجه: {c.resolution}</div>}
                    {c.status === "open" && p.can_procure && (
                      <div className={s.row} style={{ marginTop: 6 }}>
                        <input className={cx(s.input, s.inputSm)} style={{ flex: 1 }} placeholder="نتیجه رسیدگی" value={resolution[c.id] ?? ""} onChange={(e) => setResolution({ ...resolution, [c.id]: e.target.value })} />
                        <button className={cx(s.btn, s.sm)} disabled={busy || !resolution[c.id]?.trim()} onClick={() => onResolve(po, c.id, resolution[c.id])}>ثبت رسیدگی</button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
            {po.status !== "draft" && token && <div className={s.cardFlat}>
              <OrderDocuments token={token} docs={po.documents ?? []} uploadPath={p.can_receive || p.can_procure ? `${base}/purchase-orders/${po.id}/documents` : undefined}
                destinations={po.deliveries.map((d) => ({ index: d.destination_index, label: d.label || d.city || `مقصد ${n(d.destination_index + 1)}` }))} onUploaded={onReload} />
            </div>}
            {p.can_procure && ws.request.status === "awarded" && allDelivered && !openCorr && (
              <Notice tone="info" icon={<FolderLock />}>
                همه مقصدها تحویل کامل شده‌اند و مورد باز وجود ندارد. <button className={cx(s.btn, s.sm, s.primary)} disabled={busy} onClick={onClose} style={{ marginRight: 8 }}>بستن پرونده</button>
              </Notice>
            )}
          </div>
        );
      })}
    </Section>
  );
}

function FinanceCard({ ws, base, act, busy }: { ws: Workspace; base: string; act: (l: string, p: string, b?: unknown, idem?: boolean) => Promise<boolean>; busy: boolean }) {
  const f = ws.finance, cur = ws.organization.currency;
  const rows: [string, ReactNode][] = [
    ["مبلغ سفارش", f.order_total_minor != null ? money(f.order_total_minor, cur) : "پس از صدور سفارش"],
    ["پیش‌پرداخت", "تعریف نشده"], ["مانده", "—"], ["اعتبار تخصیصی", <Link key="c" href="/organization/finance#credit">مشاهده در مالی</Link>],
    ["مصرف اعتبار", "بدون ثبت"], ["سررسیدها", "بدون سررسید ثبت‌شده"], ["مطالبات و وصول", "—"], ["تسویه", "—"],
  ];
  return (
    <Section id="finance" icon={<Landmark />} title="مالی" sub={f.note}
      action={<Chip tone={f.policy_status === "approved" ? "ok" : "warn"} dot>{f.policy_status === "approved" ? "سیاست مالی تصویب‌شده" : f.policy_status === "test" ? "سیاست آزمایشی (TEST)" : "سیاست مالی تصویب نشده"}</Chip>}>
      <div className={s.grid4}>
        {f.methods.map((m) => (
          <div key={m.key} className={s.cardFlat} style={{ opacity: m.enabled ? 1 : .75 }}>
            <div className={s.spread}><b>{m.label}</b><Chip tone={m.enabled ? "ok" : "muted"}>{m.enabled ? "فعال" : "غیرفعال"}</Chip></div>
            <p className={s.small} style={{ margin: "6px 0 0", color: "var(--muted)" }}>{m.reason}</p>
          </div>
        ))}
      </div>
      {ws.orders.filter((o) => o.status !== "cancelled").map((o) => (
        <div key={o.id} style={{ marginTop: 14 }}><CaseFinance ws={ws} po={o} base={base} act={act} busy={busy} /></div>
      ))}
      {!ws.orders.length && (
        <div className={s.tableWrap} style={{ marginTop: 12 }}>
          <table className={cx(s.table, s.cards)}>
            <tbody>{rows.map(([k, v]) => <tr key={k}><td data-label={k} style={{ fontWeight: 600, width: "40%" }}>{k}</td><td data-label="" className={s.num}>{v}</td></tr>)}</tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

function NotesCard({ ws, busy, onAdd }: { ws: Workspace; busy: boolean; onAdd: (text: string) => Promise<boolean> }) {
  const [text, setText] = useState("");
  const notes = ws.timeline.filter((e) => e.type === "note");
  if (!ws.permissions.can_read_internal) {
    return <Section id="notes" icon={<NotebookPen />} title="یادداشت‌های داخلی"><Empty icon={<Lock />} title="فقط برای تدارکات، مالی و مدیر سازمان">یادداشت‌های داخلی برای درخواست‌دهنده نمایش داده نمی‌شود.</Empty></Section>;
  }
  return (
    <Section id="notes" icon={<NotebookPen />} title="یادداشت‌های داخلی" sub="قابل مشاهده برای نقش‌های داخلی سازمان؛ غیرقابل ویرایش">
      <form className={s.row} onSubmit={async (e) => { e.preventDefault(); if (text.trim() && await onAdd(text.trim())) setText(""); }}>
        <input className={s.input} style={{ flex: 1 }} value={text} onChange={(e) => setText(e.target.value)} placeholder="یادداشت داخلی…" maxLength={2000} />
        <button className={cx(s.btn, s.primary)} disabled={busy || !text.trim()}>ثبت یادداشت</button>
      </form>
      <div className={s.timeline} style={{ marginTop: 10 }}>
        {!notes.length ? <p className={s.small} style={{ color: "var(--muted)" }}>یادداشتی ثبت نشده است.</p> : notes.slice().reverse().map((e, i) => (
          <div key={i} className={cx(s.tItem, s.tInternal)}><span className={s.tDot} /><div><b>{e.actor ?? "—"}</b> <span>{String(e.details.text ?? "")}</span></div><time>{formatJalaliDateTime(e.at)}</time></div>
        ))}
      </div>
    </Section>
  );
}

function describe(e: Workspace["timeline"][number]): string {
  const d = e.details as Record<string, string | number | null | undefined>;
  switch (e.type) {
    case "approval_step": return `${d.step}: ${d.action === "approve" ? "تأیید" : "رد"}${d.comment ? ` — «${d.comment}»` : ""}`;
    case "delivery_status": return `${d.po} · مقصد ${Number(d.destination_index) + 1}: ${DELIVERY_STATUS[String(d.to)] ?? d.to}`;
    case "receipt": return `${d.po} · مقصد ${Number(d.destination_index) + 1}: ${RECEIPT_KIND[String(d.kind)] ?? d.kind} — ${d.receiver}`;
    case "correction_opened": return `${d.kind === "return" ? "مرجوعی" : "اصلاحیه"}: ${d.reason}`;
    case "correction_resolved": return `نتیجه: ${d.resolution}`;
    case "quote_awarded": return d.reason ? `علت انتخاب: ${d.reason}` : "";
    case "note": return String(d.text ?? "");
    default: return "";
  }
}

function TimelineCard({ ws }: { ws: Workspace }) {
  const events = useMemo(() => ws.timeline.slice().reverse(), [ws.timeline]);
  return (
    <Section id="timeline" icon={<History />} title="رویدادهای پرونده" sub="ثبت غیرقابل ویرایش؛ عامل و زمان هر تغییر">
      {!events.length ? <Empty title="رویدادی ثبت نشده" /> : (
        <div className={s.timeline}>
          {events.map((e, i) => (
            <div key={i} className={cx(s.tItem, e.internal && s.tInternal)}>
              <span className={s.tDot} />
              <div><b>{EVENT_LABEL[e.type] ?? e.type}</b>{e.actor && <span className={s.muted}> · {e.actor}</span>}{describe(e) && <div className={s.small} style={{ color: "var(--ink2)" }}>{describe(e)}</div>}</div>
              <time>{formatJalaliDateTime(e.at)}</time>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

// ── Drawers ────────────────────────────────────────────────────────────────

function RfqDrawer({ open, ws, onClose, onCreate }: { open: boolean; ws: Workspace; onClose: () => void; onCreate: (body: Record<string, unknown>) => void }) {
  const [title, setTitle] = useState(`استعلام ${ws.request.title}`.slice(0, 200));
  const [deadline, setDeadline] = useState("");
  const [notes, setNotes] = useState("");
  const remaining=(id:number)=>ws.coverage?.find(x=>x.purchase_request_item_id===id)?.unawarded??ws.items.find(x=>x.id===id)?.quantity??0;
  const [selected,setSelected]=useState(()=>ws.items.filter(i=>remaining(i.id)>0).map(i=>i.id));
  useEffect(()=>{if(open)setSelected(ws.items.filter(i=>remaining(i.id)>0).map(i=>i.id))},[open,ws.request.id]);
  const usableSelected=selected.filter(id=>remaining(id)>0);
  return (
    <Drawer open={open} title="ایجاد استعلام از تأمین‌کنندگان" onClose={onClose}
      footer={<><button className={s.btn} onClick={onClose}>انصراف</button><button className={cx(s.btn, s.primary)} disabled={!title.trim() || !deadline || !usableSelected.length}
        onClick={() => onCreate({ purchase_request_id: ws.request.id, title: title.trim(), deadline_at: `${deadline}T20:29:59.000Z`, notes: notes.trim() || null,items:usableSelected.map(id=>({purchase_request_item_id:id,quantity:remaining(id)})) })}>ایجاد استعلام</button></>}>
      <Notice tone="info" icon={<ClipboardList />}>اقلام انتخاب‌شده به همراه مقصدهای مربوط ارسال می‌شوند؛ برای تأمین‌کنندگان مختلف گروه‌های جدا انتخاب کنید. بودجه و یادداشت‌های داخلی نمایش داده نمی‌شود.</Notice>
      <div className={s.field}>اقلام این استعلام{ws.items.map(i=><label key={i.id} className={s.row}><input type="checkbox" disabled={remaining(i.id)===0} checked={selected.includes(i.id)} onChange={e=>setSelected(e.target.checked?[...selected,i.id]:selected.filter(id=>id!==i.id))}/>{i.name} · باقی‌مانده برای انتخاب تأمین‌کننده: {n(remaining(i.id))}</label>)}</div>
      <label className={s.field}>عنوان<input className={s.input} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} /></label>
      <label className={s.field}>مهلت پاسخ تأمین‌کننده<input className={s.input} type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} /><span className={s.hint}>{deadline ? `${formatJalali(deadline)} · ساعت ۲۳:۵۹` : "الزامی"}</span></label>
      <label className={s.field}>توضیحات برای تأمین‌کننده<textarea className={s.textarea} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={2000} /></label>
    </Drawer>
  );
}

function InviteDrawer({ rfq, cities, org, token, onClose, onInvite }: { rfq: Rfq; cities: string[]; org: string; token: string; onClose: () => void; onInvite: (ids: number[]) => void }) {
  const [list, setList] = useState<{ id: number; display_name: string; supplier_type: string | null; is_demo?: boolean; cities?: string[] }[] | null>(null);
  const [err, setErr] = useState("");
  const [picked, setPicked] = useState<number[]>([]);
  useEffect(() => { proc.suppliers(token, org).then((r) => setList(r.items)).catch((e) => { setErr(e.message); setList([]); }); }, [token, org]);
  const already = new Set(rfq.suppliers.map((x) => x.supplier_id));
  return (
    <Drawer open title={`دعوت تأمین‌کننده · ${rfq.rfq_number}`} onClose={onClose}
      footer={<><button className={s.btn} onClick={onClose}>انصراف</button><button className={cx(s.btn, s.primary)} disabled={!picked.length} onClick={() => onInvite(picked)}>دعوت {n(picked.length)} تأمین‌کننده</button></>}>
      {err && <Notice tone="bad" icon={<AlertTriangle />}>{err}</Notice>}
      {list === null ? <div className={s.skeleton} style={{ height: 120 }} /> : !list.length ? (
        <Empty icon={<Users />} title="تأمین‌کننده فعالی ثبت نشده">برای ارسال استعلام، ابتدا تأمین‌کنندگان واقعی باید در سامانه ثبت و تأیید شوند.</Empty>
      ) : list.map((sp) => (
        <label key={sp.id} className={s.cardFlat} style={{ display: "flex", gap: 10, alignItems: "center", opacity: already.has(sp.id) ? .55 : 1 }}>
          <input type="checkbox" disabled={already.has(sp.id)} checked={picked.includes(sp.id) || already.has(sp.id)}
            onChange={(e) => setPicked(e.target.checked ? [...picked, sp.id] : picked.filter((x) => x !== sp.id))} />
          <span style={{ flex: 1 }}><b>{sp.display_name}</b>{sp.supplier_type && <small className={s.muted}> · {sp.supplier_type}</small>}
            {!!sp.cities?.length && <small className={s.muted} style={{ display: "block" }}>محل: {sp.cities.join("، ")}</small>}</span>
          {sp.cities?.some((c) => cities.includes(c)) && <Chip tone="ok" title="در شهر یکی از مقصدهای این درخواست مستقر است">محلی</Chip>}
          {sp.is_demo && <Chip tone="warn" title="تأمین‌کنندهٔ نمایشی/آزمایشی؛ برای خرید واقعی دعوت نکنید">DEMO</Chip>}
          {already.has(sp.id) && <Chip tone="info">دعوت‌شده</Chip>}
        </label>
      ))}
    </Drawer>
  );
}

function ReceiptDrawer({ ws, po, idx, onClose, onSave }: { ws: Workspace; po: Order; idx: number; onClose: () => void; onSave: (b: Record<string, unknown>) => void }) {
  const dest = ws.request.destinations[idx];
  const [kind, setKind] = useState("full");
  const [receiver, setReceiver] = useState(dest?.recipient_name ?? "");
  const [notes, setNotes] = useState("");
  const [qty, setQty] = useState<Record<number, number>>(() => Object.fromEntries((po.deliveries.find(d=>d.destination_index===idx)?.allocations ?? dest?.allocations ?? ws.items.map((i, k) => ({ item_index: k, quantity: i.quantity }))).map((a) => [a.item_index, a.quantity])));
  const needNotes = kind !== "full";
  return (
    <Drawer open title={`رسید تحویل · ${dest?.label || dest?.city || `مقصد ${idx + 1}`}`} onClose={onClose}
      footer={<><button className={s.btn} onClick={onClose}>انصراف</button><button className={cx(s.btn, s.primary)} disabled={!receiver.trim() || (needNotes && !notes.trim())}
        onClick={() => onSave({ destination_index: idx, kind, receiver_name: receiver.trim(), notes: notes.trim() || null, quantities: Object.entries(qty).map(([k, v]) => ({ item_index: Number(k), quantity: v })) })}>ثبت رسید</button></>}>
      <div className={s.seg}>{Object.entries(RECEIPT_KIND).map(([k, v]) => <button type="button" key={k} className={cx(kind === k && s.segOn)} onClick={() => setKind(k)}>{v}</button>)}</div>
      <label className={s.field}>نام تحویل‌گیرنده<input className={s.input} value={receiver} onChange={(e) => setReceiver(e.target.value)} maxLength={200} /></label>
      <div className={s.field}>تعداد دریافتی
        {Object.keys(qty).map((k) => (
          <div key={k} className={s.spread}><span>{ws.items[Number(k)]?.name ?? `ردیف ${Number(k) + 1}`}</span>
            <input className={cx(s.input, s.inputSm)} style={{ width: 100 }} type="number" min={0} value={qty[Number(k)]} onChange={(e) => setQty({ ...qty, [k]: Math.max(0, Number(e.target.value) || 0) })} /></div>
        ))}
      </div>
      <label className={s.field}>توضیح {needNotes && <span style={{ color: "var(--red)" }}>(الزامی برای {RECEIPT_KIND[kind]})</span>}<textarea className={s.textarea} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={2000} /></label>
      <Notice tone="info" icon={<FileText />}>رسید پس از ثبت قابل ویرایش یا حذف نیست. زمان ثبت و کاربر ثبت‌کننده خودکار ذخیره می‌شود. بارگذاری تصویر هنوز فعال نیست.</Notice>
      <span className={s.small}>سفارش {po.po_number}</span>
    </Drawer>
  );
}

function CorrectionDrawer({ po, onClose, onSave }: { po: Order; onClose: () => void; onSave: (b: Record<string, unknown>) => void }) {
  const [kind, setKind] = useState("return");
  const [reason, setReason] = useState("");
  const receipts = po.deliveries.flatMap((d) => d.receipts);
  const [receipt, setReceipt] = useState<string>(receipts.length ? String(receipts[receipts.length - 1].id) : "");
  return (
    <Drawer open title={`مرجوعی / اصلاحیه · ${po.po_number}`} onClose={onClose}
      footer={<><button className={s.btn} onClick={onClose}>انصراف</button><button className={cx(s.btn, s.primary)} disabled={!reason.trim()} onClick={() => onSave({ kind, reason: reason.trim(), receipt_id: receipt ? Number(receipt) : null })}>ثبت</button></>}>
      <div className={s.seg}><button type="button" className={cx(kind === "return" && s.segOn)} onClick={() => setKind("return")}>مرجوعی</button><button type="button" className={cx(kind === "correction" && s.segOn)} onClick={() => setKind("correction")}>اصلاحیه</button></div>
      {receipts.length > 0 && (
        <label className={s.field}>رسید مرتبط
          <select className={s.select} value={receipt} onChange={(e) => setReceipt(e.target.value)}>
            <option value="">بدون رسید مرتبط</option>
            {receipts.map((r) => <option key={r.id} value={r.id}>{RECEIPT_KIND[r.kind]} · {r.receiver_name} · {formatJalaliDateTime(r.created_at)}</option>)}
          </select>
        </label>
      )}
      <label className={s.field}>علت<textarea className={s.textarea} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} /></label>
    </Drawer>
  );
}

function ReasonDrawer({ title, label, cta, onClose, onSave }: { title: string; label: string; cta: string; onClose: () => void; onSave: (reason: string) => void }) {
  const [reason, setReason] = useState("");
  return (
    <Drawer open title={title} onClose={onClose}
      footer={<><button className={s.btn} onClick={onClose}>انصراف</button><button className={cx(s.btn, s.primary, s.danger)} disabled={!reason.trim()} onClick={() => onSave(reason.trim())}>{cta}</button></>}>
      <label className={s.field}>{label}<textarea className={s.textarea} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} autoFocus /></label>
      <span className={s.small} style={{ color: "var(--muted)" }}><ArrowLeft size={12} /> این اقدام در رویدادهای پرونده ثبت می‌شود.</span>
    </Drawer>
  );
}


function AssignRemainder({ token, org, ws, onDone }: { token: string; org: string; ws: Workspace; onDone: () => void }) {
  const [open, setOpen] = useState(false), [f, setF] = useState({ label: "", province: "", city: "", address: "", recipient_name: "", recipient_phone: "" });
  const [err, setErr] = useState(""), [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true); setErr("");
    const extra = { ...f, allocations: (ws.unallocated ?? []).map((u) => ({ item_index: u.item_index, quantity: u.quantity })) };
    try {
      await apiRequest(`${proc.base(org)}/requests/${ws.request.id}/destinations`, { token, method: "PUT", body: JSON.stringify({ destinations: [...ws.request.destinations, extra], base_hash: ws.destinations_hash }) });
      setOpen(false); onDone();
    } catch (e) { setErr(e instanceof Error ? e.message : "ثبت ناموفق بود"); } finally { setBusy(false); }
  };
  if (!open) return <button type="button" className={cx(s.btn, s.sm)} style={{ marginRight: 8 }} onClick={() => setOpen(true)}>افزودن مقصد برای باقی‌مانده</button>;
  return (
    <div className={s.stack} style={{ marginTop: 8 }}>
      <div className={s.grid3}>{([["label", "نام مقصد"], ["province", "استان"], ["city", "شهر"], ["recipient_name", "گیرنده"], ["recipient_phone", "تلفن"], ["address", "نشانی"]] as const).map(([k, l]) => (
        <label key={k} className={s.field}>{l}<input className={s.input} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>))}</div>
      {err && <span className={s.small} style={{ color: "var(--red)" }}>{err}</span>}
      <button type="button" className={cx(s.btn, s.sm, s.primary)} disabled={busy} onClick={save}>ثبت مقصد باقی‌مانده</button>
    </div>
  );
}

function AllocationPanel({ token, org, ws, onDone }: { token: string; org: string; ws: Workspace; onDone: () => void }) {
  const dests = ws.request.destinations, alloc = ws.allocation ?? [];
  const [edit, setEdit] = useState(false), [split, setSplit] = useState(false);
  if (!dests.length) return null;
  const missing = alloc.filter((a) => a.unallocated > 0);
  const hasPo = ws.orders.some((o) => o.status !== "cancelled");
  const name = (i: number) => ws.items[i]?.name ?? `قلم ${n(i + 1)}`;
  return (
    <div className={s.card} style={{ marginBottom: 12 }} aria-label="تخصیص مقصدها">
      <div className={s.spread}><b>تخصیص به مقصدها</b>
        <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {!hasPo && ws.request.status === "draft" && <button type="button" className={cx(s.btn, s.sm)} onClick={() => setEdit(!edit)}>ویرایش تخصیص</button>}
          {!hasPo && !ws.rfqs.length && ws.permissions.can_procure && dests.length > 1 && <button type="button" className={cx(s.btn, s.sm)} onClick={() => setSplit(!split)}>جداکردن مقصد برای تأمین محلی</button>}
        </span></div>
      <div className={s.tableWrap}><table className={s.table}><thead><tr><th>قلم</th><th>کل درخواست</th><th>تخصیص‌یافته</th><th>بدون مقصد</th></tr></thead>
        <tbody>{alloc.map((a) => <tr key={a.item_index}><td>{name(a.item_index)}</td><td>{n(a.total)}</td><td>{n(a.allocated)}</td>
          <td>{a.unallocated > 0 ? <Chip tone="warn">{n(a.unallocated)}</Chip> : n(0)}</td></tr>)}</tbody></table></div>
      {missing.length > 0 && <Notice icon={<AlertTriangle />}>مقصد {missing.map((a) => `${n(a.unallocated)} ${name(a.item_index)}`).join("، ")} هنوز مشخص نیست. برای این مقدار سفارش خرید یا تعهد مالی صادر نمی‌شود تا مقصد آن ثبت شود.
        {!hasPo && <AssignRemainder token={token} org={org} ws={ws} onDone={onDone} />}</Notice>}
      {edit && <AllocationEditor token={token} org={org} ws={ws} onDone={() => { setEdit(false); onDone(); }} />}
      {split && <SplitDestinations token={token} org={org} ws={ws} />}
    </div>
  );
}

function AllocationEditor({ token, org, ws, onDone }: { token: string; org: string; ws: Workspace; onDone: () => void }) {
  const [rows, setRows] = useState(() => ws.request.destinations.map((d) => ({ ...d, allocations: ws.items.map((_, i) => ({ item_index: i, quantity: d.allocations?.find((a) => a.item_index === i)?.quantity ?? 0 })) })));
  const [err, setErr] = useState(""), [busy, setBusy] = useState(false);
  const sums = ws.items.map((_, i) => rows.reduce((a, d) => a + d.allocations[i].quantity, 0));
  const over = ws.items.some((it, i) => sums[i] > it.quantity);
  const save = async () => {
    setBusy(true); setErr("");
    const destinations = rows.filter((d) => d.allocations.some((a) => a.quantity > 0)).map((d) => ({ ...d, allocations: d.allocations.filter((a) => a.quantity > 0) }));
    try {
      await apiRequest(`${proc.base(org)}/requests/${ws.request.id}/destinations`, { token, method: "PUT", body: JSON.stringify({ destinations, base_hash: ws.destinations_hash }) });
      onDone();
    } catch (e) { setErr(e instanceof Error ? e.message : "ثبت ناموفق بود"); } finally { setBusy(false); }
  };
  return (
    <div className={s.stack} style={{ marginTop: 8 }}>
      <div className={s.tableWrap}><table className={s.table}><thead><tr><th>مقصد</th>{ws.items.map((it, i) => <th key={i}>{it.name ?? `قلم ${n(i + 1)}`}</th>)}</tr></thead>
        <tbody>{rows.map((d, di) => <tr key={di}><td>{d.label || d.city}</td>{d.allocations.map((a, i) => <td key={i}>
          <input aria-label={`تعداد ${d.label || d.city} ردیف ${i + 1}`} className={cx(s.input, s.inputSm)} style={{ width: 90 }} type="number" min={0} value={a.quantity}
            onChange={(e) => setRows(rows.map((r, ri) => ri !== di ? r : { ...r, allocations: r.allocations.map((x, xi) => xi !== i ? x : { ...x, quantity: Math.max(0, Math.floor(Number(e.target.value) || 0)) }) }))} /></td>)}</tr>)}
          <tr><td>جمع / کل</td>{ws.items.map((it, i) => <td key={i} style={{ color: sums[i] > it.quantity ? "var(--red)" : undefined }}>{n(sums[i])} / {n(it.quantity)}</td>)}</tr></tbody></table></div>
      {over && <span className={s.small} style={{ color: "var(--red)" }}>جمع تخصیص از تعداد درخواست بیشتر است.</span>}
      {err && <span className={s.small} style={{ color: "var(--red)" }}>{err}</span>}
      <button type="button" className={cx(s.btn, s.sm, s.primary)} disabled={busy || over} onClick={save}>ذخیرهٔ تخصیص</button>
    </div>
  );
}

function SplitDestinations({ token, org, ws }: { token: string; org: string; ws: Workspace }) {
  const [picked, setPicked] = useState<number[]>([]), [err, setErr] = useState(""), [busy, setBusy] = useState(false), [child, setChild] = useState<number | null>(null);
  const go = async () => {
    setBusy(true); setErr("");
    try {
      const r = await apiRequest<{ child_request_id: number }>(`${proc.base(org)}/requests/${ws.request.id}/split`, { token, method: "POST", body: JSON.stringify({ destination_indexes: picked, base_hash: ws.destinations_hash }) });
      setChild(r.child_request_id);
    } catch (e) { setErr(e instanceof Error ? e.message : "تقسیم ناموفق بود"); } finally { setBusy(false); }
  };
  if (child) return <Notice icon={<FileText />}>درخواست جدا برای تأمین محلی ساخته شد و باید جداگانه ارسال و تأیید شود. <Link href={`/organization/requests/${child}?org=${org}`} onClick={() => setTimeout(() => location.reload(), 50)}>مشاهدهٔ درخواست جدید</Link></Notice>;
  return (
    <div className={s.stack} style={{ marginTop: 8 }}>
      <span className={s.small}>مقصدهای انتخابی با مقدار تخصیص‌یافته‌شان به یک درخواست پیش‌نویس جدید منتقل می‌شوند تا با تأمین‌کنندهٔ محلی استعلام شوند؛ تعداد درخواست اصلی به همان اندازه کم می‌شود.</span>
      {ws.request.destinations.map((d, i) => <label key={i} style={{ display: "flex", gap: 8 }}><input type="checkbox" checked={picked.includes(i)} onChange={(e) => setPicked(e.target.checked ? [...picked, i] : picked.filter((x) => x !== i))} />{d.label || d.city} · {d.city}</label>)}
      {err && <span className={s.small} style={{ color: "var(--red)" }}>{err}</span>}
      <button type="button" className={cx(s.btn, s.sm, s.primary)} disabled={busy || !picked.length || picked.length === ws.request.destinations.length} onClick={go}>ساخت درخواست جدا</button>
    </div>
  );
}


type AllocationPreview={requirements:{purchase_request_item_id:number;title:string;unit:string|null;quantity:number;destinations:{destination_index:number;city:string;province:string;available:number}[]}[];suggested:{purchase_request_item_id:number;destination_index:number;quantity:number}[]|null};
function OrderAllocationDrawer({qid,org,token,busy,onClose,onCreate}:{qid:number;org:string;token:string;busy:boolean;onClose:()=>void;onCreate:(body:Record<string,unknown>)=>Promise<void>}){
 const[data,setData]=useState<AllocationPreview|null>(null),[values,setValues]=useState<Record<string,string>>({}),[error,setError]=useState('');
 useEffect(()=>{let active=true;setData(null);setError('');apiRequest<AllocationPreview>(`/orgs/${org}/procurement/purchase-orders/allocation-preview?supplier_quote_id=${qid}`,{token}).then(d=>{if(!active)return;setData(d);setValues(Object.fromEntries((d.suggested??[]).map(a=>[`${a.purchase_request_item_id}:${a.destination_index}`,String(a.quantity)])))}).catch(e=>{if(active)setError(e.message)});return()=>{active=false}},[qid,org,token]);
 const rows=data?.requirements.flatMap(r=>r.destinations.map(d=>{const v=normalizedDigits(values[`${r.purchase_request_item_id}:${d.destination_index}`]??'');const quantity=v===''?0:/^\d+$/.test(v)?Number(v):NaN;return {purchase_request_item_id:r.purchase_request_item_id,destination_index:d.destination_index,quantity,available:d.available}}))??[];
 const valid=!!data&&rows.every(a=>Number.isSafeInteger(a.quantity)&&a.quantity>=0&&a.quantity<=a.available)&&data.requirements.every(r=>!r.destinations.length||rows.filter(a=>a.purchase_request_item_id===r.purchase_request_item_id).reduce((sum,a)=>sum+a.quantity,0)===r.quantity);
 return <Drawer open title="تخصیص مقصد و صدور سفارش" onClose={onClose} footer={<><button className={s.btn} disabled={busy} onClick={onClose}>انصراف</button><button className={cx(s.btn,s.primary)} disabled={busy||!valid} onClick={()=>void onCreate({supplier_quote_id:qid,destination_allocations:rows.filter(a=>a.quantity>0).map(({available,...a})=>a)})}>صدور سفارش با این تخصیص</button></>}><div className={s.stack}><p>مبلغ و مالیات از پیشنهاد منتخب کپی می‌شوند؛ فقط سهم مقصدهای تأییدشده را مشخص کنید. خالی یعنی به این مقصد ارسال نمی‌شود.</p>{error&&<Notice tone="bad">{error}</Notice>}{!data&&!error&&<p role="status">در حال دریافت سهم باقی‌مانده مقصدها…</p>}{data?.requirements.map(r=><fieldset key={r.purchase_request_item_id} disabled={busy}><legend>{r.title} · مقدار این سفارش: {n(r.quantity)} {r.unit??'واحد ثبت نشده'}</legend>{r.destinations.length?r.destinations.map(d=><label className={s.field} key={d.destination_index}>سهم {d.city} برای {r.title}<input className={s.input} type="text" inputMode="numeric" value={values[`${r.purchase_request_item_id}:${d.destination_index}`]??''} disabled={d.available===0} onChange={e=>setValues(v=>({...v,[`${r.purchase_request_item_id}:${d.destination_index}`]:e.target.value}))}/><span className={s.hint}>حداکثر باقی‌مانده مصوب: {n(d.available)}</span></label>):<p>این درخواست مقصد تفکیک‌شده ندارد.</p>}</fieldset>)}{data&&!valid&&<Notice tone="warn">جمع سهم شهرها باید برابر مقدار هر قلم در همین پیشنهاد و در سقف باقی‌مانده مصوب باشد.</Notice>}</div></Drawer>;
}
