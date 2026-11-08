import { Suspense } from "react";
import Requests from "@/components/Requests";
export const metadata = {
  title: "ثبت درخواست | شصت‌آنلاین",
  robots: { index: false, follow: false },
};
export default function Page() {
  return (
    <Suspense fallback={<p>در حال دریافت…</p>}>
      <Requests create />
    </Suspense>
  );
}
