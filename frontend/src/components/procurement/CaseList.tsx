"use client";

// Organization purchase cases: search and filter by status / next action,
// with owner, SLA, blocked reason and order/delivery/payment state per case.

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowLeft, FolderOpen, Plus, Search } from "lucide-react";
import { useOrganization } from "@/components/organization/Dashboard";
import { useAuth } from "@/lib/auth-context";
import { apiRequest } from "@/lib/api";
import { PLAN_STATUS, PO_STATUS, PR_STATUS, URGENCY, proc, type CaseRow } from "@/lib/procurement/api";
import { daysUntil, formatJalali } from "@/lib/procurement/jalali";
import { Chip, Empty, Notice, cx, n } from "./ui";
import s from "./proc.module.css";

const STAGES: [string, string][] = [
  ["", "همه اقدام‌ها"], ["blocked", "متوقف‌شده"], ["submit", "ارسال پیش‌نویس"], ["approve", "در انتظار تأیید"], ["create_rfq", "آماده استعلام"],
  ["compare", "مقایسه پیشنهاد"], ["create_order", "صدور سفارش"], ["payment_plan", "برنامه پرداخت"], ["finance_approval", "تأیید مالی"],
  ["fulfillment", "تحویل"], ["collection", "وصول"], ["settlement", "تسویه"], ["close", "آماده بستن"],
];

export default function CaseList({ platform = false }: { platform?: boolean }) {
  const o = useOrganization(!platform);
  const { token } = useAuth();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [stage, setStage] = useState("");
  const [rows, setRows] = useState<CaseRow[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!token || (!platform && !o.selected)) return;
    const c = new AbortController();
    const t = setTimeout(() => {
      setRows(null); setError("");
      const qs = new URLSearchParams(Object.entries({ q, status, stage }).filter(([, v]) => v)).toString();
      (platform ? apiRequest<{ items: CaseRow[] }>(`/admin/procurement/cases${qs ? `?${qs}` : ""}`, { token, signal: c.signal }) : proc.cases(token, o.selected, qs, c.signal))
        .then((r) => setRows(r.items)).catch((e) => { if (!c.signal.aborted) setError(e.message); });
    }, 250);
    return () => { clearTimeout(t); c.abort(); };
  }, [token, platform, o.selected, q, status, stage]);

  return (
    <div className={s.root}>
      <header className={s.head}>
        <div className={s.headRow}>
          <div><div className={s.eyebrow}>{platform ? "مدیریت پلتفرم" : "میز کار سازمانی"}</div><h1 className={s.title}>{platform ? "پرونده‌های خرید همه سازمان‌ها" : "پرونده‌های خرید"}</h1><div className={s.meta}><span>{platform ? "فقط‌خواندنی؛ برگرفته از سوابق اصلی" : o.org?.display_name ?? "—"}</span>{rows && <span>{n(rows.length)} پرونده</span>}</div></div>
          <Link className={cx(s.btn, s.primary)} href="/organization/compose"><Plus /> سفارش سازمانی جدید</Link>
        </div>
      </header>
      <div className={s.card} style={{ marginBottom: 14 }}>
        <div className={s.grid3}>
          <label className={s.field}>جستجو
            <span style={{ position: "relative" }}><input className={s.input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="شماره یا عنوان درخواست" style={{ paddingLeft: 34 }} /><Search size={16} style={{ position: "absolute", left: 10, top: 11, color: "var(--muted)" }} /></span>
          </label>
          <label className={s.field}>وضعیت
            <select className={s.select} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">همه وضعیت‌ها</option>{Object.entries(PR_STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className={s.field}>اقدام بعدی
            <select className={s.select} value={stage} onChange={(e) => setStage(e.target.value)}>{STAGES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          </label>
        </div>
      </div>
      {error ? <Notice tone="bad" icon={<AlertTriangle />}>{error}</Notice> : rows === null ? <div className={s.skeleton} style={{ height: 240 }} /> : !rows.length ? (
        <Empty icon={<FolderOpen />} title="پرونده‌ای با این فیلترها پیدا نشد" action={<Link className={cx(s.btn, s.primary)} href="/organization/compose">ثبت سفارش سازمانی</Link>}>فیلترها را تغییر دهید یا یک درخواست جدید بسازید.</Empty>
      ) : (
        <div className={s.tableWrap}>
          <table className={cx(s.table, s.cards)}>
            <thead><tr><th>پرونده</th><th>وضعیت</th><th>مالک</th><th>اقدام بعدی</th><th>موعد</th><th>سفارش / تحویل / پرداخت</th><th /></tr></thead>
            <tbody>
              {rows.map((r) => {
                const d = daysUntil(r.needed_by_date);
                return (
                  <tr key={r.id}>
                    <td className={s.full}><b>{r.title}</b><div className={s.small} style={{ color: "var(--muted)" }}>{r.request_number} · {r.organization ?? ""} · اولویت {URGENCY[r.urgency] ?? r.urgency}{r.suppliers?.length ? ` · تأمین: ${r.suppliers.join("، ")}` : ""}</div>
                      {r.blocked_reason && <Chip tone="bad">{r.blocked_reason}</Chip>}</td>
                    <td data-label="وضعیت"><Chip tone={r.status === "completed" ? "ok" : r.status === "rejected" || r.status === "cancelled" ? "bad" : "info"} dot>{PR_STATUS[r.status] ?? r.status}</Chip></td>
                    <td data-label="مالک">{r.owner ?? "—"}</td>
                    <td data-label="اقدام بعدی"><b className={s.small}>{r.next_action.label}</b>{r.next_action.owner && <div className={s.small} style={{ color: "var(--muted)" }}>{r.next_action.owner}</div>}</td>
                    <td data-label="موعد">{r.needed_by_date ? <>{formatJalali(r.needed_by_date)} {d != null && !["completed", "cancelled"].includes(r.status) && (d < 0 ? <Chip tone="bad">تأخیر</Chip> : d <= 3 ? <Chip tone="warn">نزدیک</Chip> : null)}</> : "—"}</td>
                    <td data-label="سفارش" className={s.small}>{r.order ? <>{r.order.po_number} · {PO_STATUS[r.order.status] ?? r.order.status}<br />تحویل {n(r.order.delivered)}/{n(r.order.destinations)} · {r.order.settled ? "تسویه شد" : r.order.payment ? PLAN_STATUS[r.order.payment] : "بدون برنامه پرداخت"}</> : `${n(r.rfqs)} استعلام · ${n(r.quotes)} پیشنهاد`}</td>
                    <td>{platform ? <span className={s.small} style={{ color: "var(--muted)" }}>{r.updated_at?.slice(0, 10)}</span> : <Link className={cx(s.btn, s.sm)} href={`/organization/requests/${r.id}?org=${o.selected}`}>باز کردن <ArrowLeft /></Link>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
