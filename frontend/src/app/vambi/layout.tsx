import type { Metadata } from "next";

export const metadata: Metadata = {
  title: { default: "وامبی | جستجو و مقایسهٔ قیمت فروشندگان معتبر", template: "%s | وامبی" },
  description: "وامبی: کشف کن، مقایسه کن، هوشمندانه انتخاب کن. یک کالا، همهٔ فروشنده‌های معتبر کنار هم.",
  applicationName: "وامبی",
  icons: { icon: "/vambi/icon.svg", apple: "/vambi/icon.svg" },
};

export default function VambiLayout({ children }: { children: React.ReactNode }) {
  return children;
}
