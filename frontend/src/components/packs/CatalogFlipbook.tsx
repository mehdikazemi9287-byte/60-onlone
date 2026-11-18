"use client";
// Catalog flipbook modal — Stitch 58, built from the REAL published packs: each spread = one pack
// (right page: the pack's own item photos; left page: title, purpose, real items + quantities, real
// kind/tier/packaging chips, real price or «پس از استعلام», «add to pack builder»). The full-catalog PDF
// does not exist yet → disabled «به‌زودی». Share uses the pack's real URL.
import { useEffect, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import type { PackDetail } from "@/lib/storefront";
import { useGoodImages } from "@/lib/imageQuality";
import { toPersianNum } from "@/lib/utils";
import { packImages } from "./PackCard";
import { packBadge, packCode, packPrice } from "./PackGridCard";
import { Icon, Soon } from "./studio-ui";

type Props = { open: boolean; title: string; packs: PackDetail[]; start?: number; onClose: () => void;
  onAdd: (p: PackDetail) => void; picked?: string[]; onPick?: (slug: string) => void };

export function CatalogFlipbook({ open, title, packs, start = 0, onClose, onAdd, picked = [], onPick }: Props) {
  const [i, setI] = useState(start);
  const [zoom, setZoom] = useState(100);
  const [note, setNote] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { if (open) { setI(Math.min(start, Math.max(0, packs.length - 1))); setZoom(100); setNote(""); } }, [open, start, packs.length]);
  const good = useGoodImages(packs.flatMap((p) => p.items.map((x) => x.image_url)));
  const p = packs[i];
  const pages = packs.length * 2;
  const go = (d: number) => setI((x) => Math.min(packs.length - 1, Math.max(0, x + d)));
  const share = async () => {
    if (!p) return;
    const url = `${window.location.origin}/packs/${p.slug}`;
    try { if (navigator.share) await navigator.share({ title: p.title_fa, url }); else { await navigator.clipboard.writeText(url); setNote("نشانی پک کپی شد."); } } catch { /* cancelled */ }
  };
  const mail = p ? `mailto:?subject=${encodeURIComponent(`پک ${p.title_fa} — شصت‌آنلاین`)}&body=${encodeURIComponent(`${typeof window !== "undefined" ? window.location.origin : ""}/packs/${p.slug}`)}` : "#";
  const pics = p ? packImages(p, good, 4) : [];
  return (
    <Dialog.Root open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[60] bg-slate-900/60 backdrop-blur-sm" />
        <Dialog.Content ref={box} dir="rtl" onKeyDown={(e) => { if (e.key === "ArrowLeft") go(1); if (e.key === "ArrowRight") go(-1); }}
          className="fixed inset-0 z-[61] flex flex-col overflow-hidden bg-white shadow-2xl focus:outline-none md:inset-auto md:left-1/2 md:top-1/2 md:max-h-[94vh] md:w-[min(1360px,95vw)] md:-translate-x-1/2 md:-translate-y-1/2 md:rounded-2xl">
          <header className="flex items-center justify-between gap-3 border-b border-gray-200 px-4 py-3 md:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <span className="flex shrink-0 items-center gap-1.5 text-sm font-extrabold text-[#034EA2]">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/brand/60online-app-icon.png" alt="" className="h-6 w-6 rounded" />شصت‌آنلاین
              </span>
              <span className="hidden h-5 w-px bg-gray-200 md:block" />
              <Dialog.Title className="line-clamp-1 text-sm font-bold text-gray-900 md:text-base">{title}</Dialog.Title>
              <span className="hidden text-xs text-gray-500 lg:inline">— نسخه زنده از پک‌های منتشرشده</span>
              <span className="hidden items-center gap-1 rounded-full bg-[#9A3412] px-3 py-1 text-[11px] font-bold text-white md:inline-flex"><Icon name="local_offer" className="!text-[14px]" />{toPersianNum(packs.length)} پک</span>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <div className="hidden items-center gap-1 rounded-lg bg-gray-100 px-2 py-1 text-xs text-gray-600 md:flex">
                <button type="button" aria-label="بزرگ‌نمایی" onClick={() => setZoom((z) => Math.min(150, z + 10))} className="flex h-7 w-7 items-center justify-center"><Icon name="zoom_in" className="!text-[18px]" /></button>
                <span className="min-w-10 text-center">{toPersianNum(zoom)}٪</span>
                <button type="button" aria-label="کوچک‌نمایی" onClick={() => setZoom((z) => Math.max(70, z - 10))} className="flex h-7 w-7 items-center justify-center"><Icon name="zoom_out" className="!text-[18px]" /></button>
              </div>
              <button type="button" aria-label="تمام‌صفحه" onClick={() => { const el = box.current; if (!el) return; if (document.fullscreenElement) void document.exitFullscreen(); else void el.requestFullscreen?.(); }} className="hidden h-9 w-9 items-center justify-center rounded-lg text-gray-600 hover:bg-gray-100 md:flex"><Icon name="fullscreen" className="!text-[20px]" /></button>
              <Dialog.Close aria-label="بستن" className="flex h-9 w-9 items-center justify-center rounded-lg bg-gray-100 text-gray-700 hover:bg-gray-200"><Icon name="close" className="!text-[20px]" /></Dialog.Close>
            </div>
          </header>
          <Dialog.Description className="sr-only">کاتالوگ ورق‌زدنی پک‌های منتشرشده؛ با کلیدهای جهت ورق بزنید.</Dialog.Description>

          <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-auto bg-[#EAF1FB] px-3 py-6 md:px-20 md:py-10">
            {!p ? <p className="text-sm text-gray-500">پکی برای نمایش در کاتالوگ منتشر نشده است.</p> : <>
              <button type="button" aria-label="صفحه قبل" disabled={i === 0} onClick={() => go(-1)} className="absolute right-3 top-1/2 z-10 hidden h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-white text-gray-800 shadow-md disabled:opacity-30 md:flex md:right-5"><Icon name="arrow_forward" className="!text-[22px]" /></button>
              <button type="button" aria-label="صفحه بعد" disabled={i >= packs.length - 1} onClick={() => go(1)} className="absolute left-3 top-1/2 z-10 hidden h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-white text-gray-800 shadow-md disabled:opacity-30 md:flex md:left-5"><Icon name="arrow_back" className="!text-[22px]" /></button>
              <div style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center" }} className="grid w-full max-w-[1024px] overflow-hidden rounded-lg bg-white shadow-xl transition-transform md:grid-cols-[1fr_40px_1fr]">
                {/* Right page (RTL first): pack photography */}
                <section className="flex flex-col p-5 md:p-7">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="flex items-center gap-1.5 font-bold text-[#034EA2]"><span className="h-2 w-2 rounded-full bg-[#034EA2]" />{p.kind_fa}{p.occasion ? ` · ${p.occasion}` : ""}</span>
                    <span dir="ltr" className="text-gray-500">{packCode(p)} :شناسه کاتالوگ</span>
                  </div>
                  <div className="relative mt-6 flex aspect-[4/3.6] items-center justify-center overflow-hidden rounded-xl border border-blue-100 bg-[#EEF4FD] p-2">
                    {pics.length ? <span className={`grid h-full w-full gap-2 rounded-lg bg-white p-3 ${pics.length > 1 ? "grid-cols-2" : ""}`}>
                      {pics.map((src) => // eslint-disable-next-line @next/next/no-img-element
                        <img key={src} src={src} alt="" className="h-full w-full object-contain" />)}
                    </span> : <span className="flex flex-col items-center gap-2 text-gray-400"><Icon name="inventory_2" className="!text-[56px]" /><span className="text-[11px]">تصویر تأییدشده‌ای برای اقلام ثبت نشده</span></span>}
                    {p.packaging_fa && <span className="absolute bottom-3 left-3 flex items-center gap-1.5 rounded-lg bg-gray-700/90 px-3 py-1.5 text-[11px] font-medium text-white"><Icon name="inventory" className="!text-[14px]" />{p.packaging_fa}</span>}
                  </div>
                  <div className="mt-auto flex items-center justify-between pt-6 text-[11px] text-gray-500">
                    <span className="flex items-center gap-1.5"><Icon name="check_circle" className="!text-[15px] text-[#034EA2]" />{p.audience_fa}</span>
                    <b className="text-gray-700">صفحه {toPersianNum(i * 2 + 1)}</b>
                  </div>
                </section>
                <span aria-hidden className="hidden bg-gradient-to-l from-gray-100 via-gray-200 to-gray-100 md:block" />
                {/* Left page: details */}
                <section className="flex flex-col gap-3 border-t border-gray-100 p-5 md:border-t-0 md:p-7">
                  <div className="flex items-center justify-between text-[11px] text-gray-500"><b className="text-gray-700">صفحه {toPersianNum(i * 2 + 2)}</b><span>{p.tier_fa ? `سطح: ${p.tier_fa}` : `مخاطب: ${p.audience_fa}`}</span></div>
                  <span className="w-fit rounded bg-blue-100 px-2 py-0.5 text-[11px] font-bold text-[#034EA2]">{packBadge(p)}</span>
                  <h3 className="text-xl font-extrabold leading-snug text-gray-900 md:text-2xl">{p.title_fa}</h3>
                  <p className="line-clamp-3 text-xs leading-6 text-gray-600">{p.description_fa || p.purpose_fa}</p>
                  <div className="rounded-xl bg-blue-50/70 p-2">
                    <div className="flex items-center justify-between px-2 py-1.5 text-[11px] font-bold text-gray-600"><span>شرح محتویات بسته</span><span>تعداد در هر پک</span></div>
                    <ul className="flex max-h-[220px] flex-col gap-1.5 overflow-y-auto">
                      {p.items.map((it) => (
                        <li key={it.master_product_id} className="flex items-center justify-between gap-3 rounded-lg bg-white px-3 py-2.5 text-xs">
                          <span className="flex min-w-0 items-center gap-2 text-gray-800"><Icon name="check_circle" className="!text-[15px] text-[#034EA2]" /><span className="line-clamp-1">{it.title_fa}{it.variant_label ? ` (${it.variant_label})` : ""}</span></span>
                          <span className="shrink-0 text-[#034EA2]">{toPersianNum(it.quantity)} عدد</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-[11px] font-bold text-gray-800">
                    <span className="flex items-center justify-center gap-1 rounded-lg bg-blue-50 px-2 py-2"><Icon name="layers" className="!text-[15px] text-[#034EA2]" />{toPersianNum(p.item_count)} قلم</span>
                    <span className="flex items-center justify-center gap-1 rounded-lg bg-blue-50 px-2 py-2"><Icon name="verified_user" className="!text-[15px] text-[#034EA2]" />{p.brands.length ? `${toPersianNum(p.brands.length)} برند` : "کالای کاتالوگ"}</span>
                    <span className="flex items-center justify-center gap-1 rounded-lg bg-blue-50 px-2 py-2"><Icon name="inventory_2" className="!text-[15px] text-[#034EA2]" />حداقل {toPersianNum(Math.max(1, p.min_order_qty))}</span>
                  </div>
                  <div className="rounded-xl bg-blue-50 p-3">
                    <div className="flex items-center justify-between"><b className="text-xs text-gray-900">ارزش محاسباتی و قیمت‌گذاری:</b><span className="rounded bg-orange-100 px-2 py-0.5 text-[10px] font-bold text-[#9A3412]">{packPrice(p)}</span></div>
                    <p className="mt-1 text-[11px] leading-5 text-gray-600">قیمت نهایی و تخفیف پلکانی پس از ثبت استعلام بر اساس تیراژ از فروشندگان تأییدشده اعلام می‌شود.</p>
                  </div>
                  <div className="flex gap-2">
                    {onPick && <button type="button" aria-pressed={picked.includes(p.slug)} aria-label="افزودن به مقایسه" title="افزودن به مقایسه" onClick={() => onPick(p.slug)} className={`flex h-11 w-12 shrink-0 items-center justify-center rounded-lg border ${picked.includes(p.slug) ? "border-[#034EA2] bg-blue-50 text-[#034EA2]" : "border-gray-200 bg-gray-50 text-gray-700"}`}><Icon name="bookmark_border" fill={picked.includes(p.slug)} className="!text-[20px]" /></button>}
                    <button type="button" onClick={() => onAdd(p)} className="flex h-11 flex-1 items-center justify-center gap-2 rounded-lg bg-[#0B1F33] text-sm font-bold text-white hover:bg-[#112D46]"><Icon name="library_add" className="!text-[18px]" />افزودن این پک به پک‌ساز هوشمند</button>
                  </div>
                  <div className="flex items-center justify-between text-[10px] text-gray-500"><span>تحویل: {p.lead_time_days ? `حدود ${toPersianNum(p.lead_time_days)} روز کاری` : "در پاسخ استعلام"}</span><span dir="ltr">{packCode(p)}</span></div>
                </section>
              </div>
            </>}
          </div>

          <footer className="flex flex-col gap-3 border-t border-gray-200 px-4 py-3 md:flex-row md:items-center md:justify-between md:px-6">
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" disabled className="flex h-10 cursor-not-allowed items-center gap-2 rounded-lg bg-[#034EA2]/50 px-4 text-xs font-bold text-white"><Icon name="download" className="!text-[18px]" />دانلود نسخه کامل PDF <Soon className="bg-white/80" /></button>
              <button type="button" onClick={share} disabled={!p} className="flex h-10 items-center gap-1.5 rounded-lg bg-gray-100 px-3 text-xs font-bold text-gray-800 hover:bg-gray-200"><Icon name="share" className="!text-[18px]" />اشتراک‌گذاری</button>
              <a href={mail} className="flex h-10 items-center gap-1.5 rounded-lg bg-gray-100 px-3 text-xs font-bold text-gray-800 hover:bg-gray-200"><Icon name="send" className="!text-[18px]" />ارسال به مسئول خرید / ایمیل</a>
              {note && <span role="status" className="text-[11px] text-emerald-700">{note}</span>}
            </div>
            {packs.length > 0 && <div className="flex items-center gap-3">
              <span className="text-[11px] text-gray-500">صفحه ۱</span>
              <input type="range" min={0} max={packs.length - 1} value={i} onChange={(e) => setI(Number(e.target.value))} aria-label="پیمایش صفحات" className="w-40 accent-[#034EA2] md:w-56" />
              <span className="text-[11px] text-gray-500">صفحه {toPersianNum(pages)}</span>
              <span className="flex items-center gap-1 rounded-lg bg-blue-50 px-2.5 py-1.5 text-[11px] font-bold text-gray-800"><Icon name="auto_stories" className="!text-[16px]" />صفحه {toPersianNum(i * 2 + 1)} و {toPersianNum(i * 2 + 2)} از {toPersianNum(pages)}</span>
              <span className="hidden items-center gap-1 lg:flex">
                {packs.slice(Math.max(0, i - 1), Math.max(0, i - 1) + 3).map((x, k) => { const idx = Math.max(0, i - 1) + k; return (
                  <button key={x.slug} type="button" onClick={() => setI(idx)} aria-label={`صفحه ${idx * 2 + 1}`} className={`h-8 min-w-8 rounded border text-[10px] ${idx === i ? "border-[#034EA2] font-bold text-[#034EA2]" : "border-transparent bg-gray-50 text-gray-500"}`}>{toPersianNum(idx * 2 + 1)}</button>); })}
              </span>
            </div>}
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
