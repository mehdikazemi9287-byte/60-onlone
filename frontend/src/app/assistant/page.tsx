import type { Metadata } from "next";
import { AssistantClient } from "./AssistantClient";

export const metadata: Metadata = {
  title: "دستیار خرید هوشمند | شصت‌آنلاین",
  description:
    "دستیار قاعده‌محور شصت‌آنلاین: با گفتن دسته، بودجه و کاربرد، کالاهای واقعی کاتالوگ را پیدا کنید. بدون اطلاعات ساختگی.",
  alternates: { canonical: "https://60online.ir/assistant" },
};

export default function AssistantPage() {
  return (
    <div className="internal-page container-page py-6 md:py-10">
      <div className="internal-hero mb-6">
        <div>
          <span className="section-kicker">راهنمای خرید</span>
          <h1>دستیار خرید هوشمند</h1>
          <p>
            نیازتان را به فارسی بنویسید (دسته، بودجه، برند، کاربرد). دستیار فقط از کاتالوگ واقعی
            فروشگاه استفاده می‌کند و هیچ کالا، قیمت یا موجودی ساختگی نشان نمی‌دهد.
          </p>
        </div>
      </div>
      <AssistantClient />
    </div>
  );
}
