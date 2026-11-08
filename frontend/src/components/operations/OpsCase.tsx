"use client";

// Read-only case view for operations staff, plus ownership/coordination actions and history.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowRight, History, Lock, Truck, Wallet } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { apiRequest } from "@/lib/api";
import { DELIVERY_STATUS, EVENT_LABEL, PLAN_STATUS, PO_STATUS, PR_STATUS, RFQ_STATUS, SUPPLIER_STATE, money, type CaseRow, type Workspace } from "@/lib/procurement/api";
import { formatJalali, formatJalaliDateTime } from "@/lib/procurement/jalali";
import { Chip, Empty, Notice, cx, n } from "@/components/procurement/ui";
import s from "@/components/procurement/proc.module.css";
import { OPS_NEXT, OPS_STATUS, OpsActionDrawer, type OpsAction } from "./OperationsWorkbench";

type OpsWs = Workspace & { operations: { capabilities: string[]; case: { id: number; status: string; assignee_user_id: number | null; version: number } | null } };
type Row = CaseRow & { operations: { case_id: number | null; status: string; assignee_user_id: number | null; assignee: string | null; version: number | null; updated_at: string | null }; capabilities: string[] };
type Ev = { id: number; action: string; reason: string; created_at: string; actor_user_id: number; after_json: string };
const ACT_FA: Record<string, string> = { create: "ایجاد پرونده", assign: "واگذاری", transition: "تغییر وضعیت" };

