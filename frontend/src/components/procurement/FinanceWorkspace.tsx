"use client";

// Organization finance workbench: approvals, receivables, instruments, overdue, refunds, supplier payables,
// reconciliation, documents and the immutable ledger. Figures come only from recorded plans under the
// organization's approved policy; this system performs no bank transaction.

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { AlertTriangle, CalendarClock, FileText, Landmark, Lock, Receipt, Scale, ShieldCheck, Wallet } from "lucide-react";
import { useOrganization } from "@/components/organization/Dashboard";
import { FIN_EVENT, PART_STATUS, PAY_METHOD, PLAN_STATUS, money, proc, type FinPart, type FinanceSummary } from "@/lib/procurement/api";
import { daysUntil, formatJalali, formatJalaliDateTime } from "@/lib/procurement/jalali";
import { Chip, Empty, Notice, cx, n } from "./ui";
import s from "./proc.module.css";

const PAYABLE: Record<string, [string, "ok" | "warn" | "bad" | "info" | "muted"]> = {
  settled: ["تسویه شد", "ok"], ready: ["آماده تسویه", "info"], blocked_correction: ["اصلاحیه باز", "bad"],
  awaiting_delivery: ["در انتظار تحویل", "warn"], awaiting_collection: ["در انتظار وصول", "muted"] };
const RECON: Record<string, [string, "ok" | "warn" | "bad" | "info" | "muted"]> = {
  reconciled: ["تطبیق‌شده", "ok"], mismatch: ["مغایرت", "bad"], collected: ["وصول کامل؛ تسویه‌نشده", "info"], partial: ["وصول جزئی", "warn"], open: ["باز", "muted"] };
type Tab = "overview" | "approvals" | "collection" | "refunds" | "payables" | "reconciliation" | "documents" | "ledger";

const Env = ({ e }: { e: string }) => (e === "test" ? <Chip tone="violet">TEST</Chip> : null);

