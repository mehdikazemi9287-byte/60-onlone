import { Suspense } from "react";
import { AdminPaymentPolicy } from "@/components/procurement/PolicyPages";

export const metadata = { title: "سیاست پرداخت سازمان | 60Online", robots: { index: false, follow: false } };

export default function Page() {
  return <div className="container-wide py-6"><Suspense><AdminPaymentPolicy /></Suspense></div>;
}
