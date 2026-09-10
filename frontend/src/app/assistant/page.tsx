import type { Metadata } from "next";
import { AssistantClient } from "./AssistantClient";

export const metadata: Metadata = {
  title: "دستیار خرید هوشمند | شصت‌آنلاین",
  description:
    "دستیار حرفه‌ای خرید شصت‌آنلاین: نوع پک، تعداد نفرات و بودجه را به فارسی بگویید تا از کاتالوگ واقعی، پیش‌نویس پک ساخته و برای ویرایش به پک‌ساز منتقل شود. بدون قیمت یا کالای ساختگی.",
  alternates: { canonical: "https://60online.ir/assistant" },
};

export default function AssistantPage() {
  return (
    <div className="internal-page container-page py-6 md:py-10">
      <div className="internal-hero mb-6">
        <div>
          <span className="section-kicker">راهنمای خرید</span>
          <h1>دستیار حرفه‌ای خرید</h1>
          <p>
            نیازتان را به فارسی بنویسید: نوع پک (معیشتی، هدیه، سازمانی…)، تعداد نفرات، و بودجه (کل یا نفری). دستیار از کاتالوگ واقعی پیش‌نویس پک می‌سازد و آن را برای ویرایش نهایی و ثبت به پک‌ساز می‌سپارد.
          </p>
        </div>
      </div>
      <AssistantClient />
    </div>
  );
}
