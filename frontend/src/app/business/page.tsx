import type { Metadata } from "next";
import { BusinessApplication } from "./BusinessApplication";

export const metadata: Metadata = {
  title: "حساب سازمانی و فروشگاهی",
  description: "خرید سازمانی با اعتبار و قیمت قراردادی، و خرید عمده برای فروشگاه‌ها. درخواست باز کردن حساب بدهید؛ همکاران ما تماس می‌گیرند.",
};

export default function BusinessPage() {
  return (
    <div dir="rtl" className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="text-2xl font-black text-neutral-900 md:text-3xl">حساب سازمانی و فروشگاهی</h1>
      <p className="mt-3 leading-8 text-neutral-700">
        برای سازمان‌ها: خرید با اعتبار، صورت‌حساب هفتگی، قیمت قراردادی و گردش تأیید خرید.
        برای فروشگاه‌ها: خرید عمده با قیمت پلکانی و مهلت پرداخت.
        حساب‌ها پس از بررسی و عقد قرارداد باز می‌شوند.
      </p>
      <BusinessApplication />
    </div>
  );
}
