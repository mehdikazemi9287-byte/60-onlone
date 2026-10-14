"use client";

// Operations workbench: cross-organization queue for case managers/agents. Commercial state is derived
// from procurement records; ownership and coordination status come from the operations case.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowLeft, Inbox, Lock, Search, UserCheck } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { apiRequest, newIdempotencyKey } from "@/lib/api";
import { PLAN_STATUS, PO_STATUS, PR_STATUS, type CaseRow } from "@/lib/procurement/api";
import { daysUntil, formatJalali } from "@/lib/procurement/jalali";
import { Chip, Drawer, Empty, Notice, cx, n } from "@/components/procurement/ui";
import s from "@/components/procurement/proc.module.css";

export const OPS_STATUS: Record<string, string> = { none: "بدون پرونده عملیات", unassigned: "بدون مسئول", triage: "بررسی اولیه", sourcing: "در حال تأمین",
  waiting_customer: "منتظر مشتری", blocked: "متوقف", closed: "بسته" };
export const OPS_NEXT: Record<string, string[]> = { unassigned: [], triage: ["sourcing", "waiting_customer", "blocked", "closed"], sourcing: ["waiting_customer", "blocked", "closed"],
  waiting_customer: ["triage", "sourcing", "blocked", "closed"], blocked: ["triage", "sourcing", "waiting_customer", "closed"], closed: [] };
const STAGES: [string, string][] = [["", "همه اقدام‌ها"], ["blocked", "متوقف‌شده"], ["approve", "در انتظار تأیید"], ["create_rfq", "آماده استعلام"], ["compare", "مقایسه پیشنهاد"],
  ["create_order", "صدور سفارش"], ["payment_plan", "برنامه پرداخت"], ["finance_approval", "تأیید مالی"], ["fulfillment", "تحویل"], ["collection", "وصول"], ["settlement", "تسویه"], ["close", "آماده بستن"]];

type Ops = { case_id: number | null; status: string; assignee_user_id: number | null; assignee: string | null; version: number | null; updated_at: string | null };
type Row = CaseRow & { operations: Ops; capabilities: string[] };
type Scope = { id: number; display_name: string; capabilities: string[] };
type Staff = { id: number; full_name: string; capability: string };
type Queue = { items: Row[]; scopes: Scope[]; staff: Record<string, Staff[]> };
export type OpsAction = { kind: "create" | "assign" | "transition"; row: Row };

const age = (iso?: string) => (iso ? Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 86400000)) : null);

