import { AdminPacks } from "@/components/admin/CommerceAdmin";

export const metadata = { title: "مدیریت پک‌ها | 60Online", robots: { index: false, follow: false } };

export default function Page() {
  return <div className="container-wide py-6"><AdminPacks /></div>;
}
