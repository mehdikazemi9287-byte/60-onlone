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
            کالا را به فارسی بپرسید، یا نوع پک، تعداد نفرات و بودجه را بنویسید تا از کاتالوگ واقعی پیش‌نویس پک ساخته و به پک‌ساز سپرده شود. وضعیت سفارش، استعلام یا پرونده سازمانی خود را هم می‌توانید بپرسید.
          </p>
        </div>
      </div>
      <a href="/organization/compose?tab=assistant" className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-brand-blue/20 bg-brand-blueLight/40 px-4 py-3 text-sm">
        <span><b>خرید سازمانی دارید؟</b> دستیار خرید سازمانی 60AI درخواست چندقلمی و چندمقصدی را برایتان می‌سازد و برای استعلام ارسال می‌کند.</span>
        <span className="font-semibold text-brand-blue whitespace-nowrap">شروع ←</span>
      </a>
      <AssistantClient />
    </div>
  );
}
