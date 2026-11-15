"use client";
// قراردادهای تأمین دوره‌ای — organization view over REAL data only:
//   GET /orgs/{id}/credit-contract  (the organization's contract with limit/due terms, if any)
//   GET /me/recurring               (the caller's recurring lists; filtered to this organization)
//   POST /me/recurring {organization_id}, /me/recurring/{id}/{pause|resume|cancel}, /quote, /runs
// Lists belong to the member who created them (server rule); this page does not show other members' lists.
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { CalendarClock, Download, FileSignature, FileText, Repeat } from "lucide-react";
import { jalaliToIso } from "@/lib/jalali";
import { useAuth } from "@/lib/auth-context";
import { apiRequest, errText, FREQ_FA, RECUR_FA, type CreditContract, type DraftQuote, type RecurringList } from "@/lib/commerce";
import { faDate, formatPrice } from "@/lib/utils";
import { Flash, ListState, btnGhost, n } from "@/components/commerce/ui";
import { NewList, QuoteView, ReadyRun } from "@/components/commerce/Recurring";
import { useOrganization, OrgSelector } from "./Dashboard";
import { cn } from "@/lib/utils";

const CONTRACT_FA: Record<string, string> = { active: "فعال", frozen: "مسدود موقت", closed: "بسته‌شده" };
const STATUS_CLS: Record<string, string> = { active: "bg-emerald-50 text-emerald-800", paused: "bg-amber-50 text-amber-800", cancelled: "bg-canvas-sunken text-ink-muted" };

export default function SupplyContracts() {
  const { user } = useAuth();
  return <Body key={user?.id ?? "guest"} />;
}

