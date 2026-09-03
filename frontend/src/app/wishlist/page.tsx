"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { catalog } from "@/lib/api";
import { ProductGrid } from "@/components/product/ProductCard";
import { useWishlist } from "@/lib/wishlist";
import type { Product } from "@/lib/types";

// Minimal routing fix only — resolves the previously-404 /wishlist link in
// the header. No wishlist backend/data exists yet; this deliberately shows
// no fabricated items, matching the same-style empty state used elsewhere.
export default function WishlistPage() {
  const wishlist = useWishlist();
  const [products, setProducts] = useState<Product[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (wishlist.slugs.length === 0) {
      setProducts([]);
      return;
    }
    setProducts(null);
    Promise.all(wishlist.slugs.map((slug) => catalog.get(slug).then((res) => res.product).catch(() => null)))
      .then((items) => {
        if (!cancelled) setProducts(items.filter((item): item is Product => item !== null));
      });
    return () => { cancelled = true; };
  }, [wishlist.slugs.join("|")]);

  if (products === null) {
    return <div className="internal-page container-page py-20 text-center text-neutral-400">در حال بارگذاری علاقه‌مندی‌ها…</div>;
  }

  if (products.length > 0) {
    return (
      <div className="internal-page container-page py-6 md:py-8">
        <h1 className="text-xl md:text-2xl font-black text-neutral-900 mb-6">علاقه‌مندی‌ها</h1>
        <ProductGrid products={products} cols={4} />
      </div>
    );
  }

  return (
    <div className="internal-page container-page py-20 text-center text-neutral-400">
      <svg className="w-12 h-12 mx-auto mb-3 opacity-40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
          d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z" />
      </svg>
      <p className="font-medium">علاقه‌مندی‌های شما خالی است</p>
      <p className="text-sm mt-1 mb-5">محصولات مورد علاقه‌تان را اینجا نگه دارید</p>
      <Link href="/category" className="text-brand-blue text-sm font-semibold">
        مشاهده دسته‌بندی‌ها
      </Link>
    </div>
  );
}
