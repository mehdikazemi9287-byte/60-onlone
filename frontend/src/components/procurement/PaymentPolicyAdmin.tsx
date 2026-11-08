"use client";

// Payment-policy lifecycle for one organization: draft → review → approved (scheduled/active/superseded).
// Used by organization admins/finance (propose) and platform admins (review). Values come only from what
// the proposer enters; nothing is pre-filled as a business policy.

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, FilePlus2, History, Lock, Send, ShieldCheck, XCircle } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { apiRequest, newIdempotencyKey } from "@/lib/api";
import { PAY_METHOD, money, type PayMethod, type PolicyDraft, type PolicyList } from "@/lib/procurement/api";
import { formatJalali, formatJalaliDateTime } from "@/lib/procurement/jalali";
import { Chip, Drawer, Empty, Notice, cx, n } from "./ui";
import s from "./proc.module.css";

const METHODS: PayMethod[] = ["cash", "cheque", "credit", "bill"];
const LIFE_TONE: Record<string, "ok" | "warn" | "bad" | "info" | "muted"> = { active: "ok", scheduled: "info", in_review: "warn", draft: "muted", superseded: "muted", rejected: "bad", withdrawn: "muted" };
const EV_FA: Record<string, string> = { created: "ایجاد پیش‌نویس", edited: "ویرایش", submitted: "ارسال برای بررسی", approved: "تصویب", rejected: "رد", withdrawn: "انصراف" };

type Form = { version: string; contract_reference: string; effective_from: string; methods: PayMethod[]; credit: string; max_parts: string; max_term_days: string; dual: string };
const empty: Form = { version: "", contract_reference: "", effective_from: "", methods: [], credit: "", max_parts: "", max_term_days: "", dual: "" };
const toMinor = (toman: string) => (toman.trim() ? Math.round(Number(toman.replace(/[,،\s]/g, "")) * 10) : null);

