"use client";
// Item customization popup (Stitch screen 60), wired to the pack's REAL composition: include/exclude items,
// per-pack quantity, same-type alternatives returned by the backend, and pack count. Applying opens the
// existing editor (PackBuilderInteractive) where prices are re-fetched and the quote/cart flow happens.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import * as Dialog from "@radix-ui/react-dialog";
import { X, Minus, Plus, ImageOff, RotateCcw, Info } from "lucide-react";
import type { PackDetail } from "@/lib/storefront";
import type { PackDraft } from "@/components/home/PackBuilderInteractive";
import { useGoodImages } from "@/lib/imageQuality";
import { positiveInteger } from "@/lib/pack-input";
import { formatPrice, toPersianNum } from "@/lib/utils";
import { btnPrimary, btnSecondary } from "./studio-ui";

type Row = { key: number; on: boolean; qty: number; slug: string | null; title: string; image: string | null; price: number | null; required: boolean;
  alts: { slug: string; title: string }[]; original: { slug: string | null; title: string } };
const COUNT_PRESETS = [50, 100, 500, 1000];

function rowsOf(p: PackDetail): Row[] {
  return p.items.map((i) => ({ key: i.master_product_id, on: true, qty: i.quantity, slug: i.slug, title: i.title_fa, image: i.image_url,
    price: i.unit_price_minor, required: i.required, original: { slug: i.slug, title: i.title_fa },
    alts: (i.alternatives ?? []).filter((a): a is typeof a & { slug: string } => !!a.slug).map((a) => ({ slug: a.slug, title: `${a.title_fa}${a.variant_label ? ` · ${a.variant_label}` : ""}` })) }));
}

