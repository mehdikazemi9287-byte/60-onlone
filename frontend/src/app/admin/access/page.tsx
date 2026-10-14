import AccessConsole from "@/components/admin/AccessConsole";

export const metadata = { title: "دسترسی‌ها و نقش‌ها | 60Online", robots: { index: false, follow: false } };

export default function Page() {
  return <div className="container-wide py-6"><AccessConsole /></div>;
}