export default function OpsCase({ org, pr }: { org: string; pr: string }) {
  const { token, user, loading } = useAuth();
  const [ws, setWs] = useState<OpsWs | null>(null), [row, setRow] = useState<Row | null>(null), [staff, setStaff] = useState<{ id: number; full_name: string; capability: string }[]>([]);
  const [events, setEvents] = useState<Ev[]>([]), [error, setError] = useState(""), [act, setAct] = useState<OpsAction | null>(null), [flash, setFlash] = useState("");
  const load = useCallback(async () => {
    if (!token) return;
    try {
      const w = await apiRequest<OpsWs>(`/internal/organizations/${org}/requests/${pr}/workspace`, { token });
      setWs(w);
      const q = await apiRequest<{ items: Row[]; staff: Record<string, typeof staff> }>(`/internal/operations/queue?org=${org}&q=${encodeURIComponent(w.request.request_number)}`, { token });
      setRow(q.items.find((x) => String(x.id) === pr) ?? null); setStaff(q.staff[org] ?? []);
      if (w.operations.case) {
        const c = await apiRequest<{ case: { events: Ev[] } }>(`/internal/organizations/${org}/cases/${w.operations.case.id}`, { token });
        setEvents(c.case.events);
      }
      setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "دریافت پرونده ناموفق بود"); }
  }, [token, org, pr]);
  useEffect(() => { void load(); }, [load]);

  if (loading) return <div className={s.skeleton} style={{ height: 300 }} />;
  if (!user) return <Empty icon={<Lock />} title="ورود لازم است" />;
  if (error) return <div className={s.root}><Notice tone="bad" icon={<AlertTriangle />}>{error}</Notice><Link className={s.btn} href="/operations"><ArrowRight /> بازگشت به صف</Link></div>;
  if (!ws) return <div className={s.skeleton} style={{ height: 300 }} />;
  const r = ws.request, oc = row?.operations, mgr = ws.operations.capabilities.includes("case_manager"), cur = ws.organization.currency;
  const names: Record<number, string> = Object.fromEntries(staff.map((x) => [x.id, x.full_name]));
  return (
    <div className={s.root}>
      <Link className={cx(s.btn, s.sm, s.ghost)} href="/operations"><ArrowRight /> صف عملیات</Link>
      <header className={s.head}>
        <div className={s.eyebrow}>{ws.organization.name} · {r.request_number}</div>
        <h1 className={s.title}>{r.title}</h1>
        <div className={s.meta}><Chip tone="info" dot>{PR_STATUS[r.status] ?? r.status}</Chip><span>مشتری/درخواست‌دهنده: {ws.requester ?? "—"}</span>
          {r.needed_by_date && <span>موعد: {formatJalali(r.needed_by_date)}</span>}<span>ایجاد: {formatJalali(r.created_at)}</span></div>
      </header>
      {flash && <Notice tone="info" icon={<History />}>{flash}</Notice>}
      <div className={s.grid2} style={{ alignItems: "start" }}>
        <section className={s.card}>
          <div className={s.sectionHead}><div><h2>هماهنگی عملیات</h2><p>مالکیت و وضعیت داخلی؛ وضعیت خرید از سوابق اصلی است.</p></div></div>
          <div className={s.row}><Chip tone={oc?.status === "blocked" ? "bad" : "info"} dot>{OPS_STATUS[oc?.status ?? "none"]}</Chip><span>مسئول: <b>{oc?.assignee ?? "—"}</b></span></div>
          <p className={s.small} style={{ marginTop: 8 }}>اقدام بعدی: <b>{ws.next_action.label}</b>{ws.next_action.owner ? ` · ${ws.next_action.owner}` : ""}</p>
          {row?.blocked_reason && <Notice tone="bad" icon={<AlertTriangle />}>{row.blocked_reason}</Notice>}
          {row && <div className={s.row} style={{ marginTop: 10 }}>
            {!oc?.case_id && mgr && <button className={cx(s.btn, s.sm, s.primary)} onClick={() => setAct({ kind: "create", row })}>ایجاد پرونده</button>}
            {oc?.case_id && mgr && oc.status !== "closed" && <button className={cx(s.btn, s.sm)} onClick={() => setAct({ kind: "assign", row })}>{oc.assignee_user_id ? "واگذاری مجدد" : "واگذاری"}</button>}
            {oc?.case_id && oc.assignee_user_id && OPS_NEXT[oc.status]?.length > 0 && (mgr || oc.assignee_user_id === user.id) &&
              <button className={cx(s.btn, s.sm)} onClick={() => setAct({ kind: "transition", row })}>تغییر وضعیت</button>}
          </div>}
          <h3 className={s.small} style={{ margin: "14px 0 6px" }}><History size={14} /> تاریخچه عملیات</h3>
          {!events.length ? <p className={s.small} style={{ color: "var(--muted)" }}>هنوز رویدادی ثبت نشده است.</p> : <div className={s.timeline}>{events.map((e) => {
            const after = JSON.parse(e.after_json || "{}");
            return <div key={e.id} className={s.tItem}><span className={s.tDot} /><div><b>{ACT_FA[e.action]}</b> · {OPS_STATUS[after.status] ?? ""}{after.assignee_user_id ? ` → ${names[after.assignee_user_id] ?? `#${after.assignee_user_id}`}` : ""}
              <span className={s.muted}> · {names[e.actor_user_id] ?? `#${e.actor_user_id}`}</span><div className={s.small}>{e.reason}</div></div><time>{formatJalaliDateTime(e.created_at)}</time></div>;
          })}</div>}
        </section>
        <section className={s.card}>
          <div className={s.sectionHead}><div><h2>اقلام درخواست</h2></div></div>
          <ul className={s.small} style={{ margin: 0, paddingInlineStart: 18 }}>{ws.items.map((it, i) => <li key={i}>{(it as { free_text_description?: string; name?: string }).free_text_description ?? (it as { name?: string }).name ?? "کالا"} · {n((it as { quantity: number }).quantity)}</li>)}</ul>
          <h3 className={s.small} style={{ margin: "14px 0 6px" }}>استعلام و پیشنهادها</h3>
          {!ws.rfqs.length ? <p className={s.small} style={{ color: "var(--muted)" }}>استعلامی ایجاد نشده است.</p> : ws.rfqs.map((x) => (
            <div key={x.id} className={s.small} style={{ marginBottom: 8 }}><b>{x.rfq_number}</b> · {RFQ_STATUS[x.status] ?? x.status}
              <div>{x.suppliers.map((sp) => `${sp.name}: ${sp.quote ? `${money(sp.quote.grand_total_minor, cur)} (${sp.quote.status === "awarded" ? "انتخاب شد" : sp.quote.status})` : SUPPLIER_STATE[sp.state] ?? sp.state}`).join(" · ")}</div></div>))}
        </section>
      </div>
      <section className={s.card} style={{ marginTop: 14 }}>
        <div className={s.sectionHead}><div><h2><Truck /> سفارش، تحویل و پرداخت</h2></div></div>
        {!ws.orders.length ? <p className={s.small} style={{ color: "var(--muted)" }}>سفارش خریدی صادر نشده است.</p> : ws.orders.map((o) => (
          <div key={o.id} className={s.stack} style={{ gap: 6 }}>
            <div className={s.row}><b>{o.po_number}</b><Chip tone="info" dot>{PO_STATUS[o.status] ?? o.status}</Chip><span className={s.small}>{o.supplier} · {money(o.grand_total_minor, cur)}</span></div>
            <div className={s.row}>{o.deliveries.map((dv) => <Chip key={dv.destination_index} tone={dv.status === "delivered" ? "ok" : "muted"}>{dv.label ?? dv.city}: {DELIVERY_STATUS[dv.status ?? ""] ?? dv.status ?? "—"}{dv.tracking_reference ? ` · ${dv.tracking_reference}` : ""}</Chip>)}</div>
            <div className={s.small}><Wallet size={14} /> {o.finance.plan ? `${PLAN_STATUS[o.finance.plan.status]} · وصول ${money(o.finance.collected_minor, cur)}` : o.finance.policy ? "برنامه پرداخت ثبت نشده" : "سیاست پرداخت تصویب نشده"}
              {o.finance.plan?.environment === "test" && <Chip tone="violet">TEST</Chip>}{o.finance.settlement ? ` · تسویه ${o.finance.settlement.reference}` : ""}</div>
          </div>))}
      </section>
      <section className={s.card} style={{ marginTop: 14 }}>
        <div className={s.sectionHead}><div><h2><History /> تاریخچه پرونده</h2><p>از سوابق درخواست، استعلام، سفارش و مالی</p></div></div>
        <div className={s.timeline}>{ws.timeline.slice().reverse().map((e, i) => <div key={i} className={s.tItem}><span className={s.tDot} /><div><b>{EVENT_LABEL[e.type] ?? e.type}</b>{e.actor && <span className={s.muted}> · {e.actor}</span>}</div><time>{formatJalaliDateTime(e.at)}</time></div>)}</div>
      </section>
      {act && token && <OpsActionDrawer act={act} token={token} staff={staff} onClose={() => setAct(null)} onDone={(m) => { setAct(null); setFlash(m); void load(); }} />}
    </div>
  );
}
