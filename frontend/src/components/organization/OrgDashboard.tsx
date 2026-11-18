"use client";
// میز کار سازمانی — faithful to Stitch screen 26 (dark: 21). Real data only:
//   GET /organizations                         → organization name, legal name, national id, caller's role
//   GET /orgs/{id}/credit-contract             → credit limit / headroom (organization admin + finance only)
//   GET /orgs/{id}/orders (+ /orders/{oid})    → latest organization orders and their items (readers + finance)
//   GET /orgs/{id}/procurement/requests        → fallback list when the caller may not read orders (employees)
//   GET /me/recurring (+ pause/resume)         → the caller's recurring supply lists for this organization
// Stitch items with no backend (procurement savings, named account manager, fleet tracking) are shown as
// «به‌زودی» or replaced by real routes — never with sample numbers.
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { apiRequest, ApiError } from "@/lib/api";
import { FREQ_FA, ORDER_STATUS_FA, type CreditContract, type OrgOrderRow, type RecurringList } from "@/lib/commerce";
import { cn, faDate, toPersianNum } from "@/lib/utils";
import { useOrganization } from "./Dashboard";
import { ROLE_FA } from "./OrgShell";
import st from "./stitch.module.css";

export const fa = (v: number) => v.toLocaleString("fa-IR");
/** Rial minor units → grouped Toman digits (unit printed separately, as in Stitch). */
export const tomanDigits = (minor: number) => fa(Math.round(minor / 10));
export function Icon({ name, className }: { name: string; className?: string }) {
  return <span aria-hidden className={cn("material-symbols-outlined", className)}>{name}</span>;
}

type OrderItem = { id: number; title_fa: string; quantity: number };
type ReqRow = { id: number; title?: string; request_number?: string; status: string; created_at?: string };
type Load<T> = { state: "loading" } | { state: "ok"; data: T } | { state: "forbidden" } | { state: "error"; msg: string };

const PAY_FA: Record<string, string> = { credit: "اعتبار سازمانی", cash: "پرداخت نقدی", mixed: "اعتبار + نقدی", cheque: "چک" };
const REQ_FA: Record<string, string> = { draft: "پیش‌نویس", submitted: "ارسال‌شده", under_review: "در حال بررسی", approved: "تأییدشده", rejected: "ردشده", cancelled: "لغوشده", converted: "تبدیل به سفارش" };
const CURRENT = ["pending", "paid", "processing", "shipped"];
const FILTERS: { key: string; label: string; match: (s: string) => boolean }[] = [
  { key: "all", label: "همه", match: () => true },
  { key: "current", label: "جاری", match: (s) => CURRENT.includes(s) },
  { key: "delivered", label: "تحویل شده", match: (s) => s === "delivered" },
  { key: "pending", label: "در انتظار تایید مالی", match: (s) => s === "pending" },
];

function useLoad<T>(path: string | null, token: string | null, retry = 0): Load<T> {
  const [v, setV] = useState<Load<T>>({ state: "loading" });
  useEffect(() => {
    if (!path || !token) return;
    const c = new AbortController();
    setV({ state: "loading" });
    apiRequest<T>(path, { token, signal: c.signal }).then((d) => !c.signal.aborted && setV({ state: "ok", data: d }))
      .catch((e) => { if (c.signal.aborted) return; setV(e instanceof ApiError && e.status === 403 ? { state: "forbidden" } : { state: "error", msg: e instanceof Error ? e.message : "خطا در ارتباط با سرور" }); });
    return () => c.abort();
  }, [path, token, retry]);
  return v;
}

