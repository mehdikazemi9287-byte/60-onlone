"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft, Armchair, Bot, Building2, Check, Dumbbell, Home as HomeIcon, Search, ShoppingBasket, Sparkles, Smartphone } from "lucide-react";
import { ProductGrid } from "@/components/product/ProductCard";
import { PackBuilder } from "@/components/home/PackBuilder";
import { catalog } from "@/lib/api";
import type { Product } from "@/lib/types";

const HOME_CATEGORIES = [
  { name: "کالای دیجیتال", subtitle: "موبایل، لپ‌تاپ و تبلت", href: "/category/digital", icon: Smartphone },
  { name: "لوازم برقی", subtitle: "لوازم برقی خانه و آشپزخانه", href: "/category/appliance", icon: HomeIcon },
  { name: "خانه و آشپزخانه", subtitle: "کالاهای کاربردی غیربرقی", href: "/category/home-kitchen", icon: Armchair },
  { name: "سوپرمارکت", subtitle: "مواد غذایی و کالاهای روزمره", href: "/category/supermarket", icon: ShoppingBasket },
  { name: "زیبایی و بهداشت", subtitle: "مراقبت شخصی و بهداشتی", href: "/category/beauty-health", icon: Sparkles },
  { name: "ورزش و کمپینگ", subtitle: "لوازم ورزش و سفر", href: "/category/sports-camping", icon: Dumbbell },
];

function Hero() {
  return <section className="brand-hero relative overflow-hidden">
    <div className="absolute inset-0 pointer-events-none" aria-hidden><div className="brand-hero-glow -top-24 -right-24 h-96 w-96" /><div className="brand-hero-warm -bottom-32 left-0 h-80 w-80" /></div>
    <div className="container-page relative py-10 md:py-16"><div className="mx-auto max-w-3xl text-center">
      <span className="mb-4 inline-flex items-center gap-2 rounded-full border border-amber-300/30 bg-amber-300/10 px-3 py-1.5 text-xs font-bold text-amber-200"><Sparkles className="h-4 w-4" />خرید ساده‌تر برای خانه و سازمان</span>
      <h1 className="text-3xl font-black leading-tight text-white md:text-5xl">کالای مورد نیازتان را<span className="block text-amber-300">سریع و مطمئن پیدا کنید</span></h1>
      <p className="mx-auto mt-4 max-w-2xl text-sm leading-7 text-white/70 md:text-base">جستجو کنید، دسته‌بندی‌ها را ببینید یا برای خریدهای گروهی از پک‌ساز استفاده کنید.</p>
      <form action="/search" method="get" className="relative mx-auto mt-7 max-w-2xl">
        <input type="search" name="q" placeholder="دنبال چه کالایی هستید؟" className="h-16 w-full rounded-2xl border-2 border-white/20 bg-white pr-5 pl-16 text-base font-medium text-neutral-900 shadow-2xl placeholder:text-neutral-400 focus:border-amber-400 focus:outline-none focus:ring-4 focus:ring-amber-300/20" />
        <button type="submit" aria-label="جستجو" className="absolute left-2 top-2 flex h-12 w-12 items-center justify-center rounded-xl bg-amber-400 text-brand-navy transition-colors hover:bg-amber-300"><Search className="h-5 w-5" strokeWidth={2.2} /></button>
      </form>
      <div className="mt-4 flex flex-wrap justify-center gap-2 text-xs text-white/60"><span>پیشنهاد جستجو:</span><Link href="/search?q=برنج" className="text-white hover:text-amber-300">برنج</Link><span>•</span><Link href="/search?q=موبایل" className="text-white hover:text-amber-300">موبایل</Link><span>•</span><Link href="/search?q=لوازم اداری" className="text-white hover:text-amber-300">لوازم اداری</Link></div>
    </div></div>
  </section>;
}

function CategorySection() {
  return <section id="home-categories" className="section bg-warm-surface"><div className="container-page">
    <div className="section-heading"><div><span className="section-kicker">شروع خرید</span><h2>دسته‌بندی‌های اصلی</h2><p>مسیر کوتاه‌تر برای رسیدن به کالای مورد نیاز</p></div><Link href="/category" className="section-link">همه دسته‌بندی‌ها <ArrowLeft className="h-4 w-4" /></Link></div>
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">{HOME_CATEGORIES.map((cat, index) => { const Icon = cat.icon; return <Link key={cat.name} href={cat.href} className="category-tile group"><span className={`category-icon ${index === 0 ? "category-icon-active" : ""}`}><Icon className="h-6 w-6" strokeWidth={1.8} /></span><span className="text-sm font-bold text-neutral-900 group-hover:text-brand-navy">{cat.name}</span><span className="mt-1 line-clamp-2 text-[11px] leading-5 text-neutral-500">{cat.subtitle}</span></Link>; })}</div>
  </div></section>;
}