export default function FinanceWorkspace() {
  const o = useOrganization(true);
  const [d, setD] = useState<FinanceSummary | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("overview");
  useEffect(() => {
    if (!o.token || !o.selected) return;
    setD(null); setError("");
    proc.finance(o.token, o.selected).then(setD).catch((e) => setError(e.message));
  }, [o.token, o.selected]);
  const cur = (o.org as unknown as { currency?: string } | undefined)?.currency ?? "IRR";
  const caseHref = (id: number) => `/organization/requests/${id}?org=${o.selected}#finance`;

  const partsTable = (rows: FinPart[], empty: string) => !rows.length ? <p className={s.small} style={{ color: "var(--muted)" }}>{empty}</p> : (
    <div className={s.tableWrap}><table className={cx(s.table, s.cards)}>
      <thead><tr><th>سفارش</th><th>روش</th><th>مبلغ</th><th>سررسید</th><th>وضعیت</th><th /></tr></thead>
      <tbody>{rows.map((x) => { const days = daysUntil(x.due_date); return (
        <tr key={x.id}><td className={s.full}><b>{x.po_number}</b> <Env e={x.environment} /></td>
          <td data-label="روش">{PAY_METHOD[x.method]}{x.reference ? ` · ${x.reference}` : ""}</td>
          <td data-label="مبلغ" className={s.num}>{money(x.amount_minor, cur)}</td>
          <td data-label="سررسید">{x.due_date ? formatJalali(x.due_date) : "—"} {x.overdue ? <Chip tone="bad">سررسید گذشته</Chip> : days != null && days >= 0 && days <= 7 && x.status !== "cleared" ? <Chip tone="warn">{n(days)} روز</Chip> : null}</td>
          <td data-label="وضعیت"><Chip tone={x.status === "cleared" ? "ok" : x.status === "bounced" ? "bad" : "info"} dot>{PART_STATUS[x.status]}</Chip></td>
          <td><Link className={cx(s.btn, s.sm)} href={caseHref(x.purchase_request_id)}>ثبت در پرونده</Link></td></tr>); })}</tbody>
    </table></div>
  );

  const counts: Record<Tab, number | null> = d ? { overview: null, approvals: d.pending_approvals.length, collection: d.expected.length + d.overdue.length,
    refunds: d.refunds.length, payables: d.payables.filter((p) => p.state !== "settled").length, reconciliation: d.reconciliation.filter((r) => r.state === "mismatch").length,
    documents: null, ledger: null } : ({} as Record<Tab, null>);
  const tabs: [Tab, string][] = [["overview", "نمای کلی"], ["approvals", "در انتظار تأیید"], ["collection", "وصول و سررسید"], ["refunds", "بازپرداخت"],
    ["payables", "تسویه تأمین‌کننده"], ["reconciliation", "تطبیق"], ["documents", "اسناد"], ["ledger", "دفتر رویدادها"]];

  let body: ReactNode = null;
  if (d) {
    if (tab === "overview") body = <>
      <div className={s.kpis}>
        {[["سقف اعتبار", d.credit.limit_minor != null ? money(d.credit.limit_minor, cur) : "تعریف نشده", Landmark],
          ["مصرف اعتبار", money(d.credit.used_minor, cur), Wallet],
          ["مانده اعتبار", d.credit.remaining_minor != null ? money(d.credit.remaining_minor, cur) : "—", Wallet],
          ["مطالبات در جریان", money(d.receivable_minor, cur), Receipt]].map(([k, v, Icon]) => {
          const I = Icon as typeof Landmark;
          return <div key={k as string} className={s.kpi}><small><I /> {k as string}</small><strong className={s.num} style={{ fontSize: 20 }}>{v as string}</strong></div>;
        })}
      </div>
      <div className={s.kpis} style={{ marginTop: 10 }}>
        {[["در انتظار تأیید مالی", d.pending_approvals.length, "approvals"], ["سررسید گذشته", d.overdue.length, "collection"],
          ["آماده تسویه", d.payables.filter((p) => p.state === "ready").length, "payables"], ["مغایرت تطبیق", d.reconciliation.filter((r) => r.state === "mismatch").length, "reconciliation"]].map(([k, v, t]) => (
          <button key={k as string} className={s.kpi} style={{ textAlign: "start", cursor: "pointer" }} onClick={() => setTab(t as Tab)}><small>{k as string}</small><strong className={s.num} style={{ fontSize: 20 }}>{n(v as number)}</strong></button>))}
      </div>
      <section className={s.card}><div className={s.sectionHead}><div><h2><CalendarClock /> سررسید چک و برات</h2><p>دریافت‌نشده یا وصول‌نشده</p></div></div>
        {partsTable(d.instruments.map((x) => ({ ...x, purchase_request_id: d.plans.find((p) => p.po_number === x.po_number)?.purchase_request_id ?? 0, plan_status: "approved",
          overdue: !!x.due_date && x.due_date < d.today })), "سررسید بازی ثبت نشده است.")}</section>
    </>;
    if (tab === "approvals") body = <section className={s.card}><div className={s.sectionHead}><div><h2>برنامه‌های پرداخت در انتظار تأیید مالی</h2><p>ثبت‌کننده برنامه نمی‌تواند همان را تأیید کند؛ مبالغ بالای آستانه سیاست دو تأییدکننده متفاوت لازم دارند.</p></div></div>
      {!d.pending_approvals.length ? <p className={s.small} style={{ color: "var(--muted)" }}>برنامه‌ای در انتظار تأیید نیست.</p> : (
        <div className={s.tableWrap}><table className={cx(s.table, s.cards)}><thead><tr><th>سفارش</th><th>مبلغ</th><th /></tr></thead>
          <tbody>{d.pending_approvals.map((p) => <tr key={p.id}><td className={s.full}><b>{p.po_number}</b> <Env e={p.environment} /></td><td data-label="مبلغ" className={s.num}>{money(p.total_minor, cur)}</td>
            <td><Link className={cx(s.btn, s.sm, s.primary)} href={caseHref(p.purchase_request_id)}>بررسی و تصمیم</Link></td></tr>)}</tbody></table></div>)}</section>;
    if (tab === "collection") body = <>
      {!!d.overdue.length && <section className={s.card}><div className={s.sectionHead}><div><h2><AlertTriangle /> سررسید گذشته</h2></div></div>{partsTable(d.overdue, "")}</section>}
      <section className={s.card}><div className={s.sectionHead}><div><h2>مطالبات مورد انتظار</h2><p>بخش‌های برنامه‌های تأییدشده که هنوز دریافت نشده‌اند</p></div></div>{partsTable(d.expected, "مطالبه‌ای در انتظار دریافت نیست.")}</section>
      <section className={s.card}><div className={s.sectionHead}><div><h2>دریافت‌ها</h2><p>ثبت‌شده توسط مالی بر اساس مرجع بانکی؛ این سامانه تراکنش بانکی انجام نمی‌دهد.</p></div></div>{partsTable(d.received, "دریافتی ثبت نشده است.")}</section>
    </>;
    if (tab === "refunds") body = <section className={s.card}><div className={s.sectionHead}><div><h2>بازپرداخت‌ها</h2></div></div>
      {!d.refunds.length ? <p className={s.small} style={{ color: "var(--muted)" }}>بازپرداختی ثبت نشده است.</p> : (
        <div className={s.tableWrap}><table className={cx(s.table, s.cards)}><thead><tr><th>سفارش</th><th>مبلغ</th><th>علت</th><th>ثبت</th></tr></thead>
          <tbody>{d.refunds.map((r, i) => <tr key={i}><td className={s.full}><b>{r.po_number}</b> <Env e={r.environment} /></td><td data-label="مبلغ" className={s.num}>{money(r.amount_minor, cur)}</td>
            <td data-label="علت">{r.note}</td><td data-label="ثبت">{r.actor} · {formatJalaliDateTime(r.created_at)}</td></tr>)}</tbody></table></div>)}</section>;
    if (tab === "payables") body = <section className={s.card}><div className={s.sectionHead}><div><h2>بدهی به تأمین‌کنندگان</h2><p>تسویه فقط پس از وصول کامل، تحویل و بسته بودن اصلاحیه‌ها قابل ثبت است.</p></div></div>
      {!d.payables.length ? <p className={s.small} style={{ color: "var(--muted)" }}>برنامه پرداخت تأییدشده‌ای وجود ندارد.</p> : (
        <div className={s.tableWrap}><table className={cx(s.table, s.cards)}><thead><tr><th>سفارش</th><th>تأمین‌کننده</th><th>مبلغ</th><th>وضعیت</th><th /></tr></thead>
          <tbody>{d.payables.map((p) => <tr key={p.purchase_order_id}><td className={s.full}><b>{p.po_number}</b> <Env e={p.environment} /></td>
            <td data-label="تأمین‌کننده">{p.supplier ?? "—"} {p.supplier_is_demo && <Chip tone="warn">DEMO</Chip>}</td>
            <td data-label="مبلغ" className={s.num}>{money(p.amount_minor, cur)}</td>
            <td data-label="وضعیت"><Chip tone={PAYABLE[p.state][1]} dot>{PAYABLE[p.state][0]}</Chip>{p.settlement && <div className={s.small}>{p.settlement.reference}</div>}</td>
            <td><Link className={cx(s.btn, s.sm)} href={caseHref(p.purchase_request_id)}>پرونده</Link></td></tr>)}</tbody></table></div>)}</section>;
    if (tab === "reconciliation") body = <section className={s.card}><div className={s.sectionHead}><div><h2><Scale /> تطبیق وصول و تسویه</h2><p>وصول‌شده − بازپرداخت = مبلغ تسویه. تطبیق با صورت‌حساب بانک تا اتصال بانکی دستی است.</p></div></div>
      {!d.reconciliation.length ? <p className={s.small} style={{ color: "var(--muted)" }}>موردی برای تطبیق نیست.</p> : (
        <div className={s.tableWrap}><table className={cx(s.table, s.cards)}><thead><tr><th>سفارش</th><th>مبلغ</th><th>وصول</th><th>بازپرداخت</th><th>تسویه</th><th>وضعیت</th></tr></thead>
          <tbody>{d.reconciliation.map((r) => <tr key={r.po_number}><td className={s.full}><b>{r.po_number}</b> <Env e={r.environment} /></td>
            <td data-label="مبلغ" className={s.num}>{money(r.total_minor, cur)}</td><td data-label="وصول" className={s.num}>{money(r.collected_minor, cur)}</td>
            <td data-label="بازپرداخت" className={s.num}>{money(r.refunded_minor, cur)}</td><td data-label="تسویه" className={s.num}>{money(r.settled_minor, cur)}</td>
            <td data-label="وضعیت"><Chip tone={RECON[r.state][1]} dot>{RECON[r.state][0]}</Chip></td></tr>)}</tbody></table></div>)}</section>;
    if (tab === "documents") body = <section className={s.card}><div className={s.sectionHead}><div><h2><FileText /> اسناد</h2><p>پیش‌فاکتور و صورت‌حساب داخلی هر سفارش. فاکتور رسمی مالیاتی نیازمند اتصال به سامانه مودیان است و صادر نمی‌شود.</p></div></div>
      {!d.plans.length ? <p className={s.small} style={{ color: "var(--muted)" }}>سندی برای نمایش نیست.</p> : (
        <div className={s.tableWrap}><table className={cx(s.table, s.cards)}><thead><tr><th>سفارش</th><th>وضعیت پرداخت</th><th /></tr></thead>
          <tbody>{d.plans.map((p) => <tr key={p.id}><td className={s.full}><b>{p.po_number}</b> <Env e={p.environment} /></td><td data-label="وضعیت">{PLAN_STATUS[p.status]}</td>
            <td><div className={s.row}><Link className={cx(s.btn, s.sm)} href={`/organization/requests/${p.purchase_request_id}/proforma?org=${o.selected}`}>پیش‌فاکتور</Link>
              <Link className={cx(s.btn, s.sm)} href={`/organization/requests/${p.purchase_request_id}/proforma?org=${o.selected}&doc=statement`}>صورت‌حساب داخلی</Link></div></td></tr>)}</tbody></table></div>)}</section>;
    if (tab === "ledger") body = <section className={s.card}><div className={s.sectionHead}><div><h2><Landmark /> دفتر رویدادهای مالی</h2><p>ثبت غیرقابل ویرایش؛ بدون تراکنش بانکی در این سامانه</p></div></div>
      {!d.ledger.length ? <p className={s.small} style={{ color: "var(--muted)" }}>رویدادی ثبت نشده است.</p> : (
        <div className={s.timeline}>{d.ledger.map((e, i) => (
          <div key={i} className={s.tItem}><span className={s.tDot} /><div><b>{FIN_EVENT[e.kind] ?? e.kind}</b> · {e.po_number}{e.amount_minor ? ` · ${money(e.amount_minor, cur)}` : ""} <Env e={e.environment} />{e.actor && <span className={s.muted}> · {e.actor}</span>}{e.note && <div className={s.small}>{e.note}</div>}</div><time>{formatJalaliDateTime(e.created_at)}</time></div>
        ))}</div>)}</section>;
  }

  return (
    <div className={s.root}>
      <header className={s.head}>
        <div className={s.headRow}>
          <div><div className={s.eyebrow}>میز کار سازمانی</div><h1 className={s.title}>میز کار مالی</h1>
            <div className={s.meta}><span>{o.org?.display_name ?? "—"}</span>
              {d && (d.policy ? <Chip tone={d.policy.environment === "test" ? "violet" : "ok"} dot>{d.policy.environment === "test" ? "سیاست آزمایشی (TEST)" : "سیاست مصوب"} · نسخه {d.policy.version}</Chip> : <Chip tone="warn" dot>سیاست پرداخت تصویب نشده</Chip>)}
              {d && <Chip tone="muted">اتصال بانکی: ندارد</Chip>}</div></div>
          <Link className={cx(s.btn, s.sm)} href="/organization/payment-policy"><ShieldCheck /> سیاست پرداخت</Link>
        </div>
      </header>
      {error ? <Empty icon={<Lock />} title="دسترسی مالی لازم است">{error}</Empty> : !d ? <div className={s.skeleton} style={{ height: 280 }} /> : (
        <div className={s.stack}>
          {!d.policy && <Notice icon={<AlertTriangle />}>تا تصویب سیاست پرداخت سازمان (روش‌های مجاز، سقف اعتبار و قرارداد)، ثبت برنامه پرداخت، مصرف اعتبار، وصول و تسویه غیرفعال است. هیچ رقمی تخمینی نمایش داده نمی‌شود.</Notice>}
          {d.policy?.environment === "test" && <Notice tone="info" icon={<AlertTriangle />}>این سازمان با سیاست آزمایشی کار می‌کند؛ همهٔ رکوردها TEST هستند و اثر مالی واقعی ندارند.</Notice>}
          <div className={s.tabs} role="tablist">{tabs.map(([k, l]) => (
            <button key={k} role="tab" aria-selected={tab === k} className={cx(s.tab, tab === k && s.tabOn)} onClick={() => setTab(k)}>{l}{counts[k] ? <em>{n(counts[k])}</em> : null}</button>))}</div>
          {body}
        </div>
      )}
    </div>
  );
}
