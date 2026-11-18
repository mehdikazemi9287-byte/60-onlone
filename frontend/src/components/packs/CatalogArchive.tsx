"use client";
// Catalog archive + send form — Stitch 57 (desktop) / 59 (mobile), over REAL data only.
// There is no catalog/archive backend: each "catalog" here is a live view of the currently published packs
// of one occasion group (same filters as /pack-builder), opened in the flipbook (Stitch 58). Past seasons,
// PDF files and the automatic e-mail/WhatsApp send have no backend → shown honestly as «به‌زودی» / disabled.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { PackDetail } from "@/lib/storefront";
import { useGoodImages } from "@/lib/imageQuality";
import { toPersianNum } from "@/lib/utils";
import { loadPackDetails, packImages } from "./PackCard";
import { GROUPS } from "./pack-groups";
import { CatalogFlipbook } from "./CatalogFlipbook";
import { Icon, Soon } from "./studio-ui";

type Cat = { key: string; title: string; label: string; packs: PackDetail[] };

export function CatalogArchive() {
  const [packs, setPacks] = useState<PackDetail[] | null>(null), [error, setError] = useState("");
  const [q, setQ] = useState(""), [group, setGroup] = useState("");
  const [book, setBook] = useState<Cat | null>(null);
  useEffect(() => { let on = true; loadPackDetails().then((p) => on && setPacks(p.filter((x) => x.items.length))).catch(() => on && setError("دریافت پک‌های منتشرشده ناموفق بود.")); return () => { on = false; }; }, []);
  const cats: Cat[] = useMemo(() => (packs ? GROUPS.map(([k, l, f]) => ({ key: k, label: l, title: k ? `کاتالوگ ${l}` : "کاتالوگ جامع پک‌های شصت‌آنلاین", packs: packs.filter(f) })).filter((c) => c.packs.length) : []), [packs]);
  const shown = cats.filter((c) => (!group || c.key === group) && (!q.trim() || `${c.title} ${c.packs.map((p) => p.title_fa).join(" ")}`.includes(q.trim())));
  const good = useGoodImages((packs ?? []).flatMap((p) => p.items.map((i) => i.image_url)));
  return (
    <div dir="rtl" className="bg-[#F9F9F9]">
      <MobileArchive cats={cats} packs={packs} error={error} good={good} onOpen={setBook} />
      <div className="hidden md:block">
      <section className="bg-[#EEF3FA]">
        <div className="mx-auto flex max-w-[1240px] flex-col gap-4 px-4 pb-10 pt-6 md:flex-row md:items-end md:justify-between md:px-6 md:pb-16 md:pt-10">
          <div className="max-w-2xl">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[#DCE7F7] px-3 py-1 text-[11px] font-bold text-[#112D46]"><Icon name="collections_bookmark" className="!text-[15px] text-[#034EA2]" />مرکز اسناد و کاتالوگ‌های تدارکات سازمانی ۶۰ آنلاین</span>
            <h1 className="mt-3 text-2xl font-extrabold leading-snug text-[#0B1F33] md:text-[34px]">آرشیو کاتالوگ‌های فصلی و راهنمای سفارش عمده سازمانی</h1>
            <p className="mt-3 text-sm leading-7 text-gray-600">مشاهده تعاملی کاتالوگ پک‌های منتشرشده بر اساس مناسبت؛ همه صفحات از پک‌ها و کالاهای واقعی کاتالوگ ساخته می‌شوند. ویژه مدیران تدارکات، منابع انسانی و رفاهی.</p>
          </div>
          <Link href="/pack-builder" className="flex items-center gap-3 self-start rounded-xl border border-gray-100 bg-white p-4 shadow-sm md:self-auto">
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#EEF3FA] text-[#034EA2]"><Icon name="request_quote" className="!text-[22px]" /></span>
            <span><b className="block text-sm text-[#0B1F33]">سامانه استعلام قیمت پک</b><span className="text-[11px] text-gray-500">انتخاب پک و ثبت استعلام در پک‌ساز</span></span>
          </Link>
        </div>
      </section>

      <div className="mx-auto -mt-6 flex max-w-[1240px] flex-col gap-8 px-4 pb-16 md:-mt-8 md:px-6">
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm md:p-6">
          <label className="relative block">
            <span className="sr-only">جستجو در کاتالوگ‌ها</span>
            <Icon name="search" className="absolute right-4 top-1/2 -translate-y-1/2 !text-[20px] text-gray-500" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="جستجو در عناوین کاتالوگ، مناسبت یا نام پک..." className="h-12 w-full rounded-xl border border-gray-300 bg-white pl-4 pr-12 text-sm focus:border-[#034EA2] focus:outline-none" />
          </label>
          <div className="mt-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-2 overflow-x-auto [scrollbar-width:none]">
              <span className="flex shrink-0 items-center gap-1 text-xs font-bold text-gray-700"><Icon name="category" className="!text-[16px]" />دسته‌بندی مناسبت:</span>
              {cats.map((c) => <button key={c.key || "all"} type="button" aria-pressed={group === c.key} onClick={() => setGroup(c.key)} className={`shrink-0 rounded-full px-3.5 py-1.5 text-xs ${group === c.key ? "bg-[#034EA2] font-bold text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"}`}>{c.key ? c.label : "همه مناسبت‌ها"}</button>)}
            </div>
            <div className="flex shrink-0 items-center gap-2 text-xs">
              <span className="flex items-center gap-1 font-bold text-gray-700"><Icon name="calendar_month" className="!text-[16px]" />سال انتشار:</span>
              <span className="rounded-full bg-[#0B1F33] px-3.5 py-1.5 font-bold text-white">نسخه جاری</span>
              <span className="flex items-center gap-1 rounded-full bg-gray-100 px-3 py-1.5 text-gray-400">سال‌های گذشته <Soon /></span>
            </div>
          </div>
        </div>

        <section aria-labelledby="cat-title">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
            <h2 id="cat-title" className="flex items-center gap-2 text-xl font-extrabold text-[#0B1F33] md:text-2xl"><span className="h-6 w-1.5 rounded-full bg-[#034EA2]" />کاتالوگ‌های تدارکاتی<span className="rounded bg-gray-100 px-2 py-0.5 text-[11px] font-bold text-gray-600">{toPersianNum(cats.length)} نسخه زنده</span></h2>
            <span className="flex items-center gap-1 text-[11px] font-bold text-gray-600"><Icon name="verified_user" className="!text-[15px]" />همه صفحات از پک‌های منتشرشده و کالاهای واقعی ساخته می‌شوند</span>
          </div>
          {error ? <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>
            : !packs ? <div role="status" aria-label="در حال دریافت" className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="h-[380px] animate-pulse rounded-xl bg-white" />)}</div>
            : !shown.length ? <div className="rounded-xl border border-gray-200 bg-white p-8 text-center text-sm text-gray-600"><Icon name="menu_book" className="!text-[32px] text-gray-400" /><p className="mt-2">{packs.length ? "کاتالوگی با این جستجو پیدا نشد." : "هنوز پکی منتشر نشده است؛ کاتالوگی برای نمایش وجود ندارد."}</p></div>
            : <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
                {shown.map((c) => {
                  const pics = c.packs.flatMap((p) => packImages(p, good, 1)).slice(0, 3);
                  return (
                    <article key={c.key || "all"} className="flex flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
                      <button type="button" onClick={() => setBook(c)} className="relative block aspect-[16/9] w-full overflow-hidden bg-[#E3EBF6] text-right">
                        {pics.length ? <span className="absolute inset-0 grid grid-cols-3 gap-2 bg-white p-4">{pics.map((s) => /* eslint-disable-next-line @next/next/no-img-element */ <img key={s} src={s} alt="" className="h-full w-full object-contain" />)}</span>
                          : <Icon name="auto_stories" className="absolute left-1/2 top-[38%] -translate-x-1/2 -translate-y-1/2 !text-[44px] text-[#034EA2]/40" />}
                        <span className="absolute right-3 top-3 flex gap-1.5"><span className="rounded-full bg-[#9A3412] px-2.5 py-0.5 text-[10px] font-bold text-white">نسخه زنده</span><span className="rounded-full bg-[#112D46] px-2.5 py-0.5 text-[10px] font-bold text-white">{toPersianNum(c.packs.length)} پک</span></span>
                        <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-[#0B1F33]/85 via-[#0B1F33]/50 to-transparent px-4 pb-3 pt-10">
                          <span className="block text-[10px] text-white/80">تدارکات {c.key ? c.label : "همه مناسبت‌ها"}</span>
                          <span className="block text-base font-extrabold text-white">{c.title}</span>
                        </span>
                      </button>
                      <div className="flex flex-1 flex-col gap-3 p-4">
                        <p className="line-clamp-2 text-xs leading-6 text-gray-600">{c.packs.map((p) => p.title_fa).join("، ")}.</p>
                        <div className="grid grid-cols-2 gap-2 rounded-lg bg-gray-50 p-3 text-xs font-bold text-gray-800">
                          <span className="flex items-center gap-1.5"><Icon name="auto_stories" className="!text-[16px] text-[#034EA2]" />{toPersianNum(c.packs.length * 2)} صفحه</span>
                          <span className="flex items-center gap-1.5"><Icon name="layers" className="!text-[16px] text-[#034EA2]" />{toPersianNum(c.packs.reduce((n, p) => n + p.item_count, 0))} قلم کالا</span>
                        </div>
                        <div className="flex items-center justify-between text-[11px]"><span className="flex items-center gap-1 text-gray-600"><Icon name="payments" className="!text-[15px]" />قیمت: {c.packs.some((p) => p.price_minor != null) ? `${toPersianNum(c.packs.filter((p) => p.price_minor != null).length)} پک قیمت‌دار` : "پس از استعلام"}</span><span className="font-bold text-[#9A3412]">تخفیف تیراژ با استعلام</span></div>
                        <div className="mt-auto flex gap-2">
                          <button type="button" onClick={() => setBook(c)} className="flex h-11 flex-1 items-center justify-center gap-2 rounded-lg bg-[#034EA2] text-xs font-bold text-white hover:bg-[#023B7B]"><Icon name="chrome_reader_mode" className="!text-[18px]" />پیش‌نمایش آنلاین</button>
                          <button type="button" disabled title="فایل PDF کاتالوگ هنوز منتشر نشده است" className="flex h-11 cursor-not-allowed items-center gap-1 rounded-lg border border-gray-200 px-3 text-xs font-bold text-gray-400"><Icon name="download" className="!text-[16px]" />PDF</button>
                        </div>
                      </div>
                    </article>);
                })}
              </div>}
        </section>

        <SendForm cats={cats} />

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-5">
          {([["verified_user", "فقط کالای واقعی کاتالوگ", "بدون محصول یا تصویر نمونه"], ["request_quote", "قیمت از پیشنهاد فروشنده", "قیمت نهایی پس از استعلام"], ["receipt_long", "پیش‌فاکتور رسمی", "پس از ثبت استعلام"], ["support_agent", "پشتیبانی B2B", "از مسیر تماس با ما"]] as const).map(([i, t, s]) => (
            <div key={t} className="flex items-center gap-3 rounded-xl border border-gray-200 bg-white p-4"><Icon name={i} className="!text-[24px] text-[#034EA2]" /><span><b className="block text-sm text-[#0B1F33]">{t}</b><span className="text-[11px] text-gray-500">{s}</span></span></div>
          ))}
        </div>
      </div>
      </div>
      <CatalogFlipbook open={!!book} title={book?.title ?? ""} packs={book?.packs ?? []} onClose={() => setBook(null)}
        onAdd={(p) => { window.location.href = `/pack-builder?pack=${encodeURIComponent(p.slug)}`; }} />
    </div>
  );
}

