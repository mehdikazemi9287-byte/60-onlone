"use client";
import { scopedDraftKey, pendingDraftKey } from "@/lib/client-draft-storage";
import { useAuth } from "@/lib/auth-context";
// The single Pack Builder (/pack-builder), from the final Figma frames 166:221–166:230:
// one builder with three methods (ready pack, budget, manual), then edit → review → buy / quote.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Scale, Package, WalletCards, SlidersHorizontal, Building2 } from "lucide-react";
import { PackBuilderInteractive, type PackDraft } from "@/components/home/PackBuilderInteractive";
import { BudgetBuilder } from "./BudgetBuilder";
import { PackCard, UI, loadPackDetails } from "./PackCard";
import { useGoodImages } from "@/lib/imageQuality";
import { storefront, type PackDetail } from "@/lib/storefront";
import { toPersianNum } from "@/lib/utils";

type Method = "template" | "budget" | "scratch";
const STEPS = ["انتخاب روش", "ساخت پک", "بررسی", "خرید / استعلام"];
const GROUPS: [string, string, (p: PackDetail) => boolean][] = [
  ["", "همه پک‌ها", () => true],
  ["home", "خانه و خانواده", (p) => p.audience === "household" && p.kind !== "occasion"],
  ["gift", "هدیه", (p) => p.audience === "employee_gift"],
  ["occasion", "مناسبت", (p) => p.kind === "occasion" || !!p.occasion],
  ["work", "سازمانی و کارکنان", (p) => ["organization","office","employee_gift"].includes(p.audience)],
];
const TITLES: Record<Method, [string, string]> = {
  template: ["پک‌های پیشنهادی 60Online", "از یک پک آماده شروع کنید یا انتخاب خودتان را بسازید."],
  budget: ["پک متناسب با بودجه شما", "بودجه و تعداد پک را بدهید؛ ترکیب پیشنهادی از کالاهای واقعی کاتالوگ ساخته می‌شود و قابل ویرایش است."],
  scratch: ["پک دلخواه شما", "حذف، افزودن و تغییر تعداد اقلام؛ همه در همین پک"],
};

