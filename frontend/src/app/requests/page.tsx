import { Suspense } from "react";
import Requests from "@/components/Requests";
export const metadata = {
  title: "پیگیری درخواست‌ها | شصت‌آنلاین",
  robots: { index: false, follow: false },
};
export default function Page() {
  return (
    <Suspense fallback={<p>در حال دریافت…</p>}>
      <Requests />
    </Suspense>
  );
}