function StatusPill({ status }: { status: string }) {
  const label = ORDER_STATUS_FA[status] ?? REQ_FA[status] ?? status;
  if (["paid", "processing", "approved"].includes(status))
    return <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-st-secondary px-st-space-sm py-1 font-semibold text-st-on-secondary"><span className="h-1.5 w-1.5 rounded-full bg-st-surface-container-lowest" />{label}</span>;
  if (status === "shipped")
    return <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-st-primary-container px-st-space-sm py-1 font-semibold text-st-on-primary"><span className="h-1.5 w-1.5 rounded-full bg-st-secondary-fixed" />{label}</span>;
  if (status === "delivered" || status === "converted")
    return <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-st-surface-container-high px-st-space-sm py-1 font-semibold text-st-on-surface-variant"><Icon name="check_circle" className="text-[16px] text-st-secondary" />{label}</span>;
  if (["cancelled", "refunded", "rejected"].includes(status))
    return <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-st-error-container px-st-space-sm py-1 font-semibold text-st-on-error-container">{label}</span>;
  return <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-st-surface-container px-st-space-sm py-1 font-semibold text-st-on-surface">{label}</span>;
}

function KpiCard({ label, value, unit, icon, iconCls, children }: { label: string; value: React.ReactNode; unit?: string; icon: string; iconCls?: string; children?: React.ReactNode }) {
  return (
    <div className="relative flex flex-col justify-between gap-3 overflow-hidden rounded-xl bg-st-surface-container-lowest p-4 text-[14px] shadow-st-card">
      <span aria-hidden className="absolute inset-x-0 top-0 h-1 bg-gradient-to-l from-st-secondary via-st-secondary/40 to-st-accent/60" />
      <div className="flex items-start justify-between gap-st-space-sm">
        <div className="flex min-w-0 flex-col gap-st-space-xs"><span className="text-st-outline">{label}</span>
          <div className="flex flex-wrap items-baseline gap-st-space-xs"><span className="text-[20px] font-extrabold leading-8 text-st-primary">{value}</span>{unit && <span className="text-st-outline">{unit}</span>}</div></div>
        <div className={cn("flex h-11 w-11 shrink-0 items-center justify-center rounded-xl", iconCls)}><Icon name={icon} className="text-[22px]" /></div>
      </div>
      {children}
    </div>
  );
}