export function Steps({ active }: { active: number }) {
  return <ol aria-label="مراحل ساخت پک" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
    {STEPS.map((label,i)=><li key={label} aria-current={i===active?"step":undefined} className="flex min-h-14 items-center gap-3 rounded-xl border px-3 py-3 text-xs sm:text-sm" style={{background:i===active?UI.ink:i<active?UI.mint:"#fff",color:i===active?"#fff":UI.ink,borderColor:i===active?UI.ink:UI.line}}><span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-current text-xs font-bold">{toPersianNum(i+1)}</span><span className={i===active?"font-black":"font-medium"}>{label}</span></li>)}
  </ol>;
}

export function PackStudio(){const{user}=useAuth();return <PackStudioBody key={user?.id??"guest"}/>;}
function PackStudioBody() {
  const params = useSearchParams();
  const [method, setMethod] = useState<Method>("template"), [draft, setDraft] = useState<PackDraft | null>(null);
  const [saved, setSaved] = useState<PackDraft | null>(null), [pending, setPending] = useState<PackDraft | null>(null);
  const [packs, setPacks] = useState<PackDetail[] | null>(null), [error, setError] = useState("");
  const [revision, setRevision] = useState(0), [step, setStep] = useState(1), [group, setGroup] = useState(params.get("group") ?? "work");
  const [picked, setPicked] = useState<string[]>([]);
  const readDraft = (raw: string | null): PackDraft | null => { try { const d = JSON.parse(raw ?? "null"); return d && Array.isArray(d.items) && d.items.every((i: { slug?: string; quantity?: number }) => typeof i.slug === "string" && Number.isInteger(i.quantity) && Number(i.quantity) > 0) ? {items: d.items, count: Number.isInteger(d.count) && d.count > 0 && d.count <= 100000 ? d.count : 1} : null; } catch { return null; } };
  const fromPack = (p: PackDetail): PackDraft => ({ count: Math.max(1, p.min_order_qty), items: p.items.filter(i => i.slug).map(i => ({ slug: i.slug!, title: i.title_fa, quantity: i.quantity, imageUrl: i.image_url, priceMinor: null })) });
  useEffect(() => {
    let stored: PackDraft | null = null, handoff: PackDraft | null = null;
    try { stored = readDraft(localStorage.getItem(scopedDraftKey("60o_pack_builder_draft"))); handoff = readDraft(sessionStorage.getItem(scopedDraftKey("60o_pack_draft"))); sessionStorage.removeItem(scopedDraftKey("60o_pack_draft")); } catch { /* unavailable storage */ }
    try { handoff ??= readDraft(localStorage.getItem(pendingDraftKey("60o_pack_builder_draft"))); } catch { /* unavailable storage */ }
    const packSlug = params.get("pack");
    if (packSlug) {
      // "شخصی‌سازی این پک" from a ready-pack page: open that pack's real items in the editor.
      if (stored?.items.length) setSaved(stored);
      storefront.pack(packSlug).then(r => { const next = fromPack(r.pack); if (!next.items.length) return; if (stored?.items.length) { setDraft(stored); setPending(next); } else setDraft(next); })
        .catch(() => setError("دریافت این پک ناموفق بود؛ از فهرست پک‌ها انتخاب کنید."));
      return;
    }
    if (stored?.items.length) { setSaved(stored); setDraft(stored); if (handoff) setPending(handoff); }
    else if (handoff) setDraft(handoff);
    else if (params.get("mode") === "scratch") { setMethod("scratch"); setDraft({items: [], count: 1}); }
    else if (params.get("mode") === "budget") setMethod("budget");
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { let active = true; loadPackDetails().then(p => { if (active) setPacks(p.filter(x => x.items.length)); }).catch(() => { if (active) setError("دریافت پک‌های آماده ناموفق بود. دوباره تلاش کنید."); }); return () => { active = false; }; }, [revision]);
  const open = (next: PackDraft) => { if (saved?.items.length) setPending(next); else { setDraft(next); setRevision(x => x+1); } };
  const back = () => { try { setSaved(readDraft(localStorage.getItem(scopedDraftKey("60o_pack_builder_draft")))); } catch { /* unavailable */ } setDraft(null); setMethod("template"); };
  const filter = GROUPS.find(g => g[0] === group) ?? GROUPS[0];
  const shown = useMemo(() => packs?.filter(filter[2]) ?? null, [packs, filter]);
  const good = useGoodImages((shown ?? []).flatMap(p => p.items.map(i => i.image_url)));
  const toggle = (slug: string) => setPicked(x => x.includes(slug) ? x.filter(s => s !== slug) : x.length >= 4 ? x : [...x, slug]);
  const [title, sub] = draft ? (step >= 2 ? ["بررسی نهایی پک", "اقلام، تعداد و مبلغ را بررسی کنید؛ برای اقلام فاقد قیمت درخواست استعلام ثبت می‌شود."] : TITLES.scratch) : TITLES[method];
  return <div className="space-y-5" dir="rtl">
    <header className="flex flex-col gap-4 rounded-[24px] border p-5 md:flex-row md:items-center md:justify-between md:p-7" style={{background:UI.mint,borderColor:UI.line}}>
      <div><p className="mb-2 flex items-center gap-2 text-xs font-bold" style={{color:UI.muted}}><Building2 size={15}/> پک‌ساز 60Online · برای کارکنان، شعبه‌ها و خانواده</p><h1 id="pack-studio-title" tabIndex={-1} className="text-[26px] font-black leading-[1.65] outline-none md:text-[34px]" style={{color:UI.ink}}>{draft?title:"از یک ترکیب خوب، یک پک مناسب بسازید"}</h1><p className="mt-2 max-w-2xl text-sm leading-7" style={{color:UI.muted}}>{draft?sub:"از پک آماده شروع کنید، سقف بودجه را مشخص کنید یا اقلام را خودتان بچینید. تعداد هر قلم و تعداد پک‌ها جداست؛ قیمت نهایی و امکان ارسال با استعلام تأیید می‌شود."}</p></div>
      <Link href="/business/catalog" className="inline-flex min-h-12 shrink-0 items-center justify-center gap-2 rounded-xl border bg-white px-4 text-xs font-bold" style={{color:UI.ink,borderColor:UI.line}}><Package size={16}/> انتخاب مستقیم از کاتالوگ</Link>
    </header>
    <Link href="/account/packs" className="inline-flex min-h-11 items-center text-sm font-bold text-brand-blue">پک‌های ذخیره‌شده در حساب</Link>
    <Steps active={draft ? step : 0} />
    {pending && <div role="alert" className="rounded-2xl border border-amber-200 bg-amber-50 p-4"><p className="text-sm">یک پک ذخیره‌شده دارید. ترکیب جدید جایگزین آن شود؟</p><div className="mt-3 flex flex-wrap gap-3"><button type="button" className="min-h-11 rounded-xl px-4 text-sm font-bold text-white" style={{ background: UI.ink }} onClick={() => { setDraft(pending); setSaved(null); setPending(null); try { localStorage.removeItem(pendingDraftKey("60o_pack_builder_draft")); } catch { /* unavailable storage */ } setRevision(x => x+1); }}>جایگزینی پک</button><button type="button" className="min-h-11 px-4 text-sm" onClick={() => {setPending(null);try { localStorage.removeItem(pendingDraftKey("60o_pack_builder_draft")); } catch { /* unavailable storage */ }}}>حفظ پک فعلی</button></div></div>}
    {draft ? <PackBuilderInteractive key={revision} draft={draft} onBack={back} onStep={setStep} /> : <>
      {saved?.items.length ? <button type="button" onClick={() => setDraft(saved)} className="min-h-11 text-sm font-bold text-brand-blue">ادامه پک ذخیره‌شده ({toPersianNum(saved.items.length)} نوع کالا)</button> : null}
      <div className="grid gap-3 sm:grid-cols-3" role="tablist" aria-label="روش ساخت پک">{([["template","پک آماده",Package,"ترکیب منتشرشده را انتخاب و شخصی‌سازی کنید"],["budget","بر اساس بودجه",WalletCards,"سقف هزینه هر پک و تعداد پک‌ها را مشخص کنید"],["scratch","انتخاب دستی",SlidersHorizontal,"از کاتالوگ واقعی، اقلام دلخواه را کنار هم بچینید"]] as const).map(([key,label,Icon,description],index)=><button key={key} type="button" role="tab" aria-label={label} aria-selected={method===key} tabIndex={method===key?0:-1} onKeyDown={e=>{const move=e.key==="ArrowRight"?-1:e.key==="ArrowLeft"?1:0; if(move||e.key==="Home"||e.key==="End"){e.preventDefault();const next=e.key==="Home"?0:e.key==="End"?2:(index+move+3)%3;const buttons=e.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('button[role="tab"]');buttons?.[next]?.focus();buttons?.[next]?.click();}}} onClick={()=>{setMethod(key);if(key==="scratch")open({items:[],count:1});}} className="flex min-h-24 items-start gap-3 rounded-2xl border p-4 text-right" style={{background:method===key?UI.ink:"#fff",borderColor:method===key?UI.ink:UI.line,color:method===key?"#fff":UI.ink}}><Icon size={23} className="mt-1 shrink-0"/><span><b className="block text-sm">{label}</b><span className="mt-2 block text-xs leading-6 opacity-80">{description}</span></span></button>)}</div>
      {method === "template" && <>
        <div className="-mx-4 flex gap-2 overflow-x-auto px-4 md:mx-0 md:px-0" aria-label="گروه پک‌ها">{GROUPS.map(([k, l]) => <button key={k} type="button" aria-pressed={group === k} onClick={() => setGroup(k)} className="min-h-11 shrink-0 rounded-xl px-4 text-sm font-bold" style={group === k ? { background: UI.mint, color: UI.ink } : { color: UI.muted }}>{l}</button>)}</div>
        {error && <div role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}<button type="button" className="mr-3 min-h-11 underline" onClick={() => {setError("");setRevision(x => x+1);}}>تلاش دوباره</button></div>}
        {shown === null ? !error && <p role="status" className="py-10 text-center" style={{ color: UI.muted }}>در حال دریافت پک‌ها…</p>
          : !shown.length ? <p className="py-8 text-sm" style={{ color: UI.muted }}>پکی در این گروه منتشر نشده است؛ گروه دیگری را ببینید یا پک را دستی بسازید.</p>
          : <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{shown.map(p => <PackCard key={p.slug} p={p} good={good} compare={{ picked: picked.includes(p.slug), onPick: () => toggle(p.slug) }} />)}</div>}
        {picked.length >= 2 ? <Link href={`/packs/compare?slugs=${picked.join(",")}`} className="inline-flex min-h-11 items-center gap-1.5 rounded-xl px-4 text-sm font-bold text-white" style={{ background: UI.ink }}><Scale className="h-4 w-4" /> مقایسه {toPersianNum(picked.length)} پک</Link>
          : picked.length === 1 ? <p className="text-xs" style={{ color: UI.muted }}>برای مقایسه حداقل یک پک دیگر انتخاب کنید (حداکثر ۴).</p> : null}
      </>}
      {method === "budget" && <BudgetBuilder onOpen={(items,count) => open({items,count})} />}
    </>}
  </div>;
}
