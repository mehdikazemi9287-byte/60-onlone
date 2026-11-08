"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, RefreshCw, Clock3, ShieldCheck } from "lucide-react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { toPersianNum } from "@/lib/utils";
import {
  attentionLabels, filterAttention, formatSnapshotTime, metricValue,
  operationsState, parseDashboard, queueFilters,
  type Dashboard, type QueueFilter,
} from "./dashboard-state";
import s from "./admin.module.css";

const cards = [
  ["personal_today", "استعلام شخصی امروز", "/admin/inquiries", "در بازهٔ روزِ منطقه زمانی انتخاب‌شده"],
  ["org_waiting", "درخواست سازمانی منتظر بررسی", "/admin/cases", "ارسال‌شده یا در حال بررسی"],
  ["quotes_submitted", "Quote ارسال‌شده", "/admin/cases", "پیشنهاد تأمین‌کننده در وضعیت ارسال‌شده"],
  ["missing_images", "کالای بدون تصویر", "/admin/catalog-review", "کالای مرجع واقعی و فعال، بدون URL تصویر"],
  ["suppliers_inactive", "تأمین‌کننده غیرفعال", "/admin/suppliers", "حساب واقعی با وضعیت غیر فعال"],
  ["settlements_pending", "تسویه منتظر ثبت پرداخت", "/admin/settlements", "صورت تسویهٔ واقعی در انتظار پرداخت"],
] as const;
const entryLinks = [
  ["/admin/catalog/new", "ایجاد مستقیم کالا"],
  ["/admin/catalog#catalog-import", "ورود گروهی CSV"],
  ["/admin/media", "کتابخانه رسانه"],
] as const;
const shortcuts = [
  ["/admin/inquiries", "استعلام مشتریان"],
  ["/admin/catalog-review", "کیفیت و انتشار کاتالوگ"],
  ["/operations/requests", "میز کار عملیات"],
] as const;
type RequestState = {
  key: string;
  status: "loading" | "ready" | "error";
  data: Dashboard | null;
  message: string;
};

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
  const asOf = data ? formatSnapshotTime(data.as_of, data.timezone) : null;
  const refresh = () => setRetry((value) => value + 1);

  return <div className={s.dashboard}>
    <section className={s.heading}>
      <div><h1>پیشخوان</h1><p>استعلام‌ها، تأمین، کیفیت کاتالوگ و کارهای مالی را از همین‌جا پیگیری کنید.</p></div>
      <button type="button" className={s.secondary} disabled={busy || !token} onClick={refresh}>
        <RefreshCw size={16} aria-hidden="true" />به‌روزرسانی
      </button>
    </section>
    <nav className={s.entryLinks} aria-label="ورود اطلاعات فروشگاه">
      {entryLinks.map(([href, label]) => <Link key={href} href={href} className={s.secondary}>
        {label}<ArrowLeft size={15} aria-hidden="true" />
      </Link>)}
    </nav>
    <div className={`${s.context} ${s.dashboardContext}`}>
      <span><Clock3 size={15} aria-hidden="true" />آخرین دریافت: {asOf ?? "—"}</span>
      <span>حوزه: دسترسی‌های شما</span>
      <label>منطقه زمانی <select value={zone} onChange={(event) => setZone(event.target.value)}>
        <option value="Asia/Tehran">Asia/Tehran</option><option value="UTC">UTC</option>
      </select></label>
    </div>
    {data?.environment === "test" && <p className={s.warning} role="status">
      محیط آزمایشی · حساب‌ها و اسناد این پیش‌نمایش آزمایشی‌اند و اثر مالی واقعی ندارند.
    </p>}
    {error ? <div className={s.error} role="alert">
      <b>اطلاعات پیشخوان دریافت نشد</b><p>{error}</p>
      {token ? <button type="button" className={s.secondary} onClick={refresh}>تلاش دوباره</button>
        : <Link className={s.secondary} href="/login?next=%2Fadmin">ورود مجدد</Link>}
    </div> : <>
      <section className={s.metrics} aria-label="شاخص‌های عملیاتی" aria-busy={busy}>
        {cards.map(([key, title, href, note]) => {
          const value = metricValue(data?.metrics[key]);
          return <Link key={key} href={href} className={s.metric}>
            <span>{title}</span><strong>{value === null ? "—" : toPersianNum(value)}</strong>
            <small>{busy ? "در حال دریافت…" : value === null ? "اطلاعات این شاخص در دسترس نیست." : note}</small>
            <span className={s.metricLink}>مشاهده و رسیدگی<ArrowLeft size={14} aria-hidden="true" /></span>
          </Link>;
        })}
      </section>
      <div className={s.columns}>
        <section className={s.panel} aria-labelledby="attention-title" aria-busy={busy}>
          <div className={s.panelHead}><h2 id="attention-title">صف رسیدگی</h2><span>نمونهٔ موارد باز هر حوزه</span></div>
          <div className={s.queueFilters} role="group" aria-label="فیلتر نوع کار">
            {queueFilters.map(({ value, label }) => <button key={value} type="button"
              aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}
          </div>
          <label className={s.queueFilterMobile}>نوع مورد
            <select value={filter} onChange={(event) => setFilter(event.target.value as QueueFilter)}>
              {queueFilters.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          {busy ? <div role="status" className={`${s.empty} ${s.queueState}`}>
            <b>در حال دریافت کارهای باز…</b><p>اطلاعات پس از دریافت از سرور نمایش داده می‌شود.</p>
          </div> : attention.length ? <div className={s.queue}>
            {attention.map((item) => <Link key={`${item.kind}:${item.id}`} href={item.href}>
              <div><small>{attentionLabels[item.kind]} · شناسه {toPersianNum(item.id)}</small><b>{item.title}</b></div>
              <span>رسیدگی<ArrowLeft size={16} aria-hidden="true" /></span>
            </Link>)}
          </div> : <div className={`${s.empty} ${s.queueState}`} role="status">
            <ShieldCheck size={30} aria-hidden="true" /><h3>موردی در این نمونهٔ صف دیده نشد</h3>
            <p>برای بررسی همهٔ سوابق، بخش مربوط را از منو باز کنید.</p>
          </div>}
          {data?.attention_is_sample && <p className={s.caption}>این صف نمونه است؛ فیلترها فقط روی همین موارد دریافت‌شده اعمال می‌شوند.</p>}
        </section>
        <div className={s.sidePanels}>
          <section className={s.panel} aria-labelledby="operations-title" aria-busy={busy}>
            <div className={s.panelHead}><h2 id="operations-title">عملیات سازمانی من</h2></div>
            {opsState === "pending" ? <p role="status" className={s.caption}>در حال دریافت محدودهٔ مجاز شما…</p>
              : opsState === "ready" && data ? <div className={s.queue}>{data.operations.items.map((item) =>
                <Link key={`${item.organization_id}:${item.id}`} href={`/operations/cases/${item.organization_id}/${item.id}`}>
                  <b>{item.title}</b><ArrowLeft size={16} aria-hidden="true" />
                </Link>)}</div>
              : <p className={s.caption} role="status">{opsState === "forbidden"
                ? "برای نمایش صف، مجوز عملیات مستقل هر سازمان لازم است."
                : opsState === "empty" ? "در محدودهٔ مجاز شما پرونده‌ای در صف نیست."
                : "وضعیت عملیات هنوز دریافت نشده است."}</p>}
            {data?.operations.has_more && <p className={s.caption}>موارد بیشتری در میز کار عملیات وجود دارد.</p>}
            <Link className={s.textLink} href="/operations/requests">میز کار عملیات<ArrowLeft size={15} aria-hidden="true" /></Link>
          </section>
          <section className={s.panel} aria-labelledby="integration-title">
            <div className={s.panelHead}><h2 id="integration-title">اتصال‌های مالی</h2></div>
            <div className={s.integration}><b>سپیدار</b><span>{busy ? "در حال دریافت…"
              : data?.integrations.sepidar === "not_connected" ? "وصل نیست" : "نیازمند بررسی"}</span></div>
            <p className={s.caption}>{busy ? "وضعیت اتصال از سرور دریافت می‌شود."
              : data?.integrations.sepidar === "not_connected"
                ? "ثبت و ارسال خودکار اسناد سپیدار فعال نشده است."
                : "وضعیت عملیاتی اتصال هنوز تأیید نشده است."}</p>
            <Link className={s.textLink} href="/admin/access">بررسی سیاست‌ها و دسترسی‌ها<ArrowLeft size={15} aria-hidden="true" /></Link>
          </section>
        </div>
      </div>
    </>}
    <section className={s.shortcuts} aria-labelledby="shortcuts-title">
      <h2 id="shortcuts-title">دسترسی سریع</h2>
      <div>{shortcuts.map(([href, label]) => <Link key={href} href={href}>
        {label}<ArrowLeft size={15} aria-hidden="true" />
      </Link>)}</div>
    </section>
  </div>;
}
