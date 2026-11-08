"use client";

// Printable proforma built only from the purchase order's immutable snapshot
// (supplier quote selected by the organization). It is not an invoice and
// records no payment; payment terms follow the organization's approved policy.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, FileText, Printer } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { money, proc, PAY_METHOD, PART_STATUS, PO_STATUS, RECEIPT_KIND, type Workspace } from "@/lib/procurement/api";
import { formatJalali, formatJalaliDateTime } from "@/lib/procurement/jalali";
import { Empty, Notice, cx, n } from "./ui";
import s from "./proc.module.css";

export default function Proforma({ id }: { id: string }) {
  const { token, loading } = useAuth();
  const sp = useSearchParams();
  const org = sp.get("org") ?? "";
  const statement = sp.get("doc") === "statement";
  const [ws, setWs] = useState<Workspace | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!token || !org) return;
    proc.workspace(token, org, id).then(setWs).catch((e) => setError(e.message));
  }, [token, org, id]);

  if (loading || (!ws && !error)) return <div className={s.root}><div className={s.skeleton} style={{ height: 300 }} /></div>;
  if (!ws) return <div className={s.root}><Notice tone="bad" icon={<AlertTriangle />}>{error || "برای مشاهده پیش‌فاکتور وارد حساب سازمانی شوید."}</Notice></div>;
  const po = ws.orders.find((o) => o.status !== "cancelled");
  const cur = ws.organization.currency;
  const back = <Link className={s.btn} href={`/organization/requests/${id}?org=${org}`}>بازگشت به پرونده</Link>;
  if (!po) {
    return (
      <div className={s.root}>
        <Empty icon={<FileText />} title="پیش‌فاکتور هنوز آماده نیست" action={back}>
          پیش‌فاکتور پس از انتخاب پیشنهاد تأمین‌کننده و صدور سفارش از روی مبالغ ثابت‌شدهٔ همان سفارش ساخته می‌شود.
        </Empty>
      </div>
    );
  }
  const dests = ws.request.destinations;
  return (
    <div className={s.root}>
      <div className={cx(s.row, "print:hidden")} style={{ justifyContent: "space-between", marginBottom: 12 }}>
        {back}
        <button type="button" className={cx(s.btn, s.primary)} onClick={() => window.print()}><Printer /> چاپ / ذخیره PDF</button>
      </div>
      {/* Print only the document: hide site chrome and the panel sidebar. */}
      <style>{`@media print { body > *:not(main), header, footer, nav, aside, .mobile-bottom-nav { display: none !important; } main { padding: 0 !important; } }`}</style>
      <article className={s.card} style={{ padding: 28 }} aria-label="پیش‌فاکتور">
        <header className={s.spread} style={{ alignItems: "flex-start", borderBottom: "2px solid var(--navy)", paddingBottom: 14, marginBottom: 16 }}>
          <div>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/brand/60online-logo.jpeg" alt="60Online" style={{ height: 56, width: "auto" }} />
          </div>
          <div style={{ textAlign: "left" }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800 }}>{statement ? "صورت‌حساب داخلی تحویل و پرداخت" : "پیش‌فاکتور"}</h1>
            <div className={s.small}>شماره سفارش: <b className={s.num}>{po.po_number}</b></div>
            <div className={s.small}>درخواست: <b className={s.num}>{ws.request.request_number}</b></div>
            <div className={s.small}>تاریخ تهیه: {formatJalaliDateTime(new Date().toISOString())}</div>
          </div>
        </header>
        <div className={s.grid2} style={{ marginBottom: 16 }}>
          <div className={s.cardFlat}><div className={s.small} style={{ color: "var(--muted)" }}>خریدار</div><b>{ws.organization.name}</b><div className={s.small}>درخواست‌دهنده: {ws.requester ?? "—"}</div></div>
          <div className={s.cardFlat}><div className={s.small} style={{ color: "var(--muted)" }}>تأمین‌کننده</div><b>{po.supplier ?? "—"}</b><div className={s.small}>وضعیت سفارش: {PO_STATUS[po.status] ?? po.status}</div></div>
        </div>
        <div className={s.tableWrap}>
          <table className={s.table}>
            <thead><tr><th>#</th><th>شرح کالا</th><th>تعداد</th><th>قیمت واحد</th><th>جمع</th></tr></thead>
            <tbody>
              {po.items.map((it, k) => (
                <tr key={it.id}>
                  <td className={s.num}>{n(k + 1)}</td>
                  <td>{ws.items[k]?.name ?? it.free_text_description ?? "—"}</td>
                  <td className={s.num}>{n(it.quantity)} {it.unit}</td>
                  <td className={s.num}>{money(it.unit_price_minor_snapshot, cur)}</td>
                  <td className={s.num}>{money(it.total_minor_snapshot, cur)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ display: "grid", justifyContent: "end", marginTop: 12 }}>
          <table className={s.table} style={{ minWidth: 300 }}>
            <tbody>
              <tr><td>جمع اقلام</td><td className={s.num}>{money(po.items_total_minor, cur)}</td></tr>
              {po.discount_minor ? <tr><td>تخفیف</td><td className={s.num}>− {money(po.discount_minor, cur)}</td></tr> : null}
              <tr><td>حمل</td><td className={s.num}>{money(po.shipping_minor, cur)}</td></tr>
              <tr><td>مالیات بر ارزش افزوده</td><td className={s.num}>{money(po.vat_minor, cur)}</td></tr>
              <tr><td><b>مبلغ کل</b></td><td className={s.num}><b>{money(po.grand_total_minor, cur)}</b></td></tr>
            </tbody>
          </table>
        </div>
        {dests.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <b className={s.small}>مقصدهای تحویل</b>
            <ul className={s.small} style={{ margin: "6px 0 0", paddingRight: 18 }}>
              {dests.map((d, i) => <li key={i}>{d.label || d.city} — {d.province}، {d.city}، {d.address}{d.needed_by_date ? ` (تا ${formatJalali(d.needed_by_date)})` : ""}</li>)}
            </ul>
          </div>
        )}
        {statement && (
          <div style={{ marginTop: 16 }} className={s.grid2}>
            <div><b className={s.small}>تحویل و رسید</b>
              <ul className={s.small} style={{ margin: "6px 0 0", paddingRight: 18 }}>
                {po.deliveries.flatMap((d) => d.receipts.length ? d.receipts.map((rc) => <li key={rc.id}>{d.label || d.city}: {RECEIPT_KIND[rc.kind]} · {rc.receiver_name} · {formatJalaliDateTime(rc.created_at)}</li>)
                  : [<li key={`d${d.destination_index}`}>{d.label || d.city}: بدون رسید</li>])}
              </ul></div>
            <div><b className={s.small}>پرداخت</b>
              {po.finance.plan ? (
                <ul className={s.small} style={{ margin: "6px 0 0", paddingRight: 18 }}>
                  {po.finance.plan.parts.map((x) => <li key={x.id}>{PAY_METHOD[x.method]} · {money(x.amount_minor, cur)} · {PART_STATUS[x.status]}{x.reference ? ` · ${x.reference}` : ""}</li>)}
                  <li>وصول‌شده: {money(po.finance.collected_minor, cur)} · بازپرداخت: {money(po.finance.refunded_minor, cur)}</li>
                  <li>{po.finance.settlement ? `تسویه با تأمین‌کننده: ${money(po.finance.settlement.amount_minor, cur)} · ${po.finance.settlement.reference}` : "تسویه با تأمین‌کننده: ثبت نشده"}</li>
                  {po.finance.plan.environment === "test" && <li><b>محیط آزمایشی (TEST) — بدون اثر مالی واقعی</b></li>}
                </ul>
              ) : <p className={s.small}>برنامه پرداخت ثبت نشده است{po.finance.policy ? "" : " (سیاست پرداخت سازمان تصویب نشده)"}.</p>}
            </div>
          </div>
        )}
        <p className={s.small} style={{ marginTop: 18, color: "var(--muted)", lineHeight: 1.9 }}>
          {statement ? "این صورت‌حساب داخلی خلاصهٔ تحویل و پرداخت ثبت‌شده است و فاکتور رسمی مالیاتی نیست؛ صدور فاکتور رسمی نیازمند اتصال به سامانهٔ مودیان است. " : ""}این پیش‌فاکتور از مبالغ ثابت‌شدهٔ سفارش بر اساس پیشنهاد منتخب تأمین‌کننده تهیه شده و فاکتور یا سند پرداخت نیست.
          روش پرداخت (نقدی، چکی، اعتباری، برات) فقط طبق قرارداد و سیاست مالی تأییدشدهٔ سازمان تعیین می‌شود.
        </p>
      </article>
    </div>
  );
}