export function PackCustomizeDialog({ pack, onClose, onApply }: { pack: PackDetail | null; onClose: () => void; onApply: (draft: PackDraft) => void }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [count, setCount] = useState("");
  useEffect(() => { if (pack) { setRows(rowsOf(pack)); setCount(String(Math.max(1, pack.min_order_qty))); } }, [pack]);
  const good = useGoodImages(rows.map((r) => r.image));
  const n = positiveInteger(count);
  const min = pack ? Math.max(1, pack.min_order_qty) : 1;
  const chosen = rows.filter((r) => r.on && r.slug);
  const editable = !!pack?.customizable;
  // Same min/max as the editor and saved drafts (1..100000), plus the pack's own minimum order.
  const valid = !!n && n >= min && chosen.length > 0;
  const changed = useMemo(() => !!pack && rows.some((r, i) => !r.on || r.qty !== pack.items[i]?.quantity || r.slug !== pack.items[i]?.slug), [rows, pack]);
  const set = (key: number, patch: Partial<Row>) => setRows((xs) => xs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const apply = () => {
    if (!pack || !valid) return;
    onApply({ count: n!, items: chosen.map((r) => ({ slug: r.slug!, title: r.title, quantity: r.qty, imageUrl: r.image, priceMinor: r.slug === r.original.slug ? r.price : null })) });
  };
  return (
    <Dialog.Root open={!!pack} onOpenChange={(o) => { if (!o) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[60] bg-[#111827]/40 backdrop-blur-[2px]" />
        <Dialog.Content dir="rtl" className="fixed inset-x-0 bottom-0 z-[61] flex max-h-[92vh] flex-col rounded-t-2xl bg-white shadow-2xl focus:outline-none md:inset-auto md:left-1/2 md:top-1/2 md:w-[min(960px,94vw)] md:-translate-x-1/2 md:-translate-y-1/2 md:rounded-xl">
          {pack && <>
            <header className="flex items-start justify-between gap-4 border-b border-[#F3F4F6] p-4 md:p-5">
              <div className="min-w-0">
                <Dialog.Title className="line-clamp-1 text-base font-extrabold text-[#112D46] md:text-lg">شخصی‌سازی «{pack.title_fa}»</Dialog.Title>
                <Dialog.Description className="mt-1 text-xs text-[#6B7280]">{editable ? "حذف، تغییر تعداد یا جایگزینی هم‌نوع اقلام؛ قیمت‌ها در مرحله بعد دوباره بررسی می‌شوند." : "ترکیب این پک ثابت است؛ فقط تعداد پک را تعیین کنید."}</Dialog.Description>
              </div>
              <Dialog.Close className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[#E5E7EB] text-[#6B7280] hover:text-[#111827]" aria-label="بستن"><X className="h-4 w-4" /></Dialog.Close>
            </header>
            <div className="grid min-h-0 flex-1 overflow-y-auto md:grid-cols-12">
              <ul className="divide-y divide-[#F3F4F6] p-4 md:col-span-8 md:p-5" aria-label="اقلام پک">
                {rows.map((r) => (
                  <li key={r.key} className={`grid grid-cols-[auto_48px_minmax(0,1fr)] items-start gap-3 py-3 ${r.on ? "" : "opacity-50"}`}>
                    <input type="checkbox" checked={r.on} disabled={!editable || !r.slug} onChange={(e) => set(r.key, { on: e.target.checked })} aria-label={`گنجاندن ${r.title}`} className="mt-4 h-4 w-4 accent-[#034EA2]" />
                    <span className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-lg border border-[#F3F4F6] bg-white">
                      {r.image && good?.has(r.image) ? // eslint-disable-next-line @next/next/no-img-element
<img src={r.image} alt="" className="h-full w-full object-contain p-1" /> : <ImageOff className="h-4 w-4 text-[#D1D5DB]" aria-hidden />}
                    </span>
                    <div className="min-w-0">
                      <p className="line-clamp-2 text-sm font-bold text-[#111827]">{r.title}</p>
                      <p className="mt-0.5 text-[11px] text-[#6B7280]">{r.required ? "قلم اصلی" : "اختیاری"} · {r.slug === r.original.slug && r.price != null ? `${formatPrice(r.price)} واحد` : "قیمت پس از استعلام"}{!r.slug ? " · فعلاً در کاتالوگ فروش نیست" : ""}</p>
                      {editable && r.on && r.slug && <div className="mt-2 flex flex-wrap items-center gap-2">
                        <div className="flex items-center rounded-lg border border-[#E5E7EB]">
                          <button type="button" aria-label="کاهش تعداد" disabled={r.qty <= 1} onClick={() => set(r.key, { qty: r.qty - 1 })} className="flex h-8 w-8 items-center justify-center disabled:opacity-40"><Minus className="h-3.5 w-3.5" /></button>
                          <span className="min-w-8 text-center text-xs font-bold" aria-live="polite">{toPersianNum(r.qty)}</span>
                          <button type="button" aria-label="افزایش تعداد" disabled={r.qty >= 100} onClick={() => set(r.key, { qty: r.qty + 1 })} className="flex h-8 w-8 items-center justify-center disabled:opacity-40"><Plus className="h-3.5 w-3.5" /></button>
                        </div>
                        <span className="text-[11px] text-[#6B7280]">در هر پک</span>
                        {r.alts.length > 0 && <select aria-label={`جایگزین هم‌نوع ${r.original.title}`} value={r.slug ?? ""} onChange={(e) => {
                          const s = e.target.value; const alt = r.alts.find((a) => a.slug === s);
                          set(r.key, alt ? { slug: alt.slug, title: alt.title, image: null } : { slug: r.original.slug, title: r.original.title, image: pack.items.find((i) => i.master_product_id === r.key)?.image_url ?? null });
                        }} className="h-8 max-w-[220px] rounded-lg border border-[#E5E7EB] bg-white px-2 text-[11px]">
                          {r.original.slug && <option value={r.original.slug}>{r.original.title}</option>}
                          {r.alts.map((a) => <option key={a.slug} value={a.slug}>{a.title}</option>)}
                        </select>}
                      </div>}
                    </div>
                  </li>))}
              </ul>
              <aside className="space-y-4 border-t border-[#F3F4F6] bg-[#F9F9F9] p-4 md:col-span-4 md:border-r md:border-t-0 md:p-5">
                <div>
                  <label htmlFor="customize-count" className="text-xs font-bold text-[#112D46]">تعداد پک</label>
                  <input id="customize-count" inputMode="numeric" value={count} onChange={(e) => setCount(e.target.value)} className="mt-1 h-11 w-full rounded-xl border border-[#E5E7EB] bg-white px-3 text-center text-sm font-bold" />
                  <div className="mt-2 grid grid-cols-4 gap-1.5">{COUNT_PRESETS.map((c) => <button key={c} type="button" onClick={() => setCount(String(c))} aria-pressed={n === c} className={`h-8 rounded-lg border text-[11px] font-bold ${n === c ? "border-[#034EA2] text-[#034EA2]" : "border-[#E5E7EB] bg-white text-[#374151]"}`}>{toPersianNum(c)}</button>)}</div>
                  <p className={`mt-1 text-[11px] ${n && n < min ? "text-[#B45309]" : "text-[#6B7280]"}`}>حداقل سفارش این پک: {toPersianNum(min)} پک</p>
                </div>
                <dl className="space-y-1.5 text-xs">
                  <div className="flex justify-between"><dt className="text-[#6B7280]">اقلام انتخاب‌شده</dt><dd className="font-bold text-[#112D46]">{toPersianNum(chosen.length)} قلم</dd></div>
                  <div className="flex justify-between"><dt className="text-[#6B7280]">مبلغ کل</dt><dd className="font-bold text-[#112D46]">پس از استعلام</dd></div>
                </dl>
                <p className="flex gap-1.5 rounded-lg bg-white p-2.5 text-[11px] leading-5 text-[#6B7280]"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> انتخاب نوع بسته‌بندی و چاپ لوگوی سازمان هنوز در سامانه فعال نشده است.</p>
                <button type="button" disabled={!valid} onClick={apply} className={`${btnPrimary} w-full`}>اعمال و ادامه به بررسی</button>
                <Link href={`/packs/${pack.slug}`} className={`${btnSecondary} w-full`}>صفحه کامل پک</Link>
                {editable && changed && <button type="button" onClick={() => setRows(rowsOf(pack))} className="flex min-h-9 w-full items-center justify-center gap-1 text-[11px] text-[#6B7280] hover:text-[#034EA2]"><RotateCcw className="h-3.5 w-3.5" aria-hidden /> بازگشت به ترکیب اصلی</button>}
              </aside>
            </div>
          </>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
