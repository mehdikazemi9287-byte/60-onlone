"use client";

// Platform access console: organization roles, operations mandates, supplier users,
// payment-policy review queue and the append-only access audit. Every change needs a reason.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Building2, History, KeyRound, Lock, ShieldCheck, Store, UserPlus } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { apiRequest, newIdempotencyKey } from "@/lib/api";
import { formatJalaliDateTime } from "@/lib/procurement/jalali";
import type { PolicyDraft } from "@/lib/procurement/api";
import { Chip, Drawer, Empty, Notice, cx } from "@/components/procurement/ui";
import s from "@/components/procurement/proc.module.css";

type Member = { id: number; user_id: number; full_name: string; email: string; role: string; procurement_role: string | null; status: string };
type Grant = { user_id: number; full_name: string; email: string; capability: string; status: string; mandate_reference: string };
type Org = { id: number; display_name: string; status: string; provenance: string; members: Member[]; operations: Grant[] };
type SupUser = { user_id: number; full_name: string; email: string; role: string; status: string };
type Sup = { id: number; display_name: string; status: string; onboarding_stage: string; provenance: string; is_demo: boolean; users: SupUser[] };
type Ev = { id: number; scope: string; action: string; reason: string; created_at: string; actor: string; subject: string; organization_id: number | null; supplier_id: number | null; before: unknown; after: unknown };
type Overview = { organizations: Org[]; suppliers: Sup[]; events: Ev[]; policy_queue: PolicyDraft[]; defaults: { ops_eligible_platform_roles: string[] } };
export type U = { id: number; email: string; full_name: string; role: string; is_active: number };

const ROLE_FA: Record<string, string> = { employee: "کارمند", organization_admin: "مدیر سازمان", procurement_agent: "کارشناس تدارکات", organization_finance: "مالی سازمان" };
const PROC_FA: Record<string, string> = { "": "—", requester: "درخواست‌دهنده", approver: "تأییدکننده", procurement_officer: "مسئول خرید" };
const CAP_FA: Record<string, string> = { case_manager: "مدیر پرونده", case_agent: "کارشناس پرونده" };
const SCOPE_FA: Record<string, string> = { organization_member: "نقش سازمانی", operations_grant: "مجوز عملیات", supplier_user: "کاربر تأمین‌کننده" };
const ACT_FA: Record<string, string> = { grant: "اعطا", revoke: "لغو", change: "تغییر" };
const PROV: Record<string, [string, "ok" | "warn" | "violet"]> = { real: ["واقعی", "ok"], demo: ["DEMO", "warn"], test: ["TEST", "violet"] };

type Dlg = null | { kind: "member"; org: Org; m: Member } | { kind: "grant"; org: Org } | { kind: "supplier"; sup: Sup }
  | { kind: "revoke"; label: string; path: string; body: Record<string, unknown> };