function ProductSection() {
  const [products, setProducts] = useState<Product[] | null>(null);
  useEffect(() => { let cancelled = false; catalog.list({ page: 1, page_size: 6 }).then((r) => !cancelled && setProducts(r.items)).catch(() => !cancelled && setProducts([])); return () => { cancelled = true; }; }, []);
  return <section className="section bg-white"><div className="container-page">
    <div className="section-heading"><div><span className="section-kicker">پیشنهادهای فروشگاه</span><h2>محصولات منتخب</h2><p>کالاهای موجود در فروشگاه را یک‌جا بررسی کنید</p></div><Link href="/search" className="section-link">مشاهده محصولات <ArrowLeft className="h-4 w-4" /></Link></div>
    {products === null ? <div className="grid grid-cols-2 gap-3 md:grid-cols-3 md:gap-5">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="card aspect-[3/4] animate-pulse bg-neutral-100" />)}</div> : products.length ? <ProductGrid products={products} cols={3} /> : <div className="rounded-2xl border border-dashed border-neutral-200 bg-neutral-50 py-12 text-center text-sm text-neutral-500">در حال حاضر محصولی برای نمایش در این بخش موجود نیست.</div>}
  </div></section>;
}

function AssistantEntry() {
  const prompts = ["پیدا کردن کالا", "پیشنهاد براساس بودجه", "ساخت پک", "خرید سازمانی", "مقایسه کالا"];
  return <section className="section bg-warm-surface"><div className="container-page"><div className="assistant-panel">
    <div className="assistant-icon"><Bot className="h-7 w-7" /></div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h2 className="text-xl font-black text-brand-navy md:text-2xl">دستیار خرید هوشمند 60Online</h2><span className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-bold text-amber-800">به‌زودی</span></div><p className="mt-2 max-w-2xl text-sm leading-7 text-neutral-600">این دستیار در حال آماده‌سازی است. فعلاً برای یافتن کالا از جستجو و برای خرید گروهی از پک‌ساز استفاده کنید.</p><div className="mt-4 flex flex-wrap gap-2">{prompts.map((p) => <span key={p} className="assistant-chip">{p}</span>)}</div></div>
    <Link href="/search" className="btn-secondary-warm">جستجوی کالا <ArrowLeft className="h-4 w-4" /></Link>
  </div></div></section>;
}

function OrganizationalEntry() {
  const items = ["ثبت درخواست خرید عمده", "انتخاب و ساخت پک سازمانی", "درخواست پیش‌فاکتور"];
  return <section className="section bg-white"><div className="container-page"><div className="org-panel"><div className="org-icon"><Building2 className="h-8 w-8" /></div><div className="flex-1"><span className="text-xs font-bold text-amber-300">ویژه شرکت‌ها و سازمان‌ها</span><h2 className="mt-1 text-2xl font-black text-white md:text-3xl">خرید سازمانی، شفاف و متمرکز</h2><p className="mt-2 max-w-2xl text-sm leading-7 text-white/70">برای خریدهای گروهی و درخواست‌های سازمانی، مسیر اختصاصی 60Online را بررسی کنید.</p><div className="mt-4 flex flex-wrap gap-x-5 gap-y-2">{items.map((item) => <span key={item} className="flex items-center gap-2 text-xs font-medium text-white/85"><Check className="h-4 w-4 text-amber-300" />{item}</span>)}</div></div><Link href="/org" className="btn-warm">ورود به خرید سازمانی <ArrowLeft className="h-4 w-4" /></Link></div></div></section>;
}

function ServiceStrip() {
  return <section className="border-y border-neutral-100 bg-neutral-50"><div className="container-page grid gap-3 py-6 sm:grid-cols-3">{["جستجوی سریع در کالاها", "دسترسی روشن به دسته‌بندی‌ها", "مسیر اختصاصی خرید سازمانی"].map((item, i) => <div key={item} className="flex items-center gap-3 rounded-xl bg-white p-4 text-sm font-semibold text-neutral-700 shadow-sm"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-100 font-black text-amber-700">{i + 1}</span>{item}</div>)}</div></section>;
}

export default function HomePage() { return <><Hero /><CategorySection /><ProductSection /><PackBuilder /><AssistantEntry /><OrganizationalEntry /><ServiceStrip /></>; }
