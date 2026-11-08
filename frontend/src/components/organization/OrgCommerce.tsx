"use client";

// Organization panel — phase 3–4: org orders (invoice/cancel), monthly statement, credit contract & weekly
// statements, welfare plans, preferred sellers and approval rules. Server enforces roles; UI hides what a role can't do.
import { useEffect, useState, type ReactNode } from "react";
import { useAuth } from "@/lib/auth-context";
import { ApiError, newIdempotencyKey } from "@/lib/api";
import { latinDigits } from "@/lib/shops";
import { formatPrice, faDate } from "@/lib/utils";
import {
  apiRequest, errText, FINANCE_ROLES, ORDER_STATUS_FA,
  downloadAuthed, type ApprovalRule, type CreditContract, type CreditStatement, type OrgInvoice, type OrgOrderRow, type PreferredSeller, type WelfarePlan,
} from "@/lib/commerce";
import { useOrganization, OrgSelector } from "./Dashboard";
import { Card, Flash, ListState, btnCls, btnGhost, inputCls, n } from "@/components/commerce/ui";

type OrgState = ReturnType<typeof useOrganization>;
type Ctx = { token: string; orgId: string; role: string };
type Msg = { ok: boolean; text: string } | null;

/** Toman input → IRR minor; null when empty/invalid. */
const tomanToMinor = (v: string) => { const t = parseInt(latinDigits(v).replace(/[^\d]/g, ""), 10); return Number.isFinite(t) ? t * 10 : null; };
const numIn = (v: string) => latinDigits(v).replace(/[^\d]/g, "");

/** Shared shell: org selector + guard; children render only with an active org. */
function OrgScope({ children }: { children: (c: Ctx) => ReactNode }) {
  const { user } = useAuth();
  return <Inner key={user?.id ?? "guest"}>{children}</Inner>;
}
function Inner({ children }: { children: (c: Ctx) => ReactNode }) {
  const o: OrgState = useOrganization();
  return (
    <div dir="rtl" className="space-y-4">
      <OrgSelector state={o} />
      {o.token && o.selected && o.org && <div key={o.selected} className="space-y-4">{children({ token: o.token, orgId: o.selected, role: o.org.membership.role })}</div>}
    </div>
  );
}

/** Fetch helper with cancel + 404→empty semantics. */
function useLoad<T>(path: string | null, token: string, retry: number, pick: (r: never) => T): [T | null, string | null] {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!path) return;
    const c = new AbortController();
    setData(null); setError(null);
    apiRequest<never>(path, { token, signal: c.signal })
      .then((r) => { if (!c.signal.aborted) setData(pick(r)); })
      .catch((e) => { if (!c.signal.aborted) setError(errText(e, "بارگذاری ناموفق بود")); });
    return () => c.abort();
    // pick is a stable inline selector per call site
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, token, retry]);
  return [data, error];
}

function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-right text-sm">
        <thead className="text-xs text-neutral-500"><tr>{head.map((h) => <th key={h} scope="col" className="p-2 font-bold">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-neutral-100">{children}</tbody>
      </table>
    </div>
  );
}

