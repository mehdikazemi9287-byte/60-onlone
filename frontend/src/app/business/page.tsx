import type { Metadata } from "next";
import Link from "next/link";
import { BusinessApplication } from "./BusinessApplication";
import st from "@/components/organization/stitch.module.css";

// Bulk organizational order (سفارش عمده سازمانی) — layout of Stitch screens 52 (desktop) / 42 (mobile), mapped to the
// closest real flow: the B2B account / bulk inquiry application (POST /b2b/applications). There is no dedicated
// cultural/school pack catalog, volume-tier pricing or Setad integration in the backend, so the Stitch pack cards,
// tier table and Setad number field are not shown; every link below points to an existing route.
export const metadata: Metadata = {
  title: "سفارش عمده و حساب سازمانی",
  description: "خرید سازمانی با اعتبار و قیمت قراردادی، و خرید عمده برای فروشگاه‌ها، مدارس و نهادها. درخواست استعلام و باز کردن حساب بدهید؛ همکاران ما تماس می‌گیرند.",
};

const Icon = ({ name, className = "" }: { name: string; className?: string }) => <span aria-hidden className={`material-symbols-outlined ${className}`}>{name}</span>;

const STEPS = [
  ["ثبت درخواست استعلام", "معرفی سازمان، رابط و حجم خرید"],
  ["بررسی و عقد قرارداد", "تماس کارشناس و تعیین شرایط پرداخت"],
  ["انتخاب اقلام و پیش‌فاکتور", "پیش‌فاکتور رسمی قابل چاپ A4"],
  ["تحویل و فاکتور رسمی", "پیگیری سفارش در میز کار سازمانی"],
];
const FEATURES: [string, string, string][] = [
  ["description", "پیش‌فاکتور رسمی", "پیش‌فاکتور معتبر با مهلت، قابل چاپ و خروجی گروهی"],
  ["account_balance_wallet", "خرید با اعتبار سازمانی", "سقف اعتبار و مهلت پرداخت طبق قرارداد"],
  ["history_edu", "تأمین دوره‌ای", "فهرست‌های هفتگی و ماهانه با پیش‌فاکتور خودکار"],
  ["fact_check", "گردش تأیید خرید", "درخواست کارمند، تأیید مدیر و تبدیل به سفارش"],
  ["inventory_2", "پک‌ساز سفارشی", "ساخت بسته‌های هدیه و رفاهی از کالاهای موجود"],
  ["support_agent", "پیگیری تا تحویل", "وضعیت سفارش، تحویل و مرجوعی در یک پنل"],
];
const PAYMENTS: [string, string, string, string][] = [
  ["account_balance_wallet", "اعتبار سازمانی", "برداشت از سقف اعتبار قرارداد و تسویه در مهلت مقرر؛ صورت‌حساب هفتگی و ماهانه.", "پس از عقد قرارداد اعتباری"],
  ["payments", "پرداخت نقدی", "پرداخت آنلاین هر سفارش یا پیش‌فاکتور از درگاه بانکی.", "بدون نیاز به قرارداد"],
  ["policy", "ترکیب طبق سیاست سازمان", "روش‌های مجاز پرداخت هر سازمان در سیاست پرداخت مصوب آن تعیین می‌شود.", "تعریف در پنل سازمانی"],
];

