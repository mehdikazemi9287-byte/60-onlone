"use client";
import { useEffect, useState } from "react";
import { Beef, BookOpen, BriefcaseBusiness, Car, CookingPot, Gift, HeartPulse, Laptop, LayoutGrid, Milk, Package, Router, Shirt, ShoppingBasket, Smartphone, Sparkles } from "lucide-react";
import { categories } from "@/lib/api";
import { CategoryCard } from "@/components/product/ProductCard";
import type { Category } from "@/lib/types";

function iconFor(slug: string) { const s = slug.toLowerCase(); if (s.includes("laptop") || s.includes("computer")) return <Laptop />; if (s.includes("mobile") || s.includes("digital")) return <Smartphone />; if (s.includes("office")) return <BriefcaseBusiness />; if (s.includes("network")) return <Router />; if (s.includes("protein") || s.includes("fresh")) return <Beef />; if (s.includes("nut")) return <ShoppingBasket />; if (s.includes("dairy") || s.includes("fruit")) return <Milk />; if (s.includes("appliance") || s.includes("kitchen")) return <CookingPot />; if (s.includes("gift")) return <Gift />; if (s.includes("fashion")) return <Shirt />; if (s.includes("beauty") || s.includes("health")) return <Sparkles />; if (s.includes("book")) return <BookOpen />; if (s.includes("auto")) return <Car />; if (s.includes("mother") || s.includes("child")) return <HeartPulse />; if (s.includes("supermarket")) return <ShoppingBasket />; return <Package />; }

export default function CategoryIndexPage() {
  const [items, setItems] = useState<Category[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    categories.list()
      .then((list) => {
        if (cancelled) return;
        // Show every category (including empty ones). Non-empty first for usability.
        const sorted = [...list].sort((a, b) => (b.product_count > 0 ? 1 : 0) - (a.product_count > 0 ? 1 : 0));
        setItems(sorted);
      })
      .catch((e) => { if (!cancelled) { setError(e instanceof Error ? e.message : "خطا در دریافت دسته‌بندی‌ها"); setItems([]); } });
    return () => { cancelled = true; };
  }, []);
  const filled = items?.filter((c) => c.product_count > 0).length ?? 0;
  return (
    <div className="internal-page container-page py-6 md:py-10">
      <div className="internal-hero mb-6">
        <div className="internal-hero-icon"><LayoutGrid className="h-7 w-7" /></div>
        <div>
          <span className="section-kicker">دسترسی سریع</span>
          <h1>همه دسته‌بندی‌ها</h1>
          <p>هر ۲۰ دسته نمایش داده می‌شود{items ? `؛ ${filled} دسته دارای محصول و بقیه در حال تکمیل محصولات` : ""}.</p>
        </div>
      </div>
      {error ? (
        <div role="alert" className="card border-red-200 bg-red-50 p-6 text-center text-sm text-red-700"><b className="block mb-1">دریافت دسته‌بندی‌ها ناموفق بود</b>{error}</div>
      ) : items === null ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">{Array.from({ length: 20 }).map((_, i) => <div key={i} className="card h-36 skeleton" />)}</div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">{items.map((c) => <CategoryCard key={c.slug} name={c.name} href={`/category/${c.slug}`} count={c.product_count} icon={iconFor(c.slug)} />)}</div>
      )}
    </div>
  );
}
