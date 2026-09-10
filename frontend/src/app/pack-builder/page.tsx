import type { Metadata } from "next";
import { PackBuilderClient } from "./PackBuilderClient";

export const metadata: Metadata = {
  title: "پک‌ساز | شصت‌آنلاین",
  description:
    "پک‌ساز شصت‌آنلاین: از کاتالوگ واقعی کالا انتخاب کنید، پک بسازید و ذخیره کنید، یک‌جا به سبد بیفزایید یا درخواست پیش‌فاکتور سازمانی ثبت کنید. جمع کل فقط از قیمت‌های تأییدشده.",
  alternates: { canonical: "https://60online.ir/pack-builder" },
};

export default function PackBuilderPage() {
  return (
    <div className="internal-page container-page py-6 md:py-10">
      <div className="internal-hero mb-6">
        <div>
          <span className="section-kicker">خرید گروهی</span>
          <h1>پک‌ساز</h1>
          <p>
            بودجه و مناسبت را انتخاب کنید تا سه پک پیشنهادی (اقتصادی، متعادل، ویژه) از کالاهای واقعیِ دارای قیمت رسمی ساخته شود؛ یا پک سفارشی بسازید. تعداد را تنظیم کنید، کالا را جایگزین یا حذف کنید، پک را به سبد بیفزایید، ذخیره کنید یا درخواست پیش‌فاکتور بدهید. هیچ قیمت یا کالای بدون قیمت رسمی در پیشنهادها ظاهر نمی‌شود.
          </p>
        </div>
      </div>
      <PackBuilderClient />
    </div>
  );
}
