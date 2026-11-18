"use client";
// Admin dashboard — Stitch screen 18 (light) / 02 (dark). Every number comes from GET /admin/dashboard;
// Stitch's GMV, fleet, credit-rating and order-table samples have no backend source and are not shown.
import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { toPersianNum } from "@/lib/utils";
import {
  attentionLabels, filterAttention, metricValue,
  operationsState, parseDashboard, queueFilters,
  type Dashboard, type QueueFilter,
} from "./dashboard-state";

type RequestState = {
  key: string;
  status: "loading" | "ready" | "error";
  data: Dashboard | null;
  message: string;
};
const Icon = ({ name, className = "" }: { name: string; className?: string }) =>
  <span aria-hidden="true" className={`material-symbols-outlined ${className}`}>{name}</span>;
const card = "relative flex flex-col justify-between overflow-hidden rounded-xl border border-st-surface-container bg-st-surface-container-lowest p-st-space-lg shadow-sm transition-shadow hover:shadow-md";
const panel = "flex flex-col justify-between rounded-xl border border-st-surface-container bg-st-surface-container-lowest p-st-space-lg shadow-sm";
const kindIcon = { customer_request: "forum", catalog_image: "image", supplier: "factory" } as const;
const kindChip = {
  customer_request: "bg-st-secondary-fixed/50 text-st-secondary",
  catalog_image: "bg-st-tertiary-fixed/60 text-st-on-tertiary-fixed-variant",
  supplier: "bg-st-surface-container text-st-on-surface-variant",
} as const;

function snapshotLabel(value: string, timezone: string): string | null {
  if (!value || !Number.isFinite(Date.parse(value))) return null;
  try {
    const d = new Date(value);
    const day = new Intl.DateTimeFormat("fa-IR", { weekday: "long", day: "numeric", month: "long", timeZone: timezone }).format(d);
    const time = new Intl.DateTimeFormat("fa-IR", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: timezone }).format(d);
    return `${day} - ساعت ${time}`;
  } catch { return null; }
}

