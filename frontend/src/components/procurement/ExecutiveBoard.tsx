"use client";

// Executive procurement overview for /org: live counters from the backend and
// the concrete actions waiting on the current user.

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft, Bot, CalendarClock, ClipboardList, FileSearch, Inbox, Landmark, PackageCheck, PenSquare, ShieldCheck, Truck, Wallet,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { proc, type Dashboard } from "@/lib/procurement/api";
import { daysUntil, formatJalali } from "@/lib/procurement/jalali";
import { Chip, Empty, cx, n } from "./ui";
import s from "./proc.module.css";

export default function ExecutiveBoard({ orgId }: { orgId: string }) {
  const { token } = useAuth();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!token || !orgId) return;
    const c = new AbortController();
    setData(null); setError("");
    proc.dashboard(token, orgId, c.signal).then(setData).catch((e) => { if (!c.signal.aborted) setError(e.message); });
    return () => c.abort();
  }, [token, orgId]);

  const tiles: [string, number | null, React.ReactNode, string, string][] = data ? [
    ["درخواست‌های باز", data.counts.open_requests, <ClipboardList key="a" />, "/organization/requests", "از پیش‌نویس تا انتخاب پیشنهاد"],
    ["در انتظار استعلام", data.counts.awaiting_quotes, <FileSearch key="b" />, "/organization/requests", "استعلام‌های باز برای تأمین‌کنندگان"],
    ["پیشنهادهای رسیده", data.counts.quotes_received, <Inbox key="c" />, "/organization/requests", "آماده مقایسه و انتخاب"],
    ["نیازمند تأیید", data.counts.needs_approval, <ShieldCheck key="d" />, "/organization/requests", "در زنجیره تأیید سازمان"],
    ["سفارش‌های جاری", data.counts.active_orders, <PackageCheck key="e" />, "/organization/requests", "تأییدشده تا دریافت کامل"],
    ["در انتظار تحویل", data.counts.awaiting_delivery, <Truck key="f" />, "/organization/requests", "مقصدهای تحویل‌نشده"],
    ["سررسیدهای مالی", null, <CalendarClock key="g" />, "/organization/finance#maturity", data.finance.policy_status === "approved" ? "بدون سررسید ثبت‌شده" : "سیاست مالی تصویب نشده"],
    ["اعتبار سازمان", null, <Landmark key="h" />, "/organization/finance#credit", "سقف و تخصیص در صفحه مالی"],
  ] : [];

  return (
    <section className={s.root} style={{ marginBottom: 24 }}>
      <div className={s.card} style={{ background: "linear-gradient(135deg,#0a2735,#123c52)", color: "#fff", border: 0 }}>
        <div className={s.spread}>
          <div>
            <div style={{ fontSize: 12, color: "#a9cbe2" }}>خرید سازمانی · 60Online</div>
            <h2 style={{ fontSize: 20, fontWeight: 800, margin: "4px 0" }}>سفارش جدید را همان‌طور که فکر می‌کنید بنویسید</h2>
            <p style={{ margin: 0, color: "#c9dceb", fontSize: 13 }}>دستیار 60AI اقلام، تعداد، مقصدها و تاریخ را در پیش‌نویس می‌چیند؛ شما بازبینی و ارسال می‌کنید.</p>
          </div>
          <div className={s.row}>
            <Link href="/organization/compose?tab=assistant" className={cx(s.btn, s.primary)}><Bot /> دستیار خرید 60AI</Link>
            <Link href="/organization/compose" className={s.btn}><PenSquare /> ساخت دستی</Link>
            <Link href="/pack-builder" className={s.btn} style={{ background: "transparent", color: "#fff", borderColor: "#ffffff40" }}>پک‌ساز</Link>
          </div>
        </div>
      </div>

      {error ? <p className={s.small} style={{ color: "var(--red)" }}>{error}</p> : !data ? (
        <div className={s.kpis} style={{ marginTop: 16 }}>{Array.from({ length: 8 }).map((_, i) => <div key={i} className={s.skeleton} style={{ height: 96 }} />)}</div>
      ) : (
        <>
          <div className={s.kpis} style={{ marginTop: 16 }}>
            {tiles.map(([label, value, icon, href, hint]) => (
              <Link key={label} href={href} className={s.kpi}>
                <small>{icon} {label}</small>
                <strong className={s.num}>{value == null ? <Wallet size={22} style={{ color: "var(--faint)" }} /> : n(value)}</strong>
                <span>{hint}</span>
              </Link>
            ))}
          </div>
          <div className={s.card} style={{ marginTop: 16 }}>
            <div className={s.sectionHead}>
              <div><h2><ShieldCheck /> نیازمند اقدام شما</h2><p>{data.scope === "organization" ? "بر اساس نقش شما در سازمان" : "درخواست‌های شما"}</p></div>
              <Chip tone={data.actions.length ? "warn" : "ok"} dot>{data.actions.length ? `${n(data.actions.length)} مورد` : "موردی باقی نمانده"}</Chip>
            </div>
            {!data.actions.length ? (
              <Empty title="کاری در صف شما نیست" action={<Link className={cx(s.btn, s.primary)} href="/organization/compose">سفارش سازمانی جدید</Link>}>
                درخواست‌های نیازمند تأیید، مقایسه یا صدور سفارش به‌محض رسیدن نوبت شما اینجا نمایش داده می‌شوند.
              </Empty>
            ) : (
              <div className={s.tableWrap}>
                <table className={cx(s.table, s.cards)}>
                  <thead><tr><th>درخواست</th><th>اقدام</th><th>موعد</th><th /></tr></thead>
                  <tbody>
                    {data.actions.map((a) => {
                      const d = daysUntil(a.needed_by_date);
                      return (
                        <tr key={`${a.request_id}-${a.action}`}>
                          <td className={s.full}><b>{a.title}</b><div className={s.small} style={{ color: "var(--muted)" }}>{a.request_number}</div></td>
                          <td data-label="اقدام"><Chip tone="info">{a.action}</Chip></td>
                          <td data-label="موعد">{a.needed_by_date ? <>{formatJalali(a.needed_by_date)} {d != null && d < 0 ? <Chip tone="bad">تأخیر</Chip> : d != null && d <= 3 ? <Chip tone="warn">نزدیک</Chip> : null}</> : "—"}</td>
                          <td><Link className={cx(s.btn, s.sm)} href={`/organization/requests/${a.request_id}?org=${orgId}`}>باز کردن <ArrowLeft /></Link></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
