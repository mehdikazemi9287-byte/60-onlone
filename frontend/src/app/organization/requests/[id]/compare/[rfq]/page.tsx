import { Suspense } from "react";
import QuoteComparison from "@/components/procurement/QuoteComparison";

export const metadata = { title: "مقایسه پیشنهادها | 60Online", robots: { index: false, follow: false } };

export default async function Page({ params }: { params: Promise<{ id: string; rfq: string }> }) {
  const { id, rfq } = await params;
  return <Suspense fallback={null}><QuoteComparison requestId={id} rfqId={rfq} /></Suspense>;
}
