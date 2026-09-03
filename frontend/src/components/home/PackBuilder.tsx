import Link from "next/link";
import { Boxes, Building2, Search, ShieldAlert } from "lucide-react";
export function PackBuilder() {
  return (
    <section id="pack-builder" className="section-shell scroll-mt-28" aria-labelledby="pack-builder-title">
      <div className="container-page"><div className="overflow-hidden rounded-[2rem] border border-amber-200/70 bg-gradient-to-br from-white via-amber-50/60 to-primary-50 shadow-soft"><div className="grid gap-8 p-6 md:p-10 lg:grid-cols-[1.1fr_0.9fr] lg:items-center">
        <div>
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-100/80 px-3 py-1.5 text-xs font-bold text-amber-900"><Boxes className="h-4 w-4" aria-hidden="true" /> پک‌ساز 60Online</div>
          <h2 id="pack-builder-title" className="text-2xl font-black leading-tight text-primary-950 md:text-3xl">پک‌ساز هنوز به سبد خرید واقعی متصل نشده است</h2>
          <p className="mt-4 max-w-2xl text-sm leading-7 text-neutral-600 md:text-base">پیشنهاد خودکار کالا، ذخیره پک، افزودن یک‌جای پک به سبد و ثبت درخواست پیش‌فاکتور در نسخه فعلی فعال نیست. برای جلوگیری از نمایش قیمت یا موجودی غیرواقعی، تا زمان اتصال کامل هیچ پک آماده‌ای نمایش داده نمی‌شود.</p>
          <div className="mt-6 flex flex-col gap-3 sm:flex-row">
            <Link href="/search" className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-primary-700 px-5 py-3 text-sm font-bold text-white transition-colors hover:bg-primary-800"><Search className="h-5 w-5" aria-hidden="true" /> انتخاب کالا از فروشگاه</Link>
            <Link href="/category" className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-primary-200 bg-white px-5 py-3 text-sm font-bold text-primary-800 transition-colors hover:bg-primary-50"><Boxes className="h-5 w-5" aria-hidden="true" /> مشاهده دسته‌بندی‌ها</Link>
            <Link href="/org" className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-amber-300 bg-amber-100 px-5 py-3 text-sm font-bold text-amber-950 transition-colors hover:bg-amber-200"><Building2 className="h-5 w-5" aria-hidden="true" /> خرید سازمانی</Link>
          </div>
        </div>
        <div className="rounded-2xl border border-amber-200/80 bg-white/90 p-5 shadow-sm"><div className="flex items-start gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-800"><ShieldAlert className="h-5 w-5" aria-hidden="true" /></span>
          <div><h3 className="font-extrabold text-neutral-900">وضعیت شفاف سرویس</h3><p className="mt-2 text-sm leading-7 text-neutral-600">خرید تکی از مسیر جستجو و دسته‌بندی‌ها انجام می‌شود. فعال‌شدن پک‌ساز منوط به اتصال امن آن به قیمت، موجودی و سبد خرید سمت سرور است.</p></div>
        </div></div>
      </div></div></div>
    </section>
  );
}
