"use client";
import Link from "next/link";
import Image from "next/image";
import { useEffect, useState } from "react";
import { categories as categoriesApi } from "@/lib/api";
import type { Category } from "@/lib/types";

// Mega-market footer (2026-11-19, navy). Contact details and trust
// badges (اینماد / ساماندهی) are intentionally absent until official data exists.
const LINKS: [string, string][] = [
  ["خرید سازمانی و عمده", "/org"],
  ["مزایای کارکنان", "/benefits"],
  ["پیش‌فاکتورها", "/me/proformas"],
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
      <h3 className="mb-4 text-sm font-bold text-honey">{title}</h3>
      <ul className="space-y-3">
        {items.map(([label, href]) => (
          <li key={href + label}><Link href={href} className="text-sm text-white/75 transition hover:text-white">{label}</Link></li>
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
    <footer className="mt-12 bg-mm-deep text-white">
      <div className="mx-auto grid w-full max-w-[1360px] gap-10 px-4 py-12 sm:grid-cols-2 md:px-10 md:py-14 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <div>
          <Link href="/" className="inline-flex items-center gap-3">
            <span className="flex h-14 w-14 items-center justify-center rounded-lg bg-white p-1"><Image src="/brand/60online-app-icon.png" alt="" width={512} height={512} className="h-full w-auto" /></span>
            <b className="text-xl font-extrabold text-white">شصت‌آنلاین</b>
          </Link>
          <p className="mt-4 max-w-xs text-sm leading-7 text-white/70">مگامارکت خرید شخصی، پرسنل سازمان‌ها و خرید سازمانی و عمده؛ با قیمت تأییدشده‌ی فروشنده یا استعلام.</p>
        </div>
        {cats.length > 0 && <Col title="دسته‌بندی‌های پرطرفدار" items={cats} />}
        <Col title="خدمات" items={LINKS} />
        <Col title="راهنما و قوانین" items={HELP} />
      </div>
      <div className="border-t border-white/10 py-5 text-center text-xs text-white/60">© ۱۴۰۵ شصت‌آنلاین</div>
    </footer>
  );
}
