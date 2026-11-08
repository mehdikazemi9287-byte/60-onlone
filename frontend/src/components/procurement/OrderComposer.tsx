"use client";

// Smart Organizational Order — one Draft model fed by 60AI, Pack Builder or
// manual entry. Submitting creates a purchase request through the existing
// procurement API and sends it into review/RFQ; nothing here is a sale.

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  AlertTriangle, Bot, Building2, CalendarDays, Check, ChevronDown, FileText, MapPin, MessageSquare, Package,
  PackagePlus, Plus, RefreshCw, Search, Send, Sparkles, Trash2, Undo2, Users, Wand2, X,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { apiRequest, catalog, newIdempotencyKey, ApiError } from "@/lib/api";
import type { Product } from "@/lib/types";
import { useOrganization } from "@/components/organization/Dashboard";
import {
  type Draft, type DraftOp, type LineItem, type Priority, type RequestKind, KIND_LABEL, PRIORITY_LABEL, UNITS,
  allocated, applyOp, emptyDraft, loadDraft, loadPendingDraft, clearPendingDraft, newDestination, newItem, saveDraft, toRequestPayload, validate,
} from "@/lib/procurement/draft";
import { COPILOT_EXAMPLES, interpret, normalize, type CopilotIntent } from "@/lib/procurement/copilot";
import { formatJalali } from "@/lib/procurement/jalali";
import { PR_STATUS, money, proc } from "@/lib/procurement/api";
import { Chip, Drawer, Notice, QtyStepper, cx, n } from "./ui";
import s from "./proc.module.css";

type Msg = { role: "user" | "bot"; text: string; changes?: string[]; questions?: string[]; products?: Product[]; compare?: { a: Product | null; b: Product | null }; link?: { href: string; label: string } };
type History = { draft: Draft; past: Draft[] };

const tokens = (v: string) => normalize(v).replace(/[‌]/g, " ").split(/\s+/).filter((t) => t.length >= 2);
function confident(query: string, name: string) {
  const q = tokens(query), target = normalize(name).replace(/[‌]/g, " ");
  return q.length > 0 && q.every((t) => target.includes(t));
}

function linkPatch(p: Product): Partial<LineItem> {
  const priced = p.purchasable && typeof p.price_minor === "number" && p.price_minor > 0;
  return {
    masterProductId: p.master_product_id ?? null, sku: p.sku ?? null, imageUrl: p.image_url ?? null,
    verifiedPriceMinor: priced ? p.price_minor : null, catalog: p.master_product_id ? "matched" : "none",
  };
}

