"use client";
// قراردادهای تأمین دوره‌ای — faithful to Stitch screens 25 (list) + 19 (date/frequency/status filters, Excel export).
// Organization view over REAL data only:
//   GET /orgs/{id}/credit-contract  (the organization's credit contract, finance roles only)
//   GET /me/recurring               (the caller's recurring lists; filtered to this organization)
//   POST /me/recurring {organization_id}, /me/recurring/{id}/{pause|resume|cancel}, /quote, /runs
// Lists belong to the member who created them (server rule); this page does not show other members' lists.
// Stitch's "savings" KPI and named account manager have no backend: replaced by the real credit contract and
// generic support links. The draft PDF opens the A4 viewer (screens 32 / 10).
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { jalaliToIso } from "@/lib/jalali";
import { useAuth } from "@/lib/auth-context";
import { apiRequest, errText, FREQ_FA, RECUR_FA, type CreditContract, type DraftQuote, type RecurringList } from "@/lib/commerce";
import { cn, faDate } from "@/lib/utils";
import { NewList, QuoteView, ReadyRun } from "@/components/commerce/Recurring";
import { useOrganization } from "./Dashboard";
import { Icon, fa, tomanDigits } from "./OrgDashboard";
import ContractDraftViewer, { type DraftOrg } from "./ContractDraft";

const FREQ_LONG: Record<string, string> = { weekly: "هفتگی", biweekly: "دو هفته یک‌بار", monthly: "ماهانه" };
const ICONS = ["inventory_2", "local_mall", "cleaning_services", "coffee"];
const chip = "inline-flex items-center gap-1 rounded-lg border border-st-surface-container-low bg-st-surface px-st-space-sm py-1 text-st-on-surface";
const ghost = "rounded-lg bg-st-surface-container-low px-st-space-md py-1.5 font-semibold text-st-primary transition-colors hover:bg-st-surface-container disabled:opacity-50";

export default function SupplyContracts() {
  const { user } = useAuth();
  return <Body key={user?.id ?? "guest"} />;
}