export default function AdminDashboard() {
  const { token } = useAuth();
  const [zone, setZone] = useState("Asia/Tehran");
  const [retry, setRetry] = useState(0);
  const [filter, setFilter] = useState<QueueFilter>("all");
  const [request, setRequest] = useState<RequestState | null>(null);
  // Scope displayed results to the current session, timezone and refresh, even
  // during the render before effect cleanup. This key is never persisted/logged.
  const requestKey = `${token ?? ""}\u0000${zone}\u0000${retry}`;
  const current = request?.key === requestKey ? request : null;
  const data = token && current?.status === "ready" ? current.data : null;
  const busy = Boolean(token) && (!current || current.status === "loading");
  const error = !token
    ? "برای دریافت اطلاعات، دوباره وارد حساب مدیریت شوید."
    : current?.status === "error" ? current.message : "";

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    setRequest({ key: requestKey, status: "loading", data: null, message: "" });
    apiRequest<unknown>("/admin/dashboard?timezone=" + encodeURIComponent(zone), {
      token, signal: controller.signal, cache: "no-store",
    }).then((response) => {
      if (controller.signal.aborted) return;
      const snapshot = parseDashboard(response);
      setRequest({ key: requestKey, status: "ready", data: snapshot, message: "" });
    }).catch((cause: unknown) => {
      if (controller.signal.aborted) return;
      setRequest({ key: requestKey, status: "error", data: null,
        message: cause instanceof Error ? cause.message : "ارتباط با سرور برقرار نشد." });
    });
    return () => controller.abort();
  }, [token, zone, requestKey]);

  const attention = data ? filterAttention(data.attention, filter) : [];
  const opsState = operationsState(data?.operations ?? null, busy);
  const asOf = data ? snapshotLabel(data.as_of, data.timezone) : null;
  const refresh = () => setRetry((value) => value + 1);
  const m = (key: string) => metricValue(data?.metrics[key]);
  const show = (v: number | null) => (busy ? "…" : v === null ? "—" : toPersianNum(v));

  const kpis = [
    { key: "personal_today", title: "استعلام شخصی امروز", unit: "درخواست ثبت‌شده", icon: "forum", tone: "bg-st-secondary-fixed/50 text-st-secondary",
      foot: <><span className="text-st-on-surface-variant">بازهٔ روزِ منطقهٔ زمانی انتخاب‌شده</span><Link href="/admin/inquiries" className="font-bold text-st-secondary hover:underline">رسیدگی</Link></> },
    { key: "org_waiting", title: "درخواست سازمانی منتظر بررسی", unit: "مورد در جریان", icon: "pending_actions", tone: "bg-st-primary-fixed/40 text-st-primary-container",
      foot: <><span className="flex items-center gap-1 text-st-on-surface-variant"><span className="inline-block h-2 w-2 rounded-full bg-st-on-tertiary-container" />
        <strong className="font-bold text-st-on-surface">{show(m("quotes_submitted"))} پیشنهاد</strong>ارسال‌شدهٔ تأمین‌کننده</span>
        <Link href="/admin/cases" className="font-bold text-st-secondary hover:underline">اقدام</Link></> },
    { key: "suppliers_inactive", title: "تأمین‌کنندهٔ غیرفعال", unit: "حساب واقعی", icon: "factory", tone: "bg-st-surface-container-high text-st-on-surface-variant",
      foot: <><span className="text-st-on-surface-variant">حساب‌هایی که وضعیت فعال ندارند</span><Link href="/admin/suppliers" className="font-bold text-st-secondary hover:underline">بررسی</Link></> },
    { key: "settlements_pending", title: "تسویهٔ منتظر ثبت پرداخت", unit: "صورت تسویه", icon: "verified_user", tone: "bg-st-secondary-fixed/30 text-st-secondary",
      foot: <><span className="text-st-on-surface-variant">صورت‌های تسویهٔ در انتظار پرداخت</span><Link href="/admin/settlements" className="font-bold text-st-primary hover:underline">مالی و تسویه</Link></> },
  ] as const;

  return <div className="flex w-full flex-col text-base">
    {/* Command centre header */}
    <div className="flex flex-col justify-between gap-st-space-lg border-b border-st-surface-container pb-st-space-lg md:flex-row md:items-end">
      <div className="flex flex-col gap-st-space-xs">
        <div className="flex items-center gap-st-space-sm text-st-outline">
          <span className={`inline-flex h-2 w-2 items-center justify-center rounded-full bg-st-secondary ${busy ? "animate-pulse" : ""}`} />
          <span className="font-bold tracking-wide text-st-secondary">پایش عملیات از داده‌های سامانه</span>
          <span className="text-st-outline-variant">/</span>
          <span className="font-medium text-st-on-surface-variant">پیشخوان مدیریت</span>
        </div>
        <h1 className="font-black tracking-tight text-st-primary">مرکز مدیریت عملیات ۶۰ آنلاین</h1>
        <p className="max-w-2xl text-st-on-surface-variant">استعلام‌ها، خرید سازمانی، تأمین‌کنندگان، کیفیت کاتالوگ و تسویه‌ها را از همین‌جا پیگیری کنید.</p>
      </div>
      <div className="flex items-center gap-st-space-md self-start whitespace-nowrap rounded-xl border border-st-surface-container bg-st-surface-container-lowest p-st-space-xs shadow-sm md:self-auto">
        <div className="flex items-center gap-st-space-sm px-st-space-sm py-st-space-xs text-st-on-surface-variant">
          <Icon name="schedule" className="text-[18px] text-st-secondary" />
          <span className="font-bold text-st-on-surface">{asOf ?? (busy ? "در حال دریافت…" : "—")}</span>
        </div>
        <label className="flex items-center gap-1 text-st-outline"><span className="sr-only">منطقه زمانی</span>
          <select value={zone} onChange={(event) => setZone(event.target.value)} dir="ltr" className="rounded-lg border-0 bg-transparent text-st-on-surface-variant outline-none">
            <option value="Asia/Tehran">Asia/Tehran</option><option value="UTC">UTC</option>
          </select></label>
        <div className="h-5 w-px bg-st-surface-container" />
        <button type="button" disabled={busy || !token} onClick={refresh} className="group flex items-center gap-st-space-xs rounded-lg bg-st-surface-container-low px-st-space-md py-st-space-xs text-st-on-surface transition-all hover:bg-st-surface-container active:scale-95 disabled:opacity-50">
          <Icon name="refresh" className={`text-[18px] text-st-on-surface-variant ${busy ? "animate-spin" : ""}`} /><span>بروزرسانی داده‌ها</span>
        </button>
      </div>
    </div>

    {data?.environment === "test" && <p role="status" className="mt-st-space-md flex items-center gap-st-space-xs rounded-xl bg-st-tertiary-fixed/50 px-st-space-md py-st-space-sm text-st-on-tertiary-fixed-variant">
      <Icon name="info" className="text-[18px]" />محیط آزمایشی · حساب‌ها و اسناد این پیش‌نمایش آزمایشی‌اند و اثر مالی واقعی ندارند.</p>}

    {error ? <div role="alert" className="mt-st-space-lg flex flex-col items-start gap-st-space-sm rounded-xl border border-st-error-container bg-st-error-container/40 p-st-space-lg">
      <b className="text-st-on-error-container">اطلاعات پیشخوان دریافت نشد</b><p className="break-words text-st-on-surface-variant">{error}</p>
      {token ? <button type="button" onClick={refresh} className="rounded-xl border border-st-surface-container bg-st-surface-container-lowest px-st-space-md py-st-space-xs">تلاش دوباره</button>
        : <Link href="/login?next=%2Fadmin" className="rounded-xl bg-st-primary-container px-st-space-md py-st-space-xs text-st-on-primary">ورود مجدد</Link>}
    </div> : <>
      {/* KPI cards */}
      <section aria-label="شاخص‌های عملیاتی" aria-busy={busy} className="mt-st-space-lg grid grid-cols-1 gap-st-space-md md:grid-cols-2 xl:grid-cols-4">
        {kpis.map((k) => <div key={k.key} className={card}>
          <div className="flex items-start justify-between">
            <div className="flex flex-col gap-st-space-xs">
              <span className="text-st-on-surface-variant">{k.title}</span>
              <div className="flex items-baseline gap-st-space-xs"><span className="font-extrabold text-st-primary">{show(m(k.key))}</span><span className="text-st-outline">{k.unit}</span></div>
            </div>
            <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${k.tone}`}><Icon name={k.icon} className="text-[24px]" /></div>
          </div>
          <div className="mt-st-space-md flex items-center justify-between gap-st-space-sm border-t border-st-surface-container-low pt-st-space-sm">{k.foot}</div>
        </div>)}
      </section>

      {/* Three bento panels */}
      <div className="mt-st-space-lg grid grid-cols-1 gap-st-space-md lg:grid-cols-3">
        <section className={panel} aria-labelledby="fin-title">
          <div>
            <div className="flex items-center justify-between border-b border-st-surface-container-low pb-st-space-sm">
              <div className="flex items-center gap-st-space-xs"><div className="h-2.5 w-2.5 rounded-full bg-st-on-tertiary-container" /><h2 id="fin-title" className="font-bold text-st-primary">صورتحساب مودیان و اتصال مالی</h2></div>
              <span className="text-st-outline">سپیدار</span>
            </div>
            <p className="mt-st-space-sm text-st-on-surface-variant">ارسال صورتحساب‌ها به سامانهٔ مودیان از کنسول مودیان انجام می‌شود؛ ثبت خودکار اسناد در نرم‌افزار مالی به اتصال سپیدار وابسته است.</p>
            <div className="mt-st-space-md flex flex-col gap-st-space-xs rounded-lg bg-st-surface-container-low/50 p-st-space-sm">
              <div className="flex items-center justify-between border-b border-st-surface-container-low py-1">
                <span className="font-semibold text-st-on-surface">اتصال سپیدار</span>
                <span className={data?.integrations.sepidar === "not_connected" ? "font-bold text-st-on-tertiary-container" : "text-st-outline"}>
                  {busy ? "در حال دریافت…" : data?.integrations.sepidar === "not_connected" ? "وصل نیست" : "نیازمند بررسی"}</span>
              </div>
              <div className="flex items-center justify-between border-b border-st-surface-container-low py-1">
                <span className="font-semibold text-st-on-surface">تسویهٔ منتظر پرداخت</span><span className="text-st-outline">{show(m("settlements_pending"))} مورد</span>
              </div>
              <div className="flex items-center justify-between py-1 text-st-outline">
                <span>صورتحساب‌ها و وضعیت ارسال</span><Link href="/admin/moadian" className="font-bold text-st-secondary">مشاهده لیست</Link>
              </div>
            </div>
          </div>
          <div className="mt-st-space-sm flex items-center justify-between pt-st-space-md">
            <span className="font-medium text-st-on-surface-variant">کنسول مودیان</span>
            <Link href="/admin/moadian" className="flex items-center gap-st-space-xs rounded-xl bg-st-primary-container px-st-space-md py-st-space-xs text-st-on-primary transition-colors hover:bg-st-secondary">
              <Icon name="task_alt" className="text-[16px]" /><span>صورتحساب مودیان</span></Link>
          </div>
        </section>

        <section className={panel} aria-labelledby="ops-title" aria-busy={busy}>
          <div>
            <div className="flex items-center justify-between border-b border-st-surface-container-low pb-st-space-sm">
              <div className="flex items-center gap-st-space-xs"><div className="h-2.5 w-2.5 rounded-full bg-st-secondary" /><h2 id="ops-title" className="font-bold text-st-primary">عملیات سازمانی من</h2></div>
              {opsState === "ready" && data && <span className="rounded-full bg-st-secondary-fixed/50 px-2 py-0.5 font-bold text-st-secondary">{toPersianNum(data.operations.items.length)}{data.operations.has_more ? "+" : ""} پرونده</span>}
            </div>
            <p className="mt-st-space-sm text-st-on-surface-variant">پرونده‌های خرید سازمانی در محدودهٔ مجوز عملیات شما.</p>
            <div className="mt-st-space-md flex flex-col gap-st-space-xs">
              {opsState === "pending" ? <p role="status" className="text-st-outline">در حال دریافت محدودهٔ مجاز شما…</p>
                : opsState === "ready" && data ? data.operations.items.slice(0, 3).map((item) =>
                  <Link key={`${item.organization_id}:${item.id}`} href={`/operations/cases/${item.organization_id}/${item.id}`} className="flex items-center justify-between rounded-lg bg-st-surface p-st-space-xs hover:bg-st-surface-container">
                    <div className="flex min-w-0 items-center gap-st-space-xs"><Icon name="apartment" className="text-[20px] text-st-outline" />
                      <div className="flex min-w-0 flex-col"><span className="truncate font-bold text-st-on-surface">{item.title}</span><span className="text-st-outline">پرونده {toPersianNum(item.id)}</span></div></div>
                    <Icon name="chevron_left" className="text-[18px] text-st-secondary" /></Link>)
                : <p role="status" className="rounded-lg bg-st-surface p-st-space-sm text-st-on-surface-variant">{opsState === "forbidden"
                  ? "برای نمایش صف، مجوز عملیات مستقل هر سازمان لازم است."
                  : opsState === "empty" ? "در محدودهٔ مجاز شما پرونده‌ای در صف نیست."
                  : "وضعیت عملیات هنوز دریافت نشده است."}</p>}
            </div>
          </div>
          <div className="mt-st-space-sm flex items-center justify-between pt-st-space-md">
            <span className="text-st-outline">{data?.operations.has_more ? "موارد بیشتری در میز کار است" : "میز کار عملیات"}</span>
            <Link href="/operations/requests" className="flex items-center gap-st-space-xs rounded-xl border border-st-primary-container px-st-space-md py-st-space-xs text-st-primary-container transition-colors hover:bg-st-surface-container">
              <span>میز کار عملیات</span><Icon name="arrow_back" className="text-[16px]" /></Link>
          </div>
        </section>

        <section className={panel} aria-labelledby="log-title">
          <div>
            <div className="flex items-center justify-between border-b border-st-surface-container-low pb-st-space-sm">
              <div className="flex items-center gap-st-space-xs"><div className="h-2.5 w-2.5 rounded-full bg-st-outline" /><h2 id="log-title" className="font-bold text-st-primary">لجستیک و کیفیت کاتالوگ</h2></div>
              <span className="font-bold text-st-on-surface-variant">{show(m("missing_images"))} کالای بی‌تصویر</span>
            </div>
            <p className="mt-st-space-sm text-st-on-surface-variant">برآورد کرایهٔ حمل از تعرفهٔ حامل‌های فعال و ثبت مغایرت تحویل بارنامه. پایش زندهٔ ناوگان هنوز به سامانه وصل نیست.</p>
            <div className="mt-st-space-md flex flex-col gap-st-space-sm">
              <Link href="/logistics/estimate" className="flex items-center justify-between rounded-lg bg-st-surface p-st-space-xs hover:bg-st-surface-container"><span className="flex items-center gap-st-space-xs text-st-on-surface"><Icon name="calculate" className="text-[20px] text-st-secondary" />محاسبه‌گر وزن و کرایهٔ حمل</span><Icon name="chevron_left" className="text-[18px] text-st-outline" /></Link>
              <Link href="/admin/logistics" className="flex items-center justify-between rounded-lg bg-st-surface p-st-space-xs hover:bg-st-surface-container"><span className="flex items-center gap-st-space-xs text-st-on-surface"><Icon name="report_problem" className="text-[20px] text-st-secondary" />مغایرت تحویل و تحلیل ناوگان</span><Icon name="chevron_left" className="text-[18px] text-st-outline" /></Link>
            </div>
          </div>
          <div className="mt-st-space-sm flex items-center justify-between pt-st-space-md">
            <div className="flex items-center gap-st-space-xs text-st-outline"><Icon name="local_shipping" className="text-[16px] text-st-secondary" /><span>مانیتورینگ ناوگان: به‌زودی</span></div>
            <Link href="/admin/catalog-review" className="flex items-center gap-st-space-xs rounded-xl bg-st-surface-container px-st-space-md py-st-space-xs text-st-on-surface transition-colors hover:bg-st-surface-variant"><span>کیفیت کاتالوگ</span></Link>
          </div>
        </section>
      </div>

      {/* Attention queue table */}
      <section aria-labelledby="attention-title" aria-busy={busy} className="mt-st-space-lg flex flex-col overflow-hidden rounded-xl border border-st-surface-container bg-st-surface-container-lowest shadow-sm">
        <div className="flex flex-col justify-between gap-st-space-md border-b border-st-surface-container p-st-space-lg lg:flex-row lg:items-center">
          <div className="flex flex-col gap-st-space-xs">
            <div className="flex items-center gap-st-space-xs">
              <h2 id="attention-title" className="font-extrabold text-st-primary">صف رسیدگی</h2>
              {data && <span className="rounded-full bg-st-surface-container px-2 py-0.5 font-bold text-st-on-surface-variant">{toPersianNum(attention.length)} مورد</span>}
            </div>
            <p className="text-st-on-surface-variant">نمونهٔ موارد باز هر حوزه: استعلام شخصی، تصویر کاتالوگ و وضعیت تأمین‌کننده</p>
          </div>
          <div className="flex flex-wrap items-center gap-st-space-sm">
            <label className="flex items-center rounded-xl border border-st-surface-container bg-st-surface px-st-space-sm py-1.5">
              <Icon name="filter_alt" className="ml-1 text-[18px] text-st-outline" /><span className="sr-only">نوع مورد</span>
              <select value={filter} onChange={(event) => setFilter(event.target.value as QueueFilter)} className="cursor-pointer border-none bg-transparent text-st-on-surface outline-none">
                {queueFilters.map(({ value, label }) => <option key={value} value={value}>{value === "all" ? "همه موارد" : label}</option>)}
              </select>
            </label>
            <Link href="/admin/catalog#catalog-import" className="flex items-center gap-st-space-xs rounded-xl border border-st-surface-container px-st-space-md py-2 text-st-on-surface transition-colors hover:bg-st-surface">
              <Icon name="upload_file" className="text-[18px] text-st-outline" /><span>ورود گروهی CSV</span></Link>
            <Link href="/admin/catalog/new" className="flex items-center gap-st-space-xs rounded-xl bg-st-primary-container px-st-space-md py-2 text-st-on-primary transition-colors hover:bg-st-secondary">
              <Icon name="add_circle" className="text-[18px]" /><span>ایجاد مستقیم کالا</span></Link>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-right">
            <thead><tr className="border-b border-st-surface-container bg-st-surface text-st-on-surface-variant">
              <th className="px-st-space-lg py-st-space-md font-bold">شناسه</th>
              <th className="px-st-space-md py-st-space-md font-bold">عنوان</th>
              <th className="px-st-space-md py-st-space-md font-bold">حوزه</th>
              <th className="px-st-space-md py-st-space-md font-bold">وضعیت ثبت‌شده</th>
              <th className="px-st-space-lg py-st-space-md text-left font-bold">عملیات ادمین</th>
            </tr></thead>
            <tbody className="divide-y divide-st-surface-container text-st-on-surface">
              {busy ? <tr><td colSpan={5} role="status" className="px-st-space-lg py-st-space-xl text-center text-st-on-surface-variant">در حال دریافت کارهای باز…</td></tr>
                : attention.length ? attention.map((item) => <tr key={`${item.kind}:${item.id}`} className="transition-colors hover:bg-st-surface/60">
                  <td className="px-st-space-lg py-st-space-md font-bold text-st-primary">{toPersianNum(item.id)}</td>
                  <td className="px-st-space-md py-st-space-md"><span className="font-bold text-st-primary [overflow-wrap:anywhere]">{item.title}</span></td>
                  <td className="px-st-space-md py-st-space-md"><span className={`inline-flex items-center gap-1 rounded-full px-st-space-xs py-0.5 text-st-label-sm font-bold ${kindChip[item.kind]}`}>
                    <Icon name={kindIcon[item.kind]} className="text-[14px]" />{attentionLabels[item.kind]}</span></td>
                  <td className="px-st-space-md py-st-space-md"><span dir="ltr" className="inline-flex items-center gap-1.5 rounded-full bg-st-surface-container px-st-space-sm py-1 text-st-label-sm font-bold text-st-on-surface-variant">
                    <span className="h-1.5 w-1.5 rounded-full bg-st-on-tertiary-container" />{item.status}</span></td>
                  <td className="px-st-space-lg py-st-space-md text-left"><Link href={item.href} title="رسیدگی" className="inline-flex items-center gap-1 rounded-lg p-1.5 text-st-secondary transition-colors hover:bg-st-surface-container">
                    <Icon name="visibility" className="text-[18px]" /><span>رسیدگی</span></Link></td>
                </tr>)
                : <tr><td colSpan={5} role="status" className="px-st-space-lg py-st-space-xl text-center text-st-on-surface-variant">
                  <Icon name="task_alt" className="mb-st-space-xs block text-[30px] text-st-secondary" />موردی در این نمونهٔ صف دیده نشد؛ برای بررسی همهٔ سوابق، بخش مربوط را از منو باز کنید.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="flex flex-col items-center justify-between gap-st-space-md border-t border-st-surface-container bg-st-surface p-st-space-md text-st-on-surface-variant sm:flex-row">
          <span>{data?.attention_is_sample ? "این صف نمونه است (حداکثر ۸ مورد از هر حوزه)؛ فیلتر فقط روی همین موارد اعمال می‌شود." : "صف رسیدگی"}</span>
          <div className="flex flex-wrap items-center gap-st-space-sm">
            <Link href="/admin/inquiries" className="font-bold text-st-secondary hover:underline">استعلام‌ها</Link>
            <Link href="/admin/catalog-review" className="font-bold text-st-secondary hover:underline">کیفیت کاتالوگ</Link>
            <Link href="/admin/suppliers" className="font-bold text-st-secondary hover:underline">تأمین‌کنندگان</Link>
          </div>
        </div>
      </section>
    </>}

    {/* Audit bar */}
    <div className="mb-st-space-sm mt-st-space-lg flex flex-col items-center justify-between gap-st-space-md rounded-xl bg-st-surface-container-low p-st-space-md md:flex-row">
      <div className="flex items-center gap-st-space-sm"><Icon name="policy" className="text-[22px] text-st-secondary" />
        <span className="text-st-on-surface-variant">تغییرات کالا، قیمت، دسترسی و تنظیمات در تاریخچهٔ تغییرات سامانه ثبت می‌شود.</span></div>
      <div className="flex items-center gap-st-space-lg text-st-label-sm text-st-outline">
        <Link href="/admin/access" className="hover:text-st-primary">دسترسی‌ها و سیاست‌ها</Link>
        <Link href="/admin/audit" className="font-bold text-st-secondary hover:text-st-primary">تاریخچهٔ تغییرات</Link>
      </div>
    </div>
  </div>;
}
