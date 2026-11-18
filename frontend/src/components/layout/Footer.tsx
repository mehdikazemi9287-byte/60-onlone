"use client";
import Link from "next/link";
import Image from "next/image";
import { useEffect, useState } from "react";
import { categories as categoriesApi } from "@/lib/api";
import type { Category } from "@/lib/types";

// Matches Figma "هدر و فوتر سراسری" (node 19:224). Contact details and trust
// badges (اینماد / ساماندهی) are intentionally absent until official data exists.
const LINKS: [string, string][] = [
  ["خرید سازمانی", "/org"],
  ["پک‌ساز", "/pack-builder"],
  ["شبکهٔ فروشگاه‌های طرف قرارداد", "/stores"],
  ["در شصت‌آنلاین بفروشید", "/sell"],
  ["پیگیری سفارش", "/orders"],
];
const HELP: [string, string][] = [
  ["راهنمای خرید", "/help/buying"],
  ["پرسش‌های متداول", "/help/faq"],
  ["قوانین و مقررات", "/terms"],
  ["حریم خصوصی", "/privacy"],
  ["تماس با ما", "/contact"],
];

function Col({ title, items }: { title: string; items: [string, string][] }) {
  return (
    <div>
      <h3 className="mb-4 text-xs font-semibold tracking-wide text-ink-faint">{title}</h3>
      <ul className="space-y-3">
        {items.map(([label, href]) => (
          <li key={href + label}><Link href={href} className="text-sm text-ink-soft transition hover:text-ink">{label}</Link></li>
        ))}
      </ul>
    </div>
  );
}

export function Footer() {
  const [cats, setCats] = useState<[string, string][]>([]);
  useEffect(() => {
    let cancelled = false;
    categoriesApi.list()
      .then((items: Category[]) => !cancelled && setCats(items.filter(i => i.product_count > 0).sort((a, b) => b.product_count - a.product_count).slice(0, 5).map((i): [string, string] => [i.name, `/category/${i.slug}`])))
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);
  return (
    <footer className="mt-16 border-t border-line bg-white">
      <div className="mx-auto grid w-full max-w-[1280px] gap-10 px-4 py-12 sm:grid-cols-2 md:px-8 md:py-16 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <div>
          <Link href="/" className="inline-flex items-center gap-2">
            <Image src="/brand/60online-mark.png" alt="" width={256} height={241} className="brand-mark h-11 w-auto" />
            <b className="text-xl font-extrabold text-ink">شصت‌آنلاین</b>
          </Link>
          <p className="mt-3 max-w-xs text-sm leading-7 text-ink-muted">مارکت‌پلیس سازمانی و عمده‌فروشی؛ خرید برای سازمان، کارکنان و خانه.</p>
        </div>
        {cats.length > 0 && <Col title="دسته‌بندی‌های پرطرفدار" items={cats} />}
        <Col title="خدمات" items={LINKS} />
        <Col title="راهنما و قوانین" items={HELP} />
      </div>
      <div className="border-t border-line py-5 text-center text-xs text-ink-faint">© ۱۴۰۵ شصت‌آنلاین</div>
    </footer>
  );
}
