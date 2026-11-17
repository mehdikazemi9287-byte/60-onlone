import { Suspense } from "react";
import { PackStudio } from "@/components/packs/PackStudio";
export const metadata = { title: "پک‌ساز | شصت‌آنلاین", description: "ساخت پک‌های معیشتی و مناسبتی برای سفارش عمده سازمان‌ها؛ پک آماده، بر اساس بودجه یا انتخاب دستی از کاتالوگ واقعی." };
export default function Page() {
  return (
    <div className="bg-[#F9F9F9]">
      <div className="mx-auto w-full max-w-[1360px] px-4 py-6 sm:px-6 md:py-8 lg:px-8" dir="rtl">
        <Suspense><PackStudio /></Suspense>
      </div>
    </div>
  );
}
