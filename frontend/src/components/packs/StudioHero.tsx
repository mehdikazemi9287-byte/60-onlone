"use client";
// Hero of /pack-builder — Stitch 62 (desktop: mint panel, badge, title, copy, 60AI input + navy button) and
// Stitch 63 (mobile: compact mint panel with a collapsible 60AI drawer: occasion + head-count).
// The assistant only fills the Budget Builder; the suggestion itself is built by the real backend.
import { useState } from "react";
import { parsePackIntent, type PackIntent } from "./pack-intent";
import { OCCASIONS } from "./BudgetBuilder";
import { Icon } from "./studio-ui";

export function StudioHero({ onIntent }: { onIntent: (intent: PackIntent) => void }) {
  const [text, setText] = useState("");
  const [hint, setHint] = useState("");
  const [drawer, setDrawer] = useState(false);
  const [occasion, setOccasion] = useState("livelihood");
  const [people, setPeople] = useState("");
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const intent = parsePackIntent(text);
    if (!intent.people && !intent.budgetToman && !intent.occasion) {
      setHint("نوع پک، تعداد و بودجه هر پک را بنویسید؛ مثلاً «پک معیشتی ۲۰۰ نفره، هر پک ۲ میلیون».");
      return;
    }
    setHint(!intent.budgetToman ? "بودجه هر پک مشخص نشد؛ آن را در فرم بودجه وارد کنید." : "");
    onIntent(intent);
  };
  const submitMobile = () => {
    const n = Number(people.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))));
    onIntent({ occasion, people: Number.isInteger(n) && n > 0 && n <= 100000 ? n : null, budgetToman: null });
  };
  return (
    <>
      {/* Desktop / tablet — Stitch 62 */}
      <section aria-labelledby="pack-studio-title" className="relative hidden overflow-hidden rounded-xl border border-[#E0EBE2] bg-[#EDF3EE] p-8 shadow-sm md:block lg:p-10">
        <div className="relative z-10 flex max-w-3xl flex-col gap-4">
          <div className="inline-flex w-fit items-center gap-2 rounded-full border border-[#D5E4D8] bg-white/80 px-3 py-1 text-xs font-bold text-[#034EA2]">
            <Icon name="verified_user" className="!text-[14px]" />
            <span>تدارکات سازمانی B2B شصت‌آنلاین · فقط کالاهای واقعی کاتالوگ</span>
          </div>
          <h1 id="pack-studio-title" tabIndex={-1} className="text-2xl font-extrabold leading-snug text-[#112D46] outline-none lg:text-3xl">از یک ترکیب خوب، یک پک مناسب بسازید</h1>
          <p className="max-w-2xl text-sm font-normal leading-relaxed text-gray-600 lg:text-base">
            طراحی و سفارش پک‌های سازمانی، معیشتی و مناسبتی از کالاهای واقعی شصت‌آنلاین؛ پک آماده، بر اساس بودجه یا انتخاب دستی — قیمت نهایی و شرایط ارسال با استعلام و پیش‌فاکتور تأیید می‌شود.
          </p>
          <form onSubmit={submit} aria-label="دستیار هوشمند 60AI" className="mt-3 flex flex-wrap items-center gap-3">
            <div className="relative flex min-w-[280px] max-w-md flex-1 items-center">
              <Icon name="bolt" className="absolute right-3.5 !text-[16px] text-[#034EA2]" />
              <label htmlFor="pack-ai-input" className="sr-only">درخواست پک به زبان ساده</label>
              <input id="pack-ai-input" value={text} onChange={(e) => setText(e.target.value)} maxLength={300}
                placeholder="مثال: پک معیشتی ۵۰۰ نفره تا سقف ۱.۵ میلیون تومان..."
                className="h-11 w-full rounded-xl border border-gray-200 bg-white pl-4 pr-10 text-xs text-gray-900 placeholder:text-gray-400 focus:border-[#034EA2] focus:outline-none" />
            </div>
            <button type="submit" className="flex h-11 shrink-0 items-center gap-2 rounded-xl bg-[#112D46] px-5 text-xs font-bold text-white transition hover:bg-[#0A1C2C]">
              <span>پیشنهاد هوشمند 60AI</span><Icon name="chevron_left" className="!text-[16px]" />
            </button>
          </form>
          {hint && <p role="status" className="text-xs leading-6 text-[#92400E]">{hint}</p>}
        </div>
      </section>

      {/* Mobile — Stitch 63 */}
      <section aria-labelledby="pack-studio-title-m" className="flex flex-col gap-3 rounded-xl border border-[#D6E5D8] bg-[#EDF3EE] p-4 shadow-sm md:hidden">
        <div className="flex items-center gap-1.5 self-start rounded-full border border-[#C4DCCE] bg-white/90 px-2.5 py-1">
          <Icon name="verified" fill className="!text-[15px] text-[#034EA2]" />
          <span className="text-[11px] font-bold text-[#034EA2]">تأمین سازمانی از کالاهای واقعی</span>
        </div>
        <div>
          <h1 id="pack-studio-title-m" className="text-[19px] font-extrabold leading-snug text-[#112D46]">از یک ترکیب خوب، یک پک مناسب بسازید</h1>
          <p className="mt-1 text-[12px] leading-relaxed text-gray-600">پک آماده، بر اساس بودجه یا دستی؛ قیمت نهایی با استعلام</p>
        </div>
        <div className="pt-1">
          <button type="button" aria-expanded={drawer} aria-controls="ai-drawer" onClick={() => setDrawer((x) => !x)}
            className="flex w-full items-center justify-between rounded-xl border border-gray-200/90 bg-white p-3 transition-colors hover:bg-gray-50">
            <span className="flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#034EA2] text-white"><Icon name="smart_toy" className="!text-[18px]" /></span>
              <span className="text-right">
                <span className="block text-[13px] font-bold text-[#112D46]">دستیار هوشمند 60AI</span>
                <span className="block text-[11px] font-medium text-gray-500">پیشنهاد سریع ترکیب اقلام بر اساس بودجه</span>
              </span>
            </span>
            <Icon name="expand_more" className={`!text-[20px] text-gray-400 transition-transform ${drawer ? "rotate-180" : ""}`} />
          </button>
          {drawer && (
            <div id="ai-drawer" className="mt-2 flex flex-col gap-2.5 rounded-xl border border-gray-200 bg-white p-3">
              <div className="grid grid-cols-2 gap-2">
                <label className="block">
                  <span className="mb-1 block text-[10px] font-bold text-gray-500">نوع مناسبت</span>
                  <select value={occasion} onChange={(e) => setOccasion(e.target.value)} className="h-8 w-full rounded-lg border border-gray-200 bg-[#F9F9F9] px-2 text-[11px] text-[#112D46]">
                    {OCCASIONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1 block text-[10px] font-bold text-gray-500">تعداد پرسنل (تیراژ)</span>
                  <input inputMode="numeric" value={people} onChange={(e) => setPeople(e.target.value)} placeholder="مثلاً ۲۰۰"
                    className="h-8 w-full rounded-lg border border-gray-200 bg-[#F9F9F9] px-2 text-[11px] text-[#112D46] placeholder:text-gray-400" />
                </label>
              </div>
              <button type="button" onClick={submitMobile} className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-[#112D46] px-3 py-2 text-[12px] font-bold text-white transition-colors active:bg-[#034EA2]">
                <Icon name="auto_awesome" className="!text-[16px]" /><span>تولید چیدمان هوشمند پک</span>
              </button>
            </div>
          )}
        </div>
      </section>
    </>
  );
}
