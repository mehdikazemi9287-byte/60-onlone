import { Suspense } from "react";
import { PackStudio } from "@/components/packs/PackStudio";
export const metadata = { title: "پک‌ساز | شصت‌آنلاین" };
export default function Page() {
  return (
    <div className="container-page py-6 md:py-8" dir="rtl">
      <Suspense><PackStudio /></Suspense>
    </div>
  );
}
