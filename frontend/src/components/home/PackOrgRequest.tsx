"use client";
import { positiveInteger, tomanBudgetMinor } from "@/lib/pack-input";
import { scopedDraftKey } from "@/lib/client-draft-storage";

// Pack Builder → Organization Request (RFQ). This is NOT a sale: it creates a
// purchase request in the existing organization workflow
// (POST /orgs/{id}/procurement/requests). Pricing comes later from supplier
// quotes and organization approval. No price, stock or total is invented here.

import { FormEvent, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Building2, Plus, Minus, X } from "lucide-react";
import { apiRequest, newIdempotencyKey } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { toPersianNum } from "@/lib/utils";
import { emptyDraft, handOffDraft, newItem, newDestination } from "@/lib/procurement/draft";

export interface RfqLine { key: number; name: string; slug: string; masterProductId: number | null; unit: string | null; qty: number }
type Org = { id: number; display_name: string; currency: string; membership: { status: string; role: string } };
type Dest = { label: string; province: string; city: string; address: string; alloc: number[] };
type Receipt = { id: number; request_number: string; status: string };

const STATUS_FA: Record<string, string> = { draft: "پیش‌نویس", submitted: "ارسال‌شده برای بررسی/استعلام", under_review: "در حال بررسی", approved: "تأییدشده", rejected: "ردشده", cancelled: "لغوشده" };

const DRAFT_KEY = "60o_pack_draft";
const field = "w-full h-8 px-2 rounded-md border border-neutral-200 bg-white text-2xs focus:outline-none focus:border-brand-blue";
const emptyDest = (n: number): Dest => ({ label: "", province: "", city: "", address: "", alloc: Array(n).fill(0) });

