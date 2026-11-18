"use client";
// Hero of /pack-builder (Stitch 62/63): soft mint panel, short title, one line of copy and the 60AI input.
// The input only fills the Budget Builder; the suggestion is built by the real backend from the catalog.
import { useState } from "react";
import Link from "next/link";
import { Sparkles, ShieldCheck, MessageSquareText } from "lucide-react";
import { parsePackIntent, type PackIntent } from "./pack-intent";
import { btnPrimary } from "./studio-ui";

export function StudioHero({ onIntent }: { onIntent: (intent: PackIntent) => void }) {
  const [text, setText] = useState("");
  const [hint, setHint] = useState("");
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
  return (
    <section aria-labelledby="pack-studio-title" className="relative overflow-hidden rounded-xl border border-[#E0EBE2] bg-[#EDF3EE] p-5 shadow-[0_1px_2px_rgba(17,24,39,0.04)] md:p-8 lg:p-10">
      <div className="grid gap-6 lg:grid-cols-12 lg:items-center">
        <div className="lg:col-span-7">
          <p className="mb-3 inline-flex items-center gap-1.5 rounded-full bg-white/80 px-3 py-1 text-[11px] font-bold text-[#112D46] md:text-xs">
            <ShieldCheck className="h-4 w-4 text-[#034EA2]" strokeWidth={1.75} aria-hidden /> پک‌های معیشتی و مناسبتی · سفارش عمده سازمان‌ها
          </p>
          <h1 id="pack-studio-title" tabIndex={-1} className="text-[22px] font-extrabold leading-[1.6] text-[#112D46] outline-none md:text-3xl md:leading-[1.5]">
            از یک ترکیب خوب، یک پک مناسب بسازید
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-7 text-[#4B5563]">
            پک آماده، بر اساس بودجه یا انتخاب دستی؛ قیمت نهایی و ارسال با استعلام تأیید می‌شود.
          </p>
        </div>
        <form onSubmit={submit} className="lg:col-span-5" aria-label="دستیار هوشمند 60AI">
          <div className="rounded-xl border border-white bg-white/90 p-3 shadow-[0_4px_16px_rgba(17,45,70,0.06)] md:p-4">
            <label htmlFor="pack-ai-input" className="mb-2 flex items-center gap-1.5 text-xs font-bold text-[#112D46]">
              <Sparkles className="h-4 w-4 text-[#034EA2]" strokeWidth={1.75} aria-hidden /> دستیار هوشمند 60AI
            </label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input id="pack-ai-input" value={text} onChange={(e) => setText(e.target.value)} maxLength={300}
                placeholder="مثال: پک معیشتی ۵۰۰ نفره، هر پک تا ۱٫۵ میلیون"
                className="h-11 min-w-0 flex-1 rounded-xl border border-[#E5E7EB] bg-white px-3 text-sm placeholder:text-[#9CA3AF] focus:border-[#034EA2] focus:outline-none focus:ring-4 focus:ring-[#034EA2]/10" />
              <button type="submit" className={btnPrimary}><Sparkles className="h-4 w-4" strokeWidth={1.75} aria-hidden /> پیشنهاد پک</button>
            </div>
            {hint ? <p role="status" className="mt-2 text-xs leading-6 text-[#92400E]">{hint}</p>
              : <p className="mt-2 text-[11px] leading-6 text-[#6B7280]">پیشنهاد فقط از کالاهای واقعی کاتالوگ ساخته می‌شود.</p>}
            <Link href="/assistant" className="mt-1 inline-flex min-h-9 items-center gap-1 text-xs font-bold text-[#034EA2] hover:underline">
              <MessageSquareText className="h-4 w-4" strokeWidth={1.75} aria-hidden /> گفتگوی کامل با 60AI
            </Link>
          </div>
        </form>
      </div>
    </section>
  );
}
