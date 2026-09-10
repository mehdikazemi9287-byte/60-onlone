"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Sparkles, Send, ShoppingBag, Info, ArrowLeft } from "lucide-react";

type DraftItem = { slug: string; title: string; categoryName: string; priceMinor: number | null; quantity: number; imageUrl: string | null };
type PackDraft = {
  constraints: { recipientCount: number | null; perPersonToman: number | null; totalToman: number | null; tier: string | null; purposeLabel: string | null };
  effPerPersonToman: number | null; effTotalToman: number | null;
  items: DraftItem[]; pricedCount: number; unpricedCount: number;
  needsPriceConfirmation: boolean; totalMinor: number | null;
  explanation: string[]; followUps: string[];
  alternatives: { slug: string; title: string; priceMinor: number | null; note: string }[];
};
type Turn = { role: "user" | "assistant"; text?: string; draft?: PackDraft };

const EXAMPLES = [
  "پک معیشتی برای ۳۰ نفر، بودجه کل ۴۵ میلیون تومان",
  "پک متعادل برای ۵۰ نفر، نفری ۲ میلیون تومان",
  "پک هدیه برای ۲۰ نفر، برای هر نفر حداکثر ۱.۵ میلیون",
  "پک اقتصادی آجیل و خشکبار برای ۱۰ نفر",
];
const REVISE_HINTS = ["بودجه کل را به ۶۰ میلیون تغییر بده", "تعداد نفرات را به ۴۰ نفر برسان", "لبنیات را حذف کن", "آجیل هم اضافه کن", "پک باکیفیت‌تر بده"];

const fmt = (m: number) => Math.round(m / 10).toLocaleString("fa-IR") + " تومان";