export default function OrderComposer() { const {user,loading}=useAuth(); return loading ? <p role="status">در حال بررسی حساب…</p> : <OrderComposerBody key={user?.id??"guest"}/>; }
function OrderComposerBody() {
  const { token, user } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const orgState = useOrganization(true);
  const [hist, setHist] = useState<History>(() => ({ draft: emptyDraft(), past: [] }));
  const [ready, setReady] = useState(false);
  const [pendingDraft,setPendingDraft]=useState<Draft|null>(null);
  const [mobileTab, setMobileTab] = useState<"assistant" | "draft">(params.get("tab") === "assistant" ? "assistant" : "draft");
  const [flashing, setFlashing] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [picker, setPicker] = useState<{ mode: "add" } | { mode: "replace"; itemId: string } | null>(null);
  const [openLine, setOpenLine] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "draft" | "submit">("");
  const [error, setError] = useState("");
  const [showIssues, setShowIssues] = useState(false);
  const lock = useRef(false);
  const attempt = useRef<{ key: string; body: string } | null>(null);
  const draft = hist.draft;

  // A prompt from the homepage (?q=) starts a fresh assistant draft; the stored one stays undoable.
  const initialPrompt = useRef<string | null>(params.get("q"));
  useEffect(() => {
    const stored = loadDraft();
    setPendingDraft(loadPendingDraft());
    if (initialPrompt.current) setHist({ draft: emptyDraft("assistant"), past: stored && stored.items.length ? [stored] : [] });
    else if (stored) setHist({ draft: stored, past: [] });
    setReady(true);
  }, []);
  useEffect(() => {
    if (!ready) return;
    const t = setTimeout(() => saveDraft(draft), 300);
    return () => clearTimeout(t);
  }, [draft, ready]);

  const dispatch = useCallback((ops: DraftOp[] | DraftOp, record = true) => {
    const list = Array.isArray(ops) ? ops : [ops];
    if (!list.length) return;
    setHist((h) => {
      const next = list.reduce(applyOp, h.draft);
      return record ? { draft: next, past: [...h.past.slice(-39), h.draft] } : { ...h, draft: next };
    });
  }, []);
  const undo = useCallback(() => setHist((h) => (h.past.length ? { draft: h.past[h.past.length - 1], past: h.past.slice(0, -1) } : h)), []);

  const resolveCatalog = useCallback(async (searches: { itemId: string; query: string }[]) => {
    await Promise.all(searches.map(async ({ itemId, query }) => {
      try {
        const r = await catalog.list({ q: query, page_size: 6 });
        const hit = r.items.find((p) => p.master_product_id && confident(query, p.name));
        dispatch({ type: "updateItem", id: itemId, patch: hit ? { ...linkPatch(hit) } : { catalog: "none" } }, false);
      } catch {
        dispatch({ type: "updateItem", id: itemId, patch: { catalog: "none" } }, false);
      }
    }));
  }, [dispatch]);

  const issues = useMemo(() => validate(draft), [draft]);
  const errors = issues.filter((i) => i.level === "error");
  const units = draft.items.reduce((a, i) => a + i.quantity, 0);
  const allocOk = draft.destinations.length === 1 || draft.items.every((i) => allocated(draft, i.id) === i.quantity);
  const org = orgState.org as unknown as { id: number; display_name: string; currency?: string } | undefined;
  const currency = org?.currency ?? "IRR";

  async function send(mode: "draft" | "submit") {
    setError("");
    if (!token) { setError("برای ثبت درخواست ابتدا وارد حساب سازمانی شوید."); return; }
    if (!orgState.selected) { setError("سازمان فعال انتخاب نشده است."); return; }
    if (errors.length) { setShowIssues(true); return; }
    if (lock.current) return;
    lock.current = true; setBusy(mode);
    const body = JSON.stringify(toRequestPayload(draft, currency));
    if (!attempt.current || attempt.current.body !== body) attempt.current = { key: newIdempotencyKey(), body };
    const base = `/orgs/${orgState.selected}/procurement/requests`;
    try {
      const created = await apiRequest<{ purchase_request: { id: number; status: string } }>(base, {
        token, method: "POST", body, headers: { "Idempotency-Key": attempt.current.key },
      });
      const id = created.purchase_request.id;
      attempt.current = null;
      let submitError = "";
      if (mode === "submit" && created.purchase_request.status === "draft") {
        try { await apiRequest(`${base}/${id}/submit`, { token, method: "POST" }); }
        catch (e) { submitError = e instanceof Error ? e.message : "ارسال انجام نشد"; }
      }
      saveDraft(null);
      const q = new URLSearchParams({ org: String(orgState.selected) });
      if (submitError) q.set("submit_error", submitError);
      router.push(`/organization/requests/${id}?${q.toString()}`);
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : "ثبت درخواست ناموفق بود");
      if (e instanceof ApiError && [400, 401, 403, 404, 422].includes(e.status)) attempt.current = null;
    } finally { lock.current = false; setBusy(""); }
  }

  const title = (
    <div className={s.head}>
      <div className={s.headRow}>
        <div>
          <div className={s.eyebrow}><Link href="/org">میز کار سازمانی</Link> / سفارش سازمانی هوشمند</div>
          <h1 className={s.title}>ساخت سفارش سازمانی</h1>
          <div className={s.meta}>
            <span><Building2 size={14} /> {org ? <b>{org.display_name}</b> : user ? "در حال دریافت سازمان…" : "پس از ورود، سازمان شما انتخاب می‌شود"}</span>
            <span><Sparkles size={14} /> منبع: {draft.source === "assistant" ? "دستیار 60AI" : draft.source === "pack_builder" ? "پک‌ساز" : "ساخت دستی"}</span>
            <span><FileText size={14} /> ثبت درخواست ≠ خرید؛ قیمت پس از استعلام مشخص می‌شود</span>
          </div>
        </div>
        <div className={s.headActions}>
          {orgState.orgs.length > 1 && (
            <select className={cx(s.select, s.inputSm)} value={orgState.selected} onChange={(e) => orgState.setSelected(e.target.value)} aria-label="سازمان">
              {orgState.orgs.map((o) => <option key={o.id} value={o.id}>{o.display_name}</option>)}
            </select>
          )}
          {confirmReset ? (
            <span className={s.row}>
              <span className={s.small}>پیش‌نویس فعلی پاک شود؟ (قابل بازگردانی)</span>
              <button type="button" className={cx(s.btn, s.sm, s.danger)} onClick={() => { setHist((h) => ({ draft: emptyDraft(), past: [...h.past, h.draft] })); setConfirmReset(false); }}>بله، جدید</button>
              <button type="button" className={cx(s.btn, s.sm)} onClick={() => setConfirmReset(false)}>انصراف</button>
            </span>
          ) : (
            <button type="button" className={cx(s.btn, s.sm)} onClick={() => setConfirmReset(true)}><RefreshCw /> پیش‌نویس جدید</button>
          )}
        </div>
      </div>
    </div>
  );

  return (
    <div className={s.root}>
      {pendingDraft&&<div role="alert" className="m-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm"><p>یک پیش‌نویس پیش از ورود و یک پیش‌نویس متعلق به این حساب دارید. پیش‌نویس قبلی حفظ شده است.</p><div className="mt-3 flex flex-wrap gap-3"><button type="button" className="min-h-11 rounded-lg bg-brand-navy px-4 text-white" onClick={()=>{setHist(h=>({draft:pendingDraft,past:[...h.past,h.draft]}));clearPendingDraft();setPendingDraft(null);}}>ادامه پیش‌نویس جدید</button><button type="button" className="min-h-11 rounded-lg border px-4" onClick={()=>{clearPendingDraft();setPendingDraft(null);}}>حفظ پیش‌نویس این حساب</button></div></div>}
      {title}
      <div className={s.mTabs} role="tablist">
        <button type="button" role="tab" aria-selected={mobileTab === "assistant"} className={cx(mobileTab === "assistant" && s.segOn)} onClick={() => setMobileTab("assistant")}><Bot size={16} /> دستیار 60AI</button>
        <button type="button" role="tab" aria-selected={mobileTab === "draft"} className={cx(mobileTab === "draft" && s.segOn)} onClick={() => setMobileTab("draft")}><Package size={16} /> پیش‌نویس ({n(draft.items.length)})</button>
      </div>
      <div className={s.workspace}>
        <div className={cx(s.stack, mobileTab !== "draft" && s.mHide, flashing && s.flash)} style={{ borderRadius: 14 }}>
          <SummaryBoard draft={draft} issues={issues.length} errors={errors.length} currency={currency} />
          <RequestHeader draft={draft} dispatch={dispatch} />
          <ItemsSection draft={draft} dispatch={dispatch} openLine={openLine} setOpenLine={setOpenLine}
            onAdd={() => setPicker({ mode: "add" })} onReplace={(itemId) => setPicker({ mode: "replace", itemId })} currency={currency} />
          <DestinationsSection draft={draft} dispatch={dispatch} />
          <div className={s.stickyBar}>
            <div className={s.row} style={{ gap: 18 }}>
              <span className={s.stat}>اقلام<b className={s.num}>{n(draft.items.length)}</b></span>
              <span className={s.stat}>جمع تعداد<b className={s.num}>{n(units)}</b></span>
              <span className={s.stat}>مقصدها<b className={s.num}>{n(draft.destinations.length)}</b></span>
              <span className={s.stat}>تخصیص<b>{allocOk ? <Chip tone="ok" dot>منطبق</Chip> : <Chip tone="bad" dot>نامنطبق</Chip>}</b></span>
              {errors.length > 0 && (
                <button type="button" className={cx(s.btn, s.ghost, s.sm)} onClick={() => setShowIssues((v) => !v)}>
                  <AlertTriangle /> {n(errors.length)} مورد نیازمند تکمیل
                </button>
              )}
            </div>
            <div className={s.row}>
              <button type="button" className={cx(s.btn, s.sm)} onClick={undo} disabled={!hist.past.length} title="بازگردانی آخرین تغییر"><Undo2 /> بازگردانی</button>
              <button type="button" className={s.btn} onClick={() => send("draft")} disabled={!!busy || !draft.items.length}>{busy === "draft" ? "در حال ذخیره…" : "ذخیره پیش‌نویس"}</button>
              <button type="button" className={cx(s.btn, s.primary)} onClick={() => send("submit")} disabled={!!busy || !draft.items.length}>
                <Send /> {busy === "submit" ? "در حال ارسال…" : "ثبت و ارسال برای استعلام"}
              </button>
            </div>
            {(showIssues && issues.length > 0) && (
              <ul className={cx(s.small)} style={{ width: "100%", margin: 0, paddingRight: 18 }}>
                {issues.map((i) => <li key={i.text} style={{ color: i.level === "error" ? "var(--red)" : "var(--amber)" }}>{i.text}</li>)}
              </ul>
            )}
            {error && <div style={{ width: "100%" }}><Notice tone="bad" icon={<AlertTriangle />}>{error} {!token && <Link href="/login?next=/organization/compose">ورود</Link>}</Notice></div>}
          </div>
        </div>
        <div className={cx(s.assistantCol, mobileTab !== "assistant" && s.mHide)}>
          <Copilot draft={draft} dispatch={dispatch} undo={undo} canUndo={hist.past.length > 0}
            onApplied={() => { setFlashing(true); setTimeout(() => setFlashing(false), 1100); }} resolveCatalog={resolveCatalog}
            onShowDraft={() => setMobileTab("draft")}
            token={token} orgId={orgState.selected}
            initialPrompt={ready ? initialPrompt.current : null}
            onPromptConsumed={() => { initialPrompt.current = null; router.replace("/organization/compose?tab=assistant"); }} />
        </div>
      </div>
      <CatalogPicker open={!!picker} currency={currency} onClose={() => setPicker(null)}
        title={picker?.mode === "replace" ? "جایگزینی کالا" : "افزودن کالا از کاتالوگ"}
        onPick={(p, qty) => {
          if (picker?.mode === "replace") {
            dispatch({ type: "updateItem", id: picker.itemId, patch: { name: p.name, ...linkPatch(p) } });
          } else {
            dispatch({ type: "addItem", item: newItem(p.name, qty, linkPatch(p)) });
          }
          setPicker(null);
        }}
        onFreeText={(name, qty) => { dispatch({ type: "addItem", item: newItem(name, qty, { catalog: "none" }) }); setPicker(null); }} />
    </div>
  );
}

