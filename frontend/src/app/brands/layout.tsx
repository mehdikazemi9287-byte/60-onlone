import type { Metadata } from "next";
import { site } from "@/lib/server-catalog";

export const metadata: Metadata = {
  title: "برندهای رسمی | شصت‌آنلاین",
  description: "خرید مستقیم از برندهای رسمی و تأییدشده در شصت‌آنلاین؛ علامت تجاری هر برند بررسی شده است.",
  alternates: { canonical: `${site}/brands` },
};

export default function BrandsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