export function AssistantClient() {
  const router = useRouter();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const lastDraft = useRef<PackDraft | null>(null);

  async function ask(qRaw: string) {
    const q = qRaw.trim();
    if (!q) return;
    // carry prior constraints forward so revisions ("بودجه را ... تغییر بده") work
    const prior = lastDraft.current?.constraints;
    const carry = prior
      ? [
          prior.purposeLabel && !/(معیشتی|هدیه|مناسبتی|سازمانی|شرکتی|مدرسه|خانه)/.test(q) ? `پک ${prior.purposeLabel}` : "",
          prior.recipientCount && !/\d+\s*نفر/.test(q) ? `برای ${prior.recipientCount} نفر` : "",
          prior.perPersonToman && !/نفری|هر\s*نفر|بودجه/.test(q) ? `نفری ${prior.perPersonToman} تومان` : "",
          prior.totalToman && !/بودجه\s*کل|کل\s*بودجه|بودجه/.test(q) ? `بودجه کل ${prior.totalToman} تومان` : "",
        ].filter(Boolean).join("، ")
      : "";
    const full = carry ? `${q}، ${carry}` : q;

    setTurns((t) => [...t, { role: "user", text: q }]);
    setInput(""); setLoading(true); setErr(null);
    try {
      const r = await fetch("/api/assistant?q=" + encodeURIComponent(full), { cache: "no-store" });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "خطا در دستیار");
      lastDraft.current = data.packDraft;
      setTurns((t) => [...t, { role: "assistant", draft: data.packDraft }]);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "خطا در دستیار");
    } finally { setLoading(false); }
  }

  function transferToPackBuilder(d: PackDraft) {
    try {
      sessionStorage.setItem("60o_pack_draft", JSON.stringify({
        items: d.items.map((i) => ({ slug: i.slug, title: i.title, priceMinor: i.priceMinor, quantity: i.quantity, categoryName: i.categoryName, imageUrl: i.imageUrl })),
        perPersonToman: d.effPerPersonToman, recipientCount: d.constraints.recipientCount,
      }));
    } catch { /* ignore */ }
    router.push("/#pack-builder");
  }

  return (
    <div className="space-y-4">
      <form onSubmit={(e) => { e.preventDefault(); ask(input); }} className="card flex items-end gap-2 p-3">
        <div className="flex flex-1 items-start gap-2">
          <Sparkles className="mt-2.5 h-5 w-5 shrink-0 text-amber-500" />
          <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={2}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input); } }}
            placeholder="نیازتان را بنویسید: نوع پک، تعداد نفرات، بودجه (کل یا نفری)، سطح کیفیت…"
            className="min-h-11 w-full resize-none bg-transparent py-2 text-sm outline-none" />
        </div>
        <button type="submit" disabled={loading}
          className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-xl bg-primary-700 px-4 text-sm font-bold text-white disabled:opacity-60">
          <Send className="h-4 w-4" />{loading ? "…" : "بپرس"}
        </button>
      </form>

      {turns.length === 0 && (
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button key={ex} onClick={() => ask(ex)} className="rounded-full border border-neutral-200 bg-white px-3 py-1.5 text-xs text-neutral-600 hover:border-primary-300">{ex}</button>
          ))}
        </div>
      )}
      {err && <div role="alert" className="card border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}

      <div className="space-y-3">
        {turns.map((t, i) => t.role === "user" ? (
          <div key={i} className="mr-auto max-w-[85%] rounded-2xl rounded-tr-sm bg-primary-700 px-4 py-2 text-sm text-white">{t.text}</div>
        ) : t.draft ? (
          <div key={i} className="ml-auto w-full max-w-[95%] space-y-3">
            {/* extracted constraints */}
            <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-3 text-xs leading-6 text-neutral-600">
              <p className="mb-1 font-bold text-neutral-800">آنچه از درخواست شما فهمیدم:</p>
              <ul className="flex flex-wrap gap-x-4">
                {t.draft.constraints.purposeLabel && <li>نوع: <b>{t.draft.constraints.purposeLabel}</b></li>}
                {t.draft.constraints.tier && <li>سطح: <b>{t.draft.constraints.tier === "economic" ? "اقتصادی" : t.draft.constraints.tier === "premium" ? "باکیفیت" : "متعادل"}</b></li>}
                {t.draft.constraints.recipientCount && <li>نفرات: <b>{t.draft.constraints.recipientCount.toLocaleString("fa-IR")}</b></li>}
                {t.draft.effPerPersonToman && <li>بودجه هر نفر: <b>{t.draft.effPerPersonToman.toLocaleString("fa-IR")}</b> تومان</li>}
                {t.draft.effTotalToman && <li>بودجه کل: <b>{t.draft.effTotalToman.toLocaleString("fa-IR")}</b> تومان</li>}
              </ul>
            </div>

            {/* explanation */}
            {t.draft.explanation.map((e, k) => (
              <p key={k} className="flex items-start gap-2 text-xs leading-6 text-neutral-600"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-neutral-400" />{e}</p>
            ))}

            {/* draft items */}
            {t.draft.items.length > 0 && (
              <div className="card p-3">
                <p className="mb-2 text-sm font-bold text-neutral-800">پیش‌نویس پک ({t.draft.items.length.toLocaleString("fa-IR")} قلم{t.draft.constraints.recipientCount ? ` × ${t.draft.constraints.recipientCount.toLocaleString("fa-IR")} نفر` : ""})</p>
                <ul className="divide-y divide-neutral-100">
                  {t.draft.items.map((it) => (
                    <li key={it.slug} className="flex items-center justify-between gap-2 py-2 text-sm">
                      <span className="min-w-0 truncate">{it.title} <span className="text-2xs text-neutral-400">· {it.categoryName}</span></span>
                      <span className="shrink-0 text-2xs">{it.priceMinor != null ? fmt(it.priceMinor) : <span className="text-amber-600 font-bold">استعلام قیمت</span>}</span>
                    </li>
                  ))}
                </ul>
                <div className="mt-2 flex items-center justify-between border-t border-neutral-100 pt-2 text-sm">
                  <span className="text-neutral-500">جمع کل پک</span>
                  <span className="font-black">
                    {t.draft.totalMinor != null ? fmt(t.draft.totalMinor) : <span className="text-amber-600">نیازمند تأیید قیمت</span>}
                  </span>
                </div>
                {t.draft.unpricedCount > 0 && (
                  <p className="mt-1 text-2xs text-amber-700">{t.draft.unpricedCount.toLocaleString("fa-IR")} قلم بدون قیمت رسمی؛ جمع دقیق پس از «درخواست پیش‌فاکتور» در پک‌ساز مشخص می‌شود.</p>
                )}
                <button onClick={() => transferToPackBuilder(t.draft!)}
                  className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary-700 px-4 py-2.5 text-sm font-bold text-white">
                  <ShoppingBag className="h-4 w-4" /> انتقال این پک به پک‌ساز برای ویرایش و ثبت
                </button>
              </div>
            )}

            {/* alternatives */}
            {t.draft.alternatives.length > 0 && (
              <div className="rounded-xl border border-neutral-200 bg-white p-3 text-xs">
                <p className="mb-1.5 font-bold text-neutral-700">گزینه‌های جایگزین (کالای واقعی):</p>
                <ul className="space-y-1">
                  {t.draft.alternatives.map((a) => <li key={a.slug} className="flex justify-between gap-2"><span className="truncate">{a.title}</span><span className="shrink-0 text-neutral-500">{a.note}</span></li>)}
                </ul>
              </div>
            )}

            {/* follow-ups */}
            {t.draft.followUps.length > 0 && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-6 text-amber-900">
                {t.draft.followUps.map((f, k) => <p key={k}>• {f}</p>)}
              </div>
            )}
          </div>
        ) : null)}
      </div>

      {turns.length > 0 && (
        <div className="flex flex-wrap gap-2 border-t border-neutral-100 pt-3">
          <span className="text-2xs text-neutral-400">اصلاح گفتگو:</span>
          {REVISE_HINTS.map((h) => (
            <button key={h} onClick={() => ask(h)} className="rounded-full border border-neutral-200 bg-white px-2.5 py-1 text-2xs text-neutral-600 hover:border-primary-300">{h}</button>
          ))}
        </div>
      )}

      <p className="text-2xs leading-5 text-neutral-400">
        این دستیار قاعده‌محور است و فقط از کاتالوگ واقعی فروشگاه استفاده می‌کند. هیچ کالا، قیمت، موجودی یا تأمین‌کننده‌ی ساختگی تولید نمی‌شود.
        پک‌های خودکارِ بودجه‌محور فقط از کالاهای دارای قیمت رسمی ساخته می‌شوند؛ کالای بدون قیمت با برچسب «استعلام قیمت» می‌ماند.
        ویرایش نهایی، تعداد، سبد و پیش‌فاکتور در <Link href="/#pack-builder" className="text-primary-700 underline">پک‌ساز <ArrowLeft className="inline h-3 w-3" /></Link> انجام می‌شود.
      </p>
    </div>
  );
}