export default function AccessConsole() {
  const { token, user, loading } = useAuth();
  const [d, setD] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"orgs" | "suppliers" | "policies" | "audit">("orgs");
  const [dlg, setDlg] = useState<Dlg>(null);
  const [flash, setFlash] = useState("");

  const load = useCallback(() => {
    if (!token) return;
    apiRequest<Overview>("/admin/access", { token }).then((r) => { setD(r); setError(""); }).catch((e) => setError(e.message));
  }, [token]);
  useEffect(load, [load]);

  if (loading) return <div className={s.skeleton} style={{ height: 300 }} />;
  if (!user) return <Empty icon={<Lock />} title="ورود لازم است" action={<Link className={cx(s.btn, s.primary)} href="/login?next=/admin/access">ورود</Link>} />;
  if (error) return <Empty icon={<Lock />} title="دسترسی مدیر پلتفرم لازم است">{error}</Empty>;
  if (!d) return <div className={s.skeleton} style={{ height: 300 }} />;

  const done = (msg: string) => { setDlg(null); setFlash(msg); load(); };
  return (
    <div className={s.root}>
      <header className={s.head}>
        <div className={s.eyebrow}>مدیریت پلتفرم</div>
        <h1 className={s.title}>دسترسی‌ها و نقش‌ها</h1>
        <div className={s.meta}><span>هر تغییر با دلیل ثبت و در دفتر غیرقابل ویرایش نگه‌داری می‌شود.</span></div>
      </header>
      {flash && <Notice tone="info" icon={<ShieldCheck />}>{flash}</Notice>}
      <div className={s.tabs} role="tablist">
        {([["orgs", "سازمان‌ها", Building2], ["suppliers", "تأمین‌کنندگان", Store], ["policies", `سیاست‌های پرداخت (${d.policy_queue.length})`, KeyRound], ["audit", "دفتر تغییرات", History]] as const).map(([k, l, I]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={cx(s.tab, tab === k && s.tabOn)} onClick={() => setTab(k)}><I size={16} /> {l}</button>
        ))}
      </div>

      {tab === "orgs" && <div className={s.stack}>{d.organizations.map((o) => (
        <section key={o.id} className={s.card}>
          <div className={s.sectionHead}>
            <div><h2>{o.display_name} <Chip tone={PROV[o.provenance]?.[1]}>{PROV[o.provenance]?.[0]}</Chip></h2><p>وضعیت: {o.status === "active" ? "فعال" : o.status}</p></div>
            <div className={s.headActions}>
              <Link className={cx(s.btn, s.sm)} href={`/admin/policies?org=${o.id}`}>سیاست پرداخت</Link>
              <button className={cx(s.btn, s.sm, s.primary)} onClick={() => setDlg({ kind: "grant", org: o })}><UserPlus /> مجوز عملیات</button>
            </div>
          </div>
          <div className={s.tableWrap}><table className={cx(s.table, s.cards)}>
            <thead><tr><th>عضو</th><th>نقش سازمانی</th><th>نقش تدارکاتی</th><th>وضعیت</th><th /></tr></thead>
            <tbody>{o.members.map((m) => (
              <tr key={m.id}><td className={s.full}><b>{m.full_name}</b><div className={s.small} style={{ color: "var(--muted)" }}>{m.email}</div></td>
                <td data-label="نقش">{ROLE_FA[m.role] ?? m.role}</td><td data-label="تدارکات">{PROC_FA[m.procurement_role ?? ""]}</td>
                <td data-label="وضعیت"><Chip tone={m.status === "active" ? "ok" : "muted"} dot>{m.status === "active" ? "فعال" : m.status}</Chip></td>
                <td><button className={cx(s.btn, s.sm)} onClick={() => setDlg({ kind: "member", org: o, m })}>تغییر نقش</button></td></tr>
            ))}</tbody>
          </table></div>
          <h3 className={s.small} style={{ margin: "14px 0 6px" }}>مجوزهای عملیات داخلی</h3>
          {!o.operations.length ? <p className={s.small} style={{ color: "var(--muted)" }}>هیچ مجوز عملیاتی اعطا نشده است.</p> : (
            <div className={s.tableWrap}><table className={cx(s.table, s.cards)}>
              <thead><tr><th>کارمند</th><th>مجوز</th><th>مرجع حکم</th><th>وضعیت</th><th /></tr></thead>
              <tbody>{o.operations.map((g) => (
                <tr key={g.user_id + g.capability}><td className={s.full}><b>{g.full_name}</b><div className={s.small} style={{ color: "var(--muted)" }}>{g.email}</div></td>
                  <td data-label="مجوز">{CAP_FA[g.capability]}</td><td data-label="مرجع">{g.mandate_reference}</td>
                  <td data-label="وضعیت"><Chip tone={g.status === "active" ? "ok" : "muted"} dot>{g.status === "active" ? "فعال" : "لغوشده"}</Chip></td>
                  <td>{g.status === "active" && <button className={cx(s.btn, s.sm, s.danger)} onClick={() => setDlg({ kind: "revoke", label: `لغو ${CAP_FA[g.capability]} ${g.full_name}`,
                    path: `/admin/access/organizations/${o.id}/operations/revoke`, body: { user_id: g.user_id, capability: g.capability } })}>لغو</button>}</td></tr>
              ))}</tbody>
            </table></div>
          )}
        </section>
      ))}</div>}

      {tab === "suppliers" && <div className={s.stack}>
        <Notice tone="info" icon={<AlertTriangle />}>تأمین‌کنندگان DEMO/TEST از داده‌های نمونه‌اند؛ در استعلام سازمان واقعی قابل دعوت نیستند و در فهرست‌ها جدا نمایش داده می‌شوند.</Notice>
        {d.suppliers.map((sp) => (
          <section key={sp.id} className={s.card} style={sp.is_demo ? { borderStyle: "dashed" } : undefined}>
            <div className={s.sectionHead}>
              <div><h2>{sp.display_name} <Chip tone={PROV[sp.provenance]?.[1]}>{PROV[sp.provenance]?.[0]}</Chip></h2>
                <p>وضعیت {sp.status === "active" ? "فعال" : sp.status} · مرحله احراز: {sp.onboarding_stage}</p></div>
              <button className={cx(s.btn, s.sm, s.primary)} onClick={() => setDlg({ kind: "supplier", sup: sp })}><UserPlus /> افزودن کاربر</button>
            </div>
            {!sp.users.length ? <p className={s.small} style={{ color: "var(--muted)" }}>کاربر عملیاتی ندارد.</p> : (
              <div className={s.tableWrap}><table className={cx(s.table, s.cards)}>
                <thead><tr><th>کاربر</th><th>نقش</th><th>وضعیت</th><th /></tr></thead>
                <tbody>{sp.users.map((u) => (
                  <tr key={u.user_id}><td className={s.full}><b>{u.full_name}</b><div className={s.small} style={{ color: "var(--muted)" }}>{u.email}</div></td>
                    <td data-label="نقش">{u.role === "owner" ? "مالک" : "کاربر عملیاتی"}</td>
                    <td data-label="وضعیت"><Chip tone={u.status === "active" ? "ok" : "muted"} dot>{u.status === "active" ? "فعال" : "لغوشده"}</Chip></td>
                    <td>{u.status === "active" && <button className={cx(s.btn, s.sm, s.danger)} onClick={() => setDlg({ kind: "revoke", label: `لغو دسترسی ${u.full_name}`,
                      path: `/admin/access/suppliers/${sp.id}/users/revoke`, body: { user_id: u.user_id } })}>لغو</button>}</td></tr>
                ))}</tbody>
              </table></div>
            )}
          </section>
        ))}
      </div>}

      {tab === "policies" && <section className={s.card}>
        <div className={s.sectionHead}><div><h2>صف بررسی سیاست پرداخت</h2><p>تصویب فقط توسط مدیر پلتفرمی که پیشنهاددهنده نیست.</p></div></div>
        {!d.policy_queue.length ? <p className={s.small} style={{ color: "var(--muted)" }}>پیش‌نویس یا سیاست در انتظار بررسی وجود ندارد. هیچ سیاستی بدون تصمیم کسب‌وکار ایجاد نمی‌شود.</p> : (
          <div className={s.tableWrap}><table className={cx(s.table, s.cards)}>
            <thead><tr><th>سازمان</th><th>نسخه</th><th>محیط</th><th>وضعیت</th><th>پیشنهاددهنده</th><th /></tr></thead>
            <tbody>{d.policy_queue.map((p) => (
              <tr key={p.id}><td className={s.full}><b>{p.organization}</b></td><td data-label="نسخه">{p.version}</td>
                <td data-label="محیط"><Chip tone={p.environment === "test" ? "violet" : "ok"}>{p.environment === "test" ? "TEST" : "واقعی"}</Chip></td>
                <td data-label="وضعیت"><Chip tone="info" dot>{p.lifecycle_fa}</Chip></td><td data-label="پیشنهاددهنده">{p.proposer}</td>
                <td><Link className={cx(s.btn, s.sm)} href={`/admin/policies?org=${p.organization_id}`}>بررسی</Link></td></tr>
            ))}</tbody>
          </table></div>
        )}
      </section>}

      {tab === "audit" && <section className={s.card}>
        <div className={s.sectionHead}><div><h2><History /> دفتر تغییرات دسترسی</h2><p>ثبت غیرقابل ویرایش و حذف</p></div></div>
        {!d.events.length ? <p className={s.small} style={{ color: "var(--muted)" }}>تغییری ثبت نشده است.</p> : (
          <div className={s.timeline}>{d.events.map((e) => (
            <div key={e.id} className={s.tItem}><span className={s.tDot} /><div><b>{ACT_FA[e.action]} {SCOPE_FA[e.scope]}</b> · {e.subject}<span className={s.muted}> · توسط {e.actor}</span>
              <div className={s.small}>{e.reason}</div>
              <div className={s.small} style={{ color: "var(--muted)", overflowWrap: "anywhere" }}>{JSON.stringify(e.before)} ← {JSON.stringify(e.after)}</div></div>
              <time>{formatJalaliDateTime(e.created_at)}</time></div>
          ))}</div>
        )}
      </section>}

      <ChangeDrawer dlg={dlg} token={token!} onClose={() => setDlg(null)} onDone={done} />
    </div>
  );
}

