"use client";
// Customize popup — Stitch 60, wired to the pack's REAL composition: include/exclude items, per-pack
// quantity, same-type alternatives returned by the backend, and pack count. Applying opens the existing
// editor (PackBuilderInteractive, protected/unchanged) where prices are re-fetched and the quote/cart flow
// happens. Packaging choice and logo print have no backend: shown disabled with «به‌زودی».
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import * as Dialog from "@radix-ui/react-dialog";
import type { PackDetail } from "@/lib/storefront";
import type { PackDraft } from "@/components/home/PackBuilderInteractive";
import { useGoodImages } from "@/lib/imageQuality";
import { positiveInteger } from "@/lib/pack-input";
import { formatPrice, toPersianNum } from "@/lib/utils";
import { Icon, Soon } from "./studio-ui";
import { packBadge, packCode } from "./PackGridCard";

type Row = { key: number; on: boolean; qty: number; slug: string | null; title: string; sub: string; image: string | null; price: number | null; required: boolean;
  alts: { slug: string; title: string }[]; original: { slug: string | null; title: string } };
const COUNT_PRESETS = [50, 100, 500, 1000];

function rowsOf(p: PackDetail): Row[] {
  return p.items.map((i) => ({ key: i.master_product_id, on: true, qty: i.quantity, slug: i.slug, title: i.title_fa, image: i.image_url,
    sub: [i.brand_fa, i.variant_label].filter(Boolean).join(" · "),
    price: i.unit_price_minor, required: i.required, original: { slug: i.slug, title: i.title_fa },
    alts: (i.alternatives ?? []).filter((a): a is typeof a & { slug: string } => !!a.slug).map((a) => ({ slug: a.slug, title: `${a.title_fa}${a.variant_label ? ` · ${a.variant_label}` : ""}` })) }));
}

