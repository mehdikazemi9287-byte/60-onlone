"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Sparkles, Send, ShoppingBag, Info, ArrowLeft, ClipboardList, LogIn } from "lucide-react";
import { useAuth } from "@/lib/auth-context";

type DraftItem = { slug: string; title: string; categoryName: string; priceMinor: number | null; quantity: number; imageUrl: string | null };
type PackDraft = {
  constraints: { recipientCount: number | null; perPersonToman: number | null; totalToman: number | null; tier: string | null; purposeLabel: string | null };
  effPerPersonToman: number | null; effTotalToman: number | null;
  items: DraftItem[]; pricedCount: number; unpricedCount: number;
  needsPriceConfirmation: boolean; totalMinor: number | null;
  explanation: string[]; followUps: string[];
  alternatives: { slug: string; title: string; priceMinor: number | null; note: string }[];
};
type Match = { product: { slug: string; title: string; brand: string | null; categoryName: string; price: number | null; priceStatus: "verified" | "unpriced"; purchaseStatus: "purchasable" | "inquiry-only" | "unavailable" }; reasons: string[] };
type AccountItem = { kind: "order" | "personal_request" | "org_case"; ref: string; title: string; statusFa: string; nextAction: string | null; owner: string | null; detail: string | null; href: string };
type Account = { signedIn: boolean; user: { name: string | null; role: string } | null; orgs: { id: number; name: string; role: string }[]; items: AccountItem[]; notes: string[] };
type Turn = { role: "user" | "assistant"; text?: string; draft?: PackDraft; matches?: Match[]; note?: string | null; account?: Account; query?: string };

// Conversation survives refresh/re-entry in this tab. Account answers are NOT stored (they are re-asked live),
// so another user on a shared device never sees a previous user's orders.
const TURNS_KEY = "60o_assistant_turns";
const PACK_DRAFT_KEY = "60o_pack_builder_draft";
// A pack draft is shown only for pack questions (pack words, head count or budget); a plain product question
// ("برنج طبیعت") gets the matching store products instead of an unrequested pack.
const isPackQuestion = (q: string, d: PackDraft) =>
  /(پک|بسته|سبد|هدیه|کادو)/.test(q) || !!(d.constraints.purposeLabel || d.constraints.recipientCount || d.constraints.perPersonToman || d.constraints.totalToman);
const KIND_FA: Record<AccountItem["kind"], string> = { order: "سفارش", personal_request: "استعلام شخصی", org_case: "پرونده سازمانی" };

const EXAMPLES = [
  "پک معیشتی برای ۳۰ نفر، بودجه کل ۴۵ میلیون تومان",
  "پک متعادل برای ۵۰ نفر، نفری ۲ میلیون تومان",
  "پک هدیه برای ۲۰ نفر، برای هر نفر حداکثر ۱.۵ میلیون",
  "پک اقتصادی آجیل و خشکبار برای ۱۰ نفر",
  "برنج طبیعت",
  "وضعیت سفارش‌های من",
  "وضعیت پرونده سازمانی من",
];
const REVISE_HINTS = ["بودجه کل را به ۶۰ میلیون تغییر بده", "تعداد نفرات را به ۴۰ نفر برسان", "لبنیات را حذف کن", "آجیل هم اضافه کن", "پک باکیفیت‌تر بده"];

const fmt = (m: number) => Math.round(m / 10).toLocaleString("fa-IR") + " تومان";