export function PackOrgRequest({ lines: initial, purposeLabel, onClose }: { lines: RfqLine[]; purposeLabel: string; onClose: () => void }) {
  const { token } = useAuth();
  const [lines, setLines] = useState<RfqLine[]>(initial);
  const [orgs, setOrgs] = useState<Org[] | null>(null);
  const [orgId, setOrgId] = useState("");
  const [title, setTitle] = useState(`پک سازمانی — ${purposeLabel}`);
  const [recipients, setRecipients] = useState("");
  const [budgetToman, setBudgetToman] = useState("");
  const [needed, setNeeded] = useState("");
  const [notes, setNotes] = useState("");
  const [dests, setDests] = useState<Dest[]>([emptyDest(initial.length)]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [submitError, setSubmitError] = useState("");
  const attempt = useRef<{ key: string; body: string } | null>(null);
  const lock = useRef(false); // synchronous guard: a double click never sends twice

  useEffect(() => {
    if (!token) return;
    apiRequest<{ items: Org[] }>("/organizations", { token })
      .then((r) => {
        const active = r.items.filter((o) => o.membership?.status === "active");
        setOrgs(active);
        if (active.length === 1) setOrgId(String(active[0].id));
      })
      .catch(() => setOrgs([]));
  }, [token]);

  const setQty = (i: number, q: number) => setLines((ls) => ls.map((l, n) => (n === i ? { ...l, qty: Math.max(1, q) } : l)));
  const removeLine = (i: number) => {
    setLines((ls) => ls.filter((_, n) => n !== i));
    setDests((ds) => ds.map((d) => ({ ...d, alloc: d.alloc.filter((_, n) => n !== i) })));
  };
  const setDest = (i: number, k: keyof Omit<Dest, "alloc">, v: string) => setDests((ds) => ds.map((d, n) => (n === i ? { ...d, [k]: v } : d)));
  const setAlloc = (di: number, li: number, v: number) => setDests((ds) => ds.map((d, n) => (n === di ? { ...d, alloc: d.alloc.map((a, m) => (m === li ? Math.max(0, v) : a)) } : d)));

  function saveDraftForLogin() {
    try {
      sessionStorage.setItem(scopedDraftKey(DRAFT_KEY), JSON.stringify({
        rfq: true,
        items: lines.map((l) => ({ slug: l.slug, title: l.name, priceMinor: null, quantity: l.qty, masterProductId: l.masterProductId })),
      }));
    } catch { /* ignore */ }
  }

  // Submit goes through the existing workflow endpoint; backend role/policy
  // checks decide. On refusal the draft is kept and the reason shown.
  async function submitDraft(draft: Receipt) {
    try {
      const r = await apiRequest<{ purchase_request: Receipt }>(`/orgs/${orgId}/procurement/requests/${draft.id}/submit`, { token: token!, method: "POST" });
      setReceipt(r.purchase_request); setSubmitError("");
    } catch (err) {
      setReceipt(draft); setSubmitError(err instanceof Error ? err.message : "ارسال درخواست ناموفق بود");
    }
  }

  async function retrySubmit() {
    if (!receipt || lock.current) return;
    lock.current = true; setBusy(true);
    try { await submitDraft(receipt); } finally { lock.current = false; setBusy(false); }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const sendNow = ((e.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null)?.value !== "draft";
    if (!token || !orgId || lock.current) return;
    setError("");
    if (lines.length > 50 || lines.some(l => !Number.isSafeInteger(l.qty) || l.qty < 1 || l.qty > 100000)) { setError("تعداد هر قلم باید عدد صحیح بین ۱ و ۱۰۰٬۰۰۰ باشد."); return; }
    if (recipients && positiveInteger(recipients) === null) { setError("تعداد گیرندگان نامعتبر است."); return; }
    if (budgetToman && tomanBudgetMinor(budgetToman) === null) { setError("بودجه باید مبلغ صحیح و معتبر به تومان باشد."); return; }
    if (dests.some(d => d.alloc.some(a => !Number.isSafeInteger(a) || a < 0 || a > 100000))) { setError("تخصیص مقصدها باید عدد صحیح معتبر باشد."); return; }
    const org = orgs?.find((o) => String(o.id) === orgId);
    // One destination receives every unit; several destinations must split each item exactly.
    const allocs = dests.length === 1 ? [lines.map((l) => l.qty)] : dests.map((d) => d.alloc);
    if (lines.some((l, i) => allocs.reduce((s, a) => s + (a[i] || 0), 0) !== l.qty)) {
      setError("جمع تعداد هر قلم در مقصدها باید با تعداد درخواستی برابر باشد."); return;
    }
    const extra = [recipients ? `تعداد گیرندگان/کارکنان: ${recipients}` : "", notes.trim()].filter(Boolean).join("\n");
    const body = JSON.stringify({
      title: title.trim(),
      description: "ثبت‌شده از پک‌ساز ۶۰ — درخواست استعلام قیمت (RFQ)؛ قیمت نهایی پس از پیشنهاد تأمین‌کننده و تأیید سازمان.",
      notes: extra || null,
      items: lines.map((l) => ({
        ...(l.masterProductId ? { master_product_id: l.masterProductId } : { free_text_description: l.name }),
        quantity: l.qty, unit: l.unit, notes: null,
      })),
      destinations: dests.map((d, di) => ({
        label: d.label || null, province: d.province, city: d.city, address: d.address,
        allocations: allocs[di].map((quantity, item_index) => ({ item_index, quantity })).filter((a) => a.quantity > 0),
      })),
      needed_by_date: needed || null,
      budget_minor: org?.currency === "IRR" && budgetToman ? tomanBudgetMinor(budgetToman) : null,
      substitution_policy: "require_approval",
    });
    if (!attempt.current || attempt.current.body !== body) attempt.current = { key: newIdempotencyKey(), body };
    lock.current = true; setBusy(true);
    try {
      const r = await apiRequest<{ purchase_request: Receipt }>(`/orgs/${orgId}/procurement/requests`, {
        token, method: "POST", headers: { "Idempotency-Key": attempt.current.key }, body,
      });
      attempt.current = null;
      if (sendNow && r.purchase_request.status === "draft") await submitDraft(r.purchase_request);
      else setReceipt(r.purchase_request);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ثبت درخواست ناموفق بود");
    } finally { lock.current = false; setBusy(false); }
  }

  const shell = (children: React.ReactNode) => (
    <div className="mt-3 rounded-lg border border-brand-blue/25 bg-white p-3" data-testid="pack-rfq">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs font-bold text-neutral-900 inline-flex items-center gap-1.5"><Building2 className="w-3.5 h-3.5 text-brand-blue" /> ثبت درخواست و استعلام قیمت</p>
        <button type="button" onClick={onClose} title="بستن" className="text-neutral-400 hover:text-brand-coral"><X className="w-4 h-4" /></button>
      </div>
      {children}
    </div>
  );

  if (receipt) return shell(
    <div className="text-xs leading-6" data-testid="pack-rfq-receipt">
      <p className="font-bold text-brand-blue">درخواست {receipt.request_number} — {STATUS_FA[receipt.status] ?? receipt.status}</p>
      {submitError ? (
        <p className="text-brand-coral">پیش‌نویس ذخیره شد، اما ارسال انجام نشد: {submitError}</p>
      ) : receipt.status === "draft" ? (
        <p className="text-neutral-600">پیش‌نویس ذخیره شد و هنوز برای استعلام ارسال نشده است.</p>
      ) : (
        <p className="text-neutral-600">مراحل بعد: استعلام از تأمین‌کنندگان، پیشنهاد قیمت و تأیید سازمان. این یک خرید یا پرداخت نیست.</p>
      )}
      <div className="mt-1.5 flex flex-wrap items-center gap-3">
        {receipt.status === "draft" && (
          <button type="button" onClick={retrySubmit} disabled={busy} className="h-8 px-3 rounded-lg bg-brand-blue text-white text-2xs font-semibold disabled:opacity-40">
            {busy ? "در حال ارسال…" : "ارسال برای استعلام قیمت"}
          </button>
        )}
        <Link href={`/organization/requests/${receipt.id}?org=${orgId}`} className="text-brand-blue underline font-semibold">پیگیری درخواست</Link>
      </div>
    </div>,
  );
  if (!token) return shell(
    <p className="text-xs text-neutral-600">برای ثبت درخواست سازمانی ابتدا وارد شوید.{" "}
      <Link href={`/login?next=${encodeURIComponent("/pack-builder")}`} onClick={saveDraftForLogin} className="text-brand-blue underline font-semibold">ورود</Link>
    </p>,
  );
  if (orgs === null) return shell(<p className="text-2xs text-neutral-400">در حال دریافت سازمان‌ها…</p>);
  if (orgs.length === 0) return shell(
    <p className="text-xs text-neutral-600">حساب شما عضو فعال هیچ سازمانی نیست. برای ثبت درخواست سازمانی، مدیر سازمان باید شما را اضافه کند.{" "}
      <Link href="/org" className="text-brand-blue underline">پنل سازمان</Link>
    </p>,
  );

  return shell(
    <form onSubmit={submit} className="space-y-2.5">
      {orgs.length > 1 && (
        <select value={orgId} onChange={(e) => setOrgId(e.target.value)} className={field} required aria-label="سازمان">
          <option value="">انتخاب سازمان</option>
          {orgs.map((o) => <option key={o.id} value={o.id}>{o.display_name}</option>)}
        </select>
      )}
      <input value={title} onChange={(e) => setTitle(e.target.value)} className={field} required maxLength={200} aria-label="عنوان درخواست" />

      <div className="space-y-1.5 max-h-40 overflow-y-auto">
        {lines.map((l, i) => (
          <div key={l.key} className="flex items-center gap-1.5 rounded-md border border-neutral-100 p-1.5">
            <div className="min-w-0 flex-1">
              <p className="text-2xs font-semibold text-neutral-800 line-clamp-1">{l.name}</p>
              <p className="text-2xs text-amber-600">قیمت نیازمند استعلام</p>
            </div>
            <button type="button" onClick={() => setQty(i, l.qty - 1)} className="w-5 h-5 rounded-md border border-neutral-200 flex items-center justify-center"><Minus className="w-3 h-3" /></button>
            <input type="number" min={1} value={l.qty} onChange={(e) => setQty(i, Number(e.target.value) || 1)} aria-label={`تعداد ${l.name}`} className="w-12 h-6 text-center text-2xs border border-neutral-200 rounded-md tabular-nums" />
            <button type="button" onClick={() => setQty(i, l.qty + 1)} className="w-5 h-5 rounded-md border border-neutral-200 flex items-center justify-center"><Plus className="w-3 h-3" /></button>
            {lines.length > 1 && <button type="button" onClick={() => removeLine(i)} title="حذف" className="text-neutral-400 hover:text-brand-coral"><X className="w-3 h-3" /></button>}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        <input type="number" min={1} value={recipients} onChange={(e) => setRecipients(e.target.value)} placeholder="تعداد گیرندگان (اختیاری)" className={field} />
        <input type="number" min={0} value={budgetToman} onChange={(e) => setBudgetToman(e.target.value)} placeholder="بودجه هدف تومان (اختیاری)" className={field} />
        <label className="col-span-2 flex items-center gap-2 text-2xs text-neutral-500">تاریخ موردنیاز
          <input type="date" value={needed} onChange={(e) => setNeeded(e.target.value)} className={`${field} flex-1`} />
        </label>
      </div>

      {dests.map((d, di) => (
        <div key={di} className="rounded-md border border-neutral-100 p-1.5 space-y-1.5">
          <div className="flex items-center justify-between text-2xs font-semibold text-neutral-600">
            <span>مقصد {toPersianNum(di + 1)}</span>
            {dests.length > 1 && <button type="button" onClick={() => setDests((ds) => ds.filter((_, n) => n !== di))} className="text-neutral-400 hover:text-brand-coral">حذف مقصد</button>}
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            <input value={d.label} onChange={(e) => setDest(di, "label", e.target.value)} placeholder="نام (اختیاری)" className={field} />
            <input value={d.province} onChange={(e) => setDest(di, "province", e.target.value)} placeholder="استان" required className={field} />
            <input value={d.city} onChange={(e) => setDest(di, "city", e.target.value)} placeholder="شهر" required className={field} />
          </div>
          <input value={d.address} onChange={(e) => setDest(di, "address", e.target.value)} placeholder="نشانی" required className={field} />
          {dests.length > 1 && lines.map((l, li) => (
            <label key={l.key} className="flex items-center justify-between gap-2 text-2xs text-neutral-600">
              <span className="line-clamp-1">{l.name}</span>
              <input type="number" min={0} value={d.alloc[li] ?? 0} onChange={(e) => setAlloc(di, li, Number(e.target.value) || 0)} className="w-14 h-6 text-center border border-neutral-200 rounded-md tabular-nums" />
            </label>
          ))}
        </div>
      ))}
      <button type="button" onClick={() => setDests((ds) => [...ds, emptyDest(lines.length)])} className="text-2xs font-semibold text-brand-blue">+ افزودن مقصد</button>

      <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="توضیحات (اختیاری)" rows={2} className="w-full px-2 py-1 rounded-md border border-neutral-200 text-2xs focus:outline-none focus:border-brand-blue" />
      <p className="text-2xs text-neutral-500">جمع قطعی محاسبه نمی‌شود؛ قیمت پس از پیشنهاد تأمین‌کننده و تأیید سازمان مشخص می‌شود.</p>
      {error && <p className="text-2xs text-brand-coral">{error}</p>}
      <button type="button" onClick={() => {
        // Hand the pack to the full Order Composer (multi-destination, specs, 60AI).
        const d = emptyDraft("pack_builder");
        const items = lines.map((l) => newItem(l.name, l.qty, { masterProductId: l.masterProductId, unit: l.unit ?? "", catalog: l.masterProductId ? "matched" : "none" }));
        if (recipients && positiveInteger(recipients) === null || budgetToman && tomanBudgetMinor(budgetToman) === null) { setError("تعداد گیرندگان یا بودجه نامعتبر است."); return; }
        const saved = handOffDraft({ ...d, title: title.trim(), kind: "gift_pack", recipients: recipients ? positiveInteger(recipients) : null,
          budgetTotalToman: budgetToman ? tomanBudgetMinor(budgetToman)! / 10 : null, neededBy: needed, notes, items,
          destinations: dests.map((x) => newDestination({ label: x.label, province: x.province, city: x.city, address: x.address, alloc: Object.fromEntries(items.map((i, index) => [i.id, dests.length === 1 ? i.quantity : x.alloc[index] ?? 0])) })) });
        if (!saved) { setError("ذخیره‌سازی مرورگر در دسترس نیست؛ درخواست حفظ نشد."); return; }
        window.location.href = "/organization/compose";
      }} className="text-2xs font-semibold text-brand-blue underline">ویرایش پیشرفته در میز سفارش سازمانی (چندمقصدی، مشخصات، دستیار 60AI)</button>
      <div className="flex gap-2">
        <button type="submit" value="submit" disabled={busy || !orgId || lines.length === 0}
          className="flex-1 h-9 rounded-lg bg-brand-blue text-white text-xs font-semibold hover:bg-brand-blueDark disabled:opacity-40">
          {busy ? "در حال ثبت…" : "ثبت درخواست و استعلام قیمت"}
        </button>
        <button type="submit" value="draft" disabled={busy || !orgId || lines.length === 0}
          className="h-9 px-3 rounded-lg border border-neutral-200 text-neutral-600 text-xs font-semibold hover:border-brand-blue hover:text-brand-blue disabled:opacity-40">
          ذخیره پیش‌نویس
        </button>
      </div>
    </form>,
  );
}
