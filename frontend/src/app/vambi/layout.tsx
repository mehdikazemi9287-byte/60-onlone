import type { Metadata } from "next";

export const metadata: Metadata = {
  title: { default: "وامبی | جستجو و مقایسهٔ قیمت فروشندگان معتبر", template: "%s | وامبی" },
  description: "وامبی: یک کالا، همهٔ فروشنده‌های معتبر کنار هم. قیمت، زمان تحویل و موجودی را مقایسه کن و مطمئن بخر.",
  applicationName: "وامبی",
};

export default function VambiLayout({ children }: { children: React.ReactNode }) {
  return children;
}
