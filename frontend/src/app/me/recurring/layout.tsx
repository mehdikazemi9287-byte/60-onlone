import type { Metadata } from "next";

export const metadata: Metadata = { title: "خرید دوره‌ای | شصت‌آنلاین", robots: { index: false, follow: false } };

export default function RecurringLayout({ children }: { children: React.ReactNode }) {
  return children;
}
