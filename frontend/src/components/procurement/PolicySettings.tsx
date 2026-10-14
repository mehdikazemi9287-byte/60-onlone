"use client";

// Organization procurement policy: who may submit and the approval chain.
// Only the organization admin can change it; everyone else sees it read-only.

import { useEffect, useState } from "react";
import { AlertTriangle, ArrowDown, ArrowUp, Check, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { useOrganization } from "@/components/organization/Dashboard";
import { useAuth } from "@/lib/auth-context";
import { ROLE_LABEL, proc, type Policy } from "@/lib/procurement/api";
import { formatJalaliDateTime } from "@/lib/procurement/jalali";
import { Chip, Notice, cx, n } from "./ui";
import s from "./proc.module.css";

type Step = Policy["approval_chain"][number];
const MATCHERS: { value: string; label: string }[] = [
  { value: "procurement_role:approver", label: ROLE_LABEL.approver },
  { value: "role:procurement_agent", label: ROLE_LABEL.procurement_agent },
  { value: "procurement_role:procurement_officer", label: ROLE_LABEL.procurement_officer },
  { value: "role:organization_finance", label: ROLE_LABEL.organization_finance },
  { value: "role:organization_admin", label: ROLE_LABEL.organization_admin },
];
const matcherOf = (st: Step) => (st.role ? `role:${st.role}` : `procurement_role:${st.procurement_role}`);
const PRESET: Step[] = [
  { key: "department", label: "مدیر واحد", role: null, procurement_role: "approver" },
  { key: "procurement", label: "تدارکات", role: "procurement_agent", procurement_role: null },
  { key: "finance", label: "مالی", role: "organization_finance", procurement_role: null },
  { key: "admin", label: "مدیر سازمان", role: "organization_admin", procurement_role: null },
];

export default function PolicySettings() {
  const { token } = useAuth();
  const o = useOrganization(true);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [chain, setChain] = useState<Step[]>([]);
  const [allowed, setAllowed] = useState(true);
  const [msg, setMsg] = useState<{ tone: "info" | "bad"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const admin = o.org?.membership.role === "organization_admin";

  useEffect(() => {
    if (!token || !o.selected) return;
    proc.policy(token, o.selected).then((r) => { setPolicy(r.policy); setChain(r.policy.approval_chain); setAllowed(r.policy.employee_submit_allowed); })
      .catch((e) => setMsg({ tone: "bad", text: e.message }));
  }, [token, o.selected]);

  const update = (i: number, patch: Partial<Step>) => setChain((c) => c.map((x, k) => (k === i ? { ...x, ...patch } : x)));
  const move = (i: number, d: -1 | 1) => setChain((c) => { const x = [...c]; [x[i], x[i + d]] = [x[i + d], x[i]]; return x; });

  async function save() {
    if (!token || !policy) return;
    setBusy(true); setMsg(null);
    try {
      const r = await proc.savePolicy(token, o.selected, { employee_submit_allowed: allowed, approval_chain: chain, version: policy.version });
      setPolicy(r.policy); setChain(r.policy.approval_chain);
      setMsg({ tone: "info", text: "سیاست خرید ذخیره شد و برای درخواست‌های جدید اعمال می‌شود." });
    } catch (e) { setMsg({ tone: "bad", text: e instanceof Error ? e.message : "ذخیره ناموفق بود" }); }
    finally { setBusy(false); }
  }

  return (
    <div className={s.root}>
      <header className={s.head}>
        <div className={s.eyebrow}>میز کار سازمانی / سیاست خرید</div>
        <h1 className={s.title}>سیاست خرید و زنجیره تأیید</h1>
        <div className={s.meta}>
          <span>{o.org?.display_name ?? "—"}</span>
          {policy && <span>نسخه {n(policy.version)}{policy.updated_at ? ` · ${formatJalaliDateTime(policy.updated_at)}` : " · پیش‌فرض"}</span>}
          {!admin && <Chip>فقط مشاهده — تغییر با مدیر سازمان</Chip>}
        </div>
      </header>
      {msg && <div style={{ marginBottom: 12 }}><Notice tone={msg.tone} icon={msg.tone === "bad" ? <AlertTriangle /> : <Check />}>{msg.text}</Notice></div>}
      <div className={s.stack}>
        <section className={s.card}>
          <div className={s.sectionHead}><div><h2><ShieldCheck /> ارسال درخواست توسط کارمند</h2><p>اگر غیرفعال باشد، کارمند فقط پیش‌نویس می‌سازد و مدیر سازمان ارسال می‌کند.</p></div></div>
          <div className={s.seg}>
            <button type="button" disabled={!admin} className={cx(allowed && s.segOn)} onClick={() => setAllowed(true)}>مجاز</button>
            <button type="button" disabled={!admin} className={cx(!allowed && s.segOn)} onClick={() => setAllowed(false)}>فقط پیش‌نویس</button>
          </div>
        </section>
        <section className={s.card}>
          <div className={s.sectionHead}>
            <div><h2><ShieldCheck /> زنجیره تأیید</h2><p>مراحل به ترتیب انجام می‌شوند. بدون مرحله، یک تأیید توسط مدیر سازمان یا تأییدکننده کافی است.</p></div>
            {admin && <div className={s.row}>
              <button type="button" className={cx(s.btn, s.sm)} onClick={() => setChain(PRESET)}>الگوی پیشنهادی</button>
              <button type="button" className={cx(s.btn, s.sm)} disabled={chain.length >= 6} onClick={() => setChain([...chain, { key: `step${Date.now().toString(36)}`, label: "", role: null, procurement_role: "approver" }])}><Plus /> مرحله</button>
            </div>}
          </div>
          {!chain.length ? <Notice tone="info" icon={<ShieldCheck />}>تأیید یک‌مرحله‌ای (پیش‌فرض)</Notice> : (
            <div className={s.chain}>
              {chain.map((st, i) => (
                <div key={st.key} className={s.chainStep}>
                  <span className={s.chainIcon}>{n(i + 1)}</span>
                  <div className={s.row}>
                    <input className={cx(s.input, s.inputSm)} style={{ width: 180 }} disabled={!admin} value={st.label} placeholder="عنوان مرحله" onChange={(e) => update(i, { label: e.target.value })} />
                    <select className={cx(s.select, s.inputSm)} style={{ width: 200 }} disabled={!admin} value={matcherOf(st)} onChange={(e) => {
                      const [kind, v] = e.target.value.split(":");
                      update(i, kind === "role" ? { role: v, procurement_role: null } : { role: null, procurement_role: v });
                    }}>
                      {MATCHERS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                    </select>
                    {admin && <>
                      <button type="button" className={cx(s.btn, s.sm, s.icon)} disabled={i === 0} onClick={() => move(i, -1)} aria-label="بالا"><ArrowUp /></button>
                      <button type="button" className={cx(s.btn, s.sm, s.icon)} disabled={i === chain.length - 1} onClick={() => move(i, 1)} aria-label="پایین"><ArrowDown /></button>
                      <button type="button" className={cx(s.btn, s.sm, s.icon, s.danger)} onClick={() => setChain(chain.filter((_, k) => k !== i))} aria-label="حذف"><Trash2 /></button>
                    </>}
                  </div>
                </div>
              ))}
            </div>
          )}
          <p className={s.small} style={{ color: "var(--muted)" }}>مدیر سازمان می‌تواند هر مرحله را انجام دهد. تغییر سیاست در رویدادها ثبت می‌شود.</p>
        </section>
        {admin && <div className={s.row}><button className={cx(s.btn, s.primary)} disabled={busy || chain.some((c) => !c.label.trim())} onClick={save}>{busy ? "در حال ذخیره…" : "ذخیره سیاست"}</button></div>}
      </div>
    </div>
  );
}