export function AssistantClient() {
  const router = useRouter();
  const { token } = useAuth();
  const [confirmReplace, setConfirmReplace] = useState<PackDraft | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Homepage 60AI hands a question over with ?q=; ask it once on arrival.
  useEffect(() => {
    try { const saved = JSON.parse(sessionStorage.getItem(TURNS_KEY) || "[]"); if (Array.isArray(saved) && saved.length) setTurns(saved); } catch { /* ignore */ }
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) {
      setInput(q); void ask(q);
      // Ask once: a refresh must not resend the homepage question.
      try { const u = new URL(window.location.href); u.searchParams.delete("q"); window.history.replaceState(null, "", u.pathname + u.search); } catch { /* ignore */ }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
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
      let tk = token;
      if (!tk) { try { tk = localStorage.getItem("60online_token"); } catch { /* ignore */ } }
      const r = await fetch("/api/assistant?q=" + encodeURIComponent(full), { cache: "no-store", headers: tk ? { Authorization: `Bearer ${tk}` } : {} });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "خطا در دستیار");
      if (data.intent === "account") {
        setTurns((t) => [...t, { role: "assistant", account: data.account, query: q }]);
      } else {
        lastDraft.current = data.packDraft;
        const pack = isPackQuestion(q, data.packDraft);
        setTurns((t) => [...t, { role: "assistant", draft: pack ? data.packDraft : { ...data.packDraft, items: [], alternatives: [], explanation: [], followUps: [] },
          matches: pack ? [] : (data.matches ?? []).slice(0, 6), note: data.note ?? null, query: q }]);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "خطا در دستیار");
    } finally { setLoading(false); }
  }

  useEffect(() => {
    // Persist the conversation (without account answers) for refresh/re-entry.
    try { sessionStorage.setItem(TURNS_KEY, JSON.stringify(turns.filter((t) => !t.account).slice(-20))); } catch { /* ignore */ }
  }, [turns]);

  // Hand the draft to THE pack builder (/pack-builder) as its saved draft. Prices and stock are NOT carried over:
  // the builder re-prices every line from the live storefront on resume, so nothing stale is shown as current.
  function transferToPackBuilder(d: PackDraft, replace = false) {
    let existing = false;
    try { existing = !!localStorage.getItem(PACK_DRAFT_KEY); } catch { /* ignore */ }
    if (existing && !replace) { setConfirmReplace(d); return; }
    try {
      localStorage.setItem(PACK_DRAFT_KEY, JSON.stringify({
        items: d.items.map((i) => ({ slug: i.slug, title: i.title, priceMinor: null, quantity: i.quantity, imageUrl: i.imageUrl })),
      }));
    } catch { setErr("ذخیره پیش‌نویس در این مرورگر ممکن نیست"); return; }
    setConfirmReplace(null);
    router.push("/pack-builder?mode=edit");
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
      {confirmReplace && (
        <div role="alertdialog" aria-label="جایگزینی پیش‌نویس" className="card border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          <p>در پک‌ساز یک پیش‌نویس ذخیره‌شده دارید. با انتقال این پک، آن پیش‌نویس جایگزین می‌شود.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" onClick={() => transferToPackBuilder(confirmReplace, true)} className="rounded-xl bg-brand-navy px-4 py-2 text-xs font-bold text-white">جایگزین کن و ادامه بده</button>
            <Link href="/pack-builder" className="rounded-xl border border-brand-navy px-4 py-2 text-xs font-bold text-brand-navy">ادامه پیش‌نویس قبلی</Link>
            <button type="button" onClick={() => setConfirmReplace(null)} className="px-2 text-xs font-bold text-neutral-600">انصراف</button>
          </div>
        </div>)}

      <div className="space-y-3">
        {turns.map((t, i) => t.role === "user" ? (
          <div key={i} className="mr-auto max-w-[85%] rounded-2xl rounded-tr-sm bg-primary-700 px-4 py-2 text-sm text-white">{t.text}</div>
        ) : t.account ? (
          <AccountAnswer key={i} a={t.account} query={t.query ?? ""} />
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

            {/* real storefront products for a plain product question */}
            {t.draft.items.length === 0 && !!t.matches?.length && (
              <div className="card p-3" aria-label="کالاهای پیدا شده">
                <p className="mb-2 text-sm font-bold text-neutral-800">کالاهای موجود در فروشگاه ({t.matches.length.toLocaleString("fa-IR")})</p>
                <ul className="divide-y divide-neutral-100">
                  {t.matches.map((m) => (
                    <li key={m.product.slug} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                      <Link href={`/products/${m.product.slug}`} className="min-w-0 flex-1 truncate font-bold text-brand-navy hover:text-brand-blue">{m.product.title}
                        <span className="mr-1 text-2xs font-normal text-neutral-400">· {m.product.brand ? `${m.product.brand} · ` : ""}{m.product.categoryName}</span></Link>
                      <span className="shrink-0 text-2xs">{m.product.priceStatus === "verified" && m.product.price != null
                        ? <>{fmt(m.product.price)}{m.product.purchaseStatus !== "purchasable" && <span className="mr-1 text-amber-700">(فعلاً قابل خرید آنلاین نیست)</span>}</>
                        : <Link href={`/requests/new?q=${encodeURIComponent(m.product.title)}`} className="font-bold text-amber-700 underline">استعلام قیمت</Link>}</span>
                    </li>))}
                </ul>
                <p className="mt-2 text-2xs text-neutral-500">جایگزین‌ها و کالاهای مرتبط هر کالا در صفحه همان کالا آمده است.</p>
              </div>
            )}
            {t.draft.items.length === 0 && !t.matches?.length && (
              <p className="rounded-xl border border-neutral-200 bg-white p-3 text-xs text-neutral-600">کالایی با این مشخصات در فروشگاه پیدا نشد. <Link href={`/search?q=${encodeURIComponent(t.query ?? "")}`} className="font-bold text-brand-blue">جستجوی کامل</Link> یا <Link href={`/requests/new?q=${encodeURIComponent(t.query ?? "")}`} className="font-bold text-brand-blue">ثبت درخواست تأمین</Link></p>
            )}

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
                  {t.draft.alternatives.map((a) => <li key={a.slug} className="flex justify-between gap-2"><Link href={`/products/${a.slug}`} className="truncate hover:text-brand-blue">{a.title}</Link><span className="shrink-0 text-neutral-500">{a.note}</span></li>)}
                </ul>
              </div>
            )}

            <NextSteps query={t.query ?? ""} />

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
        این دستیار قاعده‌محور است و فقط از کاتالوگ واقعی فروشگاه و سوابق خود شما استفاده می‌کند. هیچ کالا، قیمت، موجودی، تأمین‌کننده یا وضعیت ساختگی تولید نمی‌شود و دستیار هیچ اقدامی (ثبت، تأیید، پرداخت یا لغو) را به‌جای شما انجام نمی‌دهد.
        پک‌های خودکارِ بودجه‌محور فقط از کالاهای دارای قیمت رسمی ساخته می‌شوند؛ کالای بدون قیمت با برچسب «استعلام قیمت» می‌ماند.
        ویرایش نهایی، تعداد، سبد و پیش‌فاکتور در <Link href="/pack-builder" className="text-primary-700 underline">پک‌ساز <ArrowLeft className="inline h-3 w-3" /></Link> انجام می‌شود.
      </p>
    </div>
  );
}