export default function PaymentPolicyAdmin({ orgId }: { orgId: string | number }) {
  const { token } = useAuth();
  const [d, setD] = useState<PolicyList | null>(null);
  const [error, setError] = useState(""), [flash, setFlash] = useState("");
  const [edit, setEdit] = useState<null | { draft?: PolicyDraft }>(null);
  const [review, setReview] = useState<null | { draft: PolicyDraft; action: "approve" | "reject" }>(null);
  const [busy, setBusy] = useState(false);
  const base = `/organizations/${orgId}/payment-policies`;

  const load = useCallback(() => {
    if (!token || !orgId) return;
    apiRequest<PolicyList>(base, { token }).then((r) => { setD(r); setError(""); }).catch((e) => setError(e.message));
  }, [token, orgId, base]);
  useEffect(load, [load]);

  const post = async (path: string, body: unknown, msg: string, method = "POST") => {
    if (!token || busy) return false;
    setBusy(true); setFlash("");
    try {
      await apiRequest(path, { token, method, body: JSON.stringify(body ?? {}), headers: { "Idempotency-Key": newIdempotencyKey() } });
      setFlash(msg); load(); return true;
    } catch (e) { setFlash(e instanceof Error ? e.message : "ثبت ناموفق بود"); return false; } finally { setBusy(false); }
  };

  if (error) return <Empty icon={<Lock />} title="دسترسی مدیر یا مالی سازمان لازم است">{error}</Empty>;
  if (!d) return <div className={s.skeleton} style={{ height: 260 }} />;
  const active = d.items.find((i) => i.lifecycle === "active");
  return (
    <div className={s.stack}>
      <header className={s.head}>
        <div className={s.headRow}>
          <div><div className={s.eyebrow}>سیاست پرداخت سازمان</div><h1 className={s.title}>{d.organization.display_name}</h1>
            <div className={s.meta}>{d.organization.provenance !== "real" && <Chip tone="violet">سازمان {d.organization.provenance.toUpperCase()} · فقط سیاست TEST</Chip>}
              {active ? <Chip tone="ok" dot>سیاست فعال: نسخه {active.version}</Chip> : <Chip tone="warn" dot>سیاست فعالی تصویب نشده است</Chip>}</div></div>
          {d.can_propose && <button className={cx(s.btn, s.primary)} onClick={() => setEdit({})}><FilePlus2 /> پیش‌نویس جدید</button>}
        </div>
      </header>
      {flash && <Notice tone="info" icon={<ShieldCheck />}>{flash}</Notice>}
      <Notice tone="info" icon={<AlertTriangle />}>تفکیک وظایف ثابت است: پیشنهاددهنده نمی‌تواند سیاست خود را تصویب کند و ثبت‌کننده برنامه پرداخت نمی‌تواند همان را تأیید کند. تصویب فقط توسط مدیر پلتفرم انجام می‌شود.</Notice>
      {!d.items.length ? <Empty icon={<ShieldCheck />} title="هنوز سیاستی پیشنهاد نشده است">تا تصویب سیاست، ثبت برنامه پرداخت، اعتبار، وصول و تسویه برای این سازمان غیرفعال است.</Empty> : d.items.map((p) => (
        <section key={p.id} className={s.card}>
          <div className={s.sectionHead}>
            <div><h2>نسخه {p.version} <Chip tone={LIFE_TONE[p.lifecycle]} dot>{p.lifecycle_fa}</Chip> <Chip tone={p.environment === "test" ? "violet" : "ok"}>{p.environment === "test" ? "TEST" : "واقعی"}</Chip></h2>
              <p>اجرا از {formatJalali(p.effective_from)} · پیشنهاد: {p.proposer}{p.reviewer ? ` · بررسی: ${p.reviewer}` : ""}{p.contract_reference ? ` · قرارداد: ${p.contract_reference}` : ""}</p></div>
            <div className={s.headActions}>
              {p.status === "draft" && d.can_propose && <button className={cx(s.btn, s.sm)} onClick={() => setEdit({ draft: p })}>ویرایش</button>}
              {p.status === "draft" && d.can_propose && <button className={cx(s.btn, s.sm, s.primary)} disabled={busy} onClick={() => post(`${base}/${p.id}/submit`, {}, "برای بررسی ارسال شد.")}><Send /> ارسال برای بررسی</button>}
              {(p.status === "draft" || p.status === "in_review") && d.can_propose && <button className={cx(s.btn, s.sm, s.danger)} disabled={busy} onClick={() => post(`${base}/${p.id}/withdraw`, {}, "پیش‌نویس کنار گذاشته شد.")}>انصراف</button>}
              {p.status === "in_review" && d.can_review && <>
                <button className={cx(s.btn, s.sm, s.primary)} onClick={() => setReview({ draft: p, action: "approve" })}><CheckCircle2 /> تصویب</button>
                <button className={cx(s.btn, s.sm, s.danger)} onClick={() => setReview({ draft: p, action: "reject" })}><XCircle /> رد</button></>}
            </div>
          </div>
          <div className={s.grid3}>
            <div className={s.stat}><small>روش‌های مجاز</small><b>{p.rules.methods.map((m) => PAY_METHOD[m]).join("، ")}</b></div>
            <div className={s.stat}><small>سقف اعتبار</small><b>{p.rules.credit_limit_minor ? money(p.rules.credit_limit_minor) : "—"}</b></div>
            <div className={s.stat}><small>حداکثر بخش/قسط</small><b>{n(p.rules.max_parts)}</b></div>
            <div className={s.stat}><small>حداکثر مدت سررسید</small><b>{p.rules.max_term_days != null ? `${n(p.rules.max_term_days)} روز` : "—"}</b></div>
            <div className={s.stat}><small>تأیید دومرحله‌ای از مبلغ</small><b>{p.rules.dual_approval_threshold_minor ? money(p.rules.dual_approval_threshold_minor) : "ندارد"}</b></div>
            <div className={s.stat}><small>تفکیک وظایف</small><b>الزامی</b></div>
          </div>
          {p.review_note && <p className={s.small}>یادداشت بررسی: {p.review_note}</p>}
          {!!p.events?.length && <details style={{ marginTop: 10 }}><summary className={s.small}><History size={14} /> تاریخچه ({n(p.events.length)})</summary>
            <div className={s.timeline}>{p.events.map((e, i) => <div key={i} className={s.tItem}><span className={s.tDot} /><div><b>{EV_FA[e.action] ?? e.action}</b> · {e.actor}{e.note && <div className={s.small}>{e.note}</div>}</div><time>{formatJalaliDateTime(e.created_at)}</time></div>)}</div></details>}
        </section>
      ))}
      {edit && <PolicyForm d={d} draft={edit.draft} busy={busy} onClose={() => setEdit(null)} onSave={async (body) => {
        const ok = edit.draft ? await post(`${base}/${edit.draft.id}`, { ...body, expected_row_version: edit.draft.row_version }, "پیش‌نویس ذخیره شد.", "PUT")
          : await post(base, body, "پیش‌نویس ایجاد شد.");
        if (ok) setEdit(null);
      }} />}
      {review && <ReviewDrawer r={review} busy={busy} onClose={() => setReview(null)} onSend={async (note) => {
        if (await post(`${base}/${review.draft.id}/review`, { action: review.action, note }, review.action === "approve" ? "سیاست تصویب شد." : "سیاست رد شد.")) setReview(null);
      }} />}
    </div>
  );
}

