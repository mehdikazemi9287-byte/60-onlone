import type { Metadata } from "next";

export const metadata: Metadata = { title: "هشدارهای من | شصت‌آنلاین", robots: { index: false, follow: false } };

export default function PriceAlertsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
