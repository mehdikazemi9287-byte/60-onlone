import type { Metadata } from "next";

// «وامبی چیست»: honest copy from docs/COMMS-PLAN.md.
// Every rule below mirrors app/services/price_alert_service.py; change both together.
export const metadata: Metadata = {
  title: "وامبی چیست",
  description: "وامبی قیمت یک کالا را بین فروشنده‌های طرف قرارداد شصت آنلاین مقایسه می‌کند و برای ارزان شدن یا موجود شدنش هشدار می‌دهد.",
};

const LEVELS: { who: string; alerts: string }[] = [
  { who: "خریدار عادی", alerts: "رسیدن قیمت به قیمت هدف شما، موجود شدن کالا" },
  { who: "کارمند سازمان", alerts: "رسیدن به قیمت هدف، موجود شدن، اضافه شدن کالا به سبد رفاهی سازمان" },
  { who: "مسئول خرید سازمان", alerts: "کاهش قیمت در تعداد معمول سازمان، فروشندهٔ تازه، پایان قیمت قراردادی تا ۷ روز دیگر" },
  { who: "فروشگاه طرف قرارداد", alerts: "کاهش قیمت عمده، پلهٔ تخفیف تعدادی جدید، موجود شدن" },
  { who: "فروشنده", alerts: "«دیگر بهترین پیشنهاد نیستید»، بدون نام یا قیمت رقیب" },
];

const h2 = "text-lg font-black text-[#102B7A]";
const box = "rounded-2xl bg-white p-5 ring-1 ring-[#DCE3F7]";

export default function VambiAbout() {
  return (
    <article dir="rtl" className="mx-auto max-w-3xl space-y-5 px-4 py-8 leading-8 text-neutral-800">
      <header className="space-y-2">
        <h1 className="text-2xl font-black text-[#102B7A] md:text-3xl">وامبی چیست؟</h1>
        <p className="text-base">
          قیمت یک کالا را بین فروشنده‌های طرف قرارداد شصت آنلاین مقایسه کن و برای ارزان شدن یا موجود شدنش هشدار بگیر.
        </p>
      </header>

      <section className={box} aria-labelledby="scope">
        <h2 id="scope" className={h2}>چه چیزی را مقایسه می‌کند</h2>
        <ul className="mt-2 list-disc space-y-1 pr-5">
          <li>فقط فروشنده‌هایی که با شصت آنلاین قرارداد دارند. وامبی <strong>کل بازار را مقایسه نمی‌کند</strong> و از سایت‌های دیگر قیمت جمع نمی‌کند.</li>
          <li>هر نتیجه یک کالای مشخص است و پیشنهاد همهٔ این فروشنده‌ها کنار هم دیده می‌شود: قیمت با مالیات بر ارزش افزوده، زمان تحویل، موجودی و شهر فروشنده.</li>
          <li>اگر قیمت فروشنده‌ای تأیید تازه نداشته باشد، قیمتی برای او نشان داده نمی‌شود.</li>
          <li>نمایش قیمت از قانون نمایش قیمت شصت آنلاین پیروی می‌کند؛ ممکن است قیمت فقط برای اعضا دیده شود.</li>
        </ul>
      </section>

      <section className={box} aria-labelledby="levels">
        <h2 id="levels" className={h2}>هشدار برای هر سطح</h2>
        <p className="mt-1 text-sm text-neutral-600">هر کس فقط قیمت سطح خودش را می‌بیند و فقط برای همان هشدار می‌گیرد. سطح شما از حساب شما تعیین می‌شود، نه از انتخاب شما.</p>
        <dl className="mt-3 space-y-2">
          {LEVELS.map((l) => (
            <div key={l.who} className="rounded-xl bg-[#F5F7FD] p-3">
              <dt className="font-bold text-[#102B7A]">{l.who}</dt>
              <dd className="text-sm">{l.alerts}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className={box} aria-labelledby="sms">
        <h2 id="sms" className={h2}>قانون پیامک</h2>
        <ul className="mt-2 list-disc space-y-1 pr-5">
          <li>هر هشدار در خود سایت می‌آید؛ پیامک فقط به شمارهٔ تأییدشده فرستاده می‌شود.</li>
          <li>پیامک <strong>هیچ قیمتی ندارد</strong>؛ قیمت را در سایت ببینید.</li>
          <li>هر نفر <strong>حداکثر ۲ پیامک در روز</strong> می‌گیرد و چند هشدار در یک پیامک جمع می‌شود.</li>
          <li>از <strong>ساعت ۲۲ تا ۸ صبح</strong> پیامکی فرستاده نمی‌شود.</li>
          <li>پیامک هر کالا را می‌توانید خاموش کنید؛ فروشنده‌ها هم می‌توانند پیامک هشدار را خاموش کنند و فقط در پنل ببینند.</li>
        </ul>
      </section>

      <section className={box} aria-labelledby="login">
        <h2 id="login" className={h2}>ورود</h2>
        <p className="mt-2">برای «زیر نظر بگیر» و هشدارها با همان حساب شصت آنلاین وارد شوید؛ حساب جداگانه لازم نیست.</p>
      </section>

      <p className="text-center">
        <a href="/" className="inline-block rounded-2xl bg-[#1748C9] px-6 py-3 font-bold text-white hover:bg-[#0B2A80]">جستجو در وامبی</a>
      </p>
    </article>
  );
}
