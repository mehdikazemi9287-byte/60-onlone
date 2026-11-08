import CaseList from "@/components/procurement/CaseList";

export const metadata = { title: "پرونده‌های خرید سازمان‌ها | 60Online", robots: { index: false, follow: false } };

export default function Page() {
  return <div className="container-wide py-6"><CaseList platform /></div>;
}