function PolicyForm({ d, draft, busy, onClose, onSave }: { d: PolicyList; draft?: PolicyDraft; busy: boolean; onClose: () => void; onSave: (b: Record<string, unknown>) => void }) {
  const [f, setF] = useState<Form>(() => draft ? {
    version: draft.version, contract_reference: draft.contract_reference ?? "", effective_from: draft.effective_from, methods: draft.rules.methods,
    credit: draft.rules.credit_limit_minor ? String(draft.rules.credit_limit_minor / 10) : "", max_parts: String(draft.rules.max_parts),
    max_term_days: draft.rules.max_term_days != null ? String(draft.rules.max_term_days) : "", dual: draft.rules.dual_approval_threshold_minor ? String(draft.rules.dual_approval_threshold_minor / 10) : "",
  } : empty);
  const set = (k: keyof Form, v: Form[keyof Form]) => setF((x) => ({ ...x, [k]: v }));
  const toggle = (m: PayMethod) => set("methods", f.methods.includes(m) ? f.methods.filter((x) => x !== m) : [...f.methods, m]);
  const body = {
    version: f.version, environment: d.allowed_environment, contract_reference: f.contract_reference || null, effective_from: f.effective_from,
    rules: { methods: f.methods, credit_limit_minor: f.methods.includes("credit") ? toMinor(f.credit) : null, max_parts: f.max_parts ? Number(f.max_parts) : null,
      max_term_days: f.max_term_days ? Number(f.max_term_days) : null, dual_approval_threshold_minor: toMinor(f.dual) },
  };
  return (
    <Drawer open title={draft ? `ویرایش نسخه ${draft.version}` : "پیش‌نویس سیاست پرداخت"} onClose={onClose}
      footer={<button className={cx(s.btn, s.primary)} disabled={busy || !f.version || !f.effective_from || !f.methods.length || !f.max_parts} onClick={() => onSave(body)}>{busy ? "در حال ذخیره…" : "ذخیره پیش‌نویس"}</button>}>
      <div className={s.stack}>
        <Notice tone="info" icon={<AlertTriangle />}>مقادیر باید از مصوبه/قرارداد واقعی سازمان وارد شوند. محیط این سازمان: <b>{d.allowed_environment === "test" ? "TEST (بدون اثر مالی واقعی)" : "واقعی"}</b></Notice>
        <div className={s.grid2}>
          <label className={s.field}>شماره نسخه<input className={s.input} value={f.version} onChange={(e) => set("version", e.target.value)} placeholder="مثلاً 1405-01" /></label>
          <label className={s.field}>تاریخ اجرا (میلادی)<input className={s.input} type="date" value={f.effective_from} onChange={(e) => set("effective_from", e.target.value)} /></label>
        </div>
        <label className={s.field}>مرجع قرارداد/مصوبه{d.allowed_environment === "production" ? " (الزامی)" : ""}<input className={s.input} value={f.contract_reference} onChange={(e) => set("contract_reference", e.target.value)} /></label>
        <fieldset className={s.field} style={{ border: 0, padding: 0 }}><legend>روش‌های مجاز</legend>
          <div className={s.row}>{METHODS.map((m) => <label key={m} className={s.row}><input type="checkbox" checked={f.methods.includes(m)} onChange={() => toggle(m)} /> {PAY_METHOD[m]}</label>)}</div></fieldset>
        <div className={s.grid2}>
          {f.methods.includes("credit") && <label className={s.field}>سقف اعتبار (تومان)<input className={s.input} inputMode="numeric" value={f.credit} onChange={(e) => set("credit", e.target.value)} /></label>}
          <label className={s.field}>حداکثر تعداد بخش/قسط (۱ تا ۱۲)<input className={s.input} inputMode="numeric" value={f.max_parts} onChange={(e) => set("max_parts", e.target.value)} /></label>
          <label className={s.field}>حداکثر مدت سررسید (روز)<input className={s.input} inputMode="numeric" value={f.max_term_days} onChange={(e) => set("max_term_days", e.target.value)} /></label>
          <label className={s.field}>تأیید دو نفره از مبلغ (تومان، اختیاری)<input className={s.input} inputMode="numeric" value={f.dual} onChange={(e) => set("dual", e.target.value)} /></label>
        </div>
      </div>
    </Drawer>
  );
}

function ReviewDrawer({ r, busy, onClose, onSend }: { r: { draft: PolicyDraft; action: "approve" | "reject" }; busy: boolean; onClose: () => void; onSend: (note: string) => void }) {
  const [note, setNote] = useState("");
  return (
    <Drawer open title={`${r.action === "approve" ? "تصویب" : "رد"} نسخه ${r.draft.version}`} onClose={onClose}
      footer={<button className={cx(s.btn, r.action === "approve" ? s.primary : s.danger)} disabled={busy || (r.action === "reject" && !note.trim())} onClick={() => onSend(note)}>{r.action === "approve" ? "تصویب نهایی" : "ثبت رد"}</button>}>
      <div className={s.stack}>
        {r.action === "approve" && <Notice icon={<AlertTriangle />}>با تصویب، از تاریخ {formatJalali(r.draft.effective_from)} این قواعد روی همه برنامه‌های پرداخت این سازمان اعمال می‌شود. سیاست مصوب قابل ویرایش نیست؛ تغییر فقط با نسخه جدید.</Notice>}
        <label className={s.field}>یادداشت{r.action === "reject" ? " (علت رد، الزامی)" : ""}<textarea className={s.textarea} rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></label>
      </div>
    </Drawer>
  );
}