// Stitch 57/59 auto-send form. No backend for automatic catalog delivery → the form is visible but disabled.
function SendForm({ cats }: { cats: Cat[] }) {
  const field = "h-12 w-full rounded-lg border border-gray-200 bg-gray-50 px-3 pr-10 text-sm placeholder:text-gray-400";
  return (
    <section aria-labelledby="send-title" className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
      <div className="h-1.5 bg-gradient-to-l from-[#034EA2] to-[#112D46]" />
      <div className="flex flex-col gap-6 p-5 md:p-8">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="flex items-start gap-4">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#034EA2] text-white"><Icon name="forward_to_inbox" className="!text-[26px]" /></span>
            <div>
              <h2 id="send-title" className="flex flex-wrap items-center gap-2 text-lg font-extrabold text-[#0B1F33] md:text-2xl">ارسال خودکار کاتالوگ به ایمیل یا واتساپ مسئول تدارکات <Soon /></h2>
              <p className="mt-1 text-xs leading-6 text-gray-500">ارسال خودکار نسخه PDF و فرم استعلام هنوز در سامانه فعال نشده است. تا آن زمان کاتالوگ آنلاین را باز کنید و از «اشتراک‌گذاری» یا «ارسال به مسئول خرید / ایمیل» استفاده کنید.</p>
            </div>
          </div>
          <span className="flex shrink-0 items-center gap-1.5 self-start rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-bold text-gray-500"><Icon name="bolt" className="!text-[16px]" />سیستم ارسال آنی — غیرفعال</span>
        </div>
        <fieldset disabled className="flex flex-col gap-6 border-t border-gray-100 pt-6">
          <legend className="sr-only">فرم ارسال کاتالوگ (غیرفعال)</legend>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {([["نام شرکت یا سازمان", "corporate_fare", "نام سازمان"], ["نام و سمت مسئول تدارکات / رفاه", "badge", "نام و سمت"], ["ایمیل سازمانی", "mail", "procurement@example.ir"], ["شماره همراه (واتساپ فعال)", "chat", "۰۹xxxxxxxxx"]] as const).map(([l, i, ph]) => (
              <label key={l} className="flex flex-col gap-1.5"><span className="text-xs font-bold text-gray-800">{l}</span>
                <span className="relative"><Icon name={i} className="absolute right-3 top-1/2 -translate-y-1/2 !text-[18px] text-gray-400" /><input className={field} placeholder={ph} /></span></label>
            ))}
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="flex flex-col gap-2"><span className="flex items-center gap-1 text-xs font-bold text-gray-800"><Icon name="library_add" className="!text-[16px]" />انتخاب کاتالوگ مورد نظر جهت دریافت:</span>
              <div className="grid gap-2 sm:grid-cols-2">{(cats.length ? cats : [{ key: "none", title: "کاتالوگی منتشر نشده" }]).slice(0, 4).map((c) => <label key={c.key || "all"} className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2.5 text-xs text-gray-500"><input type="checkbox" />{c.title}</label>)}</div></div>
            <div className="flex flex-col gap-2"><span className="flex items-center gap-1 text-xs font-bold text-gray-800"><Icon name="alt_route" className="!text-[16px]" />کانال ارسال فایل و فرم استعلام:</span>
              <div className="grid grid-cols-3 gap-2">{["ارسال سریع به واتساپ", "ارسال رسمی به ایمیل سازمانی", "هر دو کانال"].map((t) => <label key={t} className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2.5 text-xs text-gray-500"><input type="radio" name="send-ch" />{t}</label>)}</div></div>
          </div>
          <div className="flex flex-col-reverse items-start gap-3 border-t border-gray-100 pt-5 md:flex-row md:items-center md:justify-between">
            <span className="flex items-center gap-1.5 text-[11px] text-gray-500"><Icon name="privacy_tip" className="!text-[15px]" />این فرم تا فعال‌شدن ارسال خودکار هیچ اطلاعاتی دریافت یا ذخیره نمی‌کند.</span>
            <button type="button" className="flex h-12 cursor-not-allowed items-center gap-2 rounded-xl bg-[#034EA2]/40 px-8 text-sm font-bold text-white"><Icon name="send" className="!text-[18px]" />ارسال آنی کاتالوگ سازمانی</button>
          </div>
        </fieldset>
      </div>
    </section>
  );
}

// Stitch 59 (mobile 390): app bar, inline catalog viewer, compact send card, archive rows, consult banner.
function MobileArchive({ cats, packs, error, good, onOpen }: { cats: Cat[]; packs: PackDetail[] | null; error: string; good: Set<string> | null; onOpen: (c: Cat) => void }) {
  const [i, setI] = useState(0), [ch, setCh] = useState<"wa" | "mail">("wa");
  const all = cats[0]?.packs ?? [];
  const p = all[Math.min(i, Math.max(0, all.length - 1))];
  const pics = p ? packImages(p, good, 3) : [];
  return (
    <div className="flex flex-col gap-4 px-4 pb-28 pt-3 md:hidden">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Link href="/pack-builder" aria-label="بازگشت به پک‌ساز" className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gray-100 text-[#112D46]"><Icon name="arrow_forward" className="!text-[22px]" /></Link>
          <div className="min-w-0"><h1 className="line-clamp-1 text-[17px] font-extrabold text-[#0B1F33]">کاتالوگ آنلاین پک‌های سازمانی</h1><p className="flex items-center gap-1 text-[11px] text-gray-500"><span className="h-1.5 w-1.5 rounded-full bg-[#034EA2]" />نسخه زنده از پک‌های منتشرشده</p></div>
        </div>
        {all.length > 0 && <span className="flex shrink-0 items-center gap-1 rounded-full bg-blue-50 px-3 py-1.5 text-[11px] font-bold text-[#112D46]"><Icon name="auto_stories" className="!text-[15px]" />صفحه {toPersianNum(i * 2 + 1)} از {toPersianNum(all.length * 2)}</span>}
      </div>

      {error ? <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>
        : !packs ? <div role="status" aria-label="در حال دریافت" className="h-[460px] animate-pulse rounded-xl bg-white" />
        : !p ? <div className="rounded-xl border border-gray-200 bg-white p-6 text-center text-sm text-gray-600">هنوز پکی منتشر نشده است؛ کاتالوگی برای نمایش وجود ندارد.</div>
        : <section aria-label="پیش‌نمایش کاتالوگ" className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
            <div className="flex items-center justify-between p-3">
              <button type="button" onClick={() => cats[0] && onOpen(cats[0])} aria-label="باز کردن کاتالوگ ورق‌زدنی" className="flex h-8 w-8 items-center justify-center rounded-lg bg-gray-100 text-gray-700"><Icon name="zoom_in" className="!text-[18px]" /></button>
              <span className="flex items-center gap-1.5"><span dir="ltr" className="rounded bg-gray-100 px-2 py-0.5 text-[10px] font-bold text-gray-700">PK-{p.id} :کد</span><span className="rounded-full bg-[#9A3412] px-2.5 py-0.5 text-[10px] font-bold text-white">{p.tier_fa ?? p.kind_fa}</span></span>
            </div>
            <div className="relative mx-3 aspect-[4/3] overflow-hidden rounded-lg border border-gray-200 bg-gray-50">
              {pics.length ? <span className={`absolute inset-0 grid gap-2 bg-white p-3 ${pics.length > 1 ? "grid-cols-3 items-center" : ""}`}>{pics.map((s) => /* eslint-disable-next-line @next/next/no-img-element */ <img key={s} src={s} alt="" className="h-full w-full object-contain" />)}</span>
                : <span className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-gray-400"><Icon name="inventory_2" className="!text-[44px]" /><span className="text-[10px]">تصویر تأییدشده‌ای برای اقلام ثبت نشده</span></span>}
              <button type="button" aria-label="صفحه قبل" disabled={i === 0} onClick={() => setI((x) => x - 1)} className="absolute right-2 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full bg-white shadow disabled:opacity-30"><Icon name="chevron_right" className="!text-[22px]" /></button>
              <button type="button" aria-label="صفحه بعد" disabled={i >= all.length - 1} onClick={() => setI((x) => x + 1)} className="absolute left-2 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full bg-white shadow disabled:opacity-30"><Icon name="chevron_left" className="!text-[22px]" /></button>
              <span className="absolute inset-x-3 bottom-2 h-1 rounded-full bg-gray-200"><span className="block h-1 rounded-full bg-[#034EA2]" style={{ width: `${((i + 1) / all.length) * 100}%` }} /></span>
            </div>
            <div className="flex flex-col gap-3 p-4">
              <div><h2 className="text-base font-extrabold text-[#0B1F33]">{p.title_fa}</h2><p className="mt-0.5 line-clamp-2 text-xs text-gray-500">{p.purpose_fa}</p></div>
              <div className="grid grid-cols-2 gap-2">{p.items.slice(0, 4).map((it) => <span key={it.master_product_id} className="flex items-center gap-1.5 rounded-lg bg-gray-50 px-2 py-2 text-[11px] text-gray-700"><Icon name="check_circle" className="!text-[15px] text-[#034EA2]" /><span className="line-clamp-1">{it.title_fa}</span></span>)}</div>
              <div className="flex items-center justify-between rounded-lg bg-blue-50 px-3 py-2.5 text-[11px]"><span className="flex items-center gap-1 text-gray-600"><Icon name="inventory_2" className="!text-[15px]" />حداقل تیراژ: {toPersianNum(Math.max(1, p.min_order_qty))} عدد</span><span className="flex items-center gap-1 font-bold text-[#034EA2]"><Icon name="request_quote" className="!text-[15px]" />{p.price_minor != null ? "قیمت‌دار" : "پس از استعلام"}</span></div>
              <Link href={`/pack-builder?pack=${encodeURIComponent(p.slug)}`} className="flex h-12 items-center justify-center gap-2 rounded-xl bg-[#034EA2] text-sm font-bold text-white"><Icon name="library_add" className="!text-[18px]" />افزودن این پک به پک‌ساز ۶۰</Link>
            </div>
          </section>}

      <section aria-labelledby="m-send" className="flex flex-col gap-3 rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-[#034EA2]"><Icon name="send" className="!text-[20px]" /></span>
          <div><h2 id="m-send" className="flex items-center gap-2 text-[15px] font-extrabold text-[#0B1F33]">ارسال خودکار کاتالوگ <Soon /></h2><p className="text-[11px] leading-5 text-gray-500">ارسال خودکار PDF هنوز فعال نشده است؛ از «اشتراک‌گذاری» داخل کاتالوگ استفاده کنید.</p></div>
        </div>
        <div className="grid grid-cols-2 gap-1 rounded-lg bg-gray-100 p-1 text-xs font-bold">
          {([["wa", "ارسال به واتساپ", "chat"], ["mail", "ارسال به ایمیل", "mail"]] as const).map(([k, l, ic]) => <button key={k} type="button" aria-pressed={ch === k} onClick={() => setCh(k)} className={`flex items-center justify-center gap-1.5 rounded-md py-2 ${ch === k ? "bg-white text-[#0B1F33] shadow-sm" : "text-gray-500"}`}><Icon name={ic} className="!text-[16px]" />{l}</button>)}
        </div>
        <fieldset disabled className="flex flex-col gap-3">
          {([["نام سازمان یا شرکت", "corporate_fare", "نام سازمان"], ["نام و نام خانوادگی مسئول", "badge", "مسئول خرید یا رفاهیات"], ch === "wa" ? ["شماره تماس (واتساپ فعال)", "call", "۰۹xxxxxxxxx"] : ["آدرس پست الکترونیکی", "alternate_email", "procurement@example.ir"]] as const).map(([l, ic, ph]) => (
            <label key={l} className="flex flex-col gap-1"><span className="text-[11px] font-bold text-gray-700">{l}</span><span className="relative"><Icon name={ic} className="absolute right-3 top-1/2 -translate-y-1/2 !text-[18px] text-gray-400" /><input placeholder={ph} className="h-11 w-full rounded-lg border border-gray-200 bg-gray-50 pr-10 text-sm placeholder:text-gray-400" /></span></label>
          ))}
          <button type="button" className="flex h-12 cursor-not-allowed items-center justify-center gap-2 rounded-xl bg-[#034EA2]/40 text-sm font-bold text-white"><Icon name="send_time_extension" className="!text-[18px]" />ارسال آنی کاتالوگ PDF</button>
        </fieldset>
      </section>

      <section aria-labelledby="m-arch" className="flex flex-col gap-2.5">
        <div className="flex items-center justify-between"><h2 id="m-arch" className="flex items-center gap-1.5 text-[15px] font-extrabold text-[#0B1F33]"><Icon name="folder_special" className="!text-[18px] text-[#034EA2]" />آرشیو کاتالوگ‌های فصلی</h2><span className="text-[11px] text-gray-500">{toPersianNum(cats.length)} نسخه زنده</span></div>
        {cats.map((c) => (
          <div key={c.key || "all"} className="flex items-center gap-3 rounded-xl border border-gray-200 bg-white p-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-[#034EA2]"><Icon name="menu_book" className="!text-[22px]" /></span>
            <span className="min-w-0 flex-1"><b className="line-clamp-1 block text-[13px] text-[#0B1F33]">{c.title}</b><span className="line-clamp-1 text-[11px] text-gray-500">{toPersianNum(c.packs.length)} پک · {toPersianNum(c.packs.length * 2)} صفحه</span></span>
            <button type="button" disabled title="فایل PDF هنوز منتشر نشده است" aria-label="دانلود PDF (به‌زودی)" className="flex h-9 w-9 items-center justify-center rounded-lg border border-gray-200 text-gray-300"><Icon name="download" className="!text-[18px]" /></button>
            <button type="button" onClick={() => onOpen(c)} aria-label={`مشاهده ${c.title}`} className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-[#034EA2]"><Icon name="visibility" className="!text-[18px]" /></button>
          </div>
        ))}
      </section>

      <div className="flex items-center justify-between gap-3 rounded-xl bg-blue-50 p-3">
        <span className="flex items-center gap-2"><Icon name="support_agent" className="!text-[22px] text-[#034EA2]" /><span><b className="block text-[13px] text-[#0B1F33]">سؤال درباره پک‌ها دارید؟</b><span className="text-[11px] text-gray-500">مشاوره تدارکات سازمانی</span></span></span>
        <Link href="/contact" className="shrink-0 rounded-lg bg-[#034EA2] px-3 py-2 text-[11px] font-bold text-white">تماس با ما</Link>
      </div>
    </div>
  );
}