export function PackCustomizeDialog({ pack, onClose, onApply }: { pack: PackDetail | null; onClose: () => void; onApply: (draft: PackDraft) => void }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [count, setCount] = useState("");
  useEffect(() => { if (pack) { setRows(rowsOf(pack)); setCount(toPersianNum(Math.max(1, pack.min_order_qty))); } }, [pack]);
  const good = useGoodImages(rows.map((r) => r.image));
  const n = positiveInteger(count);
  const min = pack ? Math.max(1, pack.min_order_qty) : 1;
  const chosen = rows.filter((r) => r.on && r.slug);
  const editable = !!pack?.customizable;
  const valid = !!n && n >= min && n <= 100000 && chosen.length > 0;
  const changed = useMemo(() => !!pack && rows.some((r, i) => !r.on || r.qty !== pack.items[i]?.quantity || r.slug !== pack.items[i]?.slug), [rows, pack]);
  // A total is shown only for the untouched, fully priced composition (backend price × count).
  const total = pack && !changed && pack.price_minor != null && n && n >= min ? pack.price_minor * n : null;
  const set = (key: number, patch: Partial<Row>) => setRows((xs) => xs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const draft = (): PackDraft => ({ count: n!, items: chosen.map((r) => ({ slug: r.slug!, title: r.title, quantity: r.qty, imageUrl: r.image, priceMinor: r.slug === r.original.slug ? r.price : null })) });
  const apply = () => { if (pack && valid) onApply(draft()); };
  return (
    <Dialog.Root open={!!pack} onOpenChange={(o) => { if (!o) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[60] bg-slate-900/60 backdrop-blur-sm" />
        <Dialog.Content dir="rtl" className="fixed inset-x-0 bottom-0 z-[61] flex max-h-[92vh] flex-col overflow-hidden rounded-t-2xl border border-gray-200 bg-white shadow-2xl focus:outline-none md:inset-auto md:left-1/2 md:top-1/2 md:w-[min(1024px,94vw)] md:-translate-x-1/2 md:-translate-y-1/2 md:rounded-2xl">
          {pack && <>
            <header className="flex items-center justify-between gap-3 border-b border-gray-200 bg-white px-4 py-4 sm:px-6">
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#034EA2]/10 text-[#034EA2]"><Icon name="edit_square" className="!text-[20px]" /></span>
                <div className="flex min-w-0 flex-col">
                  <div className="flex min-w-0 flex-wrap items-center gap-2.5">
                    <Dialog.Title className="line-clamp-1 text-base font-extrabold text-[#112D46] sm:text-lg">سفارشی‌سازی اقلام {pack.title_fa}</Dialog.Title>
                    <span dir="ltr" className="rounded bg-gray-100 px-2 py-0.5 text-[11px] font-bold tracking-wider text-gray-500">{packCode(pack)}</span>
                    <span className="hidden rounded bg-[#FF7A00] px-2 py-0.5 text-[10px] font-bold text-white sm:inline-flex">{packBadge(pack)}</span>
                  </div>
                  <Dialog.Description className="mt-0.5 text-xs text-gray-500">{editable ? "حذف، تغییر تعداد یا جایگزینی هم‌نوع اقلام؛ قیمت‌ها در مرحله بعد دوباره بررسی می‌شوند." : "ترکیب این پک ثابت است؛ فقط تیراژ را تعیین کنید."}</Dialog.Description>
                </div>
              </div>
              <Dialog.Close className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-gray-200 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700" aria-label="بستن"><Icon name="close" className="!text-[20px]" /></Dialog.Close>
            </header>
            <div className="grid min-h-0 flex-1 grid-cols-1 divide-y divide-gray-200 overflow-y-auto lg:grid-cols-12 lg:divide-x lg:divide-y-0 lg:divide-x-reverse">
              <div className="flex flex-col gap-4 p-5 sm:p-6 lg:col-span-8">
                <div className="flex items-center justify-between gap-3 rounded-xl border border-blue-100 bg-blue-50/60 p-3 text-xs text-[#034EA2]">
                  <span className="flex items-center gap-2 font-medium"><Icon name="info" className="!text-[16px]" /><span>اقلام پایه این پک از کالاهای واقعی کاتالوگ انتخاب شده‌اند. می‌توانید تعداد، جایگزین هم‌نوع یا حذف اقلام را شخصی‌سازی کنید.</span></span>
                  <span className="whitespace-nowrap font-bold">{toPersianNum(rows.length)} قلم موجود</span>
                </div>
                <ul className="flex flex-col gap-3" aria-label="اقلام پک">
                  {rows.map((r) => (
                    <li key={r.key} className={`flex flex-col items-start justify-between gap-3 rounded-xl border p-3.5 transition sm:flex-row sm:items-center ${r.on ? "border-gray-200 bg-white hover:border-gray-300" : "border-dashed border-gray-300 bg-gray-50/70"}`}>
                      <div className="flex min-w-0 items-center gap-3">
                        <input type="checkbox" checked={r.on} disabled={!editable || !r.slug} onChange={(e) => set(r.key, { on: e.target.checked })} aria-label={`گنجاندن ${r.title}`} className="h-4 w-4 rounded border-gray-300 accent-[#034EA2]" />
                        <span className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-gray-200 bg-gray-100 text-[#034EA2]">
                          {r.image && good?.has(r.image) ? // eslint-disable-next-line @next/next/no-img-element
                            <img src={r.image} alt="" className="h-full w-full bg-white object-contain p-1" /> : <Icon name="package_2" className="!text-[24px]" />}
                        </span>
                        <span className="flex min-w-0 flex-col">
                          <span className={`line-clamp-1 text-xs font-bold sm:text-sm ${r.on ? "text-gray-900" : "text-gray-500"}`}>{r.title}</span>
                          <span className="text-[11px] text-gray-500">{[r.sub, r.required ? "قلم اصلی" : "اختیاری", r.slug === r.original.slug && r.price != null ? `${formatPrice(r.price)} واحد` : "قیمت پس از استعلام", !r.slug ? "فعلاً در کاتالوگ فروش نیست" : ""].filter(Boolean).join(" · ")}</span>
                        </span>
                      </div>
                      <div className="flex items-center gap-2 self-end sm:self-center">
                        {editable && r.on && r.slug ? <>
                          <span className="flex h-8 items-center rounded-lg border border-gray-200 bg-gray-50">
                            <button type="button" aria-label="کاهش تعداد" disabled={r.qty <= 1} onClick={() => set(r.key, { qty: r.qty - 1 })} className="flex h-8 w-7 items-center justify-center text-gray-700 disabled:opacity-40"><Icon name="remove" className="!text-[16px]" /></button>
                            <span className="min-w-12 text-center text-xs text-gray-700" aria-live="polite">تعداد: {toPersianNum(r.qty)}</span>
                            <button type="button" aria-label="افزایش تعداد" disabled={r.qty >= 100} onClick={() => set(r.key, { qty: r.qty + 1 })} className="flex h-8 w-7 items-center justify-center text-gray-700 disabled:opacity-40"><Icon name="add" className="!text-[16px]" /></button>
                          </span>
                          {r.alts.length > 0 && <select aria-label={`جایگزین هم‌نوع ${r.original.title}`} value={r.slug ?? ""} onChange={(e) => {
                            const s = e.target.value; const alt = r.alts.find((a) => a.slug === s);
                            set(r.key, alt ? { slug: alt.slug, title: alt.title, image: null } : { slug: r.original.slug, title: r.original.title, image: pack.items.find((i) => i.master_product_id === r.key)?.image_url ?? null });
                          }} className="h-8 max-w-[200px] rounded-lg border border-gray-200 bg-gray-50 px-2 text-xs text-gray-700 focus:border-[#034EA2] focus:outline-none">
                            {r.original.slug && <option value={r.original.slug}>{r.original.title}</option>}
                            {r.alts.map((a) => <option key={a.slug} value={a.slug}>{a.title}</option>)}
                          </select>}
                          <button type="button" onClick={() => set(r.key, { on: false })} className="h-8 rounded-lg px-2 text-xs font-medium text-red-600 transition hover:bg-red-50">حذف قلم</button>
                        </> : editable && r.slug ? <button type="button" onClick={() => set(r.key, { on: true })} className="flex h-8 items-center gap-1.5 rounded-lg border border-[#034EA2] px-3 text-xs font-bold text-[#034EA2] transition hover:bg-[#034EA2]/10">+ افزودن به پک</button>
                          : <span className="text-[11px] text-gray-400">×{toPersianNum(r.qty)}</span>}
                      </div>
                    </li>
                  ))}
                </ul>
                {editable && <button type="button" disabled={!valid} onClick={apply} className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-[#034EA2] py-2.5 text-xs font-bold text-[#034EA2] transition hover:bg-[#034EA2]/5 disabled:opacity-50">
                  <Icon name="add" className="!text-[16px]" /><span>افزودن کالای دلخواه دیگر از کاتالوگ شصت‌آنلاین (در ویرایشگر پک)</span>
                </button>}
              </div>
              <aside className="flex flex-col gap-5 bg-gray-50 p-5 sm:p-6 lg:col-span-4">
                <div className="flex flex-col gap-1.5 border-b border-gray-200 pb-3">
                  <h3 className="text-sm font-bold text-[#112D46]">پیکربندی بسته‌بندی و تحویل</h3>
                  <span className="text-[11px] text-gray-500">بسته‌بندی، هویت بصری سازمان و تیراژ</span>
                </div>
                <div className="flex flex-col gap-2">
                  <span className="text-xs font-semibold text-gray-700">نوع جعبه و بسته‌بندی پک:</span>
                  <label className="flex items-center justify-between rounded-xl border border-[#034EA2] bg-white p-2.5">
                    <span className="flex items-center gap-2"><input type="radio" checked readOnly name="packaging" className="accent-[#034EA2]" /><span className="text-xs font-bold text-gray-800">{pack.packaging_fa ?? "بسته‌بندی استاندارد تأمین‌کننده"}</span></span>
                    <span className="rounded bg-blue-50 px-2 py-0.5 text-[10px] font-bold text-[#034EA2]">ثبت‌شده برای پک</span>
                  </label>
                  <label className="flex cursor-not-allowed items-center justify-between rounded-xl border border-gray-200 bg-white p-2.5 opacity-70">
                    <span className="flex items-center gap-2"><input type="radio" disabled name="packaging" /><span className="text-xs font-semibold text-gray-500">انتخاب جعبه یا کارتن دیگر</span></span><Soon />
                  </label>
                </div>
                <label className="flex cursor-not-allowed items-start gap-2.5 rounded-xl border border-gray-200 bg-white p-3 opacity-70">
                  <input type="checkbox" disabled className="mt-0.5 h-4 w-4" />
                  <span className="flex flex-col"><span className="flex items-center gap-2 text-xs font-bold text-gray-700">چاپ لوگو و کارت تبریک سازمانی <Soon /></span><span className="text-[10px] leading-normal text-gray-500">بارگذاری لوگو و سفارش چاپ هنوز در سامانه فعال نشده است.</span></span>
                </label>
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between text-xs"><label htmlFor="customize-count" className="font-semibold text-gray-700">تیراژ سفارش (تعداد کل پک‌ها):</label><span className="text-[11px] font-medium text-gray-400">حداقل: {toPersianNum(min)} عدد</span></div>
                  <div className="flex items-center gap-1.5">{COUNT_PRESETS.map((c) => <button key={c} type="button" disabled={c < min} onClick={() => setCount(toPersianNum(c))} aria-pressed={n === c} className={`flex-1 rounded-lg border py-1.5 text-xs disabled:opacity-40 ${n === c ? "border-[#034EA2] bg-white font-bold text-[#034EA2]" : "border-gray-200 bg-white font-semibold text-gray-700 hover:bg-gray-100"}`}>{toPersianNum(c)}</button>)}</div>
                  <input id="customize-count" inputMode="numeric" value={count} onChange={(e) => setCount(e.target.value)} className="h-9 rounded-lg border border-gray-200 bg-white px-3 text-center text-xs font-bold" />
                  {n != null && n < min && <p className="text-[11px] text-[#B45309]">تیراژ کمتر از حداقل سفارش این پک است.</p>}
                </div>
                <div className="flex flex-col gap-1.5 rounded-xl border border-[#D5E4D8] bg-[#EDF3EE] p-3 text-xs">
                  <div className="flex items-center justify-between text-gray-700"><span className="text-[11px]">وزن ثبت‌شده هر پک:</span><span className="font-bold text-[#112D46]">{pack.food_weight_g ? `${toPersianNum(+(pack.food_weight_g / 1000).toFixed(1))} کیلوگرم` : "ثبت نشده"}</span></div>
                  <div className="flex items-center justify-between text-gray-700"><span className="text-[11px]">مبنای قیمت‌گذاری اقلام:</span><span className="font-bold text-gray-900">پیشنهاد فروشندگان تأییدشده</span></div>
                  <div className="flex items-center justify-between border-t border-[#D5E4D8] pt-2 font-bold text-[#034EA2]"><span>مبلغ کل برآورد:</span><span className="text-xs">{total != null ? formatPrice(total) : "پس از استعلام رسمی"}</span></div>
                </div>
                <div className="flex flex-col gap-2 pt-1">
                  <button type="button" disabled={!valid} onClick={apply} className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#112D46] text-xs font-bold text-white shadow-sm transition hover:bg-[#0A1C2C] disabled:opacity-50">
                    <Icon name="check" className="!text-[16px]" /><span>اعمال تغییرات و ادامه به پیش‌فاکتور</span>
                  </button>
                  <Link href={`/packs/${pack.slug}`} className="flex h-9 w-full items-center justify-center gap-2 rounded-xl border border-gray-300 text-xs font-semibold text-gray-700 transition hover:bg-white">
                    <Icon name="description" className="!text-[16px] text-gray-500" /><span>مشخصات کامل اقلام پک</span>
                  </Link>
                  {editable && changed && <button type="button" onClick={() => setRows(rowsOf(pack))} className="py-1 text-center text-[11px] text-gray-500 underline transition hover:text-[#034EA2]">بازگشت به ترکیب استاندارد پک</button>}
                </div>
              </aside>
            </div>
          </>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
