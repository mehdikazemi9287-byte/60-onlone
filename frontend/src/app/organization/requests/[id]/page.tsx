import { Suspense } from "react";
import CaseWorkspace from "@/components/procurement/CaseWorkspace";

export const metadata = { title: "پرونده خرید سازمانی | 60Online", robots: { index: false, follow: false } };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Suspense fallback={null}><CaseWorkspace id={id} /></Suspense>;
}
