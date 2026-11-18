"use client";

// Proforma management + batch export — faithful to Stitch screen 06 (مدیریت و خروجی تجمیعی پیش‌فاکتورهای رسمی).
// Data: GET /me/proformas (owner-scoped, ?from=&to=) and GET /me/proformas/{n}. The ZIP holds one self-contained,
// printable HTML per proforma («Print → Save as PDF» keeps Persian text correct) plus summary.csv (Excel).
// Built in the browser; nothing is uploaded. «ارسال به سامانه مودیان» has no backend → disabled «به‌زودی».
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { jalaliToIso } from "@/lib/jalali";
import { buildZip, downloadBlob } from "@/lib/zip";
import { cn, faDate, formatPrice, toPersianNum } from "@/lib/utils";
import { PrintSheet } from "@/components/print/PrintSheet";
import ProformaSheet, { proformaState as state, type ProformaDoc } from "@/components/organization/ProformaSheet";
import st from "@/components/organization/stitch.module.css";

type Row = { number: string; organization: string | null; created_at: string; valid_until: string; expired: boolean; used: boolean; total_minor: number; item_count: number };
type Detail = ProformaDoc;

const fa = (v: number) => v.toLocaleString("fa-IR");
const toman = (m: number) => fa(Math.round(m / 10));
const Icon = ({ name, className }: { name: string; className?: string }) => <span aria-hidden className={cn("material-symbols-outlined", className)}>{name}</span>;
const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const PAGE = 10;
const TABS = [
  { k: "all", l: "همه", f: () => true },
  { k: "valid", l: "معتبر و آماده پرداخت", f: (r: Row) => !r.used && !r.expired },
  { k: "used", l: "استفاده‌شده", f: (r: Row) => r.used },
  { k: "expired", l: "منقضی شده", f: (r: Row) => !r.used && r.expired },
];

function proformaHtml(d: Detail, logo: string): string {
  const rows = d.items.map((i, k) => `<tr><td>${toPersianNum(k + 1)}</td><td>${esc(i.title_fa)}</td><td dir="ltr">${esc(i.sku)}</td><td>${toPersianNum(i.quantity)}</td><td>${formatPrice(i.unit_price_minor)}</td><td>${formatPrice(i.line_total_minor)}</td></tr>`).join("");
  const tot = ([["جمع کالاها", d.subtotal_minor], ["ارسال", d.shipping_fee_minor], ["مالیات بر ارزش افزوده", d.tax_minor], ["مبلغ قابل پرداخت", d.total_minor]] as [string, number][])
    .map(([k, v], i, a) => `<tr${i === a.length - 1 ? ' class="b"' : ""}><td colspan="5">${k}</td><td>${formatPrice(v)}</td></tr>`).join("");
  return `<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><title>پیش‌فاکتور ${esc(d.number)}</title><style>
@page{size:A4;margin:16mm 14mm}body{font-family:Vazirmatn,Tahoma,"Segoe UI",sans-serif;color:#0a2735;font-size:11pt;line-height:1.9;margin:24px}
header{display:flex;align-items:center;gap:14px;border-bottom:2px solid #0a2735;padding-bottom:10px;margin-bottom:12px}header img{height:54px}
h1{font-size:17pt;margin:0}p{margin:0}.m{color:#4f5b62;font-size:9.5pt}.no{margin-right:auto;border:1px solid #dcdfe1;border-radius:8px;padding:4px 10px;text-align:left}
table{width:100%;border-collapse:collapse;margin-bottom:14px}th,td{border:1px solid #dcdfe1;padding:6px 9px;text-align:right}th{background:#f1f1ee}.b td{font-weight:800}
.n{border:1px solid #dcdfe1;border-radius:8px;padding:8px 12px;font-size:9.5pt}</style></head><body>
<header><img src="${logo}" alt=""><div><h1>پیش‌فاکتور رسمی</h1><p class="m">شصت‌آنلاین · تاریخ صدور: ${faDate(d.created_at)}</p></div><div class="no"><span class="m">شماره</span><br><b dir="ltr">${esc(d.number)}</b></div></header>
<table><tr><th>خریدار</th><td>${esc(d.organization ?? "خرید شخصی")}</td><th>معتبر تا</th><td>${faDate(d.valid_until)}</td><th>وضعیت</th><td>${state(d)}</td></tr></table>
<table><thead><tr><th>ردیف</th><th>کالا</th><th>کد کالا</th><th>تعداد</th><th>فی</th><th>جمع</th></tr></thead><tbody>${rows}</tbody><tfoot>${tot}</tfoot></table>
<p class="n">اعتبار این پیش‌فاکتور تا تاریخ ذکرشده است. اگر هنگام پرداخت مبلغ سبد از این پیش‌فاکتور بیشتر شده باشد، پرداخت انجام نمی‌شود.</p>
</body></html>`;
}