function Body() {
  const o = useOrganization();
  const { token } = useAuth();
  const orgId = o.selected ? Number(o.selected) : null;
  const [contract, setContract] = useState<CreditContract | null | undefined>(undefined);
  const [lists, setLists] = useState<RecurringList[] | null>(null), [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0), [flash, setFlash] = useState<{ ok: boolean; text: string } | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [quote, setQuote] = useState<{ id: number; q: DraftQuote | null; err?: string } | null>(null);
  const [from, setFrom] = useState(""), [to, setTo] = useState(""), [freq, setFreq] = useState(""), [st, setSt] = useState("");
  const fromIso = from.trim() ? jalaliToIso(from) : null, toIso = to.trim() ? jalaliToIso(to) : null;
  const badFrom = !!from.trim() && !fromIso, badTo = !!to.trim() && !toIso;
  const shown = lists?.filter((l) => (!freq || l.frequency === freq) && (!st || l.status === st)
    && (!fromIso || l.next_run_on >= fromIso) && (!toIso || l.next_run_on <= toIso)) ?? null;

  // PDF draft: an A4 print view (Persian text renders correctly via the browser's «Save as PDF»).
  const [draft, setDraft] = useState<{ list: RecurringList; quote: DraftQuote | null } | null>(null);
  const printDraft = async (l: RecurringList) => {
    if (!token) return;
    let q: DraftQuote | null = null;
    try { q = (await apiRequest<{ quote: DraftQuote }>(`/me/recurring/${l.id}/quote`, { token })).quote; } catch {}
    setDraft({ list: l, quote: q });
  };
  useEffect(() => {
    if (!draft) return;
    const done = () => setDraft(null);
    window.addEventListener("afterprint", done);
    const t = setTimeout(() => window.print(), 150);
    return () => { clearTimeout(t); window.removeEventListener("afterprint", done); };
  }, [draft]);

  const exportCsv = () => {
    if (!shown?.length) return;
    // Excel-compatible CSV (UTF-8 with BOM so Persian text opens correctly in Excel).
    const esc = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`;
    const rows = [["عنوان", "دوره", "وضعیت", "نوبت بعدی", "آخرین نوبت", "کالا", "تعداد"].map(esc).join(",")];
    for (const l of shown) for (const it of l.items) rows.push([l.title, FREQ_FA[l.frequency], RECUR_FA[l.status], faDate(l.next_run_on), l.last_run_on ? faDate(l.last_run_on) : "", it.title_fa, it.quantity].map(esc).join(","));
    const blob = new Blob(["\uFEFF" + rows.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `supply-contracts-${o.org?.display_name ?? orgId}-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  useEffect(() => {
    if (!token || !orgId) return;
    let off = false;
    setContract(undefined); setLists(null); setError(null);
    apiRequest<{ contract: CreditContract | null }>(`/orgs/${orgId}/credit-contract`, { token })
      .then((r) => !off && setContract(r.contract)).catch(() => !off && setContract(null));
    apiRequest<{ items: RecurringList[] }>("/me/recurring", { token })
      .then((r) => !off && setLists(r.items.filter((l) => l.organization_id === orgId)))
      .catch((e) => !off && setError(errText(e, "بارگذاری فهرست‌ها ناموفق بود")));
    return () => { off = true; };
  }, [token, orgId, retry]);

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
  const next = active.map((l) => l.next_run_on).sort()[0];

  return (
    <div dir="rtl" className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div><p className="text-[11px] font-semibold text-ink-faint">میز کار سازمانی</p>
          <h1 className="text-2xl font-extrabold text-ink">قراردادهای تأمین دوره‌ای</h1>
          <p className="mt-1 max-w-2xl text-sm text-ink-muted">اقلام تکراری سازمان (آبدارخانه، اداری، بهداشتی) را یک‌بار تعریف کنید؛ در هر دوره پیش‌فاکتور با قیمت روز ساخته می‌شود و تا تأیید شما پرداختی انجام نمی‌شود.</p></div>
      </header>
      <OrgSelector state={o} />
      <Flash msg={flash} />

      {token && orgId && <>
        <div className="grid gap-3 md:grid-cols-3">
          <section className="rounded-2xl border border-line bg-white p-5 md:col-span-2" aria-labelledby="ct-h">
            <div className="mb-3 flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-canvas-sunken text-ink"><FileSignature className="h-5 w-5" strokeWidth={1.6} /></span>
              <h2 id="ct-h" className="text-[15px] font-bold text-ink">قرارداد سازمان</h2>
              {contract && <span className={cn("mr-auto rounded-full px-2.5 py-1 text-[11px] font-bold", contract.status === "active" ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800")}>{CONTRACT_FA[contract.status] ?? contract.status}</span>}</div>
            {contract === undefined ? <p role="status" className="text-sm text-ink-faint">در حال بارگذاری…</p>
              : contract === null ? <p className="text-sm text-ink-muted">قرارداد اعتباری فعالی برای این سازمان ثبت نشده است؛ فهرست‌های دوره‌ای با روش پرداخت عادی تسویه می‌شوند.</p>
              : <dl className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
                <div><dt className="text-[11px] text-ink-faint">شمارهٔ قرارداد</dt><dd className="font-semibold text-ink">{contract.contract_number || contract.reference}</dd></div>
                <div><dt className="text-[11px] text-ink-faint">سقف اعتبار</dt><dd className="font-semibold text-ink tabular-nums">{formatPrice(contract.effective_limit_minor ?? contract.limit_minor)}</dd></div>
                <div><dt className="text-[11px] text-ink-faint">ماندهٔ قابل استفاده</dt><dd className="font-semibold text-ink tabular-nums">{formatPrice(contract.headroom_minor)}</dd></div>
                <div><dt className="text-[11px] text-ink-faint">مهلت پرداخت</dt><dd className="font-semibold text-ink">{n(contract.due_days)} روز</dd></div>
              </dl>}
          </section>
          <section className="rounded-2xl border border-line bg-white p-5" aria-label="خلاصه">
            <div className="flex items-center gap-2 text-[11px] text-ink-faint"><CalendarClock className="h-4 w-4" />نوبت بعدی تأمین</div>
            <p className="mt-2 text-xl font-extrabold text-ink">{next ? faDate(next) : "—"}</p>
            <p className="mt-1 text-xs text-ink-muted">{n(active.length)} فهرست فعال از {n(lists?.length ?? 0)}</p>
          </section>
        </div>

        <NewList token={token} organizationId={orgId} label="تعریف تأمین دوره‌ای جدید" placeholder="مثلاً اقلام ماهانهٔ آبدارخانه"
          onCreated={(l) => { setLists((c) => [l, ...(c ?? [])]); setFlash({ ok: true, text: "فهرست تأمین دوره‌ای سازمان ساخته شد." }); }} />

        <section className="rounded-2xl border border-line bg-white p-4 md:p-5" aria-labelledby="ls-h">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <h2 id="ls-h" className="flex items-center gap-2 text-[15px] font-bold text-ink"><Repeat className="h-4 w-4" />فهرست‌های تأمین این سازمان</h2>
            <button type="button" onClick={exportCsv} disabled={!shown?.length} className={`${btnGhost} inline-flex items-center gap-1.5`}><Download className="h-4 w-4" />خروجی اکسل</button>
          </div>
          <div role="search" aria-label="فیلتر فهرست‌ها" className="mb-4 grid grid-cols-2 gap-2 rounded-2xl bg-canvas p-3 md:grid-cols-4">
            <label className="grid gap-1 text-[11px] font-semibold text-ink-muted">نوبت بعدی از تاریخ
              <input value={from} onChange={(e) => setFrom(e.target.value)} placeholder="۱۴۰۵/۰۸/۰۱" inputMode="numeric" aria-invalid={badFrom} className={`form-input text-sm ${badFrom ? "!border-red-400" : ""}`} /></label>
            <label className="grid gap-1 text-[11px] font-semibold text-ink-muted">تا تاریخ
              <input value={to} onChange={(e) => setTo(e.target.value)} placeholder="۱۴۰۵/۰۸/۳۰" inputMode="numeric" aria-invalid={badTo} className={`form-input text-sm ${badTo ? "!border-red-400" : ""}`} /></label>
            <label className="grid gap-1 text-[11px] font-semibold text-ink-muted">دورهٔ ارسال
              <select value={freq} onChange={(e) => setFreq(e.target.value)} className="form-input text-sm"><option value="">همه</option>{Object.entries(FREQ_FA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label className="grid gap-1 text-[11px] font-semibold text-ink-muted">وضعیت
              <select value={st} onChange={(e) => setSt(e.target.value)} className="form-input text-sm"><option value="">همه</option><option value="active">فعال</option><option value="paused">متوقف</option></select></label>
            {(badFrom || badTo) && <p role="alert" className="col-span-full text-xs text-red-700">تاریخ را به شکل سال/ماه/روز شمسی بنویسید؛ مثل ۱۴۰۵/۰۸/۰۱</p>}
          </div>
          <ListState items={shown} error={error} empty={lists?.length ? "هیچ فهرستی با این فیلترها پیدا نشد." : "هنوز فهرست تأمین دوره‌ای برای این سازمان تعریف نکرده‌اید."} onRetry={() => setRetry((x) => x + 1)} />
          <ul className="grid gap-3 lg:grid-cols-2">
            {shown?.map((l) => <li key={l.id} className="rounded-2xl border border-line p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0"><p className="font-bold text-ink">{l.title}</p>
                  <p className="mt-0.5 text-xs text-ink-muted">{FREQ_FA[l.frequency]} · {n(l.items.length)} قلم{l.status === "active" && ` · نوبت بعد: ${faDate(l.next_run_on)}`}</p></div>
                <span className={cn("rounded-full px-2.5 py-1 text-[11px] font-bold", STATUS_CLS[l.status])}>{RECUR_FA[l.status]}</span>
              </div>
              <ul className="mt-3 flex flex-wrap gap-1.5">{l.items.map((it) => <li key={it.product_id} className="rounded-full bg-canvas px-2.5 py-1 text-[11px] text-ink-soft">{it.title_fa} × {n(it.quantity)}</li>)}</ul>
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" className={btnGhost} aria-expanded={quote?.id === l.id} onClick={() => showQuote(l.id)}>پیش‌فاکتور</button>
                <button type="button" className={`${btnGhost} inline-flex items-center gap-1.5`} onClick={() => printDraft(l)}><FileText className="h-4 w-4" />پیش‌نویس PDF</button>
                {l.status === "active" && <button type="button" className={btnGhost} disabled={busyId === l.id} onClick={() => act(l, "pause")}>توقف</button>}
                {l.status === "paused" && <button type="button" className={btnGhost} disabled={busyId === l.id} onClick={() => act(l, "resume")}>ادامه</button>}
                <button type="button" className={`${btnGhost} text-red-700`} disabled={busyId === l.id} onClick={() => act(l, "cancel")}>لغو</button>
              </div>
              {quote?.id === l.id && <QuoteView q={quote.q} err={quote.err} />}
              {l.status === "active" && <ReadyRun token={token} listId={l.id} />}
            </li>)}
          </ul>
        </section>
      </>}
      {draft && createPortal(<ContractDraft orgName={o.org?.display_name ?? ""} contract={contract ?? null} list={draft.list} quote={draft.quote} />, document.body)}
    </div>
  );
}

function ContractDraft({ orgName, contract, list, quote }: { orgName: string; contract: CreditContract | null; list: RecurringList; quote: DraftQuote | null }) {
  const today = faDate(new Date().toISOString().slice(0, 10));
  const lineOf = (pid: number) => quote?.lines.find((x) => x.product_id === pid);
  return (
    <div className="contract-print" dir="rtl" aria-hidden="true">
      <header className="cp-head">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/brand/60online-mark.png" alt="" />
        <div><h1>پیش‌نویس قرارداد تأمین دوره‌ای</h1><p>شصت‌آنلاین · تاریخ تهیه: {today}</p></div>
      </header>
      <p className="cp-note">این سند پیش‌نویس است و تا امضای طرفین اعتبار قراردادی ندارد. قیمت‌ها پیش‌برآورد با قیمت روز تهیه هستند و در هر نوبت دوباره محاسبه می‌شوند.</p>
      <table className="cp-kv"><tbody>
        <tr><th>سازمان خریدار</th><td>{orgName || "—"}</td><th>عنوان فهرست</th><td>{list.title}</td></tr>
        <tr><th>دورهٔ تأمین</th><td>{FREQ_FA[list.frequency]}</td><th>نوبت بعدی</th><td>{faDate(list.next_run_on)}</td></tr>
        <tr><th>وضعیت</th><td>{RECUR_FA[list.status]}</td><th>قرارداد اعتباری</th><td>{contract ? `${contract.contract_number || contract.reference} · مهلت پرداخت ${n(contract.due_days)} روز` : "ثبت نشده"}</td></tr>
      </tbody></table>
      <table className="cp-items">
        <thead><tr><th>ردیف</th><th>کالا</th><th>تعداد در هر نوبت</th><th>مبلغ واحد (پیش‌برآورد)</th><th>مبلغ ردیف</th></tr></thead>
        <tbody>{list.items.map((it, i) => { const ln = lineOf(it.product_id); return (
          <tr key={it.product_id}><td>{n(i + 1)}</td><td>{it.title_fa}</td><td>{n(it.quantity)}</td>
            <td>{ln ? formatPrice(ln.unit_price_minor) : "—"}</td><td>{ln ? formatPrice(ln.line_after_discounts_minor) : "قابل فروش نیست"}</td></tr>); })}</tbody>
        {quote && <tfoot>
          {quote.totals.discount_total_minor > 0 && <tr><td colSpan={4}>تخفیف دوره‌ای</td><td>{formatPrice(quote.totals.discount_total_minor)}</td></tr>}
          <tr><td colSpan={4}>جمع قابل پرداخت هر نوبت (پیش‌برآورد)</td><td>{formatPrice(quote.totals.payable_minor)}</td></tr></tfoot>}
      </table>
      <div className="cp-sign"><div><b>نمایندهٔ سازمان خریدار</b><span>نام، سمت، امضا و مهر</span></div><div><b>شصت‌آنلاین</b><span>نام، سمت، امضا و مهر</span></div></div>
    </div>
  );
}
