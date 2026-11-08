import { Suspense } from "react";
import OrderComposer from "@/components/procurement/OrderComposer";

export const metadata = { title: "سفارش سازمانی هوشمند | 60Online", robots: { index: false, follow: false } };

export default function Page() {
  return <Suspense fallback={null}><OrderComposer /></Suspense>;
}