function NextSteps({ query }: { query: string }) {
  const q = encodeURIComponent(query);
  return (
    <div className="flex flex-wrap gap-2 text-xs" aria-label="اقدام بعدی">
      <Link href={`/search?q=${q}`} className="rounded-full border border-neutral-200 bg-white px-3 py-1.5 font-bold text-neutral-700 hover:border-brand-blue">جستجو در فروشگاه</Link>
      <Link href={`/requests/new?q=${q}`} className="rounded-full border border-neutral-200 bg-white px-3 py-1.5 font-bold text-neutral-700 hover:border-brand-blue">درخواست شخصی / استعلام</Link>
      <Link href="/organization/compose" className="rounded-full border border-neutral-200 bg-white px-3 py-1.5 font-bold text-neutral-700 hover:border-brand-blue">درخواست سازمانی</Link>
    </div>
  );
}

function AccountAnswer({ a, query }: { a: Account; query: string }) {
  return (
    <div className="ml-auto w-full max-w-[95%] space-y-2" aria-label="وضعیت حساب">
      {!a.signedIn ? (
        <div className="card flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
          <span>{a.notes[0] ?? "برای دیدن وضعیت، وارد حساب شوید."}</span>
          <Link href={`/login?next=${encodeURIComponent("/assistant?q=" + query)}`} className="inline-flex items-center gap-1 rounded-xl bg-brand-navy px-3 py-2 text-xs font-bold text-white"><LogIn className="h-3.5 w-3.5" /> ورود</Link>
        </div>
      ) : (
        <div className="card p-3 text-sm">
          <p className="mb-2 flex items-center gap-1.5 font-bold text-neutral-800"><ClipboardList className="h-4 w-4" />
            وضعیت سوابق شما{a.orgs.length ? <span className="text-2xs font-normal text-neutral-500"> · {a.orgs.map((o) => `${o.name} (${o.role})`).join("، ")}</span> : null}</p>
          {a.items.length > 0 && <ul className="divide-y divide-neutral-100">{a.items.map((it) => (
            <li key={it.kind + it.ref} className="py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Link href={it.href} className="min-w-0 truncate font-bold text-brand-navy hover:text-brand-blue">{KIND_FA[it.kind]} {it.ref} — {it.title}</Link>
                <span className="shrink-0 rounded-full bg-neutral-100 px-2 py-0.5 text-2xs font-bold">{it.statusFa}</span>
              </div>
              {it.detail && <p className="mt-0.5 text-2xs text-neutral-500">{it.detail}</p>}
              {it.nextAction && <p className="mt-0.5 text-xs">اقدام بعدی: <b>{it.nextAction}</b>{it.owner ? <span className="text-neutral-500"> · مسئول: {it.owner}</span> : null}</p>}
            </li>))}</ul>}
          {a.notes.map((n, k) => <p key={k} className="mt-1 text-xs text-neutral-600">{n}</p>)}
          <p className="mt-2 text-2xs text-neutral-400">این اطلاعات مستقیم از سوابق شما خوانده شده و دستیار تغییری در آن‌ها نمی‌دهد. برای هر اقدام، صفحه همان مورد را باز کنید.</p>
        </div>
      )}
    </div>
  );
}
