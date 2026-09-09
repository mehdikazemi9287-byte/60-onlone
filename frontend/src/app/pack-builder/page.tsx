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
            کالاهای واقعی کاتالوگ را به پک اضافه کنید، پک را ذخیره و ویرایش کنید و یک‌جا به سبد
            بیفزایید یا برای سازمان درخواست پیش‌فاکتور بدهید. قیمت و موجودی هیچ‌گاه ساختگی نیست؛
            جمع کل فقط از اقلام دارای قیمت تأییدشده محاسبه می‌شود.
          </p>
        </div>
      </div>
      <PackBuilderClient />
    </div>
  );
}