export default function BusinessPage() {
  return (
    <main dir="rtl" className={`${st.shell} bg-st-background text-st-on-surface`}>
      {/* Hero */}
      <section className="border-b border-st-surface-container bg-st-surface-container-lowest">
        <div className="mx-auto max-w-[1440px] px-st-space-md py-st-space-lg md:px-st-margin-lg">
          <nav aria-label="مسیر" className="flex items-center gap-1 text-[13px] text-st-outline"><Link href="/">۶۰ آنلاین</Link><Icon name="chevron_left" className="text-[14px]" /><Link href="/org">خرید سازمانی</Link><Icon name="chevron_left" className="text-[14px]" /><span className="font-bold text-st-primary">سفارش عمده و حساب سازمانی</span></nav>
          <div className="mt-st-space-md flex flex-col justify-between gap-st-space-lg lg:flex-row lg:items-end">
            <div className="max-w-3xl">
              <p className="font-bold text-st-secondary">تدارکات انبوه B2B · شرکت‌ها، مدارس، نهادها و فروشگاه‌ها</p>
              <h1 className="mt-st-space-xs text-[26px] font-extrabold leading-[1.5] text-st-primary md:text-[36px]">سفارش عمده و سازمانی ویژه مدارس، نهادها و شرکت‌ها</h1>
              <p className="mt-st-space-sm leading-8 text-st-on-surface-variant">برای سازمان‌ها: خرید با اعتبار، صورت‌حساب هفتگی، قیمت قراردادی و گردش تأیید خرید. برای فروشگاه‌ها: خرید عمده با قیمت پلکانی و مهلت پرداخت. حساب‌ها پس از بررسی و عقد قرارداد باز می‌شوند.</p>
            </div>
            <div className="flex flex-wrap gap-st-space-sm">
              <a href="#inquiry" className="inline-flex h-12 items-center gap-st-space-xs rounded-xl bg-st-primary-container px-st-space-lg font-bold text-st-on-primary"><Icon name="request_quote" className="text-[20px]" />ثبت درخواست استعلام</a>
              <Link href="/pack-builder" className="inline-flex h-12 items-center gap-st-space-xs rounded-xl bg-st-surface-container-low px-st-space-lg font-semibold text-st-primary"><Icon name="inventory_2" className="text-[20px]" />ساخت پک سفارشی</Link>
            </div>
          </div>
          <ol className="mt-st-space-lg grid gap-st-space-sm rounded-xl bg-st-surface p-st-space-sm sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map(([t, d], i) => (
              <li key={t} className={`flex items-center gap-st-space-sm rounded-xl p-st-space-sm ${i === 0 ? "bg-st-surface-container-lowest shadow-sm" : ""}`}>
                <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg font-bold ${i === 0 ? "bg-st-primary-container text-st-on-primary" : "bg-st-surface-container text-st-primary"}`}>{(i + 1).toLocaleString("fa-IR")}</span>
                <span><b className="block text-st-primary">{t}</b><span className="text-[13px] text-st-on-surface-variant">{d}</span></span>
              </li>))}
          </ol>
        </div>
      </section>

      {/* Feature strip */}
      <section className="mx-auto grid max-w-[1440px] grid-cols-2 gap-st-space-sm px-st-space-md py-st-space-lg md:grid-cols-3 md:px-st-margin-lg lg:grid-cols-6">
        {FEATURES.map(([i, t, d]) => (
          <div key={t} className="flex flex-col items-center gap-st-space-xs rounded-xl bg-st-surface-container-lowest p-st-space-md text-center shadow-sm">
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-st-secondary-fixed text-st-on-secondary-fixed"><Icon name={i} className="text-[22px]" /></span>
            <b className="text-st-primary">{t}</b><span className="text-[13px] text-st-on-surface-variant">{d}</span>
          </div>))}
      </section>

      <div className="mx-auto grid max-w-[1440px] gap-st-space-lg px-st-space-md pb-st-space-xl md:px-st-margin-lg lg:grid-cols-[1fr_380px]">
        {/* Payment methods */}
        <section aria-labelledby="pay-h" className="flex flex-col gap-st-space-md">
          <div><h2 id="pay-h" className="flex items-center gap-st-space-xs text-[20px] font-bold text-st-primary"><Icon name="payments" className="text-[22px] text-st-secondary" />روش‌های پرداخت و تسهیلات تجاری تدارکات</h2>
            <p className="text-st-on-surface-variant">منطبق بر قرارداد و سیاست پرداخت هر سازمان</p></div>
          <div className="grid gap-st-space-md md:grid-cols-2">
            {PAYMENTS.map(([i, t, d, c]) => (
              <article key={t} className="flex flex-col gap-st-space-sm rounded-xl bg-st-surface-container-lowest p-st-space-lg shadow-sm">
                <div className="flex items-center gap-st-space-sm"><span className="flex h-10 w-10 items-center justify-center rounded-lg bg-st-surface-container text-st-primary"><Icon name={i} className="text-[22px]" /></span><h3 className="font-bold text-st-primary">{t}</h3></div>
                <p className="text-[14px] leading-7 text-st-on-surface-variant">{d}</p>
                <p className="mt-auto flex justify-between rounded-lg bg-st-surface px-st-space-sm py-1.5 text-[13px]"><span className="text-st-outline">شرایط:</span><b className="text-st-primary">{c}</b></p>
              </article>))}
            <article className="flex flex-col gap-st-space-sm rounded-xl border border-dashed border-st-outline-variant p-st-space-lg">
              <div className="flex items-center gap-st-space-sm"><span className="flex h-10 w-10 items-center justify-center rounded-lg bg-st-surface-container text-st-outline"><Icon name="account_balance" className="text-[22px]" /></span><h3 className="font-bold text-st-on-surface-variant">تسویه در سامانه تدارکات دولت (ستاد)</h3></div>
              <p className="text-[14px] text-st-on-surface-variant">اتصال به سامانه ستاد هنوز فعال نیست.</p>
              <span className="self-start rounded-full bg-st-surface-container px-st-space-sm py-0.5 text-[13px] text-st-on-surface-variant">به‌زودی</span>
            </article>
          </div>
          <div className="flex flex-col items-start justify-between gap-st-space-sm rounded-xl bg-st-primary-container p-st-space-lg text-st-on-primary md:flex-row md:items-center">
            <div><b>حساب سازمانی فعال دارید؟</b><p className="text-[14px] opacity-80">سفارش، پیش‌فاکتور و تأمین دوره‌ای را از میز کار سازمانی مدیریت کنید.</p></div>
            <Link href="/org" className="inline-flex shrink-0 items-center gap-st-space-xs rounded-xl bg-st-surface-container-lowest px-st-space-md py-st-space-sm font-bold text-st-primary">ورود به میز کار سازمانی<Icon name="chevron_left" className="text-[18px]" /></Link>
          </div>
        </section>

        {/* Inquiry form card (Stitch «خلاصه سبد استعلام B2B») */}
        <aside id="inquiry" className="scroll-mt-24 self-start rounded-xl bg-st-surface-container-lowest p-st-space-lg shadow-sm lg:sticky lg:top-24">
          <div className="mb-st-space-md flex items-center justify-between border-b border-st-surface-container pb-st-space-sm">
            <h2 className="flex items-center gap-st-space-xs font-bold text-st-primary"><Icon name="request_quote" className="text-[20px] text-st-secondary" />فرم استعلام و حساب B2B</h2>
            <span className="rounded-full bg-st-primary-container px-st-space-sm py-0.5 text-[12px] text-st-on-primary">مشخصات حقوقی</span>
          </div>
          <BusinessApplication />
        </aside>
      </div>
    </main>
  );
}
