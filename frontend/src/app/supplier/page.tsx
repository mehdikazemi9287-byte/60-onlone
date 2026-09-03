import Link from "next/link";
import { ArrowLeft, LockKeyhole, ShieldAlert, Store } from "lucide-react";

export default function SupplierPage() {
  return <div className="internal-page container-page py-8 md:py-12">
    <nav className="page-breadcrumb"><Link href="/">خانه</Link><span>/</span><span>پورتال تأمین‌کننده</span></nav>
    <section className="internal-hero"><div className="internal-hero-icon"><Store className="h-8 w-8" /></div><div className="flex-1"><span className="section-kicker">دسترسی اختصاصی</span><h1>پورتال تأمین‌کننده</h1><p>این بخش برای نمایش عمومی هویت، فروش، تسویه یا عملکرد تأمین‌کنندگان طراحی نشده است.</p></div></section>
    <div className="mx-auto mt-6 max-w-3xl rounded-3xl border border-neutral-200 bg-white p-7 text-center shadow-brand-card md:p-10"><span className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-amber-100 text-amber-800"><LockKeyhole className="h-8 w-8" /></span><h2 className="mt-5 text-xl font-black text-brand-navy">اطلاعات تأمین‌کننده برای نمایش عمومی در دسترس نیست</h2><p className="mx-auto mt-3 max-w-xl text-sm leading-7 text-neutral-600">نام، نشان تأیید، امتیاز، درآمد، سفارش‌ها، محصولات و وضعیت تسویه تنها در یک حساب واقعی و احراز‌شده معنا دارند. هیچ داده آزمایشی در این صفحه به‌عنوان اطلاعات تجاری واقعی نمایش داده نمی‌شود.</p><div className="mt-5 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-right"><ShieldAlert className="mt-0.5 h-5 w-5 flex-shrink-0 text-amber-700"/><p className="text-xs leading-6 text-amber-900">دسترسی تأمین‌کنندگان مستلزم زمینه احراز هویت و مجوز مناسب است. تا زمان فراهم بودن آن، این صفحه عمداً وضعیت خالی و شفاف نشان می‌دهد.</p></div><div className="mt-6 flex justify-center"><Link href="/" className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-neutral-200 px-5 text-sm font-bold text-neutral-700 hover:bg-neutral-50">بازگشت به فروشگاه <ArrowLeft className="h-4 w-4" /></Link></div></div>
  </div>;
}
