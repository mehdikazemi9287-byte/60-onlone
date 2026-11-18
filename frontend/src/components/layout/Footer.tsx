"use client";
// Footer — Google Stitch screen 30 (4-column grid + bottom bar). Links point to real routes only.
// Stitch's trust-badge column (اینماد / ساماندهی / اتحادیه) is replaced by real top categories until
// official badge data exists; its version label is omitted. Mobile (screen 16) has no footer: its links live in
// the header drawer.
import Link from "next/link";
import Image from "next/image";
import { useTaxonomy } from "./MegaMenu";

const SERVICES: [string, string][] = [
  ["صدور پیش‌فاکتور رسمی", "/me/proformas"],
  ["خرید سازمانی و اعتبار سازمان", "/org"],
  ["قراردادهای تأمین دوره‌ای", "/organization/supply-contracts"],
  ["پک‌ساز", "/pack-builder"],
  ["در شصت‌آنلاین بفروشید", "/sell"],
];
const HELP: [string, string][] = [
  ["شرایط بازگشت کالا", "/help/returns"],
  ["حفظ حریم خصوصی", "/privacy"],
  ["راهنمای خرید", "/help/buying"],
  ["پرسش‌های متداول", "/help/faq"],
  ["تماس با ما", "/contact"],
];

function Col({ title, items }: { title: string; items: [string, string][] }) {
  return (
    <div className="flex flex-col gap-st-space-sm">
      <span className="text-st-title-md font-bold text-st-primary">{title}</span>
      {items.map(([label, href]) => <Link key={href + label} href={href} className="text-st-body-sm text-st-on-surface-variant hover:text-st-on-surface">{label}</Link>)}
    </div>
  );
}

export function Footer() {
  const tree = useTaxonomy();
  const cats: [string, string][] = (tree ?? []).slice().sort((a, b) => b.product_count - a.product_count).slice(0, 5).map((n) => [n.name_fa, `/category/${n.slug}`]);
  return (
    <footer className="hidden w-full border-t border-st-surface-container bg-st-surface-container-lowest py-st-space-xl md:block">
      <div className="mx-auto w-full max-w-[1440px] px-st-gutter md:px-st-margin-md xl:px-st-margin-lg">
        <div className="grid grid-cols-1 gap-st-gutter-lg border-b border-st-surface-container-low pb-st-space-xl md:grid-cols-4">
          <div className="flex flex-col gap-st-space-md">
            <Link href="/" className="flex items-center gap-st-space-sm">
              <Image src="/brand/60online-mark.png" alt="" width={256} height={241} className="brand-mark h-8 w-auto" />
              <span className="text-st-title-lg font-bold text-st-primary">شصت‌آنلاین</span>
            </Link>
            <p className="text-st-body-sm leading-relaxed text-st-on-surface-variant">مارکت‌پلیس تأمین کالای سازمانی و خانگی؛ خرید برای سازمان، کارکنان و خانه، با پیش‌فاکتور رسمی و قیمت‌های تأییدشده.</p>
          </div>
          <Col title="خدمات شرکتی و سازمانی" items={SERVICES} />
          <Col title="راهنما و شفافیت حقوقی" items={HELP} />
          {cats.length > 0 && <Col title="دسته‌بندی‌های پرطرفدار" items={cats} />}
        </div>
        <div className="flex flex-col items-center justify-between gap-st-space-md pt-st-space-lg md:flex-row">
          <span className="text-st-body-sm text-st-on-surface-variant">کلیه حقوق مادی و معنوی این پلتفرم متعلق به «شصت‌آنلاین» است.</span>
          <span className="text-st-label-sm text-st-outline">© ۱۴۰۵ شصت‌آنلاین</span>
        </div>
      </div>
    </footer>
  );
}
