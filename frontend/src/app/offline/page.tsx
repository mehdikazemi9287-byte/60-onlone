import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "اتصال برقرار نیست | شصت‌آنلاین", robots: { index: false, follow: false } };
export const dynamic = "force-static";

export default function OfflinePage() {
  return (
    <div className="internal-page container-page py-20 text-center">
      <h1 className="mb-3 text-xl font-black text-neutral-900">اتصال اینترنت برقرار نیست</h1>
      <p className="mb-6 text-sm text-neutral-600">به اینترنت وصل شو و دوباره امتحان کن. سبد خرید و سفارش‌هایت محفوظ است.</p>
      {/* No prefetch while offline; if the client-side fetch fails, Next.js falls back to a full navigation. */}
      <Link href="/" prefetch={false} className="inline-block rounded-xl bg-neutral-900 px-5 py-2 font-bold text-white">تلاش دوباره</Link>
    </div>
  );
}