// ── Summary board ──────────────────────────────────────────────────────────

function SummaryBoard({ draft, issues, errors, currency }: { draft: Draft; issues: number; errors: number; currency: string }) {
  const units = draft.items.reduce((a, i) => a + i.quantity, 0);
  const priced = draft.items.filter((i) => i.verifiedPriceMinor);
  const catalogTotal = priced.reduce((a, i) => a + (i.verifiedPriceMinor ?? 0) * i.quantity, 0);
  const budget = draft.budgetTotalToman ?? (draft.budgetPerCapitaToman && draft.recipients ? draft.budgetPerCapitaToman * draft.recipients : null);
  const allocOk = draft.destinations.length === 1 || draft.items.every((i) => allocated(draft, i.id) === i.quantity);
  const checks = 6, passed = Math.max(0, checks - Math.min(checks, errors));
  const readiness = draft.items.length ? Math.round((passed / checks) * 100) : 0;
  const tiles: [string, ReactNode, ReactNode][] = [
    ["اقلام", <>{n(draft.items.length)} <small>قلم</small></>, `${n(units)} واحد`],
    ["مقصدها", <>{n(draft.destinations.filter((d) => d.city).length)} <small>شهر</small></>, allocOk ? <Chip tone="ok" dot>تخصیص منطبق</Chip> : <Chip tone="bad" dot>تخصیص نامنطبق</Chip>],
    ["بودجه هدف", budget ? money(budget * 10, currency) : "بدون سقف", draft.budgetPerCapitaToman ? `سرانه ${money(draft.budgetPerCapitaToman * 10, currency)}` : "اختیاری"],
    ["قیمت", priced.length ? money(catalogTotal, currency) : "نیازمند استعلام", `${n(draft.items.length - priced.length)} قلم بدون قیمت قطعی`],
    ["تاریخ موردنیاز", draft.neededBy ? formatJalali(draft.neededBy) : "تعیین نشده", PRIORITY_LABEL[draft.priority]],
  ];
  return (
    <section className={s.summary} aria-label="خلاصه پیش‌نویس">
      <div className={s.readiness}>
        <span>آمادگی ارسال</span>
        <b className={s.num}>{n(readiness)}٪</b>
        <div className={s.bar}><i style={{ width: `${readiness}%`, background: readiness === 100 ? "var(--green)" : "var(--blue)" }} /></div>
        <small>{errors ? `${n(errors)} مورد باقی‌مانده` : issues ? "آماده؛ یک هشدار" : draft.items.length ? "آماده ارسال" : "با دستیار یا کاتالوگ شروع کنید"}</small>
      </div>
      {tiles.map(([k, v, sub]) => (
        <div key={k} className={s.sumTile}><span>{k}</span><b className={s.num}>{v}</b><small>{sub}</small></div>
      ))}
    </section>
  );
}