export default function OrgDashboard() {
  const { user, token } = useAuth();
  const o = useOrganization(!!user);
  const orgId = o.selected || null;
  const [retry, setRetry] = useState(0);
  const isFinance = ["organization_admin", "organization_finance"].includes(o.org?.membership.role ?? "");
  const orders = useLoad<{ items: (OrgOrderRow & { purchase_request_id?: number | null })[] }>(orgId ? `/orgs/${orgId}/orders` : null, token, retry);
  const requests = useLoad<{ items: ReqRow[]; total: number }>(orgId && orders.state === "forbidden" ? `/orgs/${orgId}/procurement/requests` : null, token, retry);
  const credit = useLoad<{ contract: CreditContract | null }>(orgId && isFinance ? `/orgs/${orgId}/credit-contract` : null, token, retry);
  const [lists, setLists] = useState<RecurringList[] | null>(null);
  const [busyList, setBusyList] = useState<number | null>(null), [listErr, setListErr] = useState<string | null>(null);
  const [items, setItems] = useState<Record<number, OrderItem[]>>({});
  const [filter, setFilter] = useState("all"), [q, setQ] = useState("");

  useEffect(() => {
    if (!token || !orgId) return;
    let off = false; setLists(null);
    apiRequest<{ items: RecurringList[] }>("/me/recurring", { token }).then((r) => !off && setLists(r.items.filter((l) => l.organization_id === Number(orgId) && l.status !== "cancelled"))).catch(() => !off && setLists([]));
    return () => { off = true; };
  }, [token, orgId, retry]);

  const allOrders = useMemo(() => (orders.state === "ok" ? orders.data.items : []), [orders]);
  const shown = allOrders.filter((r) => FILTERS.find((f) => f.key === filter)!.match(r.status) && (!q.trim() || [r.order_number, r.po_reference ?? "", ...(items[r.id] ?? []).map((i) => i.title_fa)].join(" ").includes(q.trim()))).slice(0, 6);
  const shownIds = shown.map((r) => r.id).join(",");
  useEffect(() => { // item titles/counts for the visible rows only (≤ 6 small reads)
    if (!token || !orgId) return;
    const missing = shownIds.split(",").filter(Boolean).map(Number).filter((id) => !(id in items));
    missing.forEach((id) => apiRequest<{ order: { items: OrderItem[] } }>(`/orgs/${orgId}/orders/${id}`, { token })
      .then((r) => setItems((m) => ({ ...m, [id]: r.order.items }))).catch(() => setItems((m) => ({ ...m, [id]: [] }))));
  }, [shownIds, token, orgId]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = async (l: RecurringList) => {
    if (!token) return;
    setBusyList(l.id); setListErr(null);
    try { const { list } = await apiRequest<{ list: RecurringList }>(`/me/recurring/${l.id}/${l.status === "active" ? "pause" : "resume"}`, { token, method: "POST" });
      setLists((c) => c && c.map((x) => (x.id === l.id ? list : x))); }
    catch (e) { setListErr(e instanceof Error ? e.message : "تغییر وضعیت ناموفق بود"); } finally { setBusyList(null); }
  };

  if (!user) return <PublicIntro />;
  if (o.loading) return <p role="status" className="rounded-xl bg-st-surface-container-lowest p-st-space-lg shadow-sm">در حال دریافت سازمان‌ها…</p>;
  if (o.error) return <p role="alert" className="rounded-xl bg-st-error-container p-st-space-lg text-st-on-error-container">{o.error} <button className="underline" onClick={o.retry}>تلاش مجدد</button></p>;
  if (!o.org) return <div className="rounded-xl bg-st-surface-container-lowest p-st-space-lg shadow-sm"><h1 className="font-bold text-st-primary">عضویت فعال سازمانی برای این حساب یافت نشد</h1><p className="mt-st-space-xs text-st-on-surface-variant">سازمان و دسترسی باید توسط مسئول مجاز ثبت شوند. برای درخواست حساب سازمانی از <Link className="text-st-secondary underline" href="/business">فرم حساب سازمانی</Link> استفاده کنید.</p></div>;

  const org = o.org as typeof o.org & { legal_name?: string | null; national_id?: string | null };
  const contract = credit.state === "ok" ? credit.data.contract : null;
  const limit = contract ? contract.effective_limit_minor ?? contract.limit_minor : 0;
  const active = lists?.filter((l) => l.status === "active") ?? [];
  const processing = allOrders.filter((r) => ["paid", "processing"].includes(r.status)).length;
  const shipped = allOrders.filter((r) => r.status === "shipped").length;

  return (
    <div className="flex w-full flex-col gap-5">
      {o.orgs.length > 1 && <label className="flex items-center gap-st-space-sm self-start rounded-xl bg-st-surface-container-lowest px-st-space-md py-st-space-xs shadow-sm"><span className="text-st-outline">سازمان فعال</span>
        <select aria-label="سازمان فعال" value={o.selected} onChange={(e) => o.setSelected(e.target.value)} className="rounded-lg border-0 bg-transparent font-bold text-st-primary">{o.orgs.map((x) => <option key={x.id} value={x.id}>{x.display_name}</option>)}</select></label>}

      {/* Greeting & corporate status */}
      <section className="relative overflow-hidden rounded-xl bg-st-navy p-5 text-white shadow-st-raise">
        <span aria-hidden className="pointer-events-none absolute -left-16 -top-20 h-56 w-56 rounded-full bg-st-secondary/50 blur-3xl" />
        <span aria-hidden className="pointer-events-none absolute -bottom-20 left-1/3 h-40 w-40 rounded-full bg-st-accent/20 blur-3xl" />
        <div className="relative flex flex-col justify-between gap-st-space-md lg:flex-row lg:items-center">
          <div className="flex min-w-0 flex-col gap-st-space-xs">
            <div className="flex items-center gap-st-space-xs"><span className="inline-flex h-2 w-2 rounded-full bg-st-accent" /><span className="text-[14px] font-bold text-st-on-navy-muted">عضویت فعال سازمانی • {ROLE_FA[org.membership.role] ?? org.membership.role}</span></div>
            <h1 className="flex flex-wrap items-baseline gap-x-st-space-sm gap-y-1 font-normal">
              <span className="text-[22px] font-extrabold text-white">خوش‌آمدید، {user.full_name}</span>
              <span className="text-[14px] text-st-on-navy-muted">{org.legal_name || org.display_name}{org.national_id ? ` (شناسه ملی: ${toPersianNum(org.national_id)})` : ""}</span>
            </h1>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-st-space-sm">
            <Link href={isFinance ? "/organization/statement" : "/me/proformas"} className="inline-flex items-center gap-st-space-xs rounded-full bg-white/10 px-st-space-md py-2 text-[14px] text-white ring-1 ring-white/20 transition-colors hover:bg-white/20">
              <Icon name="receipt" className="text-[18px]" /><span>{isFinance ? "صورت‌حساب تجمیعی ماهانه" : "پیش‌فاکتورهای من"}</span></Link>
            <Link href="/organization/compose" className="inline-flex items-center gap-st-space-xs rounded-full bg-st-accent px-st-space-lg py-2 text-[14px] font-bold text-white shadow-[0_10px_24px_-10px_rgb(255_122_0/0.8)] transition-transform hover:-translate-y-0.5">
              <Icon name="add_circle" className="text-[20px]" /><span>ثبت سفارش شرکتی جدید</span></Link>
          </div>
        </div>
      </section>

      {/* KPI cards */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="اعتبار سازمانی قابل استفاده" icon="account_balance_wallet" iconCls="bg-st-navy text-white"
          value={!isFinance ? "ویژه مدیر و مالی" : credit.state === "loading" ? "…" : contract ? tomanDigits(contract.headroom_minor) : "قرارداد ثبت نشده"} unit={contract ? "تومان" : undefined}>
          {contract ? <div className="flex flex-col gap-st-space-xs pt-st-space-xs">
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-st-surface-container"><div className="h-full rounded-full bg-st-secondary" style={{ width: `${limit ? Math.min(100, Math.round((contract.headroom_minor / limit) * 100)) : 0}%` }} /></div>
            <div className="flex items-center justify-between gap-2 text-st-on-surface-variant"><span>سقف مصوب: {tomanDigits(limit)}</span><span className="font-bold text-st-secondary">{contract.status === "active" ? `مهلت پرداخت ${fa(contract.due_days)} روزه` : contract.status === "frozen" ? "مسدود موقت" : "بسته‌شده"}</span></div>
          </div> : <span className="text-st-on-surface-variant">{isFinance ? "قرارداد اعتباری پس از عقد قرارداد فعال می‌شود" : "مبلغ اعتبار فقط برای نقش مالی نمایش داده می‌شود"}</span>}
        </KpiCard>
        <KpiCard label="سفارش‌های در حال پردازش" icon="conveyor_belt" iconCls="bg-st-secondary-fixed text-st-secondary"
          value={orders.state === "ok" ? fa(processing + shipped) : orders.state === "forbidden" ? "—" : "…"} unit={orders.state === "ok" ? "سفارش جاری" : undefined}>
          {orders.state === "ok" ? <div className="flex flex-wrap items-center gap-st-space-sm pt-st-space-xs text-st-on-surface-variant">
            <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-st-secondary" />{fa(processing)} در حال آماده‌سازی</span><span className="text-st-outline">•</span>
            <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-st-on-tertiary-container" />{fa(shipped)} ارسال‌شده</span></div>
            : <span className="text-st-on-surface-variant">{orders.state === "forbidden" ? "سفارش‌های سازمان برای نقش شما قابل مشاهده نیست" : " "}</span>}
        </KpiCard>
        <KpiCard label="صرفه‌جویی تدارکات امسال" icon="trending_up" iconCls="bg-st-tertiary-fixed text-st-on-tertiary-container" value="به‌زودی">
          <span className="text-st-on-surface-variant">گزارش صرفه‌جویی پس از اتصال گزارش‌های مالی فعال می‌شود</span>
        </KpiCard>
        <KpiCard label="قراردادهای دوره‌ای فعال" icon="autorenew" iconCls="bg-st-mint text-st-mint-ink" value={lists ? fa(active.length) : "…"} unit={lists ? "فهرست تأمین مداوم" : undefined}>
          <div className="flex items-center gap-st-space-xs truncate pt-st-space-xs text-st-on-surface-variant">
            {lists?.length ? <><span className="truncate font-semibold text-st-primary">{lists.slice(0, 3).map((l) => l.title).join("، ")}</span><span className="shrink-0 text-st-outline">| فهرست‌های شما</span></> : <span>هنوز فهرستی تعریف نشده</span>}</div>
        </KpiCard>
      </div>

      {/* Orders table */}
      <section className="flex flex-col overflow-hidden rounded-xl bg-st-surface-container-lowest shadow-sm" aria-labelledby="orders-h">
        <div className="flex flex-col justify-between gap-st-space-md p-st-space-lg lg:flex-row lg:items-center">
          <div className="flex flex-col gap-st-space-xs">
            <div className="flex items-center gap-st-space-sm"><h2 id="orders-h" className="font-bold text-st-primary">آخرین سفارش‌ها و درخواست‌های تدارکات شرکت</h2>
              {orders.state === "ok" && <span className="whitespace-nowrap rounded-full bg-st-accent px-2 py-0.5 text-[12px] font-bold text-white">{fa(allOrders.length)} سفارش</span>}</div>
            <span className="text-st-outline">{orders.state === "forbidden" ? "درخواست‌های خرید مجاز حساب شما" : "فاکتورها، وضعیت پردازش و شیوه تسویه سفارش‌های سازمان"}</span>
          </div>
          {orders.state === "ok" && <div className="flex flex-wrap items-center gap-st-space-sm">
            <div role="tablist" aria-label="فیلتر وضعیت" className="flex items-center gap-1 rounded-xl bg-st-surface-container-low p-1">
              {FILTERS.map((f) => { const count = allOrders.filter((r) => f.match(r.status)).length; return (
                <button key={f.key} role="tab" aria-selected={filter === f.key} type="button" onClick={() => setFilter(f.key)}
                  className={cn("rounded-lg px-st-space-md py-1.5 transition-all", filter === f.key ? "bg-st-surface-container-lowest font-bold text-st-primary shadow-sm" : "text-st-on-surface-variant hover:text-st-primary")}>
                  {f.label}{f.key === "current" && count ? ` (${fa(count)})` : ""}</button>); })}
            </div>
            <div className="relative"><input aria-label="فیلتر کد سفارش یا کالا" value={q} onChange={(e) => setQ(e.target.value)} className="h-10 rounded-xl border-0 bg-st-surface-container-low pl-8 pr-st-space-md text-st-on-surface outline-none placeholder:text-st-outline" placeholder="فیلتر کد سفارش یا کالا..." type="search" />
              <Icon name="tune" className="pointer-events-none absolute left-2.5 top-2.5 text-[18px] text-st-outline" /></div>
          </div>}
        </div>
        {orders.state === "loading" ? <p role="status" className="px-st-space-lg pb-st-space-lg text-st-outline">در حال دریافت سفارش‌ها…</p>
          : orders.state === "error" ? <p role="alert" className="px-st-space-lg pb-st-space-lg text-st-error">{orders.msg} <button className="underline" onClick={() => setRetry((x) => x + 1)}>تلاش مجدد</button></p>
          : orders.state === "forbidden" ? <RequestsTable load={requests} />
          : <>
            <div className="w-full overflow-x-auto">
              <table className="w-full border-collapse text-right">
                <thead><tr className="bg-st-surface-container-low text-st-on-surface-variant">
                  {["شماره سفارش", "تاریخ ثبت", "عنوان اقلام و شرح خرید", "تعداد اقلام", "مبلغ فاکتور (تومان)", "شیوه تسویه", "وضعیت فرآیند"].map((h, i) =>
                    <th key={h} scope="col" className={cn("px-st-space-md py-st-space-md font-semibold", i === 0 && "px-st-space-lg", i === 3 && "text-center")}>{h}</th>)}
                  <th scope="col" className="px-st-space-lg py-st-space-md text-left font-semibold">عملیات</th></tr></thead>
                <tbody className="text-st-on-surface">
                  {shown.map((r, i) => { const its = items[r.id]; return (
                    <tr key={r.id} className={cn("transition-colors hover:bg-st-surface-container", i % 2 === 1 && "bg-st-surface")}>
                      <td className="px-st-space-lg py-st-space-md font-bold text-st-primary"><span dir="ltr" className="tracking-wide">{r.order_number}</span></td>
                      <td className="px-st-space-md py-st-space-md text-st-on-surface-variant">{faDate(r.placed_at)}</td>
                      <td className="px-st-space-md py-st-space-md"><div className="flex min-w-[200px] flex-col">
                        <span className="text-st-primary">{its === undefined ? "…" : its.length ? its.slice(0, 2).map((x) => x.title_fa).join(" + ") + (its.length > 2 ? ` و ${fa(its.length - 2)} قلم دیگر` : "") : "—"}</span>
                        <span className="text-st-outline">{r.po_reference ? `مرجع خرید: ${r.po_reference}` : "بدون شماره مرجع خرید"}</span></div></td>
                      <td className="px-st-space-md py-st-space-md text-center font-bold">{its ? `${fa(its.reduce((s, x) => s + x.quantity, 0))} قلم` : "…"}</td>
                      <td className="px-st-space-md py-st-space-md"><span className="font-bold text-st-primary">{tomanDigits(r.total_minor)}</span></td>
                      <td className="px-st-space-md py-st-space-md"><span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-st-space-sm py-1 font-semibold", r.payment_method === "credit" ? "bg-st-secondary-fixed text-st-on-secondary-fixed" : "bg-st-surface-container text-st-on-surface")}>{PAY_FA[r.payment_method ?? ""] ?? r.payment_method ?? "—"}</span></td>
                      <td className="px-st-space-md py-st-space-md"><StatusPill status={r.status} /></td>
                      <td className="px-st-space-lg py-st-space-md text-left"><div className="flex items-center justify-end gap-st-space-xs">
                        <Link href="/organization/delivery" title="تحویل و مرجوعی" aria-label={`تحویل سفارش ${r.order_number}`} className="flex h-9 w-9 items-center justify-center rounded-lg bg-st-surface-container text-st-primary transition-colors hover:bg-st-surface-container-high"><Icon name="local_shipping" className="text-[18px]" /></Link>
                        <Link href={`/organization/b2b-orders?order=${r.id}`} title="فاکتور و پیش‌نمایش صورتحساب" aria-label={`فاکتور سفارش ${r.order_number}`} className="flex h-9 w-9 items-center justify-center rounded-lg bg-st-surface-container text-st-primary transition-colors hover:bg-st-surface-container-high"><Icon name="download" className="text-[18px]" /></Link>
                      </div></td>
                    </tr>); })}
                  {!shown.length && <tr><td colSpan={8} className="px-st-space-lg py-st-space-xl text-center text-st-on-surface-variant">{allOrders.length ? "سفارشی با این فیلتر پیدا نشد." : "هنوز سفارش سازمانی ثبت نشده است. درخواست خرید پس از تأیید به سفارش تبدیل می‌شود."}</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="flex flex-col items-center justify-between gap-st-space-sm bg-st-surface-container-low p-st-space-md text-st-on-surface-variant sm:flex-row">
              <span>نمایش {fa(shown.length)} سفارش از کل {fa(allOrders.length)} سفارش ثبت‌شده {org.display_name}</span>
              <Link href="/organization/b2b-orders" className="rounded-lg bg-st-surface-container-lowest px-st-space-md py-st-space-xs font-bold text-st-primary transition-colors hover:bg-st-surface-container">مشاهده تمام تاریخچه سفارش‌ها</Link>
            </div>
          </>}
      </section>

      {/* Bottom dual column */}
      <div className="grid grid-cols-1 gap-st-space-md lg:grid-cols-12">
        <section className="flex flex-col gap-st-space-lg rounded-xl bg-st-surface-container-lowest p-st-space-lg shadow-sm lg:col-span-7" aria-labelledby="rc-h">
          <div className="flex items-center justify-between gap-st-space-sm">
            <div className="flex flex-col gap-st-space-xs"><div className="flex items-center gap-st-space-xs"><Icon name="history_edu" className="text-[22px] text-st-secondary" /><h2 id="rc-h" className="font-bold text-st-primary">قراردادهای تامین دوره‌ای و شارژ خودکار</h2></div>
              <span className="text-st-outline">هر دوره پیش‌فاکتور با قیمت روز ساخته می‌شود و تا تأیید شما پرداختی انجام نمی‌شود</span></div>
            <Link href="/organization/supply-contracts" className="shrink-0 font-semibold text-st-secondary hover:underline">مدیریت قراردادها</Link>
          </div>
          {listErr && <p role="alert" className="text-st-error">{listErr}</p>}
          <div className="flex flex-col gap-st-space-sm">
            {lists === null ? <p role="status" className="text-st-outline">در حال دریافت…</p>
              : !lists.length ? <div className="rounded-xl bg-st-surface p-st-space-md text-st-on-surface-variant">هنوز فهرست تأمین دوره‌ای برای این سازمان ندارید. <Link href="/organization/supply-contracts" className="font-semibold text-st-secondary">تعریف فهرست</Link></div>
              : lists.slice(0, 4).map((l, i) => (
                <div key={l.id} className="flex items-center justify-between gap-st-space-sm rounded-xl bg-st-surface p-st-space-md transition-colors hover:bg-st-surface-container-low">
                  <div className="flex min-w-0 items-center gap-st-space-md">
                    <div className={cn("flex h-12 w-12 shrink-0 items-center justify-center rounded-xl", i === 0 ? "bg-st-primary-container text-st-on-primary" : "bg-st-surface-container text-st-primary")}><Icon name="inventory_2" className="text-[24px]" /></div>
                    <div className="flex min-w-0 flex-col">
                      <div className="flex min-w-0 items-center gap-st-space-xs"><span className="truncate font-bold text-st-primary">{l.title}</span>
                        <span className={cn("shrink-0 rounded-full px-st-space-xs py-0.5", l.frequency === "monthly" ? "bg-st-surface-container-high text-st-on-surface-variant" : "bg-st-secondary-fixed text-st-on-secondary-fixed")}>{FREQ_FA[l.frequency]}</span></div>
                      <span className="text-st-outline">{l.status === "active" ? `تحویل بعدی: ${faDate(l.next_run_on)}` : "متوقف موقت"} • {fa(l.items.length)} قلم</span>
                    </div>
                  </div>
                  <button type="button" role="switch" aria-checked={l.status === "active"} aria-label={`${l.status === "active" ? "توقف" : "ازسرگیری"} ${l.title}`}
                    disabled={busyList === l.id} onClick={() => toggle(l)} className={st.switch} />
                </div>))}
          </div>
        </section>

        <section className="flex flex-col justify-between gap-st-space-lg rounded-xl bg-st-surface-container-lowest p-st-space-lg shadow-sm lg:col-span-5" aria-labelledby="sp-h">
          <div className="flex flex-col gap-st-space-md">
            <div className="flex items-center justify-between"><h2 id="sp-h" className="font-bold text-st-secondary">پشتیبانی اختصاصی سازمانی</h2>
              <span className="inline-flex items-center gap-1 text-st-on-surface-variant"><span className="h-2 w-2 rounded-full bg-st-outline" />به‌زودی</span></div>
            <div className="flex items-center gap-st-space-md">
              <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-st-surface-container text-st-primary"><Icon name="support_agent" className="text-[32px]" /></div>
              <div className="flex min-w-0 flex-col"><span className="font-bold text-st-primary">کارشناس حساب سازمانی</span>
                <span className="text-st-on-surface-variant">معرفی کارشناس اختصاصی هنوز در سامانه فعال نشده است</span></div>
            </div>
            <p className="rounded-xl bg-st-surface p-st-space-md leading-relaxed text-st-on-surface-variant">تا آن زمان، برای افزایش سقف اعتبار، استعلام عمده یا تنظیم زمان‌بندی تأمین از پشتیبانی عمومی یا ثبت درخواست خرید استفاده کنید.</p>
          </div>
          <div className="flex flex-col items-center gap-st-space-sm pt-st-space-xs sm:flex-row">
            <Link href="/contact" className="inline-flex h-12 w-full items-center justify-center gap-st-space-xs rounded-xl bg-st-primary-container text-st-on-primary transition-colors hover:bg-st-secondary sm:flex-1"><Icon name="call" className="text-[18px]" /><span>تماس با پشتیبانی</span></Link>
            <Link href="/organization/requests" className="inline-flex h-12 w-full items-center justify-center gap-st-space-xs rounded-xl bg-st-surface-container text-st-primary transition-colors hover:bg-st-surface-container-high sm:flex-1"><Icon name="chat" className="text-[18px]" /><span>ثبت درخواست تدارکات</span></Link>
          </div>
        </section>
      </div>
    </div>
  );
}

function RequestsTable({ load }: { load: Load<{ items: ReqRow[]; total: number }> }) {
  if (load.state === "loading") return <p role="status" className="px-st-space-lg pb-st-space-lg text-st-outline">در حال دریافت درخواست‌ها…</p>;
  if (load.state !== "ok") return <p className="px-st-space-lg pb-st-space-lg text-st-on-surface-variant">مشاهده سفارش‌ها و درخواست‌های سازمان برای نقش شما فعال نیست. <Link href="/organization/requests" className="text-st-secondary underline">درخواست‌های خرید من</Link></p>;
  const rows = load.data.items.slice(0, 6);
  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full border-collapse text-right">
        <thead><tr className="bg-st-surface-container-low text-st-on-surface-variant">{["شماره پیگیری", "تاریخ ثبت", "عنوان درخواست", "وضعیت فرآیند"].map((h) => <th key={h} scope="col" className="px-st-space-lg py-st-space-md font-semibold">{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={r.id} className={cn(i % 2 === 1 && "bg-st-surface")}>
          <td className="px-st-space-lg py-st-space-md font-bold text-st-primary" dir="ltr" style={{ textAlign: "right" }}>{r.request_number}</td>
          <td className="px-st-space-lg py-st-space-md text-st-on-surface-variant">{faDate(r.created_at)}</td>
          <td className="px-st-space-lg py-st-space-md text-st-primary">{r.title}</td>
          <td className="px-st-space-lg py-st-space-md"><StatusPill status={r.status} /></td></tr>)}
          {!rows.length && <tr><td colSpan={4} className="px-st-space-lg py-st-space-xl text-center text-st-on-surface-variant">هنوز درخواستی ثبت نشده است. <Link href="/organization/requests" className="text-st-secondary underline">ثبت درخواست</Link></td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function PublicIntro() {
  return (
    <section className="rounded-xl bg-st-surface-container-lowest p-st-space-lg shadow-sm">
      <div className="flex items-center gap-st-space-xs"><span className="h-2 w-2 rounded-full bg-st-secondary" /><span className="font-bold text-st-secondary">پرتال سازمانی ۶۰ · سامانه مدیریت تدارکات B2B</span></div>
      <h1 className="mt-st-space-xs text-[28px] font-bold text-st-primary">خرید سازمانی، از درخواست تا پیگیری</h1>
      <p className="mt-st-space-xs max-w-2xl text-st-on-surface-variant">سفارش‌ها، پیش‌فاکتورها، قراردادهای تأمین دوره‌ای و اعتبار سازمان در یک میز کار. اطلاعات سازمان فقط پس از ورود با حساب دارای عضویت فعال نمایش داده می‌شود.</p>
      <div className="mt-st-space-md flex flex-wrap gap-st-space-sm">
        <Link href="/login?next=/org" className="inline-flex items-center gap-st-space-xs rounded-full bg-st-primary-container px-st-space-lg py-st-space-sm text-st-on-primary"><Icon name="login" className="text-[20px]" />ورود به پنل سازمانی</Link>
        <Link href="/business" className="inline-flex items-center gap-st-space-xs rounded-full bg-st-surface-container-low px-st-space-md py-st-space-sm text-st-primary">درخواست حساب سازمانی</Link>
      </div>
    </section>
  );
}