function StatusPill({ r }: { r: Row }) {
  return r.used ? <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-st-surface-container-high px-st-space-sm py-1 text-[13px] font-semibold text-st-on-surface-variant"><Icon name="check_circle" className="text-[14px]" />استفاده‌شده</span>
    : r.expired ? <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-st-error-container px-st-space-sm py-1 text-[13px] font-semibold text-st-on-error-container"><Icon name="schedule" className="text-[14px]" />منقضی شده</span>
    : <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-st-secondary-fixed px-st-space-sm py-1 text-[13px] font-semibold text-st-on-secondary-fixed"><span className="h-1.5 w-1.5 rounded-full bg-st-secondary" />معتبر و آماده پرداخت</span>;
}

export default function ProformaListPage() {
  const { token, user, loading } = useAuth();
  const [rows, setRows] = useState<Row[] | null>(null), [err, setErr] = useState<string | null>(null);
  const [from, setFrom] = useState(""), [to, setTo] = useState(""), [q, setQ] = useState(""), [tab, setTab] = useState("all"), [page, setPage] = useState(0);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<{ done: number; total: number; kind: "zip" | "print" } | null>(null), [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [printDocs, setPrintDocs] = useState<Detail[] | null>(null);
  const donePrint = useCallback(() => setPrintDocs(null), []);
  const fromIso = from.trim() ? jalaliToIso(from) : null, toIso = to.trim() ? jalaliToIso(to) : null;
  const bad = (!!from.trim() && !fromIso) || (!!to.trim() && !toIso);

  useEffect(() => {
    if (!token || bad) return;
    let off = false; setRows(null); setErr(null);
    const qs = new URLSearchParams(); if (fromIso) qs.set("from", fromIso); if (toIso) qs.set("to", toIso);
    apiRequest<{ items: Row[] }>(`/me/proformas${qs.toString() ? "?" + qs : ""}`, { token })
      .then((r) => { if (!off) { setRows(r.items); setSel(new Set()); setPage(0); } })
      .catch((e) => !off && setErr(e instanceof Error ? e.message : "بارگذاری ناموفق بود"));
    return () => { off = true; };
  }, [token, fromIso, toIso, bad]);

  const filtered = useMemo(() => (rows ?? []).filter((r) => TABS.find((t) => t.k === tab)!.f(r) && (!q.trim() || [r.number, r.organization ?? "خرید شخصی"].join(" ").includes(q.trim()))), [rows, tab, q]);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE));
  const pageRows = filtered.slice(page * PAGE, page * PAGE + PAGE);
  const picked = (rows ?? []).filter((r) => sel.has(r.number));
  const pickedSum = picked.reduce((s, r) => s + r.total_minor, 0);
  const allOnPage = pageRows.length > 0 && pageRows.every((r) => sel.has(r.number));
  const toggle = (n: string) => setSel((s) => { const x = new Set(s); if (x.has(n)) x.delete(n); else x.add(n); return x; });
  const last30 = () => { const d = new Date(Date.now() - 30 * 864e5); setFrom(d.toLocaleDateString("fa-IR-u-ca-persian", { year: "numeric", month: "2-digit", day: "2-digit" })); setTo(""); };

  const fetchDetails = async (kind: "zip" | "print") => {
    const out: Detail[] = [];
    setBusy({ done: 0, total: picked.length, kind });
    for (const [i, r] of picked.entries()) {
      out.push({ ...r, ...(await apiRequest<Detail>(`/me/proformas/${encodeURIComponent(r.number)}`, { token: token! })) });
      setBusy({ done: i + 1, total: picked.length, kind });
    }
    return out;
  };
  const exportZip = async () => {
    if (!token || !picked.length) return;
    setMsg(null);
    try {
      const logo = await fetch("/brand/60online-mark.png").then((r) => r.blob()).then((b) => new Promise<string>((res) => { const f = new FileReader(); f.onload = () => res(String(f.result)); f.readAsDataURL(b); })).catch(() => "");
      const docs = await fetchDetails("zip");
      const csv = [["شماره", "تاریخ صدور", "معتبر تا", "خریدار", "وضعیت", "تعداد قلم", "مبلغ (ریال)"].join(",")];
      const files = docs.map((d) => ({ name: `${d.number}.html`, data: proformaHtml(d, logo) }));
      for (const r of picked) csv.push([r.number, faDate(r.created_at), faDate(r.valid_until), `"${(r.organization ?? "خرید شخصی").replace(/"/g, '""')}"`, state(r), r.item_count, r.total_minor].join(","));
      files.push({ name: "summary.csv", data: "﻿" + csv.join("\r\n") });
      downloadBlob(buildZip(files), `proformas-${new Date().toISOString().slice(0, 10)}.zip`);
      setMsg({ ok: true, text: `${fa(picked.length)} پیش‌فاکتور در فایل زیپ آماده شد.` });
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "ساخت فایل زیپ ناموفق بود" }); }
    finally { setBusy(null); }
  };
  const printAll = async () => {
    if (!token || !picked.length) return;
    setMsg(null);
    try { setPrintDocs(await fetchDetails("print")); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "آماده‌سازی چاپ ناموفق بود" }); } finally { setBusy(null); }
  };

  if (!loading && !user) return <main dir="rtl" className={cn(st.shell, "mx-auto max-w-[1440px] px-st-margin py-st-space-xl")}><div className="rounded-xl bg-st-surface-container-lowest p-st-space-lg shadow-sm"><h1 className="font-bold text-st-primary">پیش‌فاکتورهای رسمی</h1><p className="mt-1 text-st-on-surface-variant">برای مشاهده پیش‌فاکتورها وارد شوید.</p><Link href="/login?next=/me/proformas" className="mt-st-space-md inline-flex rounded-full bg-st-primary-container px-st-space-lg py-st-space-sm text-st-on-primary">ورود</Link></div></main>;

  return (
    <main dir="rtl" className={cn(st.shell, "mx-auto max-w-[1440px] bg-st-background px-st-space-md pb-28 pt-st-space-lg text-st-on-surface md:px-st-margin-lg md:pb-st-space-xl")}>
      <div className="flex flex-wrap items-center justify-between gap-st-space-sm text-[13px]">
        <nav aria-label="مسیر" className="flex items-center gap-1 text-st-on-surface-variant"><Link href="/account">حساب کاربری</Link><Icon name="chevron_left" className="text-[14px]" /><Link href="/org">اسناد و فاکتورهای رسمی</Link><Icon name="chevron_left" className="text-[14px]" /><span className="font-bold text-st-secondary">خروجی تجمیعی پیش‌فاکتورها</span></nav>
        <span className="inline-flex items-center gap-1 rounded-full bg-st-surface-container-low px-st-space-sm py-0.5 text-st-on-surface-variant"><span className="h-1.5 w-1.5 rounded-full bg-st-secondary" />ساخت فایل‌ها در مرورگر شما؛ بدون ارسال به سرور</span>
      </div>

      {/* Header */}
      <section className="mt-st-space-md flex flex-col justify-between gap-st-space-md rounded-xl bg-st-surface-container-lowest p-st-space-lg shadow-sm lg:flex-row lg:items-center">
        <div className="flex items-center gap-st-space-md">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <div className="hidden h-16 w-28 shrink-0 items-center justify-center rounded-xl border border-st-surface-container bg-st-surface p-2 sm:flex"><img src="/brand/60online-mark.png" alt="۶۰ آنلاین" className="h-full w-auto object-contain" /></div>
          <div><div className="flex flex-wrap items-center gap-st-space-sm"><h1 className="text-[20px] font-bold text-st-primary">مدیریت و صدور تجمیعی پیش‌فاکتورهای رسمی</h1>
            <span className="rounded-full bg-st-primary-container px-st-space-sm py-0.5 text-[12px] text-st-on-primary">پیش‌فاکتورهای من</span></div>
            <p className="text-st-on-surface-variant">انتخاب گروهی، تولید بسته زیپ قابل چاپ و فایل اکسل خلاصه برای حسابداری</p></div>
        </div>
        <div className="flex gap-st-space-sm">
          <div className="rounded-xl bg-st-surface-container-low px-st-space-md py-st-space-sm"><p className="text-[13px] text-st-outline">کل پیش‌فاکتورها</p><p className="font-bold text-st-primary">{rows ? fa(rows.length) : "…"} <span className="text-[13px] font-normal text-st-outline">فقره</span></p></div>
          <div className="rounded-xl bg-st-surface-container-low px-st-space-md py-st-space-sm"><p className="text-[13px] text-st-outline">مبلغ منتخب فعلی</p><p className="font-bold text-st-primary">{toman(pickedSum)} <span className="text-[13px] font-normal text-st-outline">تومان</span></p></div>
        </div>
      </section>

      {/* Batch progress (only while building) */}
      {busy && <section role="status" className="mt-st-space-md rounded-xl bg-st-surface-container-lowest p-st-space-lg shadow-sm">
        <div className="flex items-center gap-st-space-sm"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-st-secondary-fixed text-st-on-secondary-fixed"><Icon name="sync" className="animate-spin text-[22px]" /></div>
          <div><p className="font-bold text-st-primary">{busy.kind === "zip" ? "در حال آماده‌سازی و فشرده‌سازی پیش‌فاکتورها…" : "در حال آماده‌سازی برگه‌های چاپی A4…"}</p>
            <p className="text-[13px] text-st-on-surface-variant">{fa(busy.done)} از {fa(busy.total)} سند دریافت شد</p></div>
          <span className="mr-auto rounded-full bg-st-secondary-fixed px-st-space-sm py-0.5 text-[13px] text-st-on-secondary-fixed">٪{fa(Math.round((busy.done / Math.max(1, busy.total)) * 100))} تکمیل شده</span></div>
        <div className="mt-st-space-sm h-2 overflow-hidden rounded-full bg-st-surface-container"><div className="h-full rounded-full bg-st-secondary transition-all" style={{ width: `${(busy.done / Math.max(1, busy.total)) * 100}%` }} /></div>
      </section>}

      {/* Action bar */}
      <section className="mt-st-space-md flex flex-col justify-between gap-st-space-sm rounded-xl bg-st-surface-container-lowest p-st-space-md shadow-sm lg:flex-row lg:items-center">
        <div className="flex flex-wrap items-center gap-st-space-sm">
          <label className="inline-flex cursor-pointer items-center gap-st-space-xs rounded-lg border border-st-surface-container px-st-space-sm py-1.5 font-semibold text-st-primary">
            <input type="checkbox" className="h-4 w-4 rounded accent-[#266489]" checked={allOnPage} onChange={() => setSel((s) => { const x = new Set(s); pageRows.forEach((r) => (allOnPage ? x.delete(r.number) : x.add(r.number))); return x; })} />انتخاب همه در این صفحه</label>
          <span className="inline-flex items-center gap-1 rounded-lg bg-st-primary-container px-st-space-sm py-1.5 text-[14px] text-st-on-primary"><Icon name="check_circle" className="text-[16px]" />{fa(sel.size)} پیش‌فاکتور انتخاب شده</span>
          {sel.size > 0 && <button type="button" onClick={() => setSel(new Set())} className="text-[14px] text-st-outline hover:text-st-primary">پاک کردن انتخاب‌ها</button>}
        </div>
        <div className="flex flex-wrap items-center gap-st-space-sm">
          <button type="button" onClick={exportZip} disabled={!sel.size || !!busy} className="inline-flex items-center gap-st-space-xs rounded-lg bg-st-primary-container px-st-space-md py-st-space-sm font-semibold text-st-on-primary disabled:opacity-50"><Icon name="folder_zip" className="text-[18px]" />دانلود فایل ZIP پیش‌فاکتورها ({fa(sel.size)} سند)</button>
          <button type="button" onClick={printAll} disabled={!sel.size || !!busy} className="inline-flex items-center gap-st-space-xs rounded-lg border border-st-surface-container bg-st-surface-container-lowest px-st-space-md py-st-space-sm font-semibold text-st-primary disabled:opacity-50"><Icon name="print" className="text-[18px]" />چاپ تجمیعی A4</button>
          <button type="button" disabled title="اتصال به سامانه مودیان هنوز فعال نیست" className="inline-flex cursor-not-allowed items-center gap-st-space-xs rounded-lg bg-st-secondary-fixed px-st-space-md py-st-space-sm font-semibold text-st-on-secondary-fixed opacity-60"><Icon name="send" className="text-[18px]" />ارسال به سامانه مودیان (به‌زودی)</button>
        </div>
      </section>
      {msg && <p role={msg.ok ? "status" : "alert"} className={cn("mt-st-space-sm rounded-xl p-st-space-sm", msg.ok ? "bg-st-secondary-fixed text-st-on-secondary-fixed" : "bg-st-error-container text-st-on-error-container")}>{msg.text}</p>}

      {/* Filters + table */}
      <section className="mt-st-space-md overflow-hidden rounded-xl bg-st-surface-container-lowest shadow-sm">
        <div role="search" aria-label="فیلتر پیش‌فاکتورها" className="flex flex-col gap-st-space-sm p-st-space-md">
          <div className="flex flex-col gap-st-space-sm lg:flex-row">
            <label className="flex flex-1 items-center gap-st-space-xs rounded-xl border border-st-outline-variant px-st-space-sm"><Icon name="search" className="text-[20px] text-st-outline" />
              <input value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} type="search" aria-label="جستجو" placeholder="جستجو بر اساس نام سازمان یا شماره پیش‌فاکتور..." className="h-11 w-full border-0 bg-transparent p-0 outline-none placeholder:text-st-outline focus:ring-0" /></label>
            <div className={cn("flex items-center gap-st-space-xs rounded-xl bg-st-surface-container-low px-st-space-sm py-1", bad && "outline outline-1 outline-st-error")}>
              <Icon name="calendar_month" className="text-[18px] text-st-secondary" /><span className="text-[13px] text-st-on-surface-variant">از:</span>
              <input value={from} onChange={(e) => setFrom(e.target.value)} placeholder="۱۴۰۵/۰۸/۰۱" inputMode="numeric" aria-label="از تاریخ" aria-invalid={bad} className="w-24 border-0 bg-transparent p-0 text-center font-bold text-st-primary outline-none focus:ring-0" />
              <span className="text-[13px] text-st-on-surface-variant">تا:</span>
              <input value={to} onChange={(e) => setTo(e.target.value)} placeholder="۱۴۰۵/۰۸/۳۰" inputMode="numeric" aria-label="تا تاریخ" aria-invalid={bad} className="w-24 border-0 bg-transparent p-0 text-center font-bold text-st-primary outline-none focus:ring-0" />
              <button type="button" onClick={last30} className="rounded-lg bg-st-surface-container-lowest px-st-space-xs py-0.5 text-[12px] text-st-on-surface-variant">۳۰ روز اخیر</button>
            </div>
          </div>
          {bad && <p role="alert" className="text-[13px] text-st-error">تاریخ را به شکل سال/ماه/روز شمسی بنویسید؛ مثل ۱۴۰۵/۰۸/۰۱</p>}
          <div className="flex flex-wrap items-center justify-between gap-st-space-sm">
            <div className="flex flex-wrap items-center gap-st-space-xs"><span className="text-[13px] text-st-outline">وضعیت اسناد:</span>
              {TABS.map((t) => <button key={t.k} type="button" aria-pressed={tab === t.k} onClick={() => { setTab(t.k); setPage(0); }}
                className={cn("rounded-full px-st-space-sm py-1 text-[14px]", tab === t.k ? "bg-st-secondary font-bold text-st-on-secondary" : "bg-st-surface-container-low text-st-on-surface-variant hover:bg-st-surface-container")}>{t.l} ({fa((rows ?? []).filter(t.f).length)})</button>)}
            </div>
            <span className="flex items-center gap-1 text-[13px] text-st-outline"><Icon name="table_view" className="text-[16px]" />نمایش {fa(pageRows.length)} مورد از {fa(filtered.length)} سند</span>
          </div>
        </div>
        {err ? <p role="alert" className="p-st-space-lg text-st-error">{err}</p>
          : rows === null ? <p role="status" className="p-st-space-xl text-center text-st-outline">در حال بارگذاری…</p>
          : !rows.length ? <p className="p-st-space-xl text-center text-st-on-surface-variant">پیش‌فاکتوری در این بازه نیست. از سبد خرید «دریافت پیش‌فاکتور» را بزنید.</p>
          : <div className="overflow-x-auto"><table className="w-full border-collapse text-right">
            <thead><tr className="bg-st-surface-container-low text-[14px] text-st-on-surface-variant">
              <th scope="col" className="w-12 px-st-space-md py-st-space-sm"><span className="sr-only">انتخاب</span></th>
              {["شناسه سند رسمی", "خریدار حقوقی / شخصی", "تاریخ صدور و انقضا", "مبلغ کل با مالیات (تومان)", "وضعیت", "عملیات"].map((h) => <th key={h} scope="col" className="px-st-space-md py-st-space-sm font-semibold">{h}</th>)}</tr></thead>
            <tbody>{pageRows.map((r) => (
              <tr key={r.number} className={cn("border-t border-st-surface-container-low transition-colors hover:bg-st-surface", sel.has(r.number) && "bg-st-surface")}>
                <td className="px-st-space-md py-st-space-sm"><input type="checkbox" className="h-5 w-5 rounded accent-[#266489]" checked={sel.has(r.number)} onChange={() => toggle(r.number)} aria-label={`انتخاب ${r.number}`} /></td>
                <td className="px-st-space-md py-st-space-sm"><div className="flex items-center gap-st-space-xs"><Icon name="description" className="text-[20px] text-st-secondary" />
                  <div><Link href={`/me/proformas/${encodeURIComponent(r.number)}`} className="block font-bold text-st-primary hover:underline" dir="ltr" style={{ textAlign: "right" }}>{r.number}</Link><span className="text-[12px] text-st-outline">{fa(r.item_count)} قلم کالا</span></div></div></td>
                <td className="px-st-space-md py-st-space-sm"><p className="font-bold text-st-primary">{r.organization ?? "خرید شخصی"}</p><p className="text-[12px] text-st-secondary">{r.organization ? "خرید سازمانی" : "حساب شخصی"}</p></td>
                <td className="px-st-space-md py-st-space-sm"><p className="text-st-primary">{faDate(r.created_at)}</p><p className="flex items-center gap-1 text-[12px] text-st-secondary"><Icon name="schedule" className="text-[14px]" />اعتبار تا {faDate(r.valid_until)}</p></td>
                <td className="px-st-space-md py-st-space-sm"><p className="font-bold text-st-primary">{toman(r.total_minor)}</p><p className="text-[12px] text-st-outline">شامل مالیات و ارسال</p></td>
                <td className="px-st-space-md py-st-space-sm"><StatusPill r={r} /></td>
                <td className="px-st-space-md py-st-space-sm"><div className="flex items-center gap-st-space-xs">
                  <Link href={`/me/proformas/${encodeURIComponent(r.number)}`} aria-label={`مشاهده ${r.number}`} title="مشاهده" className="flex h-9 w-9 items-center justify-center rounded-lg text-st-on-surface-variant hover:bg-st-surface-container"><Icon name="visibility" className="text-[20px]" /></Link>
                  <Link href={`/me/proformas/${encodeURIComponent(r.number)}?print=1`} aria-label={`چاپ ${r.number}`} title="چاپ A4" className="flex h-9 w-9 items-center justify-center rounded-lg text-st-on-surface-variant hover:bg-st-surface-container"><Icon name="print" className="text-[20px]" /></Link>
                </div></td>
              </tr>))}
              {!pageRows.length && <tr><td colSpan={7} className="p-st-space-xl text-center text-st-on-surface-variant">موردی با این فیلتر پیدا نشد.</td></tr>}
            </tbody></table></div>}
        {rows && rows.length > 0 && <div className="flex flex-wrap items-center justify-between gap-st-space-sm border-t border-st-surface-container-low p-st-space-md text-[14px] text-st-on-surface-variant">
          <div className="flex items-center gap-st-space-xs">
            <button type="button" aria-label="صفحه قبل" disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="flex h-9 w-9 items-center justify-center rounded-lg border border-st-surface-container disabled:opacity-40"><Icon name="chevron_right" className="text-[18px]" /></button>
            {Array.from({ length: pages }, (_, i) => i).slice(0, 7).map((i) => <button key={i} type="button" aria-current={page === i ? "page" : undefined} onClick={() => setPage(i)} className={cn("flex h-9 w-9 items-center justify-center rounded-lg", page === i ? "bg-st-primary-container font-bold text-st-on-primary" : "border border-st-surface-container")}>{fa(i + 1)}</button>)}
            <button type="button" aria-label="صفحه بعد" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)} className="flex h-9 w-9 items-center justify-center rounded-lg border border-st-surface-container disabled:opacity-40"><Icon name="chevron_left" className="text-[18px]" /></button>
          </div>
          <span>نمایش صفحه {fa(page + 1)} از {fa(pages)} (مجموع {fa(filtered.length)} پیش‌فاکتور) | تعداد ردیف در هر صفحه: {fa(PAGE)}</span>
        </div>}
      </section>

      <div className="mt-st-space-lg grid gap-st-space-md md:grid-cols-3">
        {[["inventory_2", "بسته زیپ قابل چاپ", "هر پیش‌فاکتور یک صفحه HTML مستقل دارد که در هر مرورگر با «چاپ ← ذخیره به PDF» فارسی درست خروجی می‌دهد."],
          ["table_view", "خلاصه اکسل برای حسابداری", "فایل summary.csv با شماره، تاریخ، خریدار، وضعیت و مبلغ ریالی همه اسناد انتخاب‌شده."],
          ["qr_code_2", "بارکد شماره سند", "برگه چاپی A4 بارکد Code128 شماره پیش‌فاکتور را برای ثبت و بایگانی سریع دارد."]].map(([i, t, d]) => (
          <div key={t} className="rounded-xl bg-st-surface-container-lowest p-st-space-lg shadow-sm"><div className="flex items-center gap-st-space-xs"><Icon name={i} className="text-[22px] text-st-secondary" /><h2 className="font-bold text-st-primary">{t}</h2></div><p className="mt-1 text-[14px] text-st-on-surface-variant">{d}</p></div>))}
      </div>
      {printDocs && <PrintSheet onDone={donePrint}>{printDocs.map((d) => <ProformaSheet key={d.number} p={d} buyer={user?.full_name} />)}</PrintSheet>}
    </main>
  );
}