// ── Request header ─────────────────────────────────────────────────────────

function RequestHeader({ draft, dispatch }: { draft: Draft; dispatch: (op: DraftOp) => void }) {
  const [constraint, setConstraint] = useState("");
  const set = (patch: Partial<Draft>) => dispatch({ type: "set", patch: patch as never });
  return (
    <section className={s.card}>
      <input className={cx(s.input, s.titleInput)} value={draft.title} placeholder="عنوان درخواست — مثلاً «پک شب یلدا ۱۴۰۵»"
        onChange={(e) => set({ title: e.target.value })} aria-label="عنوان درخواست" maxLength={200} />
      <div className={s.row} style={{ marginTop: 14, gap: 16 }}>
        <div className={s.seg} role="radiogroup" aria-label="نوع درخواست">
          {(Object.keys(KIND_LABEL) as RequestKind[]).map((k) => (
            <button type="button" key={k} role="radio" aria-checked={draft.kind === k} className={cx(draft.kind === k && s.segOn)} onClick={() => set({ kind: k })}>{KIND_LABEL[k]}</button>
          ))}
        </div>
        <div className={s.seg} role="radiogroup" aria-label="اولویت">
          {(Object.keys(PRIORITY_LABEL) as Priority[]).map((k) => (
            <button type="button" key={k} role="radio" aria-checked={draft.priority === k} className={cx(draft.priority === k && s.segOn)} onClick={() => set({ priority: k })}>{PRIORITY_LABEL[k]}</button>
          ))}
        </div>
      </div>
      <div className={s.grid4} style={{ marginTop: 14 }}>
        <label className={s.field}>تاریخ موردنیاز
          <input className={s.input} type="date" value={draft.neededBy} onChange={(e) => set({ neededBy: e.target.value })} />
          <span className={s.hint}><CalendarDays size={12} /> {draft.neededBy ? formatJalali(draft.neededBy) : "تعیین نشده"}</span>
        </label>
        <label className={s.field}>تعداد گیرندگان
          <input className={s.input} type="number" min={1} inputMode="numeric" value={draft.recipients ?? ""} placeholder="اختیاری"
            onChange={(e) => set({ recipients: e.target.value ? Math.max(1, Number(e.target.value)) : null })} />
        </label>
        <label className={s.field}>بودجه کل (تومان)
          <input className={s.input} type="number" min={0} inputMode="numeric" value={draft.budgetTotalToman ?? ""} placeholder="اختیاری"
            onChange={(e) => set({ budgetTotalToman: e.target.value ? Number(e.target.value) : null })} />
          <span className={s.hint}>{draft.budgetTotalToman ? money(draft.budgetTotalToman * 10) : "سقف هدف؛ قیمت قطعی نیست"}</span>
        </label>
        <label className={s.field}>بودجه سرانه (تومان)
          <input className={s.input} type="number" min={0} inputMode="numeric" value={draft.budgetPerCapitaToman ?? ""} placeholder="اختیاری"
            onChange={(e) => set({ budgetPerCapitaToman: e.target.value ? Number(e.target.value) : null })} />
          <span className={s.hint}>{draft.budgetPerCapitaToman ? money(draft.budgetPerCapitaToman * 10) : "برای پک‌های نفری"}</span>
        </label>
      </div>
      <div className={s.grid2} style={{ marginTop: 12 }}>
        <div className={s.field}>محدودیت‌ها و الزامات
          <div className={s.row}>
            {draft.constraints.map((c) => (
              <span key={c} className={cx(s.chip, s.info)}>{c}
                <button type="button" aria-label={`حذف ${c}`} style={{ border: 0, background: "none", color: "inherit", padding: 0, display: "grid" }}
                  onClick={() => set({ constraints: draft.constraints.filter((x) => x !== c) })}><X size={12} /></button>
              </span>
            ))}
          </div>
          <form className={s.row} onSubmit={(e) => { e.preventDefault(); if (constraint.trim()) { set({ constraints: [...draft.constraints, constraint.trim()] }); setConstraint(""); } }}>
            <input className={cx(s.input, s.inputSm)} style={{ flex: 1 }} value={constraint} onChange={(e) => setConstraint(e.target.value)} placeholder="مثلاً «فقط برند با گارانتی ۱۸ ماهه»" />
            <button type="submit" className={cx(s.btn, s.sm)}><Plus /> افزودن</button>
          </form>
        </div>
        <label className={s.field}>توضیحات
          <textarea className={s.textarea} value={draft.notes} onChange={(e) => set({ notes: e.target.value })} placeholder="هر نکته‌ای که تأمین‌کننده یا تدارکات باید بداند" maxLength={4000} />
        </label>
      </div>
    </section>
  );
}

// ── Line items ─────────────────────────────────────────────────────────────

