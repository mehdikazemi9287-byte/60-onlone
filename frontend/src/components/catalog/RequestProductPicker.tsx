"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
export type RequestProduct = { id: number; name: string; category: string; brand: string | null; variant: string | null; size: string | null; net_quantity: string | null; unit: string | null; package_quantity: number | null; supplier: string | null; supplier_codes: string[]; slug: string; price: null; stock: null; purchasable: false };
export type RequestSelection = { product: RequestProduct; quantity: number };
export const PACK_REQUEST_KEY = "60online_pack_request_v1";
type Result = { items: RequestProduct[]; total_pages: number; total: number; suppliers: string[] };
export function RequestProductPicker({ value, onChange, initialSupplier = "", initialQuery = "" }: { initialSupplier?: string; initialQuery?: string; value: RequestSelection[]; onChange: (value: RequestSelection[]) => void }) {
  const [q, setQ] = useState(initialQuery), [category, setCategory] = useState(""), [supplier, setSupplier] = useState(initialSupplier), [page, setPage] = useState(1);
  const [categories, setCategories] = useState<{slug: string; name_fa: string}[]>([]), [result, setResult] = useState<Result | null>(null), [error, setError] = useState(""), [loading, setLoading] = useState(false);
  useEffect(() => { apiRequest<{ items: {slug: string; name_fa: string}[] }>("/categories").then(r => setCategories(r.items)).catch(e => setError(e.message)); }, []);
  useEffect(() => {
    let live = true; setLoading(true); setError("");
    const timer = setTimeout(() => { const params = new URLSearchParams({q, category, supplier, page: String(page)}); apiRequest<Result>("/catalog/selection?" + params).then(r => { if(live) setResult(r); }).catch(e => { if(live) { setError(e.message); setResult(null); } }).finally(() => { if(live) setLoading(false); }); }, 250);
    return () => { live = false; clearTimeout(timer); };
  }, [q, category, supplier, page]);
  return <div className="space-y-4" data-testid="request-product-picker">
    <p className="text-sm leading-7">انتخاب کالا برای درخواست تأمین و استعلام قیمت است. قیمت و موجودی باید تأیید شوند؛ انتخاب به معنی امکان خرید مستقیم نیست.</p>
    <div className="grid gap-3 sm:grid-cols-3">
      <label>جستجوی کالا یا کد<input aria-label="جستجوی کالای درخواست" className="block border rounded-xl p-3 w-full" value={q} onChange={e => {setQ(e.target.value); setPage(1);}} /></label>
      <label>دسته‌بندی<select aria-label="دسته‌بندی کالای درخواست" className="block border rounded-xl p-3 w-full" value={category} onChange={e => {setCategory(e.target.value); setPage(1);}}><option value="">همه دسته‌بندی‌ها</option>{categories.map(c => <option key={c.slug} value={c.slug}>{c.name_fa}</option>)}</select></label>
      <label>تأمین‌کننده<select aria-label="تأمین‌کننده کالای درخواست" className="block border rounded-xl p-3 w-full" value={supplier} onChange={e => {setSupplier(e.target.value); setPage(1);}}><option value="">همه تأمین‌کنندگان</option>{result?.suppliers.map(s => <option key={s} value={s}>{s}</option>)}</select></label>
    </div>
    {error && <p role="alert">{error}</p>}{loading && <p role="status">در حال جستجو…</p>}
    {!loading && result?.total === 0 && <p>کالایی با این فیلتر یافت نشد.</p>}
    <ul className="grid gap-3 sm:grid-cols-2">{!loading && result?.items.map(product => <li key={product.id} className="border rounded-xl p-3 min-w-0" data-product-id={product.id}>
      <Link href={"/products/"+product.slug} className="font-bold">{product.name}</Link><p className="text-xs mt-2">{[product.supplier, product.variant, product.size, product.net_quantity, ...product.supplier_codes].filter(Boolean).join(" · ")}</p>
      <p className="text-xs mt-2">نیازمند استعلام قیمت و موجودی</p><button type="button" className="border rounded-lg p-2 mt-3" disabled={value.some(x => x.product.id===product.id) || value.length>=50} onClick={() => onChange([...value,{product,quantity:1}])}>انتخاب برای درخواست</button>
    </li>)}</ul>
    {result && result.total_pages>1 && <div className="flex gap-3 items-center"><button type="button" disabled={page<=1 || loading} onClick={() => setPage(page-1)}>قبلی</button><span>{page} / {result.total_pages}</span><button type="button" disabled={page>=result.total_pages || loading} onClick={() => setPage(page+1)}>بعدی</button></div>}
    {value.length>0 && <ul className="space-y-3" aria-label="کالاهای انتخاب‌شده">{value.map((item,n) => <li key={item.product.id} className="border rounded-xl p-3"><span>{item.product.name}</span><label className="block mt-2">تعداد موردنیاز<input aria-label={"تعداد "+item.product.name} className="border rounded-lg p-2 mx-2 w-24" type="number" min={1} max={100000} step={1} required value={item.quantity} onChange={e => onChange(value.map((x,i) => i===n?{...x,quantity:Number(e.target.value)}:x))} /></label>{item.product.unit && <span className="text-xs">واحد: {item.product.unit}</span>}<button type="button" className="mr-3 text-sm" onClick={() => onChange(value.filter((_,i) => i!==n))}>حذف</button></li>)}</ul>}
  </div>;
}
