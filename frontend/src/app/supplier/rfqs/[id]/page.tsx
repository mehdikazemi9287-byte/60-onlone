import { SupplierQuoteBuilder } from "@/components/procurement/SupplierRfq";

export const metadata = { title: "ثبت پیشنهاد قیمت | شصت‌آنلاین", robots: { index: false, follow: false } };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <div className="container-page py-6"><SupplierQuoteBuilder rfqId={id} /></div>;
}