function ItemsSection({ draft, dispatch, openLine, setOpenLine, onAdd, onReplace, currency }: {
  draft: Draft; dispatch: (op: DraftOp) => void; openLine: string | null; setOpenLine: (id: string | null) => void;
  onAdd: () => void; onReplace: (id: string) => void; currency: string;
}) {
  const upd = (id: string, patch: Partial<LineItem>) => dispatch({ type: "updateItem", id, patch });
  return (
    <section className={s.card} id="items">
      <div className={s.sectionHead}>
        <div><h2><Package /> اقلام درخواست</h2><p>کالای کاتالوگ یا شرح آزاد؛ قیمت قطعی پس از پیشنهاد تأمین‌کننده</p></div>
        <div className={s.row}>
          <button type="button" className={cx(s.btn, s.sm)} onClick={() => dispatch({ type: "addItem", item: newItem("", 1, { catalog: "none" }) })}><Plus /> ردیف آزاد</button>
          <button type="button" className={cx(s.btn, s.sm, s.primary)} onClick={onAdd}><Search /> افزودن از کاتالوگ</button>
        </div>
      </div>
      {!draft.items.length ? (
        <div className={s.empty}>
          <PackagePlus />
          <h3>هنوز قلمی اضافه نشده</h3>
          <p>از کاتالوگ انتخاب کنید، یک ردیف آزاد بسازید، یا درخواستتان را به دستیار 60AI بنویسید تا اقلام، تعداد و مقصدها را خودش بچیند.</p>
          <button type="button" className={cx(s.btn, s.primary)} onClick={onAdd}><Search /> جستجو در کاتالوگ</button>
        </div>
      ) : (
        <div className={s.stack} style={{ gap: 10 }}>
          {draft.items.map((i, idx) => {
            const open = openLine === i.id;
            return (
              <div key={i.id} className={s.lineCard}>
                <div className={s.spread} style={{ alignItems: "flex-start" }}>
                  <div className={s.prod} style={{ flex: 1 }}>
                    <span className={s.thumb}>{i.imageUrl ? <img src={i.imageUrl} alt="" /> : <Package />}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <input className={cx(s.input, s.inputSm)} value={i.name} onChange={(e) => upd(i.id, { name: e.target.value, ...(i.masterProductId ? { masterProductId: null, sku: null, imageUrl: null, verifiedPriceMinor: null, catalog: "none" } : {}) })}
                        aria-label={`شرح قلم ${idx + 1}`} placeholder="شرح کالا یا خدمت" />
                      <div className={s.row} style={{ marginTop: 5, gap: 6 }}>
                        {i.catalog === "searching" && <Chip tone="info">در حال تطبیق با کاتالوگ…</Chip>}
                        {i.masterProductId ? <Chip tone="ok" dot>کالای کاتالوگ{i.sku ? ` · ${i.sku}` : ""}</Chip> : i.catalog !== "searching" && <Chip>شرح آزاد</Chip>}
                        {i.verifiedPriceMinor ? <Chip tone="violet" title="قیمت پیشنهاد معتبر کاتالوگ؛ قیمت نهایی سازمانی پس از پیشنهاد">قیمت کاتالوگ: {money(i.verifiedPriceMinor, currency)}</Chip> : <Chip tone="warn">نیازمند استعلام</Chip>}
                      </div>
                    </div>
                  </div>
                  <div className={s.row}>
                    <QtyStepper value={i.quantity} onChange={(v) => upd(i.id, { quantity: v })} label={`تعداد ${i.name || idx + 1}`} />
                    <select className={cx(s.select, s.inputSm)} style={{ width: 92 }} value={i.unit} onChange={(e) => upd(i.id, { unit: e.target.value })} aria-label="واحد">
                      {Array.from(new Set([i.unit, ...UNITS])).map((u) => <option key={u}>{u}</option>)}
                    </select>
                    <button type="button" className={cx(s.btn, s.sm, s.icon)} onClick={() => setOpenLine(open ? null : i.id)} aria-expanded={open} title="مشخصات و قیمت هدف"><ChevronDown style={{ transform: open ? "rotate(180deg)" : undefined }} /></button>
                    <button type="button" className={cx(s.btn, s.sm, s.icon)} onClick={() => onReplace(i.id)} title="جایگزینی کالا"><RefreshCw /></button>
                    <button type="button" className={cx(s.btn, s.sm, s.icon, s.danger)} onClick={() => dispatch({ type: "removeItem", id: i.id })} title="حذف"><Trash2 /></button>
                  </div>
                </div>
                {open && (
                  <div className={s.lineGrid}>
                    <label className={s.field}>مشخصات هدف
                      <input className={cx(s.input, s.inputSm)} value={i.targetSpec} onChange={(e) => upd(i.id, { targetSpec: e.target.value })} placeholder="مثلاً IPS، ۲۴ اینچ، ۷۵ هرتز" maxLength={2000} />
                    </label>
                    <label className={s.field}>جایگزین قابل قبول
                      <input className={cx(s.input, s.inputSm)} value={i.alternative} onChange={(e) => upd(i.id, { alternative: e.target.value })} placeholder="مثلاً هر برند هم‌رده با گارانتی" maxLength={2000} />
                    </label>
                    <label className={s.field}>قیمت هدف واحد (اختیاری)
                      <input className={cx(s.input, s.inputSm)} type="number" min={0} value={i.targetUnitPriceToman ?? ""} onChange={(e) => upd(i.id, { targetUnitPriceToman: e.target.value ? Number(e.target.value) : null })} placeholder="تومان" />
                    </label>
                    <div className={s.field}>وضعیت قیمت
                      <span className={s.hint} style={{ lineHeight: 1.6 }}>قیمت هدف فقط راهنمای تأمین‌کننده است و قیمت قطعی محسوب نمی‌شود.</span>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ── Destinations & allocation ──────────────────────────────────────────────

function DestinationsSection({ draft, dispatch }: { draft: Draft; dispatch: (op: DraftOp) => void }) {
  const multi = draft.destinations.length > 1;
  const upd = (id: string, patch: Record<string, string>) => dispatch({ type: "updateDestination", id, patch });
  return (
    <section className={s.card} id="destinations">
      <div className={s.sectionHead}>
        <div><h2><MapPin /> مقصدها و سهم تحویل</h2><p>هر مقصد وضعیت تحویل و رسید مستقل خواهد داشت</p></div>
        <div className={s.row}>
          {multi && <button type="button" className={cx(s.btn, s.sm)} onClick={() => dispatch({ type: "splitEqual" })}><Wand2 /> تقسیم مساوی</button>}
          <button type="button" className={cx(s.btn, s.sm)} onClick={() => dispatch({ type: "addDestination", destination: newDestination() })} disabled={draft.destinations.length >= 20}><Plus /> افزودن مقصد</button>
        </div>
      </div>
      <div className={s.grid2}>
        {draft.destinations.map((d, idx) => (
          <div key={d.id} className={s.cardFlat}>
            <div className={s.spread} style={{ marginBottom: 8 }}>
              <strong className={s.row} style={{ gap: 6 }}><MapPin size={15} /> {d.label || d.city || `مقصد ${n(idx + 1)}`}</strong>
              {multi && <button type="button" className={cx(s.btn, s.ghost, s.sm, s.danger)} onClick={() => dispatch({ type: "removeDestination", id: d.id })}><Trash2 /> حذف</button>}
            </div>
            <div className={s.grid2} style={{ gap: 8 }}>
              <label className={s.field}>نام شعبه/واحد<input className={cx(s.input, s.inputSm)} value={d.label} onChange={(e) => upd(d.id, { label: e.target.value })} /></label>
              <label className={s.field}>گیرنده<input className={cx(s.input, s.inputSm)} value={d.recipient} onChange={(e) => upd(d.id, { recipient: e.target.value })} /></label>
              <label className={s.field}>استان<input className={cx(s.input, s.inputSm)} value={d.province} onChange={(e) => upd(d.id, { province: e.target.value })} required /></label>
              <label className={s.field}>شهر<input className={cx(s.input, s.inputSm)} value={d.city} onChange={(e) => upd(d.id, { city: e.target.value })} required /></label>
              <label className={s.field}>تلفن<input className={cx(s.input, s.inputSm)} value={d.phone} inputMode="tel" dir="ltr" onChange={(e) => upd(d.id, { phone: e.target.value })} /></label>
              <label className={s.field}>بازه تحویل<input className={cx(s.input, s.inputSm)} value={d.window} placeholder="مثلاً شنبه تا چهارشنبه ۹ تا ۱۶" onChange={(e) => upd(d.id, { window: e.target.value })} /></label>
            </div>
            <label className={s.field} style={{ marginTop: 8 }}>نشانی کامل<input className={cx(s.input, s.inputSm)} value={d.address} onChange={(e) => upd(d.id, { address: e.target.value })} required /></label>
            <label className={s.field} style={{ marginTop: 8 }}>توضیحات مقصد<input className={cx(s.input, s.inputSm)} value={d.notes} onChange={(e) => upd(d.id, { notes: e.target.value })} /></label>
          </div>
        ))}
      </div>
      {multi && draft.items.length > 0 && (
        <div className={s.tableWrap} style={{ marginTop: 14 }}>
          <table className={cx(s.table, s.matrix)}>
            <thead>
              <tr><th>قلم</th>{draft.destinations.map((d, i) => <th key={d.id}>{d.label || d.city || `مقصد ${n(i + 1)}`}</th>)}<th>تطبیق</th></tr>
            </thead>
            <tbody>
              {draft.items.map((i) => {
                const a = allocated(draft, i.id), ok = a === i.quantity;
                return (
                  <tr key={i.id}>
                    <td><b>{i.name || "بدون شرح"}</b> <span className={s.muted}>({n(i.quantity)} {i.unit})</span></td>
                    {draft.destinations.map((d) => (
                      <td key={d.id}>
                        <input type="number" min={0} className={cx(!ok && s.off)} value={d.alloc[i.id] ?? 0} aria-label={`سهم ${d.label || d.city} از ${i.name}`}
                          onChange={(e) => dispatch({ type: "setAlloc", destinationId: d.id, itemId: i.id, quantity: Number(e.target.value) })} />
                      </td>
                    ))}
                    <td>{ok ? <Chip tone="ok"><Check /> {n(a)}</Chip> : <Chip tone="bad">{n(a)} از {n(i.quantity)}</Chip>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── 60AI copilot ───────────────────────────────────────────────────────────

function Copilot({ draft, dispatch, undo, canUndo, onApplied, resolveCatalog, onShowDraft, initialPrompt, onPromptConsumed, token, orgId }: {
  draft: Draft; dispatch: (ops: DraftOp[] | DraftOp, record?: boolean) => void; undo: () => void; canUndo: boolean;
  onApplied: () => void; resolveCatalog: (s: { itemId: string; query: string }[]) => Promise<void>; onShowDraft: () => void;
  initialPrompt: string | null; onPromptConsumed: () => void; token: string | null; orgId: string;
}) {
  // Answers that read live data (catalog / procurement) without editing the draft.
  async function answer(intent: CopilotIntent): Promise<Msg> {
    if (intent.kind === "find" || intent.kind === "alternatives") {
      let list = (await catalog.list({ q: intent.query, page_size: 8 })).items;
      if (!list.length && /\u200c/.test(intent.query)) list = (await catalog.list({ q: intent.query.replace(/\u200c/g, " "), page_size: 8 })).items;
      if (intent.kind === "alternatives" && list[0]?.category) {
        const base = list[0];
        list = (await catalog.list({ category: base.category!.slug, page_size: 12 })).items.filter((x) => x.id !== base.id);
      }
      list = list.slice(0, 4);
      return list.length
        ? { role: "bot", text: intent.kind === "find" ? `در کاتالوگ برای «${intent.query}» پیدا شد:` : `جایگزین‌های هم‌دسته برای «${intent.query}»:`, products: list }
        : intent.kind === "alternatives" ? { role: "bot", text: `در دستهٔ «${intent.query}» کالای دیگری در کاتالوگ ثبت نشده است.` }
        : { role: "bot", text: `برای «${intent.query}» کالایی در کاتالوگ پیدا نشد؛ می‌توانید آن را به‌صورت شرح آزاد اضافه کنید، مثلاً «۱۰ ${intent.query}».` };
    }
    if (intent.kind === "compare") {
      const [a, b] = await Promise.all([intent.a, intent.b].map((q) => catalog.list({ q, page_size: 3 }).then((x) => x.items.find((y) => y.master_product_id) ?? null)));
      return { role: "bot", text: a && b ? "مقایسه بر اساس داده‌های ثبت‌شده در کاتالوگ:" : "یکی از دو کالا در کاتالوگ پیدا نشد.", compare: { a, b } };
    }
    if (intent.kind === "status") {
      if (!token || !orgId) return { role: "bot", text: "برای دیدن وضعیت درخواست‌ها وارد حساب سازمانی شوید." };
      const list = await apiRequest<{ items: { id: number; request_number: string; title: string; status: string }[] }>(`/orgs/${orgId}/procurement/requests`, { token });
      const pr = intent.ref ? list.items.find((x) => x.request_number === intent.ref) : list.items[0];
      if (!pr) return { role: "bot", text: intent.ref ? `درخواست ${intent.ref} در سازمان شما پیدا نشد.` : "هنوز درخواستی در سازمان شما ثبت نشده است." };
      const ws = await proc.workspace(token, orgId, pr.id);
      return { role: "bot", text: `${pr.request_number} — «${pr.title}»\nوضعیت: ${PR_STATUS[pr.status] ?? pr.status}\nاقدام بعدی: ${ws.next_action.label}${ws.next_action.owner ? ` (مسئول: ${ws.next_action.owner})` : ""}`,
        link: { href: `/organization/requests/${pr.id}?org=${orgId}`, label: "باز کردن پرونده" } };
    }
    const errs = validate(draft).filter((i) => i.level === "error");
    const steps = !draft.items.length ? ["اقلام و تعداد را بنویسید یا از کاتالوگ اضافه کنید."]
      : errs.length ? errs.slice(0, 4).map((i) => i.text)
        : ["پیش‌نویس کامل است؛ «ثبت و ارسال برای استعلام» را بزنید.", "بعد از ارسال: تأیید سازمان ← استعلام از تأمین‌کنندگان ← مقایسه و انتخاب پیشنهاد ← سفارش ← تحویل و رسید."];
    return { role: "bot", text: "قدم‌های بعدی:", changes: steps };
  }

  const [log, setLog] = useState<Msg[]>([{
    role: "bot",
    text: "سلام! نیاز خریدتان را همان‌طور که به همکارتان می‌گویید بنویسید. اقلام، تعداد، گیرندگان، بودجه، مقصدها و تاریخ را در پیش‌نویس کنار همین گفتگو می‌چینم و فقط سؤال‌های ضروری را می‌پرسم.\nقیمت یا موجودی حدس زده نمی‌شود؛ اقلام بدون قیمت معتبر «نیازمند استعلام» می‌مانند.",
  }]);
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end", behavior: "smooth" }); }, [log]);
  useEffect(() => {
    if (!initialPrompt) return;
    onPromptConsumed();
    submit(undefined, initialPrompt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialPrompt]);
  const suggestions = useMemo(() => {
    const out: string[] = [];
    if (!draft.items.length) return COPILOT_EXAMPLES.slice(0, 2);
    if (draft.destinations.length > 1) out.push("مساوی تقسیم کن");
    if (!draft.neededBy) out.push("تحویل تا آخر ماه");
    if (!draft.destinations.some((d) => d.city)) out.push("تحویل تهران و کرج");
    const first = draft.items[0];
    if (first) out.push(`تعداد ${first.name} را ${first.quantity + 10} کن`);
    if (draft.budgetTotalToman || draft.budgetPerCapitaToman) out.push("بودجه را ۱۰ درصد کمتر کن");
    out.push("برگرد");
    return out.slice(0, 4);
  }, [draft]);

  function submit(e?: FormEvent, preset?: string) {
    e?.preventDefault();
    const value = (preset ?? text).trim();
    if (!value) return;
    setText("");
    const r = interpret(value, draft);
    if (r.intent) {
      const intent = r.intent;
      setLog((l) => [...l, { role: "user", text: value }, { role: "bot", text: "در حال بررسی…" }]);
      answer(intent)
        .catch((e): Msg => ({ role: "bot", text: e instanceof Error ? e.message : "پاسخ از سرور دریافت نشد." }))
        .then((m) => setLog((l) => [...l.slice(0, -1), m]));
      return;
    }
    if (r.undo) {
      if (canUndo) undo();
      setLog((l) => [...l, { role: "user", text: value }, { role: "bot", text: canUndo ? "آخرین تغییر برگردانده شد." : "تغییری برای بازگردانی وجود ندارد." }]);
      return;
    }
    const first = !draft.items.length;
    if (r.ops.length) {
      dispatch(first ? [{ type: "set", patch: { source: "assistant" } } as DraftOp, ...r.ops] : r.ops);
      onApplied();
    }
    if (r.searches.length) void resolveCatalog(r.searches);
    const addedItems = r.changes.some((c) => c.startsWith("قلم"));
    setLog((l) => [...l, { role: "user", text: value }, {
      role: "bot",
      text: r.ops.length ? "پیش‌نویس به‌روز شد:" : "",
      changes: [...r.changes, ...(addedItems ? ["قیمت اقلام پس از استعلام از تأمین‌کنندگان مشخص می‌شود."] : [])],
      questions: r.questions,
    }]);
  }

  return (
    <div className={s.chat}>
      <div className={s.chatHead}>
        <div><strong><Bot size={18} /> 60AI · دستیار خرید سازمانی</strong><small>تغییرات مستقیم روی پیش‌نویس اعمال می‌شود</small></div>
        <button type="button" className={cx(s.btn, s.sm)} style={{ background: "transparent", color: "#cfe0ee", borderColor: "#ffffff26" }} onClick={undo} disabled={!canUndo}><Undo2 /> بازگردانی</button>
      </div>
      <div className={s.chatLog} aria-live="polite">
        {log.map((m, i) => (
          <div key={i} className={cx(s.msg, m.role === "user" ? s.msgUser : s.msgBot)}>
            {m.text}
            {m.changes && m.changes.length > 0 && <ul>{m.changes.map((c) => <li key={c}>{c}</li>)}</ul>}
            {m.questions?.map((q) => <span key={q} className={s.msgQ}><MessageSquare size={12} /> {q}</span>)}
            {m.products && (
              <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
                {m.products.map((p) => (
                  <div key={p.id} style={{ display: "flex", gap: 8, alignItems: "center", background: "#ffffff0f", borderRadius: 10, padding: 6 }}>
                    <span className={s.thumb} style={{ width: 36, height: 36 }}>{p.image_url ? <img src={p.image_url} alt="" /> : <Package />}</span>
                    <span style={{ flex: 1, minWidth: 0, fontSize: 12 }}><b style={{ display: "block" }}>{p.name}</b><span style={{ color: "#9fb7c9" }}>{p.category?.name}{p.purchasable && p.price_minor ? ` · ${money(p.price_minor)}` : " · نیازمند استعلام"}</span></span>
                    <button type="button" className={cx(s.btn, s.sm)} onClick={() => { dispatch({ type: "addItem", item: newItem(p.name, 1, linkPatch(p)) }); onApplied(); }}>افزودن</button>
                  </div>
                ))}
              </div>
            )}
            {m.compare && (m.compare.a || m.compare.b) && (
              <table style={{ width: "100%", marginTop: 8, fontSize: 12, borderCollapse: "collapse" }}>
                <tbody>
                  {([["نام", (x: Product) => x.name], ["برند", (x: Product) => x.brand ?? "—"], ["دسته", (x: Product) => x.category?.name ?? "—"], ["قیمت", (x: Product) => (x.purchasable && x.price_minor ? money(x.price_minor) : "نیازمند استعلام")]] as [string, (x: Product) => string][]).map(([k, f]) => (
                    <tr key={k} style={{ borderTop: "1px solid #ffffff1a" }}><th style={{ textAlign: "right", padding: 4, color: "#9fb7c9" }}>{k}</th><td style={{ padding: 4 }}>{m.compare!.a ? f(m.compare!.a) : "—"}</td><td style={{ padding: 4 }}>{m.compare!.b ? f(m.compare!.b) : "—"}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
            {m.link && <Link href={m.link.href} className={cx(s.btn, s.sm)} style={{ marginTop: 8, background: "transparent", color: "#9fd0ff", borderColor: "#ffffff26" }}>{m.link.label}</Link>}
            {m.role === "bot" && i > 0 && m.changes?.length ? (
              <button type="button" onClick={onShowDraft} className={cx(s.btn, s.sm, s.mOnly)} style={{ marginTop: 8, background: "transparent", color: "#9fd0ff", borderColor: "#ffffff26" }}>مشاهده پیش‌نویس</button>
            ) : null}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form className={s.chatInput} onSubmit={submit}>
        <div className={s.examples} aria-label="پیشنهادها">
          {suggestions.map((x) => <button type="button" key={x} onClick={() => submit(undefined, x)}>{x}</button>)}
        </div>
        <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="مثلاً: برای ۳۰۰ نفر پک یلدا، سرانه ۲ میلیون، تحویل تهران ۱۵۰ و کرج ۱۵۰ تا ۲۵ آذر"
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }} aria-label="پیام به دستیار" />
        <div className={s.spread}>
          <span style={{ fontSize: 11, color: "#8ba6ba" }}>Enter ارسال · Shift+Enter خط جدید · «برگرد» برای بازگردانی</span>
          <button type="submit" className={cx(s.btn, s.primary, s.sm)} disabled={!text.trim()}><Send /> ارسال</button>
        </div>
      </form>
    </div>
  );
}

// ── Catalog picker drawer ──────────────────────────────────────────────────

function CatalogPicker({ open, title, onClose, onPick, onFreeText, currency }: {
  open: boolean; title: string; onClose: () => void; onPick: (p: Product, qty: number) => void; onFreeText: (name: string, qty: number) => void; currency: string;
}) {
  const [q, setQ] = useState("");
  const [qty, setQty] = useState(1);
  const [items, setItems] = useState<Product[] | null>(null);
  useEffect(() => {
    if (!open) return;
    const c = new AbortController();
    const t = setTimeout(() => {
      setItems(null);
      catalog.list({ q: q.trim() || undefined, page_size: 24 }).then((r) => { if (!c.signal.aborted) setItems(r.items); }).catch(() => setItems([]));
    }, 250);
    return () => { clearTimeout(t); c.abort(); };
  }, [q, open]);
  return (
    <Drawer open={open} title={title} onClose={onClose}>
      <div className={s.row}>
        <input className={s.input} style={{ flex: 1 }} autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="جستجو در کاتالوگ…" aria-label="جستجوی کالا" />
        <QtyStepper value={qty} onChange={setQty} label="تعداد" />
      </div>
      {q.trim() && (
        <button type="button" className={cx(s.btn, s.sm)} onClick={() => onFreeText(q.trim(), qty)}><Plus /> افزودن «{q.trim()}» به‌صورت شرح آزاد</button>
      )}
      {items === null ? (
        <div className={s.stack} style={{ gap: 8 }}>{[0, 1, 2].map((k) => <div key={k} className={s.skeleton} style={{ height: 56 }} />)}</div>
      ) : items.length === 0 ? (
        <p className={s.muted}>کالایی پیدا نشد؛ می‌توانید آن را به‌صورت شرح آزاد اضافه کنید.</p>
      ) : items.filter((p) => p.master_product_id).map((p) => {
        const priced = p.purchasable && p.price_minor;
        return (
          <button type="button" key={p.id} onClick={() => onPick(p, qty)} className={s.cardFlat} style={{ display: "flex", gap: 10, alignItems: "center", textAlign: "right" }}>
            <span className={s.thumb}>{p.image_url ? <img src={p.image_url} alt="" /> : <Package />}</span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <b style={{ display: "block", fontSize: 13 }}>{p.name}</b>
              <small className={s.muted}>{p.category?.name ?? ""}{p.sku ? ` · ${p.sku}` : ""}</small>
            </span>
            {priced ? <Chip tone="violet">{money(p.price_minor, currency)}</Chip> : <Chip tone="warn">نیازمند استعلام</Chip>}
          </button>
        );
      })}
    </Drawer>
  );
}
