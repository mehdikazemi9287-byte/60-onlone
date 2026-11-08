import { AdminCatalogReview } from "@/components/admin/CommerceAdmin";

export const metadata = { title: "بازبینی کاتالوگ | 60Online", robots: { index: false, follow: false } };

export default function Page() {
  return <div className="container-wide py-6"><AdminCatalogReview /></div>;
}
