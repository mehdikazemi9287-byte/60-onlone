import { SupplierRfqList } from "@/components/procurement/SupplierRfq";

export const metadata = { title: "استعلام‌های تأمین‌کننده | شصت‌آنلاین", robots: { index: false, follow: false } };

export default function Page() {
  return <div className="container-page py-6"><SupplierRfqList /></div>;
}
