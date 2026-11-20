"use client";
// Staff roles (internal teams), password-lockout unlock and second-factor reset for one account.
// Backend: /api/v1/admin/staff/users/<id>, PUT .../roles, POST /admin/users/<id>/unlock, POST /admin/users/<id>/mfa/reset.
import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import a from "./admin.module.css";
import s from "@/components/content/content.module.css";

type Detail = {
  user: { id: number; email: string; full_name: string; role: string; is_active: boolean };
  staff_roles: string[]; super_admin: boolean;
  mfa: { enrolled: boolean; activated_at: string | null; recovery_codes_remaining: number };
  login_lockout: { locked: boolean; locked_until: number | null; failed_count: number };
};
export const STAFF_ROLE_FA: Record<string, string> = {
  finance: "مالی", support: "پشتیبانی مشتریان", catalog: "کاتالوگ و تأمین‌کنندگان",
  marketing: "بازاریابی", content: "محتوا و سئو", logistics: "لجستیک و ارسال",
};

export function StaffAccessPanel({ token, userId, currentUserId }: { token: string; userId: number; currentUserId?: number }) {
  const [d, setD] = useState<Detail | null>(null), [roles, setRoles] = useState<string[]>([]);
  const [reason, setReason] = useState(""), [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const load = useCallback(async () => {
    const r = await apiRequest<Detail>(`/admin/staff/users/${userId}`, { token });
    setD(r); setRoles(r.staff_roles); setReason(""); setConfirmed(false);
  }, [token, userId]);
  useEffect(() => { setD(null); setError(""); setNotice(""); load().catch((e) => setError((e as Error).message)); }, [load]);
  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true); setError(""); setNotice("");
    try { await fn(); await load(); setNotice(done); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  if (!d) return error ? <p className={s.message} role="alert">{error}</p> : null;
  const self = d.user.id === currentUserId, eligible = ["customer", "employee"].includes(d.user.role);
  const ok = reason.trim().length >= 3 && confirmed && !busy;
  return <div className={s.panel}>
    <h2>نقش‌های کارکنان و امنیت ورود</h2>
    {d.super_admin ? <p className={s.note}>این حساب مدیر ارشد است و به همهٔ بخش‌ها دسترسی دارد.</p> : <>
      <p className={s.note}>هر نقش فقط بخش‌های همان تیم را باز می‌کند. نقش فقط به حساب «مشتری» یا «کارمند پلتفرم» داده می‌شود.</p>
      <fieldset disabled={!eligible || self || busy} style={{ border: 0, padding: 0 }}>
        {Object.entries(STAFF_ROLE_FA).map(([code, label]) => <label key={code} className={s.check}>
          <input type="checkbox" checked={roles.includes(code)} onChange={(e) => setRoles((r) => e.target.checked ? [...r, code] : r.filter((x) => x !== code))} />{label}</label>)}
      </fieldset>
    </>}
    <p className={s.note}>ورود دومرحله‌ای: {d.mfa.enrolled ? `فعال (${d.mfa.recovery_codes_remaining} کد بازیابی باقی‌مانده)` : "فعال نشده"} · ورود با رمز: {d.login_lockout.locked ? "قفل شده پس از تلاش‌های ناموفق" : "باز"}</p>
    <label>دلیل تغییر<textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></label>
    <label className={s.check}><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />حساب انتخاب‌شده و این تغییر را تأیید می‌کنم</label>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {!d.super_admin && eligible && !self && <button className={a.primary} disabled={!ok}
        onClick={() => act(() => apiRequest(`/admin/staff/users/${userId}/roles`, { token, method: "PUT", body: JSON.stringify({ roles, expected_roles: d.staff_roles, reason, confirm_scope: true }) }), "نقش‌های کارکنان با ثبت سابقه به‌روز شد.")}>ثبت نقش‌ها</button>}
      {d.login_lockout.locked && <button className={a.primary} disabled={!ok}
        onClick={() => act(() => apiRequest(`/admin/users/${userId}/unlock`, { token, method: "POST", body: JSON.stringify({ reason }) }), "قفل ورود برداشته شد.")}>باز کردن قفل ورود</button>}
      {d.mfa.enrolled && !self && <button className={a.primary} disabled={!ok}
        onClick={() => act(() => apiRequest(`/admin/users/${userId}/mfa/reset`, { token, method: "POST", body: JSON.stringify({ reason, confirm_scope: true }) }), "ورود دومرحله‌ای بازنشانی شد؛ کاربر در ورود بعدی دوباره فعالش می‌کند.")}>بازنشانی ورود دومرحله‌ای</button>}
    </div>
    {error && <p className={s.message} role="alert">{error}</p>}{notice && <p className={s.message} role="status">{notice}</p>}
  </div>;
}
