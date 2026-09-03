import Link from "next/link";
import { ArrowLeft, Building2, LockKeyhole, PackageCheck, Search } from "lucide-react";

export default function OrgPage() {
  return <div className="internal-page container-page py-8 md:py-12">
    <nav className="page-breadcrumb"><Link href="/">خانه</Link><span>/</span><span>خرید سازمانی</span></nav>
    <section className="internal-hero">
      <div className="internal-hero-icon"><Building2 className="h-8 w-8" /></div>
      <div className="flex-1"><span className="section-kicker">ویژه شرکت‌ها و مجموعه‌ها</span><h1>خرید سازمانی 60Online</h1><p>مسیر معرفی و بررسی خریدهای گروهی و سازمانی؛ بدون نمایش اطلاعات آزمایشی به‌عنوان داده واقعی.</p></div>
    </section>
    <div className="mt-6 grid gap-5 lg:grid-cols-[1.15fr_.85fr]">
      <section className="card p-6 md:p-8"><h2 className="text-lg font-black text-brand-navy">امکانات عمومی قابل استفاده</h2><div className="mt-5 grid gap-3 sm:grid-cols-2">
        <Link href="/search" className="feature-link"><Search /><span><b>جستجو و انتخاب کالا</b><small>بررسی کالاهای موجود در فروشگاه</small></span><ArrowLeft className="mr-auto" /></Link>
        <Link href="/#pack-builder" className="feature-link"><PackageCheck /><span><b>پک‌ساز</b><small>چیدمان یک پک براساس کالاهای در دسترس</small></span><ArrowLeft className="mr-auto" /></Link>
      </div><p className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-900">اطلاعات و شرایط هر درخواست سازمانی پس از بررسی همان درخواست مشخص می‌شود. اعتبار، سقف خرید یا شرایط پرداخت از پیش در این صفحه ادعا نمی‌شود.</p></section>
      <aside className="card border-brand-navy/10 bg-brand-navy p-6 text-white md:p-8"><span className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-white/10 text-amber-300"><LockKeyhole className="h-6 w-6" /></span><h2 className="text-lg font-black">داشبورد سازمانی عمومی نیست</h2><p className="mt-2 text-sm leading-7 text-white/65">مشخصات سازمان، اعضا، سفارش‌ها و اطلاعات مالی فقط باید در یک حساب واقعی و مجاز نمایش داده شوند. در حال حاضر داده سازمانی عمومی برای نمایش وجود ندارد.</p><div className="mt-5 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-xs leading-6 text-white/60">دسترسی به داشبورد سازمانی در نسخه عمومی فعال نیست.</div></aside>
    </div>
  </div>;
}