function Body() {
  const o = useOrganization();
  const { token } = useAuth();
  const orgId = o.selected ? Number(o.selected) : null;
  const isFinance = ["organization_admin", "organization_finance"].includes(o.org?.membership.role ?? "");
  const [contract, setContract] = useState<CreditContract | null | undefined>(undefined);
  const [lists, setLists] = useState<RecurringList[] | null>(null), [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0), [flash, setFlash] = useState<{ ok: boolean; text: string } | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [quote, setQuote] = useState<{ id: number; q: DraftQuote | null; err?: string } | null>(null);
  const [from, setFrom] = useState(""), [to, setTo] = useState(""), [freq, setFreq] = useState(""), [stf, setStf] = useState("");
  const fromIso = from.trim() ? jalaliToIso(from) : null, toIso = to.trim() ? jalaliToIso(to) : null;
  const badFrom = !!from.trim() && !fromIso, badTo = !!to.trim() && !toIso;
  const shown = lists?.filter((l) => (!freq || l.frequency === freq) && (!stf || l.status === stf)
    && (!fromIso || l.next_run_on >= fromIso) && (!toIso || l.next_run_on <= toIso))
    .sort((a, b) => (a.status === b.status ? a.next_run_on.localeCompare(b.next_run_on) : a.status === "active" ? -1 : 1)) ?? null;

  const [draft, setDraft] = useState<{ list: RecurringList; quote: DraftQuote | null } | null>(null);
  const printDraft = async (l: RecurringList) => {
    if (!token) return;
    let q: DraftQuote | null = null;
    try { q = (await apiRequest<{ quote: DraftQuote }>(`/me/recurring/${l.id}/quote`, { token })).quote; } catch { /* sheet shows «—» */ }
    setDraft({ list: l, quote: q });
  };
  const closeDraft = useCallback(() => setDraft(null), []);

  const exportCsv = () => {
    if (!shown?.length) return;
    // Excel-compatible CSV (UTF-8 with BOM so Persian text opens correctly in Excel).
    const esc = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`;
    const rows = [["عنوان", "دوره", "وضعیت", "نوبت بعدی", "آخرین نوبت", "کالا", "تعداد"].map(esc).join(",")];
    for (const l of shown) for (const it of l.items) rows.push([l.title, FREQ_FA[l.frequency], RECUR_FA[l.status], faDate(l.next_run_on), l.last_run_on ? faDate(l.last_run_on) : "", it.title_fa, it.quantity].map(esc).join(","));
    const blob = new Blob(["﻿" + rows.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `supply-contracts-${o.org?.display_name ?? orgId}-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  useEffect(() => {
    if (!token || !orgId) return;
    let off = false;
    setContract(undefined); setLists(null); setError(null);
    if (isFinance) apiRequest<{ contract: CreditContract | null }>(`/orgs/${orgId}/credit-contract`, { token })
      .then((r) => !off && setContract(r.contract)).catch(() => !off && setContract(null));
    else setContract(null);
    apiRequest<{ items: RecurringList[] }>("/me/recurring", { token })
      .then((r) => !off && setLists(r.items.filter((l) => l.organization_id === orgId && l.status !== "cancelled")))
      .catch((e) => !off && setError(errText(e, "بارگذاری فهرست‌ها ناموفق بود")));
    return () => { off = true; };
  }, [token, orgId, retry, isFinance]);

  const act = async (l: RecurringList, action: "pause" | "resume" | "cancel") => {
    if (!token) return;
    if (action === "cancel" && !window.confirm(`فهرست «${l.title}» لغو شود؟ این کار برگشت ندارد.`)) return;
    setBusyId(l.id); setFlash(null);
    try {
      const { list } = await apiRequest<{ list: RecurringList }>(`/me/recurring/${l.id}/${action}`, { token, method: "POST" });
      setLists((cur) => cur && (list.status === "cancelled" ? cur.filter((x) => x.id !== l.id) : cur.map((x) => (x.id === l.id ? list : x))));
      setFlash({ ok: true, text: action === "pause" ? "تأمین دوره‌ای متوقف شد." : action === "resume" ? "تأمین دوره‌ای دوباره فعال شد." : "فهرست لغو شد." });
    } catch (e) { setFlash({ ok: false, text: errText(e) }); } finally { setBusyId(null); }
  };
  const showQuote = async (id: number) => {
    if (!token) return;
    if (quote?.id === id) { setQuote(null); return; }
    setQuote({ id, q: null });
    try { const r = await apiRequest<{ quote: DraftQuote }>(`/me/recurring/${id}/quote`, { token }); setQuote((c) => (c?.id === id ? { id, q: r.quote } : c)); }
    catch (e) { setQuote((c) => (c?.id === id ? { id, q: null, err: errText(e) } : c)); }
  };

  const active = lists?.filter((l) => l.status === "active") ?? [];
  const paused = lists?.filter((l) => l.status === "paused") ?? [];
  const next = active.map((l) => l.next_run_on).sort()[0];
  const segBtn = (on: boolean) => cn("rounded-md px-st-space-sm py-1 transition-all", on ? "bg-st-surface-container-lowest font-bold text-st-primary shadow-sm" : "text-st-on-surface-variant hover:text-st-primary");
  const pill = (on: boolean) => cn("rounded-full px-st-space-sm py-1 transition-colors", on ? "bg-st-primary-container font-semibold text-st-on-primary" : "bg-st-surface-container-low text-st-on-surface-variant hover:bg-st-surface-container");

  return (
    <div dir="rtl" className="flex w-full flex-col gap-st-space-xl">
      {/* Banner */}
      <section className="relative overflow-hidden rounded-xl border border-st-surface-container-low bg-st-surface-container-lowest p-st-space-lg shadow-sm">
        <div className="flex flex-col justify-between gap-st-space-md lg:flex-row lg:items-center">
          <div className="flex min-w-0 flex-col gap-st-space-xs">
            <div className="flex items-center gap-st-space-xs"><span className="inline-flex h-2 w-2 rounded-full bg-st-secondary" /><span className="font-bold text-st-secondary">مدیریت زنجیره تأمین پیوسته • پیش‌فاکتور خودکار</span></div>
            <h1 className="font-bold text-st-primary">قراردادهای تأمین هوشمند و شارژ خودکار اقلام سازمان</h1>
            <p className="text-st-on-surface-variant">اقلام تکراری سازمان را یک‌بار تعریف کنید؛ در هر دوره پیش‌فاکتور با قیمت روز ساخته می‌شود و تا تأیید شما پرداختی انجام نمی‌شود.</p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-st-space-sm">
            {o.orgs.length > 1 && <select aria-label="سازمان فعال" value={o.selected} onChange={(e) => o.setSelected(e.target.value)} className="rounded-xl border border-st-surface-container bg-st-surface-container-low px-st-space-sm py-st-space-sm text-st-primary">{o.orgs.map((x) => <option key={x.id} value={x.id}>{x.display_name}</option>)}</select>}
            <a href="#new-list" className="inline-flex items-center gap-st-space-xs rounded-xl bg-st-primary-container px-st-space-lg py-st-space-sm text-st-on-primary shadow-sm transition-colors hover:bg-st-secondary"><Icon name="add" className="text-[20px]" /><span>ثبت قرارداد تأمین جدید</span></a>
          </div>
        </div>
      </section>

      {o.error && <p role="alert" className="rounded-xl bg-st-error-container p-st-space-md text-st-on-error-container">{o.error} <button className="underline" onClick={o.retry}>تلاش مجدد</button></p>}
      {!o.loading && token && !o.orgs.length && !o.error && <p className="rounded-xl bg-st-surface-container-lowest p-st-space-lg text-st-on-surface-variant shadow-sm">عضویت فعال سازمانی برای این حساب یافت نشد.</p>}
      {flash && <p role={flash.ok ? "status" : "alert"} className={cn("rounded-xl p-st-space-md", flash.ok ? "bg-st-secondary-fixed text-st-on-secondary-fixed" : "bg-st-error-container text-st-on-error-container")}>{flash.text}</p>}

      {token && orgId && <>
        {/* KPIs */}
        <div className="grid grid-cols-1 gap-st-space-md md:grid-cols-3">
          <div className="flex items-center justify-between rounded-xl border border-st-surface-container-low bg-st-surface-container-lowest p-st-space-lg shadow-sm">
            <div className="flex flex-col gap-st-space-xs"><span className="text-st-outline">قراردادهای فعال دوره جاری</span>
              <div className="flex items-baseline gap-st-space-xs"><span className="font-bold text-st-primary">{lists ? fa(lists.length) : "…"}</span><span className="font-bold text-st-secondary">فهرست تأمین سازمان</span></div>
              <span className="text-st-on-surface-variant">{fa(active.length)} فعال هم‌اکنون • {fa(paused.length)} متوقف موقت</span></div>
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-st-secondary-fixed text-st-on-secondary-fixed"><Icon name="assignment_turned_in" className="text-[24px]" /></div>
          </div>
          <div className="flex items-center justify-between rounded-xl border border-st-surface-container-low bg-st-surface-container-lowest p-st-space-lg shadow-sm">
            <div className="flex flex-col gap-st-space-xs"><span className="text-st-outline">تاریخ تحویل محموله بعدی</span>
              <span className="font-bold text-st-primary">{next ? faDate(next) : "نوبت فعالی نیست"}</span>
              <div className="flex items-center gap-1 font-bold text-st-secondary"><Icon name="local_shipping" className="text-[16px]" /><span>{next ? "پیش‌فاکتور هر نوبت برای تأیید شما ساخته می‌شود" : "فهرستی را فعال کنید"}</span></div></div>
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-st-primary-container text-st-on-primary"><Icon name="event_upcoming" className="text-[24px]" /></div>
          </div>
          <div className="flex items-center justify-between rounded-xl border border-st-surface-container-low bg-st-surface-container-lowest p-st-space-lg shadow-sm">
            <div className="flex flex-col gap-st-space-xs"><span className="text-st-outline">قرارداد اعتباری سازمان</span>
              {!isFinance ? <><span className="font-bold text-st-primary">ویژه مدیر و مالی</span><span className="text-st-on-surface-variant">جزئیات اعتبار فقط برای نقش مالی نمایش داده می‌شود</span></>
                : contract === undefined ? <span className="text-st-outline">…</span>
                : contract ? <><div className="flex items-baseline gap-st-space-xs"><span className="font-bold text-st-primary">{tomanDigits(contract.headroom_minor)}</span><span className="font-bold text-st-tertiary-container">تومان مانده قابل استفاده</span></div>
                  <span className="text-st-on-surface-variant">سقف {tomanDigits(contract.effective_limit_minor ?? contract.limit_minor)} تومان • مهلت پرداخت {fa(contract.due_days)} روز</span></>
                : <><span className="font-bold text-st-primary">ثبت نشده</span><span className="text-st-on-surface-variant">پرداخت هر نوبت پس از تأیید پیش‌فاکتور</span></>}</div>
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-st-surface-container-high text-st-primary"><Icon name="account_balance_wallet" className="text-[24px]" /></div>
          </div>
        </div>

        <div className="flex flex-col gap-st-space-md">
          {/* Filter toolbar (screen 19) */}
          <div role="search" aria-label="فیلتر قراردادها" className="flex flex-col justify-between gap-st-space-md rounded-xl border border-st-surface-container bg-st-surface-container-lowest p-st-space-md shadow-sm xl:flex-row xl:items-center">
            <div className="flex flex-wrap items-center gap-st-space-md">
              <div className="flex flex-wrap items-center gap-st-space-xs"><Icon name="calendar_today" className="text-[18px] text-st-outline" /><span className="text-st-outline">بازه تاریخی:</span>
                {([["از:", from, setFrom, badFrom, "۱۴۰۵/۰۸/۰۱"], ["تا:", to, setTo, badTo, "۱۴۰۵/۰۸/۳۰"]] as [string, string, (v: string) => void, boolean, string][]).map(([lab, v, set, bad, ph]) => (
                  <label key={lab} className={cn("flex items-center gap-1 rounded-lg border bg-st-surface-container-low px-st-space-sm py-1", bad ? "border-st-error" : "border-st-surface-container")}>
                    <span className="text-st-on-surface-variant">{lab}</span>
                    <input value={v} onChange={(e) => set(e.target.value)} placeholder={ph} inputMode="numeric" aria-invalid={bad} aria-label={`نوبت بعدی ${lab}`} className="w-24 border-0 bg-transparent p-0 text-center text-st-primary outline-none placeholder:text-st-outline focus:ring-0" />
                    <Icon name="event" className="text-[14px] text-st-outline" /></label>))}
              </div>
              <div className="flex flex-wrap items-center gap-st-space-xs"><span className="text-st-outline">تناوب:</span>
                <div className="flex items-center rounded-lg border border-st-surface-container bg-st-surface-container-low p-0.5">
                  <button type="button" aria-pressed={!freq} onClick={() => setFreq("")} className={segBtn(!freq)}>همه دوره‌ها</button>
                  {Object.entries(FREQ_FA).map(([k, v]) => <button key={k} type="button" aria-pressed={freq === k} onClick={() => setFreq(k)} className={segBtn(freq === k)}>{v}</button>)}
                </div></div>
              <div className="flex items-center gap-st-space-xs"><span className="text-st-outline">وضعیت:</span>
                <div className="flex items-center gap-1">{[["", "همه"], ["active", "در جریان"], ["paused", "متوقف موقت"]].map(([k, v]) =>
                  <button key={k} type="button" aria-pressed={stf === k} onClick={() => setStf(k)} className={pill(stf === k)}>{v}</button>)}</div></div>
            </div>
            <button type="button" onClick={exportCsv} disabled={!shown?.length} className="inline-flex shrink-0 items-center gap-st-space-xs self-start rounded-lg border border-st-surface-container bg-st-surface-container-lowest px-st-space-md py-1.5 font-semibold text-st-primary shadow-sm transition-colors hover:bg-st-surface-container-low disabled:opacity-50 xl:self-auto">
              <Icon name="table_view" className="text-[18px] text-st-secondary" /><span>خروجی اکسل اقلام و فهرست‌ها</span></button>
          </div>
          {(badFrom || badTo) && <p role="alert" className="text-st-error">تاریخ را به شکل سال/ماه/روز شمسی بنویسید؛ مثل ۱۴۰۵/۰۸/۰۱</p>}

          <div className="flex flex-col justify-between gap-st-space-sm sm:flex-row sm:items-center">
            <div className="flex items-center gap-st-space-sm"><h2 className="font-bold text-st-primary">فهرست قراردادهای جاری سازمان</h2>
              <span className="rounded-full bg-st-surface-container px-st-space-xs py-0.5 text-st-on-surface-variant">{fa(shown?.length ?? 0)} فهرست</span></div>
            <div className="flex items-center gap-st-space-xs"><span className="text-st-outline">مرتب‌سازی بر اساس:</span><span className="font-bold text-st-primary">موعد تحویل نزدیک</span></div>
          </div>

          {error ? <p role="alert" className="rounded-xl bg-st-error-container p-st-space-md text-st-on-error-container">{error} <button className="underline" onClick={() => setRetry((x) => x + 1)}>تلاش مجدد</button></p>
            : shown === null ? <p role="status" className="text-st-outline">در حال دریافت فهرست‌ها…</p>
            : !shown.length ? <div className="rounded-xl border border-st-surface-container bg-st-surface-container-lowest p-st-space-xl text-center text-st-on-surface-variant shadow-sm">{lists?.length ? "هیچ فهرستی با این فیلترها پیدا نشد." : "هنوز فهرست تأمین دوره‌ای برای این سازمان تعریف نکرده‌اید."}</div>
            : shown.map((l, idx) => { const on = l.status === "active"; return (
              <article key={l.id} className="flex flex-col gap-st-space-md rounded-xl border border-st-surface-container bg-st-surface-container-lowest p-st-space-lg shadow-sm transition-all hover:border-st-secondary">
                <div className="flex flex-col justify-between gap-st-space-md border-b border-st-surface-container-low pb-st-space-md lg:flex-row lg:items-center">
                  <div className="flex items-start gap-st-space-md">
                    <div className={cn("flex h-12 w-12 shrink-0 items-center justify-center rounded-xl", idx === 0 && on ? "bg-st-primary-container text-st-on-primary" : "bg-st-surface-container text-st-primary")}><Icon name={ICONS[idx % ICONS.length]} className="text-[24px]" /></div>
                    <div className="flex flex-col gap-1">
                      <div className="flex flex-wrap items-center gap-st-space-xs"><h3 className="font-bold text-st-primary">{l.title}</h3>
                        <span className={cn("rounded-full px-st-space-xs py-0.5 font-semibold", l.frequency === "monthly" ? "bg-st-surface-container text-st-on-surface-variant" : "bg-st-secondary-fixed text-st-on-secondary-fixed")}>دوره: {FREQ_LONG[l.frequency]}</span>
                        {on ? <span className="inline-flex items-center gap-1 rounded-full bg-st-surface-container-low px-st-space-xs py-0.5 font-bold text-st-secondary"><span className="h-2 w-2 rounded-full bg-st-secondary" />فعال و در جریان</span>
                          : <span className="inline-flex items-center gap-1 rounded-full bg-st-error-container px-st-space-xs py-0.5 font-bold text-st-error"><Icon name="pause_circle" className="text-[14px]" />متوقف موقت</span>}
                      </div>
                      <div className="flex flex-wrap items-center gap-st-space-md text-st-on-surface-variant">
                        <span>کد فهرست: <b className="text-st-primary" dir="ltr">RC-{fa(l.id)}</b></span><span>•</span>
                        <span>اقلام: <b className="text-st-primary">{fa(l.items.length)} قلم</b></span><span>•</span>
                        {on ? <span className="font-semibold text-st-secondary">تاریخ تحویل بعدی: {faDate(l.next_run_on)}</span>
                          : <span className="text-st-outline">آخرین نوبت: {l.last_run_on ? faDate(l.last_run_on) : "هنوز اجرا نشده"} (در انتظار ازسرگیری)</span>}
                      </div>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-st-space-xs self-start lg:self-center">
                    {on ? <button type="button" aria-expanded={quote?.id === l.id} onClick={() => showQuote(l.id)} className="inline-flex items-center gap-1 rounded-lg bg-st-surface-container px-st-space-sm py-1.5 font-semibold text-st-primary transition-colors hover:bg-st-surface-container-high"><Icon name="receipt_long" className="text-[16px]" /><span>پیش‌نمایش پیش‌فاکتور نوبت</span></button>
                      : <button type="button" disabled={busyId === l.id} onClick={() => act(l, "resume")} className="inline-flex items-center gap-1 rounded-lg bg-st-secondary px-st-space-md py-1.5 font-bold text-st-on-secondary shadow-sm transition-colors hover:bg-st-primary-container disabled:opacity-50"><Icon name="play_arrow" className="text-[18px]" /><span>ازسرگیری قرارداد</span></button>}
                  </div>
                </div>
                {!on && <div className="flex items-center gap-st-space-xs rounded-lg border border-st-surface-container bg-st-surface-container-low p-st-space-sm text-st-on-surface-variant"><Icon name="info" className="text-[18px] text-st-outline" /><span>این فهرست متوقف است؛ تا ازسرگیری، نوبت و پیش‌فاکتور جدیدی ساخته نمی‌شود.</span></div>}
                <div className="flex flex-col justify-between gap-st-space-md pt-st-space-xs lg:flex-row lg:items-center">
                  <div className="flex min-w-0 flex-col gap-st-space-xs"><span className="text-st-outline">{on ? "اقلام مصرفی تأمین شونده در هر محموله:" : "اقلام ذخیره شده در فهرست:"}</span>
                    <ul className="flex flex-wrap items-center gap-st-space-sm">{l.items.map((it) => <li key={it.product_id} className={cn(chip, !on && "text-st-outline")}>{on && <Icon name="check_circle" className="text-[16px] text-st-secondary" />}<span>{it.title_fa} ({fa(it.quantity)} عدد)</span></li>)}</ul></div>
                  <div className="flex shrink-0 flex-wrap items-center gap-st-space-xs">
                    {on && <button type="button" className={ghost} disabled={busyId === l.id} onClick={() => act(l, "pause")}>توقف موقت</button>}
                    <button type="button" className={cn(ghost, "inline-flex items-center gap-1")} onClick={() => printDraft(l)}><Icon name="description" className="text-[16px]" />پیش‌نویس قرارداد A4</button>
                    <button type="button" disabled={busyId === l.id} onClick={() => act(l, "cancel")} className="rounded-lg px-st-space-sm py-1.5 text-st-outline transition-colors hover:bg-st-error-container hover:text-st-error disabled:opacity-50">لغو قرارداد</button>
                  </div>
                </div>
                {quote?.id === l.id && <QuoteView q={quote.q} err={quote.err} />}
                {on && token && <ReadyRun token={token} listId={l.id} />}
              </article>); })}
        </div>

        <section id="new-list" className="scroll-mt-24 rounded-xl border border-st-surface-container-low bg-st-surface-container-lowest p-st-space-lg shadow-sm">
          <NewList token={token} organizationId={orgId} label="+ ثبت قرارداد تأمین جدید" placeholder="مثلاً اقلام ماهانهٔ آبدارخانه"
            onCreated={(l) => { setLists((c) => [l, ...(c ?? [])]); setFlash({ ok: true, text: "فهرست تأمین دوره‌ای سازمان ساخته شد." }); }} />
        </section>

        {/* Support banner */}
        <section className="flex flex-col items-center justify-between gap-st-space-md rounded-xl border border-st-surface-container-low bg-st-surface-container-lowest p-st-space-lg shadow-sm lg:flex-row">
          <div className="flex items-center gap-st-space-md">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-st-primary-container text-st-on-primary"><Icon name="support_agent" className="text-[24px]" /></div>
            <div className="flex flex-col gap-0.5"><span className="font-bold text-st-primary">نیاز به تغییر حجم عمده یا افزودن پیمان اختصاصی دارید؟</span>
              <span className="text-st-on-surface-variant">برای قراردادهای فصلی یا حجم عمده، درخواست خرید ثبت کنید یا با پشتیبانی سازمانی تماس بگیرید.</span></div>
          </div>
          <div className="flex shrink-0 items-center gap-st-space-sm">
            <Link href="/contact" className="inline-flex items-center gap-1 rounded-xl bg-st-surface-container px-st-space-md py-st-space-sm font-semibold text-st-primary transition-colors hover:bg-st-surface-container-high"><Icon name="call" className="text-[18px]" /><span>تماس با پشتیبانی</span></Link>
            <Link href="/organization/requests" className="inline-flex items-center gap-1 rounded-xl bg-st-primary px-st-space-md py-st-space-sm font-semibold text-st-on-primary transition-colors hover:bg-st-secondary"><Icon name="post_add" className="text-[18px]" /><span>درخواست قرارداد جدید</span></Link>
          </div>
        </section>
      </>}
      {draft && o.org && <ContractDraftViewer org={o.org as DraftOrg} contract={contract ?? null} list={draft.list} quote={draft.quote} onClose={closeDraft} />}
    </div>
  );
}