export function UserPicker({ token, value, onChange }: { token: string; value: U | null; onChange: (u: U | null) => void }) {
  const [q, setQ] = useState(""), [items, setItems] = useState<U[]>([]);
  useEffect(() => {
    if (q.trim().length < 2) { setItems([]); return; }
    const c = new AbortController();
    const t = setTimeout(() => apiRequest<{ items: U[] }>(`/admin/access/users?q=${encodeURIComponent(q)}`, { token, signal: c.signal })
      .then((r) => setItems(r.items)).catch(() => {}), 250);
    return () => { clearTimeout(t); c.abort(); };
  }, [q, token]);
  if (value) return <div className={s.row} style={{ justifyContent: "space-between" }}><span><b>{value.full_name}</b> · {value.email} · نقش پلتفرم: {value.role}</span><button className={cx(s.btn, s.sm)} onClick={() => onChange(null)}>تغییر</button></div>;
  return (
    <label className={s.field}>جستجوی کاربر (ایمیل یا نام)
      <input className={s.input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="حداقل ۲ نویسه" />
      {items.map((u) => <button key={u.id} type="button" className={cx(s.btn, s.sm, s.ghost)} style={{ justifyContent: "flex-start" }} onClick={() => onChange(u)}>{u.full_name} · {u.email} · {u.role}</button>)}
    </label>
  );
}

function ChangeDrawer({ dlg, token, onClose, onDone }: { dlg: Dlg; token: string; onClose: () => void; onDone: (m: string) => void }) {
  const [reason, setReason] = useState(""), [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const [role, setRole] = useState(""), [proc, setProc] = useState(""), [cap, setCap] = useState("case_agent"), [mandate, setMandate] = useState("");
  const [u, setU] = useState<U | null>(null), [supRole, setSupRole] = useState("operator"), [convert, setConvert] = useState(false);
  useEffect(() => {
    setReason(""); setErr(""); setU(null); setMandate(""); setConvert(false);
    if (dlg?.kind === "member") { setRole(dlg.m.role); setProc(dlg.m.procurement_role ?? ""); }
  }, [dlg]);
  if (!dlg) return null;
  const send = async (method: string, path: string, body: Record<string, unknown>, msg: string) => {
    setBusy(true); setErr("");
    try {
      await apiRequest(path, { token, method, body: JSON.stringify({ ...body, reason }), headers: { "Idempotency-Key": newIdempotencyKey() } });
      onDone(msg);
    } catch (e) { setErr(e instanceof Error ? e.message : "ثبت ناموفق بود"); } finally { setBusy(false); }
  };
  const title = dlg.kind === "member" ? `نقش ${dlg.m.full_name}` : dlg.kind === "grant" ? `مجوز عملیات · ${dlg.org.display_name}` : dlg.kind === "supplier" ? `کاربر ${dlg.sup.display_name}` : dlg.label;
  const submit = () => {
    if (dlg.kind === "member") return send("PATCH", `/admin/access/organizations/${dlg.org.id}/members/${dlg.m.id}`, { role, procurement_role: proc || null }, "نقش سازمانی به‌روزرسانی شد.");
    if (dlg.kind === "grant") return send("POST", `/admin/access/organizations/${dlg.org.id}/operations/grant`, { user_id: u?.id, capability: cap, mandate_reference: mandate }, "مجوز عملیات اعطا شد.");
    if (dlg.kind === "supplier") return send("POST", `/admin/access/suppliers/${dlg.sup.id}/users/grant`, { user_id: u?.id, role: supRole, convert_customer: convert }, "کاربر تأمین‌کننده افزوده شد.");
    return send("POST", dlg.path, dlg.body, "دسترسی لغو شد.");
  };
  return (
    <Drawer open title={title} onClose={onClose} footer={<button className={cx(s.btn, s.primary)} disabled={busy || reason.trim().length < 3} onClick={submit}>{busy ? "در حال ثبت…" : "ثبت تغییر"}</button>}>
      <div className={s.stack}>
        {dlg.kind === "member" && <>
          <label className={s.field}>نقش سازمانی<select className={s.select} value={role} onChange={(e) => setRole(e.target.value)}>{Object.entries(ROLE_FA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className={s.field}>نقش تدارکاتی<select className={s.select} value={proc} onChange={(e) => setProc(e.target.value)}>{Object.entries(PROC_FA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        </>}
        {dlg.kind === "grant" && <>
          <Notice tone="info" icon={<ShieldCheck />}>فقط کارکنان فعال پلتفرم (نقش employee یا admin). مشتری و تأمین‌کننده مجوز عملیات نمی‌گیرند.</Notice>
          <UserPicker token={token} value={u} onChange={setU} />
          <label className={s.field}>مجوز<select className={s.select} value={cap} onChange={(e) => setCap(e.target.value)}>{Object.entries(CAP_FA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className={s.field}>مرجع حکم/قرارداد مأموریت<input className={s.input} value={mandate} onChange={(e) => setMandate(e.target.value)} /></label>
        </>}
        {dlg.kind === "supplier" && <>
          <UserPicker token={token} value={u} onChange={setU} />
          <label className={s.field}>نقش<select className={s.select} value={supRole} onChange={(e) => setSupRole(e.target.value)}><option value="operator">کاربر عملیاتی</option><option value="owner">مالک</option></select></label>
          {u?.role === "customer" && <label className={s.row}><input type="checkbox" checked={convert} onChange={(e) => setConvert(e.target.checked)} /> تبدیل این حساب مشتری به کاربر تأمین‌کننده را تأیید می‌کنم</label>}
        </>}
        <label className={s.field}>دلیل تغییر (الزامی)<textarea className={s.textarea} value={reason} onChange={(e) => setReason(e.target.value)} rows={3} /></label>
        {err && <Notice tone="bad" icon={<AlertTriangle />}>{err}</Notice>}
      </div>
    </Drawer>
  );
}