// ── Orders ──────────────────────────────────────────────────────────────────
export function OrgOrders() { return <OrgScope>{(c) => <OrdersBody {...c} />}</OrgScope>; }
function OrdersBody({ token, orgId }: Ctx) {
  const [retry, setRetry] = useState(0);
  const [rows, error] = useLoad<OrgOrderRow[]>(`/orgs/${orgId}/orders`, token, retry, (r: { items: OrgOrderRow[] }) => r.items);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Card title="سفارش‌های سازمان">
      <ListState items={rows} error={error} empty="هنوز سفارش سازمانی ثبت نشده است." onRetry={() => setRetry((x) => x + 1)} />
      {rows && rows.length > 0 && (
        <ul className="divide-y divide-neutral-100">
          {rows.map((r) => (
            <li key={r.id} className="py-2">
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="min-w-0"><span dir="ltr" className="font-bold">{r.order_number}</span>
                  <span className="block text-xs text-neutral-500">{faDate(r.placed_at)} · {ORDER_STATUS_FA[r.status] ?? r.status}{r.po_reference ? ` · PO ${r.po_reference}` : ""}</span></span>
                <span className="flex items-center gap-2"><b>{formatPrice(r.total_minor)}</b>
                  <button type="button" className={btnGhost} aria-expanded={open === r.id} onClick={() => setOpen(open === r.id ? null : r.id)}>{open === r.id ? "بستن" : "فاکتور"}</button></span>
              </div>
              {open === r.id && <OrderInvoice token={token} orgId={orgId} row={r} onCancelled={() => { setOpen(null); setRetry((x) => x + 1); }} />}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function OrderInvoice({ token, orgId, row, onCancelled }: { token: string; orgId: string; row: OrgOrderRow; onCancelled: () => void }) {
  const [inv, error] = useLoad<OrgInvoice>(`/orgs/${orgId}/orders/${row.id}/invoice`, token, 0, (r: { invoice: OrgInvoice }) => r.invoice);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  const cancellable = ["pending", "paid"].includes(row.status);
  const cancel = async () => {
    if (!window.confirm(`سفارش ${row.order_number} لغو شود؟`)) return;
    setBusy(true); setMsg(null);
    try {
      await apiRequest(`/orgs/${orgId}/orders/${row.id}/cancel`, { token, method: "POST", body: JSON.stringify({ reason: reason.trim() || undefined }) });
      onCancelled();
    } catch (e) { setMsg({ ok: false, text: errText(e, "لغو سفارش ناموفق بود") }); } finally { setBusy(false); }
  };
  if (error) return <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>;
  if (!inv) return <p role="status" className="mt-2 text-sm text-neutral-400">در حال دریافت فاکتور…</p>;
  return (
    <div className="mt-2 space-y-2 rounded-xl bg-neutral-50 p-3 text-sm">
      <p className="text-xs text-neutral-600">فاکتور <span dir="ltr">{inv.invoice_number}</span> · {inv.buyer.legal_name ?? inv.buyer.display_name}
        {inv.buyer.national_id ? ` · شناسهٔ ملی ${inv.buyer.national_id}` : ""}{inv.purchase_request_number ? ` · درخواست ${inv.purchase_request_number}` : ""}</p>
      <ul className="space-y-1">
        {inv.lines.map((l) => <li key={l.id} className="flex justify-between gap-2"><span className="min-w-0 truncate">{l.title_fa} × {n(l.quantity)}</span><span>{formatPrice(l.line_total_minor)}</span></li>)}
      </ul>
      <dl className="grid grid-cols-2 gap-1 border-t border-neutral-200 pt-2 text-xs">
        <dt>جمع کالا</dt><dd className="text-left">{formatPrice(inv.subtotal_minor)}</dd>
        <dt>ارسال</dt><dd className="text-left">{formatPrice(inv.shipping_fee_minor)}</dd>
        <dt>مالیات بر ارزش افزوده</dt><dd className="text-left">{formatPrice(inv.tax_minor)}</dd>
        <dt className="font-black">مبلغ کل</dt><dd className="text-left font-black">{formatPrice(inv.total_minor)}</dd>
        {inv.credit_minor > 0 && <><dt>از اعتبار</dt><dd className="text-left">{formatPrice(inv.credit_minor)}</dd></>}
      </dl>
      <button type="button" className={btnGhost} onClick={() => window.print()}>چاپ فاکتور</button>
      {cancellable && (
        <div className="space-y-2 border-t border-neutral-200 pt-2">
          <label className="block text-xs font-bold">دلیل لغو <span className="font-normal text-neutral-500">(اختیاری)</span>
            <input className={inputCls} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
          <button type="button" className={`${btnGhost} text-red-700`} disabled={busy} onClick={cancel}>{busy ? "در حال لغو…" : "لغو سفارش"}</button>
        </div>
      )}
      <Flash msg={msg} />
    </div>
  );
}

// ── Monthly statement ───────────────────────────────────────────────────────
type Statement = { month: string; orders: (OrgOrderRow & { tax_minor: number })[];
  totals: { orders_count: number; subtotal_minor: number; tax_minor: number; total_minor: number; credit_minor: number; cash_outstanding_minor: number } };
export function OrgStatement() { return <OrgScope>{(c) => <StatementBody {...c} />}</OrgScope>; }
function StatementBody({ token, orgId }: Ctx) {
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [retry, setRetry] = useState(0);
  const valid = /^\d{4}-\d{2}$/.test(month);
  const [st, error] = useLoad<Statement>(valid ? `/orgs/${orgId}/statement?month=${month}` : null, token, retry, (r: Statement) => r);
  return (
    <Card title="صورت‌حساب ماهانه" action={
      <label className="text-xs font-bold">ماه<input type="month" dir="ltr" className={`${inputCls} w-40`} value={month} onChange={(e) => setMonth(e.target.value)} /></label>}>
      <ListState items={st ? st.orders : null} error={error} empty="در این ماه سفارشی ثبت نشده است." onRetry={() => setRetry((x) => x + 1)} />
      {st && (
        <>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[["تعداد سفارش", n(st.totals.orders_count)], ["مبلغ کل", formatPrice(st.totals.total_minor)], ["مالیات", formatPrice(st.totals.tax_minor)],
              ["نقدی معوق", formatPrice(st.totals.cash_outstanding_minor)]].map(([k, v]) => (
              <div key={k} className="rounded-xl border border-neutral-200 p-3"><dt className="text-xs text-neutral-500">{k}</dt><dd className="font-black">{v}</dd></div>))}
          </dl>
          {st.orders.length > 0 && (
            <Table head={["سفارش", "تاریخ", "وضعیت", "مبلغ"]}>
              {st.orders.map((o) => <tr key={o.id}><td className="p-2" dir="ltr">{o.order_number}</td><td className="p-2">{faDate(o.placed_at)}</td>
                <td className="p-2">{ORDER_STATUS_FA[o.status] ?? o.status}</td><td className="p-2">{formatPrice(o.total_minor)}</td></tr>)}
            </Table>
          )}
        </>
      )}
    </Card>
  );
}

// ── Credit contract + weekly statements ─────────────────────────────────────
const CONTRACT_FA: Record<string, string> = { active: "فعال", frozen: "مسدود", closed: "بسته" };
const STMT_FA: Record<string, string> = { open: "باز", paid: "پرداخت‌شده", overdue: "سررسید گذشته" };
export function OrgCredit() { return <OrgScope>{(c) => <CreditBody {...c} />}</OrgScope>; }
function CreditBody({ token, orgId }: Ctx) {
  const [retry, setRetry] = useState(0);
  const [contract, cErr] = useLoad<{ c: CreditContract | null }>(`/orgs/${orgId}/credit-contract`, token, retry, (r: { contract: CreditContract | null }) => ({ c: r.contract }));
  const [stmts, sErr] = useLoad<CreditStatement[]>(`/orgs/${orgId}/statements`, token, retry, (r: { statements: CreditStatement[] }) => r.statements);
  const c = contract?.c;
  return (
    <>
      <Card title="قرارداد اعتباری">
        {cErr ? <ListState items={null} error={cErr} empty="" onRetry={() => setRetry((x) => x + 1)} />
          : !contract ? <ListState items={null} error={null} empty="" />
          : !c ? <p className="rounded-xl bg-neutral-50 p-4 text-center text-sm text-neutral-500">قرارداد اعتباری فعالی برای این سازمان ثبت نشده است.</p>
          : (
            <>
              {c.status === "frozen" && <p role="alert" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">اعتبار مسدود است{c.freeze_reason === "overdue" ? "؛ صورت‌حساب سررسیدگذشته دارید." : "."}</p>}
              <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[["سقف اعتبار", formatPrice(c.limit_minor)], ["مصرف‌شده", formatPrice(c.outstanding_minor)], ["باقی‌مانده", formatPrice(c.headroom_minor)],
                  ["وضعیت", CONTRACT_FA[c.status] ?? c.status]].map(([k, v]) => (
                  <div key={k} className="rounded-xl border border-neutral-200 p-3"><dt className="text-xs text-neutral-500">{k}</dt><dd className="font-black">{v}</dd></div>))}
              </dl>
              {c.ramp_enabled && c.ramp_pct !== undefined && c.ramp_pct < 100 && (
                <p className="rounded-xl bg-primary-50 p-3 text-sm text-primary-800">سقف پلکانی: الان {n(c.ramp_pct)}٪ سقف قرارداد ({formatPrice(c.effective_limit_minor ?? 0)}) قابل استفاده است. هر دو صورت‌حساب که به‌موقع پرداخت شود یک پله بالا می‌رود؛ دیرکرد آن را به پلهٔ اول برمی‌گرداند.</p>)}
              <p className="text-xs text-neutral-500">قرارداد <span dir="ltr">{c.contract_number ?? c.reference}</span>{c.funder_name ? ` · تأمین‌کننده: ${c.funder_name}` : ""} · صورت‌حساب هفتگی، مهلت پرداخت {n(c.due_days)} روز</p>
            </>
          )}
      </Card>
      <OrgReports token={token} orgId={orgId} />
      <Card title="صورت‌حساب‌های هفتگی">
        <ListState items={stmts} error={sErr} empty="هنوز صورت‌حسابی صادر نشده است." onRetry={() => setRetry((x) => x + 1)} />
        {stmts && stmts.length > 0 && (
          <Table head={["دوره", "مصرف", "پرداخت", "مانده", "سررسید", "وضعیت"]}>
            {stmts.map((s) => (
              <tr key={s.id}><td className="p-2">{faDate(s.period_start)} تا {faDate(s.period_end)}</td><td className="p-2">{formatPrice(s.usage_minor)}</td>
                <td className="p-2">{formatPrice(s.payments_minor)}</td><td className="p-2 font-bold">{formatPrice(s.closing_minor)}</td><td className="p-2">{faDate(s.due_at)}</td>
                <td className={`p-2 ${s.status === "overdue" ? "font-bold text-red-700" : ""}`}>{STMT_FA[s.status] ?? s.status}</td></tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}

function OrgReports({ token, orgId }: { token: string; orgId: string }) {
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const [from, setFrom] = useState(() => iso(new Date(Date.now() - 30 * 864e5)));
  const [to, setTo] = useState(() => iso(new Date()));
  const [err, setErr] = useState<string | null>(null);
  const get = async (kind: "payroll" | "spend") => {
    setErr(null);
    try { await downloadAuthed(`/orgs/${orgId}/reports/${kind}.csv?from=${from}&to=${to}`, token, `${kind}-${from}.csv`); }
    catch (e) { setErr(errText(e)); }
  };
  return (
    <Card title="گزارش برای مالی و منابع انسانی">
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <label>از <input type="date" dir="ltr" className={inputCls} value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label>تا <input type="date" dir="ltr" className={inputCls} value={to} onChange={(e) => setTo(e.target.value)} /></label>
        <button className={btnCls} onClick={() => get("spend")}>خرید سازمان (CSV)</button>
        <button className={btnGhost} onClick={() => get("payroll")}>مصرف اعتبار هر کارمند (CSV)</button>
      </div>
      <p className="text-xs text-neutral-500">فایل مصرف اعتبار برای منابع انسانی است؛ کسر آن از حقوق فقط طبق توافق کتبی سازمان با کارمند انجام شود. بودجهٔ رفاهی در آن نمی‌آید.</p>
      {err && <p role="alert" className="text-sm text-red-700">{err}</p>}
    </Card>
  );
}

// ── Welfare plans ───────────────────────────────────────────────────────────
const PLAN_FA: Record<string, string> = { free: "آزاد", category: "دسته‌های مشخص", product: "کالاهای مشخص" };
export function OrgWelfare() { return <OrgScope>{(c) => <WelfareBody {...c} />}</OrgScope>; }
function WelfareBody({ token, orgId, role }: Ctx) {
  const finance = FINANCE_ROLES.includes(role);
  const [retry, setRetry] = useState(0);
  const [plans, error] = useLoad<WelfarePlan[]>(finance ? `/orgs/${orgId}/welfare-plans` : null, token, retry, (r: { plans: WelfarePlan[] }) => r.plans);
  const [msg, setMsg] = useState<Msg>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [memberFor, setMemberFor] = useState<number | null>(null);
  if (!finance) return <p className="rounded-xl bg-amber-50 p-4 text-sm text-amber-800">طرح‌های رفاهی فقط برای مدیر و مالی سازمان است.</p>;
  const close = async (p: WelfarePlan) => {
    if (!window.confirm(`طرح «${p.title}» بسته شود؟ بعد از بستن، کارکنان نمی‌توانند از آن خرید کنند.`)) return;
    setBusy(p.id); setMsg(null);
    try { await apiRequest(`/orgs/${orgId}/welfare-plans/${p.id}/close`, { token, method: "POST" }); setMsg({ ok: true, text: "طرح بسته شد." }); setRetry((x) => x + 1); }
    catch (e) { setMsg({ ok: false, text: errText(e) }); } finally { setBusy(null); }
  };
  return (
    <>
      <Flash msg={msg} />
      <NewWelfarePlan token={token} orgId={orgId} onDone={() => { setMsg({ ok: true, text: "طرح ساخته شد." }); setRetry((x) => x + 1); }} />
      <Card title="طرح‌های رفاهی">
        <ListState items={plans} error={error} empty="هنوز طرحی ساخته نشده است." onRetry={() => setRetry((x) => x + 1)} />
        <ul className="space-y-2">
          {plans?.map((p) => (
            <li key={p.id} className="rounded-xl border border-neutral-200 p-3 text-sm">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <span className="min-w-0"><b>{p.title}</b>
                  <span className="block text-xs text-neutral-500">{PLAN_FA[p.plan_type]} · سقف هر نفر {formatPrice(p.per_employee_cap_minor)} · تا {faDate(p.expires_at)}
                    {p.all_members ? " · همهٔ کارکنان" : ""} · {p.status === "active" ? "فعال" : "بسته"}</span></span>
                {p.status === "active" && (
                  <span className="flex gap-2">
                    {!p.all_members && <button type="button" className={btnGhost} aria-expanded={memberFor === p.id} onClick={() => setMemberFor(memberFor === p.id ? null : p.id)}>افزودن عضو</button>}
                    <button type="button" className={`${btnGhost} text-red-700`} disabled={busy === p.id} onClick={() => close(p)}>بستن طرح</button>
                  </span>
                )}
              </div>
              {memberFor === p.id && <AddMember token={token} orgId={orgId} planId={p.id} onDone={(t) => { setMsg(t); if (t.ok) setMemberFor(null); }} />}
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}

type Member = { id: number; full_name: string; status: string };
function AddMember({ token, orgId, planId, onDone }: { token: string; orgId: string; planId: number; onDone: (m: { ok: boolean; text: string }) => void }) {
  const [members, error] = useLoad<Member[]>(`/organizations/${orgId}/members`, token, 0, (r: { items: Member[] }) => r.items.filter((m) => m.status === "active"));
  const [mid, setMid] = useState("");
  const [cap, setCap] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); if (!mid) return;
    setBusy(true);
    try {
      const capMinor = tomanToMinor(cap);
      await apiRequest(`/orgs/${orgId}/welfare-plans/${planId}/members`, { token, method: "POST",
        body: JSON.stringify({ membership_id: Number(mid), ...(capMinor ? { cap_minor: capMinor } : {}) }) });
      onDone({ ok: true, text: "عضو به طرح اضافه شد." }); setMid(""); setCap("");
    } catch (e2) { onDone({ ok: false, text: errText(e2) }); } finally { setBusy(false); }
  };
  if (error) return <p role="alert" className="mt-2 text-xs text-red-700">{error}</p>;
  return (
    <form onSubmit={submit} className="mt-2 grid gap-2 sm:grid-cols-[1fr_10rem_auto] sm:items-end">
      <label className="text-xs font-bold">کارمند
        <select className={inputCls} required value={mid} onChange={(e) => setMid(e.target.value)} disabled={!members}>
          <option value="">{members ? "انتخاب کنید" : "در حال بارگذاری…"}</option>
          {members?.map((m) => <option key={m.id} value={m.id}>{m.full_name}</option>)}
        </select></label>
      <label className="text-xs font-bold">سقف ویژه (تومان، اختیاری)
        <input className={inputCls} inputMode="numeric" dir="ltr" value={cap} onChange={(e) => setCap(numIn(e.target.value))} /></label>
      <button type="submit" className={btnCls} disabled={busy || !mid}>افزودن</button>
    </form>
  );
}

function NewWelfarePlan({ token, orgId, onDone }: { token: string; orgId: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ title: "", plan_type: "free", cap: "", expires: "", cats: "", all: true });
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cap = tomanToMinor(f.cap);
    if (!cap) { setErr("سقف هر نفر را وارد کن."); return; }
    setBusy(true); setErr(null);
    try {
      await apiRequest(`/orgs/${orgId}/welfare-plans`, { token, method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify({
        title: f.title.trim(), plan_type: f.plan_type, per_employee_cap_minor: cap, expires_at: `${f.expires} 23:59:59`, all_members: f.all,
        ...(f.plan_type === "category" ? { category_slugs: f.cats.split(/[,،\s]+/).filter(Boolean) } : {}) }) });
      setKey(newIdempotencyKey()); setOpen(false); setF({ title: "", plan_type: "free", cap: "", expires: "", cats: "", all: true }); onDone();
    } catch (e2) { setErr(errText(e2, "ساخت طرح ناموفق بود")); } finally { setBusy(false); }
  };
  if (!open) return <button type="button" className={btnCls} onClick={() => setOpen(true)}>طرح رفاهی جدید</button>;
  return (
    <form onSubmit={submit} className="space-y-3 rounded-2xl border border-neutral-200 bg-white p-4">
      <h2 className="text-base font-black">طرح رفاهی جدید</h2>
      <label className="block text-sm font-bold">عنوان<input className={inputCls} required maxLength={120} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block text-sm font-bold">نوع
          <select className={inputCls} value={f.plan_type} onChange={(e) => setF({ ...f, plan_type: e.target.value })}>
            <option value="free">آزاد (هر کالا)</option><option value="category">دسته‌های مشخص</option>
          </select></label>
        <label className="block text-sm font-bold">سقف هر نفر (تومان)
          <input className={inputCls} required inputMode="numeric" dir="ltr" value={f.cap} onChange={(e) => setF({ ...f, cap: numIn(e.target.value) })} /></label>
        <label className="block text-sm font-bold">پایان طرح
          <input className={inputCls} required type="date" dir="ltr" value={f.expires} onChange={(e) => setF({ ...f, expires: e.target.value })} /></label>
      </div>
      {f.plan_type === "category" && (
        <label className="block text-sm font-bold">نامک دسته‌ها<input className={inputCls} required dir="ltr" value={f.cats} onChange={(e) => setF({ ...f, cats: e.target.value })} placeholder="supermarket, stationery" />
          <span className="mt-1 block text-xs font-normal text-neutral-500">با ویرگول جدا کن</span></label>
      )}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.all} onChange={(e) => setF({ ...f, all: e.target.checked })} />همهٔ کارکنان عضو طرح باشند</label>
      {err && <p role="alert" className="text-sm text-red-600">{err}</p>}
      <div className="flex gap-2"><button type="submit" className={btnCls} disabled={busy}>{busy ? "در حال ثبت…" : "ساخت طرح"}</button>
        <button type="button" className={btnGhost} onClick={() => setOpen(false)}>انصراف</button></div>
    </form>
  );
}

// ── Preferred sellers + approval rules ──────────────────────────────────────
const ROLE_FA: Record<string, string> = { organization_admin: "مدیر سازمان", organization_finance: "مالی", approver: "تأییدکننده" };
export function OrgBuyingRules() { return <OrgScope>{(c) => <><PreferredBody {...c} /><RulesBody {...c} /></>}</OrgScope>; }

function PreferredBody({ token, orgId, role }: Ctx) {
  const admin = role === "organization_admin";
  const [retry, setRetry] = useState(0);
  const [data, error] = useLoad<{ mode: string; items: PreferredSeller[] }>(`/orgs/${orgId}/preferred-sellers`, token, retry, (r: { mode: string; items: PreferredSeller[] }) => r);
  const [f, setF] = useState({ supplier_id: "", category_id: "", note: "" });
  const [msg, setMsg] = useState<Msg>(null);
  const [busy, setBusy] = useState(false);
  const add = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setMsg(null);
    try {
      await apiRequest(`/orgs/${orgId}/preferred-sellers`, { token, method: "POST", body: JSON.stringify({
        ...(f.supplier_id ? { supplier_id: Number(f.supplier_id) } : {}), ...(f.category_id ? { category_id: Number(f.category_id) } : {}), note: f.note.trim() || undefined }) });
      setF({ supplier_id: "", category_id: "", note: "" }); setMsg({ ok: true, text: "فروشنده اضافه شد." }); setRetry((x) => x + 1);
    } catch (e2) { setMsg({ ok: false, text: errText(e2) }); } finally { setBusy(false); }
  };
  const remove = async (id: number) => {
    setBusy(true); setMsg(null);
    try { await apiRequest(`/orgs/${orgId}/preferred-sellers/${id}`, { token, method: "DELETE" }); setRetry((x) => x + 1); }
    catch (e) { setMsg({ ok: false, text: errText(e) }); } finally { setBusy(false); }
  };
  return (
    <Card title="فروشندگان ترجیحی" action={data && <span className="rounded-full bg-neutral-100 px-3 py-1 text-xs">خرید هدایت‌شده: {({ off: "خاموش", warn: "هشدار", enforce: "اجباری" } as Record<string, string>)[data.mode] ?? data.mode}</span>}>
      <ListState items={data ? data.items : null} error={error} empty="فروشندهٔ ترجیحی تعریف نشده است." onRetry={() => setRetry((x) => x + 1)} />
      <ul className="divide-y divide-neutral-100 text-sm">
        {data?.items.map((p) => (
          <li key={p.id} className="flex items-center justify-between gap-2 py-2">
            <span>{p.supplier_id ? `فروشندهٔ #${n(p.supplier_id)}` : "همهٔ فروشندگان"}{p.category_id ? ` · دستهٔ #${n(p.category_id)}` : ""}{p.note ? ` · ${p.note}` : ""}</span>
            {admin && <button type="button" className="text-xs font-bold text-red-700" disabled={busy} onClick={() => remove(p.id)}>حذف</button>}
          </li>
        ))}
      </ul>
      {admin && (
        <form onSubmit={add} className="grid gap-2 sm:grid-cols-4 sm:items-end">
          <label className="text-xs font-bold">شناسهٔ فروشنده<input className={inputCls} inputMode="numeric" dir="ltr" value={f.supplier_id} onChange={(e) => setF({ ...f, supplier_id: numIn(e.target.value) })} /></label>
          <label className="text-xs font-bold">شناسهٔ دسته (اختیاری)<input className={inputCls} inputMode="numeric" dir="ltr" value={f.category_id} onChange={(e) => setF({ ...f, category_id: numIn(e.target.value) })} /></label>
          <label className="text-xs font-bold">توضیح<input className={inputCls} maxLength={500} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
          <button type="submit" className={btnCls} disabled={busy || (!f.supplier_id && !f.category_id)}>افزودن</button>
        </form>
      )}
      <Flash msg={msg} />
    </Card>
  );
}

function RulesBody({ token, orgId, role }: Ctx) {
  const admin = role === "organization_admin";
  const [retry, setRetry] = useState(0);
  const [rules, error] = useLoad<ApprovalRule[]>(`/orgs/${orgId}/approval-rules`, token, retry, (r: { items: ApprovalRule[] }) => r.items);
  const [f, setF] = useState({ name: "", min: "", max: "", decision: "require_approvals", required: "1", role: "" });
  const [msg, setMsg] = useState<Msg>(null);
  const [busy, setBusy] = useState(false);
  const add = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setMsg(null);
    try {
      await apiRequest(`/orgs/${orgId}/approval-rules`, { token, method: "POST", body: JSON.stringify({
        name: f.name.trim(), min_total_minor: tomanToMinor(f.min) ?? 0, max_total_minor: tomanToMinor(f.max), decision: f.decision,
        required_approvals: Number(f.required) || 1, approver_role: f.role || null }) });
      setF({ name: "", min: "", max: "", decision: "require_approvals", required: "1", role: "" }); setMsg({ ok: true, text: "قاعده ثبت شد." }); setRetry((x) => x + 1);
    } catch (e2) { setMsg({ ok: false, text: e2 instanceof ApiError && e2.code === "approval_rule_overlap" ? e2.message : errText(e2) }); } finally { setBusy(false); }
  };
  const off = async (id: number) => {
    setBusy(true); setMsg(null);
    try { await apiRequest(`/orgs/${orgId}/approval-rules/${id}`, { token, method: "DELETE" }); setRetry((x) => x + 1); }
    catch (e) { setMsg({ ok: false, text: errText(e) }); } finally { setBusy(false); }
  };
  return (
    <Card title="قواعد تأیید خرید">
      <ListState items={rules} error={error} empty="قاعده‌ای تعریف نشده است؛ همهٔ درخواست‌ها با گردش عادی تأیید می‌شوند." onRetry={() => setRetry((x) => x + 1)} />
      <ul className="divide-y divide-neutral-100 text-sm">
        {rules?.map((r) => (
          <li key={r.id} className={`flex flex-wrap items-center justify-between gap-2 py-2 ${r.is_active ? "" : "opacity-50"}`}>
            <span className="min-w-0"><b>{r.name}</b>
              <span className="block text-xs text-neutral-500">از {formatPrice(r.min_total_minor)} {r.max_total_minor != null ? `تا ${formatPrice(r.max_total_minor)}` : "به بالا"} ·{" "}
                {r.decision === "auto_approve" ? "تأیید خودکار" : `${n(r.required_approvals)} تأیید${r.approver_role ? ` (${ROLE_FA[r.approver_role] ?? r.approver_role})` : ""}`}{r.is_active ? "" : " · غیرفعال"}</span></span>
            {admin && r.is_active && <button type="button" className="text-xs font-bold text-red-700" disabled={busy} onClick={() => off(r.id)}>غیرفعال کردن</button>}
          </li>
        ))}
      </ul>
      {admin && (
        <form onSubmit={add} className="grid gap-2 sm:grid-cols-3 sm:items-end">
          <label className="text-xs font-bold">نام قاعده<input className={inputCls} required maxLength={120} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
          <label className="text-xs font-bold">از مبلغ (تومان)<input className={inputCls} inputMode="numeric" dir="ltr" value={f.min} onChange={(e) => setF({ ...f, min: numIn(e.target.value) })} /></label>
          <label className="text-xs font-bold">تا مبلغ (تومان، خالی = بی‌سقف)<input className={inputCls} inputMode="numeric" dir="ltr" value={f.max} onChange={(e) => setF({ ...f, max: numIn(e.target.value) })} /></label>
          <label className="text-xs font-bold">تصمیم
            <select className={inputCls} value={f.decision} onChange={(e) => setF({ ...f, decision: e.target.value })}>
              <option value="require_approvals">نیاز به تأیید</option><option value="auto_approve">تأیید خودکار</option>
            </select></label>
          {f.decision === "require_approvals" && <>
            <label className="text-xs font-bold">تعداد تأیید
              <select className={inputCls} value={f.required} onChange={(e) => setF({ ...f, required: e.target.value })}>
                {[1, 2, 3, 4, 5].map((k) => <option key={k} value={k}>{n(k)}</option>)}
              </select></label>
            <label className="text-xs font-bold">نقش تأییدکننده
              <select className={inputCls} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
                <option value="">هر تأییدکننده</option>{Object.entries(ROLE_FA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select></label>
          </>}
          <button type="submit" className={btnCls} disabled={busy}>ثبت قاعده</button>
        </form>
      )}
      <Flash msg={msg} />
    </Card>
  );
}
