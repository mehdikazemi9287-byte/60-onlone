"use client";

// Proforma history + batch export (Stitch 2026-11). Data: GET /me/proformas (owner-scoped) and GET /me/proformas/{n}.
// The ZIP holds one self-contained, printable HTML per proforma (opens in any browser; «Print → Save as PDF»
// keeps Persian text correct) plus summary.csv (Excel-compatible). Built in the browser; nothing is uploaded.
import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronLeft, FileArchive, Loader2 } from "lucide-react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { jalaliToIso } from "@/lib/jalali";
import { buildZip, downloadBlob } from "@/lib/zip";
import { cn, faDate, formatPrice, toPersianNum } from "@/lib/utils";

type Row = { number: string; organization: string | null; created_at: string; valid_until: string; expired: boolean; used: boolean; total_minor: number; item_count: number };
type Detail = Row & { items: { title_fa: string; sku: string; quantity: number; unit_price_minor: number; line_total_minor: number }[];
  subtotal_minor: number; shipping_fee_minor: number; tax_minor: number };

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const state = (r: Row) => (r.used ? "استفاده‌شده" : r.expired ? "منقضی‌شده" : "معتبر");

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

export default function ProformaListPage() {
  const { token } = useAuth();
  const [rows, setRows] = useState<Row[] | null>(null), [err, setErr] = useState<string | null>(null);
  const [from, setFrom] = useState(""), [to, setTo] = useState("");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<{ done: number; total: number } | null>(null), [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const fromIso = from.trim() ? jalaliToIso(from) : null, toIso = to.trim() ? jalaliToIso(to) : null;
  const bad = (!!from.trim() && !fromIso) || (!!to.trim() && !toIso);

  useEffect(() => {
    if (!token || bad) return;
    let off = false; setRows(null); setErr(null);
    const q = new URLSearchParams(); if (fromIso) q.set("from", fromIso); if (toIso) q.set("to", toIso);
    apiRequest<{ items: Row[] }>(`/me/proformas${q.toString() ? "?" + q : ""}`, { token })
      .then((r) => { if (!off) { setRows(r.items); setSel(new Set()); } })
      .catch((e) => !off && setErr(e instanceof Error ? e.message : "بارگذاری ناموفق بود"));
    return () => { off = true; };
  }, [token, fromIso, toIso, bad]);

  const toggle = (n: string) => setSel((s) => { const x = new Set(s); if (x.has(n)) x.delete(n); else x.add(n); return x; });
  const all = !!rows?.length && sel.size === rows.length;

  const exportZip = async () => {
    if (!token || !rows || !sel.size) return;
    setMsg(null);
    const picked = rows.filter((r) => sel.has(r.number));
    setBusy({ done: 0, total: picked.length });
    try {
      const logo = await fetch("/brand/60online-mark.png").then((r) => r.blob()).then((b) => new Promise<string>((res) => { const f = new FileReader(); f.onload = () => res(String(f.result)); f.readAsDataURL(b); })).catch(() => "");
      const files: { name: string; data: string }[] = [];
      const csv = [["شماره", "تاریخ صدور", "معتبر تا", "خریدار", "وضعیت", "تعداد قلم", "مبلغ (ریال)"].join(",")];
      for (const [i, r] of picked.entries()) {
        const d = await apiRequest<Detail>(`/me/proformas/${encodeURIComponent(r.number)}`, { token });
        files.push({ name: `${r.number}.html`, data: proformaHtml({ ...r, ...d }, logo) });
        csv.push([r.number, faDate(r.created_at), faDate(r.valid_until), `"${(r.organization ?? "خرید شخصی").replace(/"/g, '""')}"`, state(r), r.item_count, r.total_minor].join(","));
        setBusy({ done: i + 1, total: picked.length });
      }
      files.push({ name: "summary.csv", data: "﻿" + csv.join("\r\n") });
      downloadBlob(buildZip(files), `proformas-${new Date().toISOString().slice(0, 10)}.zip`);
      setMsg({ ok: true, text: `${toPersianNum(picked.length)} پیش‌فاکتور در فایل زیپ آماده شد.` });
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "ساخت فایل زیپ ناموفق بود" }); }
    finally { setBusy(null); }
  };

  return (
    <main className="mx-auto max-w-4xl px-4 pb-28 pt-6 md:py-10">
      <nav aria-label="مسیر" className="page-breadcrumb"><Link href="/account">حساب کاربری</Link><ChevronLeft className="h-3 w-3" /><span>پیش‌فاکتورها</span></nav>
      <h1 className="text-2xl font-extrabold text-ink">پیش‌فاکتورهای من</h1>
      <p className="mt-1 text-sm text-ink-muted">پیش‌فاکتورهای رسمی را انتخاب کنید و یکجا در قالب فایل زیپ دریافت کنید.</p>

      <div role="search" aria-label="فیلتر تاریخ" className="mt-5 grid grid-cols-2 gap-2 rounded-2xl border border-line bg-white p-3 md:max-w-md">
        <label className="grid gap-1 text-[11px] font-semibold text-ink-muted">از تاریخ<input value={from} onChange={(e) => setFrom(e.target.value)} placeholder="۱۴۰۵/۰۸/۰۱" inputMode="numeric" aria-invalid={!!from.trim() && !fromIso} className="form-input text-sm" /></label>
        <label className="grid gap-1 text-[11px] font-semibold text-ink-muted">تا تاریخ<input value={to} onChange={(e) => setTo(e.target.value)} placeholder="۱۴۰۵/۰۸/۳۰" inputMode="numeric" aria-invalid={!!to.trim() && !toIso} className="form-input text-sm" /></label>
        {bad && <p role="alert" className="col-span-2 text-xs text-red-700">تاریخ را به شکل سال/ماه/روز شمسی بنویسید؛ مثل ۱۴۰۵/۰۸/۰۱</p>}
      </div>

      <section aria-label="فهرست پیش‌فاکتورها" className="mt-4 overflow-hidden rounded-3xl border border-line bg-white">
        {err ? <p role="alert" className="p-6 text-sm text-red-700">{err}</p>
          : rows === null ? <p role="status" className="p-8 text-center text-sm text-ink-faint">در حال بارگذاری…</p>
          : !rows.length ? <p className="p-10 text-center text-sm text-ink-muted">پیش‌فاکتوری در این بازه نیست. از سبد خرید «دریافت پیش‌فاکتور» را بزنید.</p>
          : <>
            <label className="flex min-h-12 cursor-pointer items-center gap-3 border-b border-line bg-canvas px-4 text-sm font-semibold text-ink-soft">
              <input type="checkbox" className="h-5 w-5" checked={all} onChange={() => setSel(all ? new Set() : new Set(rows.map((r) => r.number)))} />انتخاب همه ({toPersianNum(rows.length)})</label>
            <ul className="divide-y divide-line">{rows.map((r) => (
              <li key={r.number} className={cn("flex items-center gap-3 px-4 py-3", sel.has(r.number) && "bg-canvas")}>
                <input type="checkbox" className="h-5 w-5 shrink-0" checked={sel.has(r.number)} onChange={() => toggle(r.number)} aria-label={`انتخاب ${r.number}`} />
                <Link href={`/me/proformas/${encodeURIComponent(r.number)}`} className="min-w-0 flex-1">
                  <span className="block font-mono text-[13px] font-bold text-ink" dir="ltr" style={{ textAlign: "right" }}>{r.number}</span>
                  <span className="text-xs text-ink-muted">{faDate(r.created_at)} · {toPersianNum(r.item_count)} قلم · {r.organization ?? "خرید شخصی"}</span>
                </Link>
                <div className="text-left"><b className="block text-sm text-ink tabular-nums">{formatPrice(r.total_minor)}</b>
                  <span className={cn("text-[11px] font-bold", r.used ? "text-ink-muted" : r.expired ? "text-amber-700" : "text-emerald-700")}>{state(r)}</span></div>
              </li>))}</ul>
          </>}
      </section>
      {msg && <p role={msg.ok ? "status" : "alert"} className={cn("mt-3 rounded-xl p-3 text-sm", msg.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700")}>{msg.text}</p>}

      {sel.size > 0 && (
        <div className="sticky bottom-[calc(76px+env(safe-area-inset-bottom))] z-10 mt-4 flex items-center gap-3 rounded-3xl border border-line bg-white/95 p-3 backdrop-blur md:bottom-6">
          <span className="flex-1 text-sm font-semibold text-ink">{toPersianNum(sel.size)} پیش‌فاکتور انتخاب شده</span>
          <button type="button" onClick={exportZip} disabled={!!busy} className="inline-flex min-h-11 items-center gap-2 rounded-full bg-ink px-5 text-sm font-bold text-white disabled:opacity-60">
            {busy ? <><Loader2 className="h-4 w-4 animate-spin" />در حال ساخت {toPersianNum(busy.done)} از {toPersianNum(busy.total)}</> : <><FileArchive className="h-4 w-4" />دانلود زیپ</>}</button>
        </div>)}
      <p className="mt-3 text-[11px] text-ink-faint">فایل زیپ برای هر پیش‌فاکتور یک صفحهٔ HTML قابل چاپ (با «چاپ ← ذخیره به PDF» در هر مرورگر) و یک فایل summary.csv برای اکسل دارد.</p>
    </main>
  );
}
