import { Suspense } from "react";
import Proforma from "@/components/procurement/Proforma";

export const metadata = { title: "پیش‌فاکتور | 60Online", robots: { index: false, follow: false } };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Suspense fallback={null}><Proforma id={id} /></Suspense>;
}