export default function OperationsWorkbench() {
  const { token, user, loading } = useAuth();
  const [q, setQ] = useState(""), [org, setOrg] = useState(""), [stage, setStage] = useState(""), [opsStatus, setOpsStatus] = useState(""), [assignee, setAssignee] = useState("");
  const [d, setD] = useState<Queue | null>(null), [error, setError] = useState(""), [flash, setFlash] = useState("");
  const [act, setAct] = useState<OpsAction | null>(null), [tick, setTick] = useState(0);
  const [queueSession, setQueueSession] = useState<string | null>(null);
  useEffect(() => { setAct(null); setFlash(""); setError(""); }, [token]);
  useEffect(() => {
    if (!token) return;
    const c = new AbortController();
    const t = setTimeout(() => {
      const qs = new URLSearchParams(Object.entries({ q, org, stage, ops_status: opsStatus, assignee }).filter(([, v]) => v)).toString();
      apiRequest<Queue>(`/internal/operations/queue${qs ? `?${qs}` : ""}`, { token, signal: c.signal }).then((r) => { if (!c.signal.aborted) { setD(r); setQueueSession(token); setError(""); } })
        .catch((e) => { if (!c.signal.aborted) setError(e.message); });
    }, 250);
    return () => { clearTimeout(t); c.abort(); };
  }, [token, q, org, stage, opsStatus, assignee, tick]);

  if (loading) return <div className={s.skeleton} style={{ height: 300 }} />;
  if (!user) return <Empty icon={<Lock />} title="ورود لازم است" action={<Link className={cx(s.btn, s.primary)} href="/login?next=/operations">ورود</Link>} />;
  if (error) return <Notice tone="bad" icon={<AlertTriangle />}>{error}</Notice>;
  if (!d || queueSession !== token) return <div className={s.skeleton} style={{ height: 300 }} />;
  if (!d.scopes.length && !org) return <Empty icon={<Lock />} title="مجوز عملیات داخلی ندارید">مجوز مدیر یا کارشناس پرونده را مدیر پلتفرم از بخش «دسترسی‌ها» اعطا می‌کند. عضویت مشتری این مجوز را ایجاد نمی‌کند.</Empty>;
  const unassigned = d.items.filter((r) => !r.operations.assignee_user_id).length;
  const blocked = d.items.filter((r) => r.blocked_reason || r.operations.status === "blocked").length;
  const mine = d.items.filter((r) => r.operations.assignee_user_id === user.id).length;
  return (
    <div className={s.root}>
      <header className={s.head}>
        <div className={s.eyebrow}>عملیات داخلی</div><h1 className={s.title}>میز کار عملیات</h1>
        <div className={s.meta}><span>{d.scopes.map((x) => x.display_name).join("، ")}</span><span>{n(d.items.length)} پرونده</span></div>
      </header>
      {flash && <Notice tone="info" icon={<UserCheck />}>{flash}</Notice>}
      <div className={s.kpis}>
        {[["در صف", d.items.length], ["بدون مسئول", unassigned], ["متوقف", blocked], ["واگذارشده به من", mine]].map(([k, v]) => (
          <div key={k} className={s.kpi}><small>{k}</small><strong className={s.num} style={{ fontSize: 22 }}>{n(v as number)}</strong></div>))}
      </div>
      <div className={s.card} style={{ margin: "14px 0" }}>
        <div className={s.grid4} style={{ gap: 10 }}>
          <label className={s.field}>جستجو<span style={{ position: "relative" }}><input className={s.input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="شماره یا عنوان" style={{ paddingLeft: 34 }} /><Search size={16} style={{ position: "absolute", left: 10, top: 11, color: "var(--muted)" }} /></span></label>
          <label className={s.field}>سازمان<select className={s.select} value={org} onChange={(e) => setOrg(e.target.value)}><option value="">همه سازمان‌های مجاز</option>{d.scopes.map((x) => <option key={x.id} value={x.id}>{x.display_name}</option>)}</select></label>
          <label className={s.field}>اقدام بعدی<select className={s.select} value={stage} onChange={(e) => setStage(e.target.value)}>{STAGES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className={s.field}>وضعیت عملیات<select className={s.select} value={opsStatus} onChange={(e) => setOpsStatus(e.target.value)}><option value="">همه</option>{Object.entries(OPS_STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className={s.field}>مسئول<select className={s.select} value={assignee} onChange={(e) => setAssignee(e.target.value)}><option value="">همه</option><option value="me">من</option><option value="none">بدون مسئول</option></select></label>
        </div>
      </div>
      {!d.items.length ? <Empty icon={<Inbox />} title="پرونده‌ای با این فیلترها نیست">فیلترها را تغییر دهید.</Empty> : (
        <div className={s.tableWrap}><table className={cx(s.table, s.cards)}>
          <thead><tr><th>پرونده</th><th>عملیات</th><th>اقدام بعدی</th><th>موعد / سن</th><th>سفارش · تحویل · پرداخت</th><th /></tr></thead>
          <tbody>{d.items.map((r) => {
            const due = daysUntil(r.needed_by_date), a = age(r.created_at), mgr = r.capabilities.includes("case_manager"), o = r.operations;
            return (
              <tr key={`${r.organization_id}-${r.id}`}>
                <td className={s.full}><b>{r.title}</b>
                  <div className={s.small} style={{ color: "var(--muted)" }}>{r.request_number} · {r.organization} · مشتری: {r.requester ?? "—"}{r.suppliers?.length ? ` · تأمین: ${r.suppliers.join("، ")}` : ""}</div>
                  <div className={s.row} style={{ marginTop: 4 }}><Chip tone="info" dot>{PR_STATUS[r.status] ?? r.status}</Chip>{r.blocked_reason && <Chip tone="bad">{r.blocked_reason}</Chip>}</div></td>
                <td data-label="عملیات"><Chip tone={o.status === "blocked" ? "bad" : o.status === "none" || o.status === "unassigned" ? "warn" : "ok"} dot>{OPS_STATUS[o.status]}</Chip>
                  <div className={s.small}>{o.assignee ?? "بدون مسئول"}</div></td>
                <td data-label="اقدام بعدی"><b className={s.small}>{r.next_action.label}</b>{r.next_action.owner && <div className={s.small} style={{ color: "var(--muted)" }}>{r.next_action.owner}</div>}</td>
                <td data-label="موعد">{r.needed_by_date ? formatJalali(r.needed_by_date) : "—"} {due != null && r.status !== "completed" && (due < 0 ? <Chip tone="bad">تأخیر</Chip> : due <= 3 ? <Chip tone="warn">نزدیک</Chip> : null)}
                  <div className={s.small} style={{ color: "var(--muted)" }}>سن: {a != null ? `${n(a)} روز` : "—"}</div></td>
                <td data-label="سفارش" className={s.small}>{r.order ? <>{r.order.po_number} · {PO_STATUS[r.order.status] ?? r.order.status}<br />تحویل {n(r.order.delivered)}/{n(r.order.destinations)} · {r.order.settled ? "تسویه شد" : r.order.payment ? PLAN_STATUS[r.order.payment] : "بدون برنامه پرداخت"}</> : `${n(r.rfqs)} استعلام · ${n(r.quotes)} پیشنهاد`}</td>
                <td><div className={s.row}>
                  {!o.case_id && mgr && <button className={cx(s.btn, s.sm, s.primary)} onClick={() => setAct({ kind: "create", row: r })}>ایجاد پرونده</button>}
                  {o.case_id && mgr && o.status !== "closed" && <button className={cx(s.btn, s.sm)} onClick={() => setAct({ kind: "assign", row: r })}>{o.assignee_user_id ? "واگذاری مجدد" : "واگذاری"}</button>}
                  {o.case_id && o.assignee_user_id && OPS_NEXT[o.status]?.length > 0 && (mgr || o.assignee_user_id === user.id) && <button className={cx(s.btn, s.sm)} onClick={() => setAct({ kind: "transition", row: r })}>تغییر وضعیت</button>}
                  <Link className={cx(s.btn, s.sm)} href={`/operations/cases/${r.organization_id}/${r.id}`}>باز کردن <ArrowLeft /></Link>
                </div></td>
              </tr>);
          })}</tbody>
        </table></div>
      )}
      {act && token && <OpsActionDrawer act={act} token={token} staff={d.staff[String(act.row.organization_id)] ?? []} onClose={() => setAct(null)}
        onDone={(m) => { setAct(null); setFlash(m); setTick((x) => x + 1); }} />}
    </div>
  );
}

export function OpsActionDrawer({ act, token, staff, onClose, onDone }: { act: OpsAction; token: string; staff: Staff[]; onClose: () => void; onDone: (m: string) => void }) {
  const o = act.row.operations, base = `/internal/organizations/${act.row.organization_id}/cases`;
  const [reason, setReason] = useState(""), [who, setWho] = useState(""), [to, setTo] = useState(""), [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const [key] = useState(newIdempotencyKey);
  const people = Array.from(new Map(staff.map((x) => [x.id, x])).values());
  const send = useCallback(async () => {
    setBusy(true); setErr("");
    const [path, body] = act.kind === "create" ? [base, { purchase_request_id: act.row.id, reason }]
      : act.kind === "assign" ? [`${base}/${o.case_id}/assign`, { assignee_user_id: Number(who), expected_version: o.version, reason }]
        : [`${base}/${o.case_id}/transition`, { status: to, expected_version: o.version, reason }];
    try {
      await apiRequest(path, { token, method: "POST", body: JSON.stringify(body), headers: { "Idempotency-Key": key } });
      onDone(act.kind === "create" ? "پرونده عملیات ایجاد شد." : act.kind === "assign" ? "مسئول پرونده ثبت شد." : "وضعیت پرونده تغییر کرد.");
    } catch (e) { setErr(e instanceof Error ? e.message : "ثبت ناموفق بود"); } finally { setBusy(false); }
  }, [act, base, o, who, to, reason, token, key, onDone]);
  const ready = reason.trim() && (act.kind === "create" || (act.kind === "assign" ? who : to));
  return (
    <Drawer open title={`${act.kind === "create" ? "ایجاد پرونده" : act.kind === "assign" ? "واگذاری" : "تغییر وضعیت"} · ${act.row.request_number}`} onClose={onClose}
      footer={<button className={cx(s.btn, s.primary)} disabled={busy || !ready} onClick={send}>{busy ? "در حال ثبت…" : "ثبت"}</button>}>
      <div className={s.stack}>
        {act.kind === "assign" && <label className={s.field}>مسئول<select className={s.select} value={who} onChange={(e) => setWho(e.target.value)}><option value="">انتخاب کنید</option>
          {people.map((p) => <option key={p.id} value={p.id} disabled={p.id === o.assignee_user_id}>{p.full_name}</option>)}</select></label>}
        {act.kind === "transition" && <label className={s.field}>وضعیت جدید<select className={s.select} value={to} onChange={(e) => setTo(e.target.value)}><option value="">انتخاب کنید</option>
          {(OPS_NEXT[o.status] ?? []).map((x) => <option key={x} value={x}>{OPS_STATUS[x]}</option>)}</select></label>}
        {to === "closed" && <Notice icon={<AlertTriangle />}>بستن پرونده عملیات فقط هماهنگی داخلی را می‌بندد؛ وضعیت خرید، پرداخت و تحویل از سوابق اصلی خوانده می‌شود.</Notice>}
        <label className={s.field}>دلیل (الزامی، در تاریخچه ثبت می‌شود)<textarea className={s.textarea} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        {err && <Notice tone="bad" icon={<AlertTriangle />}>{err}</Notice>}
      </div>
    </Drawer>
  );
}
