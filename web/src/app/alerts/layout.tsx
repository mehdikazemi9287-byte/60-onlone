import type { Metadata } from "next";

export const metadata: Metadata = { title: "کالاهای زیر نظر", robots: { index: false, follow: false } };

export default function AlertsLayout({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-3xl px-4 py-6">{children}</div>;
}
