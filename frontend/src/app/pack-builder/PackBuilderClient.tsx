"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Minus, Plus, Trash2, Save, Search, ShoppingCart, FileText, PackagePlus } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { catalog, packs, type Pack, type PackRow, type PackCartResult } from "@/lib/api";
import type { Product } from "@/lib/types";

const KINDS: { v: string; t: string }[] = [
  { v: "custom", t: "دلخواه" },
  { v: "essentials", t: "معیشتی" },
  { v: "gift", t: "هدیه" },
  { v: "seasonal", t: "مناسبتی" },
  { v: "organization", t: "سازمانی" },
];

function statusBadge(s: string) {
  if (s === "purchasable" || s === "verified")
    return { t: s === "verified" ? "قیمت‌دار" : "قابل خرید", c: "border-emerald-200 bg-emerald-50 text-emerald-700" };
  if (s === "inquiry-only" || s === "unpriced")
    return { t: s === "unpriced" ? "بدون قیمت" : "استعلامی", c: "border-amber-200 bg-amber-50 text-amber-700" };
  return { t: "ناموجود", c: "border-neutral-200 bg-neutral-100 text-neutral-500" };
}

export function PackBuilderClient() {
  const { token, loading: authLoading } = useAuth();
  const [rows, setRows] = useState<PackRow[]>([]);
  const [pack, setPack] = useState<Pack | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [cartResult, setCartResult] = useState<PackCartResult | null>(null);

  // search
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Product[]>([]);
  const [searching, setSearching] = useState(false);

  const refreshList = useCallback(async () => {
    if (!token) return;
    const r = await packs.list(token);
    setRows(r.packs);
  }, [token]);

  useEffect(() => { refreshList(); }, [refreshList]);

  async function loadPack(id: number) {
    if (!token) return;
    setErr(null); setCartResult(null); setMsg(null);
    try { const r = await packs.get(token, id); setPack(r.pack); }
    catch (e) { setErr(e instanceof Error ? e.message : "خطا"); }
  }

  async function newPack() {
    if (!token) return;
    const name = prompt("نام پک جدید:", "پک جدید");
    if (!name) return;
    setBusy(true); setErr(null);
    try {
      const r = await packs.create(token, name);
      setPack(r.pack); await refreshList();
    } catch (e) { setErr(e instanceof Error ? e.message : "خطا"); }
    finally { setBusy(false); }
  }

  async function doSearch(e?: React.FormEvent) {
    e?.preventDefault();
    if (!q.trim()) return;
    setSearching(true);
    try {
      const r = await catalog.list({ q: q.trim(), page_size: 24 });
      setResults(r.items);
    } finally { setSearching(false); }
  }

  async function mutate(fn: () => Promise<{ pack: Pack }>) {
    setBusy(true); setErr(null); setCartResult(null);
    try { const r = await fn(); setPack(r.pack); await refreshList(); }
    catch (e) { setErr(e instanceof Error ? e.message : "خطا"); }
    finally { setBusy(false); }
  }

  const addProduct = (p: Product) =>
    pack && token && mutate(() => packs.setItem(token, pack.id, p.id, 1));
  const setQty = (productId: number, qty: number) =>
    pack && token && qty >= 0 && mutate(() => packs.setItem(token, pack.id, productId, qty));
  const removeLine = (productId: number) =>
    pack && token && mutate(() => packs.removeItem(token, pack.id, productId));

  async function rename() {
    if (!pack || !token) return;
    const name = prompt("نام جدید پک:", pack.name);
    if (!name || name === pack.name) return;
    await mutate(() => packs.rename(token, pack.id, name));
  }
  async function deletePack() {
    if (!pack || !token || !confirm("این پک حذف شود؟")) return;
    setBusy(true);
    try { await packs.remove(token, pack.id); setPack(null); await refreshList(); }
    finally { setBusy(false); }
  }
  async function addAllToCart() {
    if (!pack || !token) return;
    setBusy(true); setErr(null); setMsg(null);
    try {
      const res = await packs.addToCart(token, pack.id);
      setCartResult(res);
    } catch (e) { setErr(e instanceof Error ? e.message : "خطا"); }
    finally { setBusy(false); }
  }
  async function requestProforma() {
    if (!pack || !token) return;
    const note = prompt("توضیح برای درخواست پیش‌فاکتور (اختیاری):", "");
    if (note === null) return;
    setBusy(true); setErr(null); setCartResult(null);
    try {
      const r = await packs.proforma(token, pack.id, note);
      setMsg(`درخواست پیش‌فاکتور ثبت شد (شماره ${r.request_id.toLocaleString("fa-IR")}). پیگیری از بخش «درخواست‌های من».`);
    } catch (e) { setErr(e instanceof Error ? e.message : "خطا"); }
    finally { setBusy(false); }
  }

  if (authLoading) return <div className="card p-8 text-center text-neutral-500">در حال بارگذاری…</div>;
  if (!token)
    return (
      <div className="card p-8 text-center">
        <PackagePlus className="mx-auto mb-3 h-10 w-10 text-neutral-300" />
        <p className="font-bold text-neutral-800">برای ساختن و ذخیره پک وارد شوید</p>
        <Link href="/login" className="mt-4 inline-block rounded-xl bg-primary-700 px-5 py-2.5 text-sm font-bold text-white">ورود</Link>
      </div>
    );

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1.1fr]">
      {/* picker */}
      <section className="space-y-4">
        <form onSubmit={doSearch} className="card flex items-center gap-2 p-3">
          <Search className="h-5 w-5 shrink-0 text-neutral-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="جستجوی کالا برای افزودن به پک"
            aria-label="جستجوی کالا" className="min-h-11 w-full bg-transparent text-sm outline-none" />
          <button className="rounded-lg bg-primary-700 px-4 py-2 text-xs font-bold text-white">{searching ? "…" : "جستجو"}</button>
        </form>
        <ul className="space-y-2">
          {results.map((p) => {
            const b = statusBadge(p.purchasable ? "purchasable" : "inquiry-only");
            return (
              <li key={p.id} className="card flex items-center justify-between gap-3 p-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-neutral-900">{p.name}</p>
                  <p className="text-2xs text-neutral-500">{p.category?.name}{p.brand ? " · " + p.brand : ""}</p>
                  <span className={"mt-1 inline-block rounded border px-1.5 py-0.5 text-2xs " + b.c}>{b.t}</span>
                </div>
                <button disabled={busy || !pack} onClick={() => addProduct(p)}
                  className="shrink-0 rounded-lg border border-primary-200 bg-primary-50 px-3 py-2 text-xs font-bold text-primary-800 disabled:opacity-50">
                  {pack ? "افزودن" : "اول یک پک بسازید"}
                </button>
              </li>
            );
          })}
          {q && !searching && results.length === 0 && (
            <li className="card p-6 text-center text-sm text-neutral-500">کالایی یافت نشد.</li>
          )}
        </ul>
      </section>

      {/* pack */}
      <section className="space-y-4">
        <div className="card p-4">
          <div className="flex flex-wrap items-center gap-2">
            <select value={pack?.id ?? ""} onChange={(e) => e.target.value && loadPack(Number(e.target.value))}
              aria-label="انتخاب پک ذخیره‌شده" className="min-h-11 flex-1 rounded-xl border border-neutral-200 p-2 text-sm">
              <option value="">— پک ذخیره‌شده —</option>
              {rows.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.item_count.toLocaleString("fa-IR")} قلم)</option>)}
            </select>
            <button onClick={newPack} disabled={busy} className="rounded-xl bg-primary-700 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50">
              <Plus className="ml-1 inline h-4 w-4" />پک جدید
            </button>
          </div>
        </div>

        {err && <div role="alert" className="card border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}
        {msg && <div className="card border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{msg}</div>}

        {!pack ? (
          <div className="card p-8 text-center text-neutral-500">یک پک بسازید یا از فهرست بالا انتخاب کنید.</div>
        ) : (
          <>
            <div className="card p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="font-black text-neutral-900">{pack.name}</h2>
                <div className="flex gap-1">
                  <button onClick={rename} className="rounded-lg p-2 text-neutral-500 hover:bg-neutral-100" aria-label="تغییر نام"><Save className="h-4 w-4" /></button>
                  <button onClick={deletePack} className="rounded-lg p-2 text-red-500 hover:bg-red-50" aria-label="حذف پک"><Trash2 className="h-4 w-4" /></button>
                </div>
              </div>
              {pack.items.length === 0 ? (
                <p className="py-6 text-center text-sm text-neutral-500">این پک خالی است. از پنل کنار کالا اضافه کنید.</p>
              ) : (
                <ul className="divide-y divide-neutral-100">
                  {pack.items.map((it) => {
                    const b = statusBadge(it.purchase_status);
                    return (
                      <li key={it.product_id} className="flex items-center gap-3 py-3">
                        <div className="min-w-0 flex-1">
                          {it.slug ? (
                            <Link href={"/products/" + it.slug} className="truncate text-sm font-semibold text-neutral-900 hover:text-primary-700">{it.title}</Link>
                          ) : (
                            <span className="text-sm font-semibold text-neutral-500">{it.title}</span>
                          )}
                          <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                            <span className={"rounded border px-1.5 py-0.5 text-2xs " + b.c}>{b.t}</span>
                            {it.unit_price != null && <span className="text-2xs text-neutral-600">{it.unit_price.toLocaleString("fa-IR")} ت/واحد</span>}
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          <button onClick={() => setQty(it.product_id, it.quantity - 1)} disabled={busy} className="rounded-md border p-1.5 disabled:opacity-40" aria-label="کم کردن"><Minus className="h-3.5 w-3.5" /></button>
                          <span className="w-8 text-center text-sm font-bold">{it.quantity.toLocaleString("fa-IR")}</span>
                          <button onClick={() => setQty(it.product_id, it.quantity + 1)} disabled={busy} className="rounded-md border p-1.5 disabled:opacity-40" aria-label="زیاد کردن"><Plus className="h-3.5 w-3.5" /></button>
                          <button onClick={() => removeLine(it.product_id)} disabled={busy} className="mr-1 rounded-md p-1.5 text-red-500 hover:bg-red-50 disabled:opacity-40" aria-label="حذف"><Trash2 className="h-3.5 w-3.5" /></button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            <div className="card space-y-2 p-4 text-sm">
              <div className="flex justify-between">
                <span className="text-neutral-600">جمع اقلام دارای قیمت تأییدشده</span>
                <b>{pack.summary.verified_subtotal != null ? pack.summary.verified_subtotal.toLocaleString("fa-IR") + " تومان" : "—"}</b>
              </div>
              {pack.summary.unpriced_item_count > 0 && (
                <div className="flex justify-between text-amber-700">
                  <span>اقلام بدون قیمت تأییدشده (استعلامی)</span>
                  <b>{pack.summary.unpriced_item_count.toLocaleString("fa-IR")} قلم</b>
                </div>
              )}
              <p className="pt-1 text-xs leading-6 text-neutral-500">{pack.summary.note}</p>
            </div>

            <div className="flex flex-col gap-2 sm:flex-row">
              <button onClick={addAllToCart} disabled={busy || pack.items.length === 0}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-primary-700 px-4 py-3 text-sm font-bold text-white disabled:opacity-50">
                <ShoppingCart className="h-4 w-4" />افزودن یک‌جا به سبد
              </button>
              <button onClick={requestProforma} disabled={busy || pack.items.length === 0}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl border border-amber-300 bg-amber-100 px-4 py-3 text-sm font-bold text-amber-950 disabled:opacity-50">
                <FileText className="h-4 w-4" />درخواست پیش‌فاکتور
              </button>
            </div>

            {cartResult && (
              <div className="card p-4 text-sm">
                <p className="font-bold text-neutral-800">نتیجه افزودن به سبد:</p>
                {cartResult.added.length > 0 && (
                  <p className="mt-1 text-emerald-700">{cartResult.added.length.toLocaleString("fa-IR")} قلم به سبد افزوده شد.</p>
                )}
                {cartResult.skipped.length > 0 && (
                  <ul className="mt-1 space-y-1 text-amber-700">
                    {cartResult.skipped.map((s) => <li key={s.product_id}>• {s.title}: {s.reason}</li>)}
                  </ul>
                )}
                {cartResult.added.length > 0 && <Link href="/cart" className="mt-2 inline-block font-bold text-primary-700">مشاهده سبد ←</Link>}
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
