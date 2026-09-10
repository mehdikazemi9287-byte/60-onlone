"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Minus, Plus, Trash2, Save, Search, ShoppingCart, FileText, Sparkles, ArrowLeftRight } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { catalog, cart as cartApi, packs, type Pack, type PackRow } from "@/lib/api";
import {
  BUDGET_PRESETS_MINOR, OCCASIONS, filterPriced, budgetState, buildRecommendations,
  addItem, removeItem, setQuantity, replaceItem, packTotalMinor,
  type PBProduct, type PBItem,
} from "@/lib/pack-builder";
import type { Product } from "@/lib/types";

const fmt = (minor: number) => Math.round(minor / 10).toLocaleString("fa-IR") + " تومان";

/** normalized catalog Product -> pure-logic PBProduct (never invents a price). */
function toPB(p: Product): PBProduct {
  return { ...p, id: p.id, price_minor: p.price_minor, title_fa: p.name, slug: p.slug, in_stock: p.stock !== 0 };
}

type Budget = (typeof BUDGET_PRESETS_MINOR)[number];
type Occasion = (typeof OCCASIONS)[number];
interface Editing { label: string; items: PBItem[]; }

export function PackBuilderClient() {
  const { token } = useAuth();
  const [budget, setBudget] = useState<Budget | null>(null);
  const [occasion, setOccasion] = useState<Occasion | null>(null);
  const [products, setProducts] = useState<PBProduct[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // search-and-add / replace
  const [q, setQ] = useState("");
  const [results, setResults] = useState<PBProduct[]>([]);
  const [replaceTarget, setReplaceTarget] = useState<number | "">("");

  // server-side saved packs (compatibility addition — does not replace original)
  const [savedRows, setSavedRows] = useState<PackRow[]>([]);
  const refreshSaved = useCallback(async () => {
    if (!token) return;
    try { setSavedRows((await packs.list(token)).packs); } catch { /* optional */ }
  }, [token]);
  useEffect(() => { refreshSaved(); }, [refreshSaved]);

  const runBuild = useCallback(async (b: Budget | null, o: Occasion | null) => {
    if (!b || !o) return;
    setLoading(true); setErr(null);
    try {
      const results = await Promise.all(
        o.category_slugs.map((slug) => catalog.list({ category: slug, page_size: 24 })),
      );
      setProducts(filterPriced(results.flatMap((r) => r.items.map(toPB))));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "دریافت کالاها ناموفق بود");
    } finally { setLoading(false); }
  }, []);

  const recs = useMemo(
    () => (products.length && budget ? buildRecommendations(products, budget.amount_minor) : null),
    [products, budget],
  );

  const runSearch = useCallback(async (term: string) => {
    if (!term || term.trim().length < 2) { setResults([]); return; }
    try {
      const r = await catalog.list({ q: term.trim(), page_size: 6 });
      setResults(filterPriced(r.items.map(toPB)));
    } catch { /* optional-effort */ }
  }, []);

  const editItems = editing?.items ?? [];
  const bState = budget && editing ? budgetState(editItems, budget.amount_minor) : null;

  function openEdit(label: string, items: PBItem[]) {
    setEditing({ label, items: items.map((it) => ({ ...it })) });
    setNote(null); setErr(null); setResults([]); setReplaceTarget("");
  }
  function patchItems(next: PBItem[]) { setEditing((e) => (e ? { ...e, items: next } : e)); }

  async function addPackToCart(label: string, items: PBItem[]) {
    if (!token) { setErr("برای افزودن پک ابتدا وارد شوید"); return; }
    if (!items.length) { setErr("پک خالی است"); return; }
    setErr(null); setNote(null);
    let added = 0; const skipped: string[] = [];
    for (const it of items) {
      try { await cartApi.add(token, it.product.id, it.quantity); added++; }
      catch (e) { skipped.push(`${it.product.title_fa}: ${e instanceof Error ? e.message : "افزوده نشد"}`); }
    }
    setNote(
      `پک «${label}»: ${added.toLocaleString("fa-IR")} قلم به سبد افزوده شد` +
      (skipped.length ? ` — ${skipped.length.toLocaleString("fa-IR")} قلم افزوده نشد (${skipped[0]})` : ""),
    );
  }

  async function saveEditingPack() {
    if (!token || !editing) { setErr("برای ذخیره پک وارد شوید"); return; }
    if (!editing.items.length) { setErr("پک خالی است"); return; }
    try {
      const created: { pack: Pack } = await packs.create(token, editing.label || "پک سفارشی");
      for (const it of editing.items) await packs.setItem(token, created.pack.id, it.product.id, it.quantity);
      await refreshSaved();
      setNote(`پک «${editing.label}» ذخیره شد. از «درخواست‌های من» / پنل کاربر قابل بازیابی است.`);
    } catch (e) { setErr(e instanceof Error ? e.message : "ذخیره پک ناموفق بود"); }
  }

  async function proformaEditingPack() {
    if (!token || !editing) { setErr("برای درخواست پیش‌فاکتور وارد شوید"); return; }
    if (!editing.items.length) { setErr("پک خالی است"); return; }
    try {
      const created: { pack: Pack } = await packs.create(token, editing.label || "پک سفارشی");
      for (const it of editing.items) await packs.setItem(token, created.pack.id, it.product.id, it.quantity);
      const r = await packs.proforma(token, created.pack.id, "درخواست پیش‌فاکتور از پک‌ساز");
      await refreshSaved();
      setNote(`درخواست پیش‌فاکتور ثبت شد (شماره ${r.request_id.toLocaleString("fa-IR")}).`);
    } catch (e) { setErr(e instanceof Error ? e.message : "ثبت پیش‌فاکتور ناموفق بود"); }
  }

  async function loadSaved(id: number) {
    if (!token) return;
    try {
      const { pack } = await packs.get(token, id);
      openEdit(pack.name, pack.items
        .filter((l) => l.slug)
        .map((l) => ({ product: { id: l.product_id, price_minor: l.unit_price != null ? l.unit_price * 10 : null, title_fa: l.title, slug: l.slug ?? undefined, in_stock: l.in_stock }, quantity: l.quantity })));
    } catch (e) { setErr(e instanceof Error ? e.message : "بازیابی پک ناموفق بود"); }
  }

  // ── Editing panel ─────────────────────────────────────────────────────────
  if (editing) {
    return (
      <div className="space-y-4">
        {err && <div role="alert" className="card border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}
        {note && <div className="card border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{note}</div>}
        <div className="card space-y-4 p-4 md:p-5">
          <div className="flex items-center justify-between">
            <strong className="text-neutral-900">ویرایش: {editing.label}</strong>
            <button onClick={() => setEditing(null)} className="rounded-lg border px-3 py-1.5 text-sm">بستن ویرایش</button>
          </div>

          {editItems.length ? (
            <div className="divide-y divide-neutral-100">
              {editItems.map((it) => (
                <div key={it.product.id} className="flex items-center gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-neutral-900">{it.product.title_fa}</p>
                    <p className="text-2xs text-neutral-500">
                      {it.product.price_minor != null ? fmt(it.product.price_minor * it.quantity) : "بدون قیمت رسمی"}
                    </p>
                  </div>
                  <div className="flex items-center gap-1">
                    <button aria-label="کاهش تعداد" onClick={() => patchItems(setQuantity(editItems, it.product.id, it.quantity - 1))} className="rounded-md border p-1.5"><Minus className="h-3.5 w-3.5" /></button>
                    <span className="w-8 text-center text-sm font-bold">{it.quantity.toLocaleString("fa-IR")}</span>
                    <button aria-label="افزایش تعداد" onClick={() => patchItems(setQuantity(editItems, it.product.id, it.quantity + 1))} className="rounded-md border p-1.5"><Plus className="h-3.5 w-3.5" /></button>
                    <button aria-label={`حذف ${it.product.title_fa}`} onClick={() => patchItems(removeItem(editItems, it.product.id))} className="mr-1 rounded-md p-1.5 text-red-500 hover:bg-red-50"><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-4 text-center text-sm text-neutral-500">این پک هنوز کالایی ندارد — از جست‌وجوی زیر کالا اضافه کنید.</p>
          )}

          {bState && (
            <div className="flex items-center justify-between rounded-lg bg-neutral-50 px-3 py-2 text-sm">
              <span className="font-bold">جمع: {fmt(bState.total_minor)}</span>
              <span className={bState.over_budget ? "text-red-600" : "text-emerald-700"}>
                {bState.over_budget ? `${fmt(-bState.remaining_minor)} بیش از بودجه` : `${fmt(bState.remaining_minor)} باقی‌مانده`}
              </span>
            </div>
          )}

          <div>
            <label htmlFor="pb-search" className="mb-1 block text-sm text-neutral-600">جست‌وجوی کالا برای افزودن یا جایگزینی</label>
            <input id="pb-search" type="search" value={q} placeholder="نام کالا…"
              onChange={(e) => { setQ(e.target.value); runSearch(e.target.value); }}
              className="min-h-11 w-full rounded-xl border border-neutral-200 px-3 text-sm" />
            <select value={replaceTarget} onChange={(e) => setReplaceTarget(e.target.value ? Number(e.target.value) : "")}
              className="mt-1.5 w-full rounded-xl border border-neutral-200 p-2 text-sm">
              <option value="">افزودن کالای جدید (جایگزینی نیست)</option>
              {editItems.map((it) => <option key={it.product.id} value={it.product.id}>جایگزینی: {it.product.title_fa}</option>)}
            </select>
          </div>

          {results.length > 0 && (
            <ul className="space-y-2">
              {results.map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-3 rounded-lg border border-neutral-100 p-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-neutral-800">{p.title_fa}</p>
                    <p className="text-2xs text-neutral-500">{p.price_minor != null ? fmt(p.price_minor) : ""}</p>
                  </div>
                  <button
                    onClick={() => {
                      patchItems(replaceTarget ? replaceItem(editItems, replaceTarget, p) : addItem(editItems, p, 1));
                      setReplaceTarget("");
                    }}
                    className="shrink-0 rounded-lg border border-primary-200 bg-primary-50 px-3 py-1.5 text-xs font-bold text-primary-800">
                    {replaceTarget ? <><ArrowLeftRight className="ml-1 inline h-3 w-3" />جایگزینی</> : "افزودن"}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {q.trim().length >= 2 && results.length === 0 && (
            <p className="text-sm text-neutral-500">کالایی با قیمت رسمی یافت نشد.</p>
          )}

          <div className="flex flex-col gap-2 sm:flex-row">
            <button onClick={() => addPackToCart(editing.label, editItems)} className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-primary-700 px-4 py-3 text-sm font-bold text-white">
              <ShoppingCart className="h-4 w-4" />افزودن این پک ویرایش‌شده به سبد
            </button>
            <button onClick={saveEditingPack} className="inline-flex items-center justify-center gap-2 rounded-xl border border-primary-200 bg-white px-4 py-3 text-sm font-bold text-primary-800">
              <Save className="h-4 w-4" />ذخیره پک
            </button>
            <button onClick={proformaEditingPack} className="inline-flex items-center justify-center gap-2 rounded-xl border border-amber-300 bg-amber-100 px-4 py-3 text-sm font-bold text-amber-950">
              <FileText className="h-4 w-4" />پیش‌فاکتور
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Budget / occasion / recommendations ───────────────────────────────────
  return (
    <div className="space-y-5">
      {err && <div role="alert" className="card border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}
      {note && <div className="card border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{note}</div>}

      <div className="card space-y-4 p-4 md:p-5">
        <div>
          <p className="mb-1.5 text-sm text-neutral-500">بودجه</p>
          <div className="flex flex-wrap gap-2">
            {BUDGET_PRESETS_MINOR.map((b) => (
              <button key={b.id} type="button"
                onClick={() => { setBudget(b); runBuild(b, occasion); }}
                className={"rounded-full border px-3 py-1.5 text-xs font-bold " + (budget?.id === b.id ? "border-primary-600 bg-primary-600 text-white" : "border-neutral-200 bg-white text-neutral-700")}>
                {b.label}
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="mb-1.5 text-sm text-neutral-500">مناسبت / کاربرد</p>
          <div className="flex flex-wrap gap-2">
            {OCCASIONS.map((o) => (
              <button key={o.id} type="button"
                onClick={() => { setOccasion(o); runBuild(budget, o); }}
                className={"rounded-full border px-3 py-1.5 text-xs font-bold " + (occasion?.id === o.id ? "border-primary-600 bg-primary-600 text-white" : "border-neutral-200 bg-white text-neutral-700")}>
                {o.label}
              </button>
            ))}
          </div>
        </div>
        <button type="button" onClick={() => openEdit("پک سفارشی", [])}
          className="inline-flex items-center gap-2 self-start rounded-xl border border-primary-200 bg-white px-4 py-2.5 text-sm font-bold text-primary-800">
          <Sparkles className="h-4 w-4" />+ پک سفارشی از صفر (جست‌وجوی آزاد)
        </button>
      </div>

      {loading && (
        <div className="grid gap-3 md:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="card h-48 skeleton" />)}</div>
      )}

      {recs && !loading && (
        <div className="grid gap-3 md:grid-cols-3">
          {[recs.economy, recs.balanced, recs.premium].map((tier) => (
            <div key={tier.id} className="card space-y-3 p-4">
              <div className="flex items-center justify-between">
                <strong className="text-neutral-900">{tier.label}</strong>
                <span className={"rounded-md border px-2 py-0.5 text-2xs font-medium " + (tier.over_budget ? "border-red-200 bg-red-50 text-red-700" : "border-emerald-200 bg-emerald-50 text-emerald-700")}>
                  {tier.over_budget ? "خارج از بودجه" : "در محدوده بودجه"}
                </span>
              </div>
              {tier.items.length ? (
                <ul className="space-y-1 text-sm">
                  {tier.items.slice(0, 4).map((it) => (
                    <li key={it.product.id} className="flex justify-between gap-2">
                      <span className="truncate text-neutral-700">{it.product.title_fa}</span>
                      <span className="shrink-0 text-neutral-400">{it.product.price_minor != null ? fmt(it.product.price_minor) : ""}</span>
                    </li>
                  ))}
                  {tier.items.length > 4 && <li className="text-2xs text-neutral-400">+ {(tier.items.length - 4).toLocaleString("fa-IR")} قلم دیگر</li>}
                </ul>
              ) : (
                <p className="text-sm text-neutral-500">کالای واجد شرایط با قیمت رسمی برای این بودجه یافت نشد.</p>
              )}
              <div className="flex items-center justify-between text-sm">
                <span className="font-bold">جمع: {fmt(tier.total_minor)}</span>
                <span className="text-neutral-400">
                  {tier.over_budget ? `${fmt(-tier.remaining_minor)} بیش از بودجه` : `${fmt(tier.remaining_minor)} باقی‌مانده`}
                </span>
              </div>
              {tier.items.length > 0 && (
                <div className="flex gap-2">
                  <button onClick={() => addPackToCart(tier.label, tier.items)} className="flex-1 rounded-lg border border-primary-200 bg-primary-50 px-3 py-2 text-xs font-bold text-primary-800">افزودن این پک به سبد</button>
                  <button onClick={() => openEdit(tier.label, tier.items)} className="flex-1 rounded-lg bg-primary-700 px-3 py-2 text-xs font-bold text-white">ویرایش (حذف/جایگزینی/تعداد)</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {budget && occasion && !recs && !loading && (
        <p className="text-sm text-neutral-500">برای این ترکیب بودجه/مناسبت هنوز کالای دارای قیمت رسمی کافی نیست.</p>
      )}

      {token && savedRows.length > 0 && (
        <div className="card p-4">
          <p className="mb-2 text-sm font-bold text-neutral-800">پک‌های ذخیره‌شده شما</p>
          <ul className="flex flex-wrap gap-2">
            {savedRows.map((r) => (
              <li key={r.id}>
                <button onClick={() => loadSaved(r.id)} className="rounded-lg border border-neutral-200 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 hover:border-primary-300">
                  {r.name} <span className="text-neutral-400">({r.item_count.toLocaleString("fa-IR")})</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!token && (
        <p className="text-xs text-neutral-500">
          افزودن پک به سبد و ذخیره پک نیازمند <Link href="/login" className="text-primary-700 underline">ورود</Link> است. مشاهده پیشنهادها آزاد است.
        </p>
      )}
      <p className="text-xs text-neutral-400">
        همه کالاها و قیمت‌ها از کاتالوگ واقعی خوانده می‌شوند. کالای بدون قیمت رسمی هرگز در پیشنهادها یا جمع بودجه ظاهر نمی‌شود.
        {" "}اگر همه پیشنهادها خالی‌اند یعنی هنوز قیمت رسمی برای آن دسته/بودجه ثبت نشده است.
      </p>
    </div>
  );
}
