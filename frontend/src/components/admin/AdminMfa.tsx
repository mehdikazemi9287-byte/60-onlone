"use client";
// Admin / staff second factor (TOTP). First visit: enrollment with any authenticator app, then one-time
// recovery codes. Later visits: a 6-digit code (or a recovery code). Backend: /api/v1/auth/mfa/* (mfa_service).
import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { mfa, type AdminAccess } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import s from "./admin.module.css";

const latin = (v: string) => v.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))).replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)));
const field = { padding: "10px 12px", border: "1px solid #cbd5e1", borderRadius: 10, fontSize: 18, letterSpacing: 4, textAlign: "center" as const, direction: "ltr" as const, width: "100%", maxWidth: 260 };

export function AdminMfa({ access }: { access: AdminAccess }) {
  const { token, adoptToken } = useAuth();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState(""), [useRecovery, setUseRecovery] = useState(false);
  const [codes, setCodes] = useState<string[] | null>(null), [pending, setPending] = useState<string | null>(null);
  const [saved, setSaved] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "خطا در ارتباط با سرور"); } finally { setBusy(false); }
  };
  if (!token) return null;

  if (codes && pending) return <section aria-label="کدهای بازیابی" style={{ maxWidth: 520 }}>
    <ShieldCheck size={36} /><h1>کدهای بازیابی</h1>
    <p>اگر گوشی در دسترس نبود، با یکی از این کدها وارد شوید. هر کد فقط یک بار کار می‌کند و دیگر نمایش داده نمی‌شود. آن‌ها را جای امنی (بیرون از این رایانه) نگه دارید.</p>
    <ol dir="ltr" style={{ columns: 2, fontFamily: "monospace", fontSize: 16, textAlign: "left" }}>{codes.map((c) => <li key={c}>{c}</li>)}</ol>
    <label style={{ display: "flex", gap: 8, alignItems: "center" }}><input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />کدها را ذخیره کردم</label>
    <button className={s.primary} disabled={!saved || busy} onClick={() => run(() => adoptToken(pending))}>ورود به پیشخوان</button>
    {error && <p role="alert">{error}</p>}
  </section>;

  if (!access.mfa_enrolled) return <section aria-label="فعال‌سازی ورود دومرحله‌ای" style={{ maxWidth: 520 }}>
    <ShieldCheck size={36} /><h1>فعال‌سازی ورود دومرحله‌ای</h1>
    <p>برای ورود به بخش مدیریت، علاوه بر رمز عبور، کد شش‌رقمی برنامهٔ احراز هویت (مانند Google Authenticator، Microsoft Authenticator یا Aegis) لازم است.</p>
    {!setup ? <button className={s.primary} disabled={busy} onClick={() => run(async () => { const r = await mfa.enrollStart(token); setSetup(r); })}>{busy ? "در حال آماده‌سازی…" : "شروع فعال‌سازی"}</button> : <>
      <ol style={{ textAlign: "right", lineHeight: 2 }}>
        <li>در برنامهٔ احراز هویت «افزودن حساب» و سپس «وارد کردن کلید» را بزنید (روی گوشی می‌توانید <a href={setup.otpauth_uri}>این پیوند</a> را باز کنید).</li>
        <li>این کلید را وارد کنید (نوع: بر اساس زمان):<div dir="ltr" style={{ fontFamily: "monospace", fontSize: 16, wordBreak: "break-all", padding: 8, background: "#f1f5f9", borderRadius: 8 }}>{setup.secret.match(/.{1,4}/g)?.join(" ")}</div></li>
        <li>کد شش‌رقمی‌ای که برنامه نشان می‌دهد را بنویسید:</li>
      </ol>
      <input aria-label="کد شش‌رقمی" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(latin(e.target.value).replace(/\D/g, ""))} style={field} />
      <button className={s.primary} disabled={busy || code.length !== 6} onClick={() => run(async () => { const r = await mfa.enrollConfirm(token, code); setCodes(r.recovery_codes); setPending(r.access_token); })}>تأیید و فعال‌سازی</button>
    </>}
    {error && <p role="alert">{error}</p>}
  </section>;

  return <section aria-label="تأیید دومرحله‌ای" style={{ maxWidth: 520 }}>
    <ShieldCheck size={36} /><h1>تأیید دومرحله‌ای</h1>
    <p>{useRecovery ? "یکی از کدهای بازیابی را وارد کنید. هر کد فقط یک بار پذیرفته می‌شود." : "کد شش‌رقمی برنامهٔ احراز هویت را وارد کنید."}</p>
    <input aria-label={useRecovery ? "کد بازیابی" : "کد شش‌رقمی"} inputMode={useRecovery ? "text" : "numeric"} autoComplete="one-time-code" maxLength={useRecovery ? 11 : 6}
      value={code} onChange={(e) => setCode(useRecovery ? latin(e.target.value).toUpperCase() : latin(e.target.value).replace(/\D/g, ""))} style={field} />
    <button className={s.primary} disabled={busy || (useRecovery ? code.length < 10 : code.length !== 6)}
      onClick={() => run(async () => { const r = await mfa.verify(token, useRecovery ? { recovery_code: code } : { code }); await adoptToken(r.access_token); })}>{busy ? "در حال بررسی…" : "تأیید"}</button>
    <button type="button" onClick={() => { setUseRecovery(!useRecovery); setCode(""); setError(""); }}>{useRecovery ? "استفاده از کد برنامه" : "به گوشی دسترسی ندارم (کد بازیابی)"}</button>
    {access.recovery_codes_remaining > 0 && access.recovery_codes_remaining <= 3 && <p>فقط {access.recovery_codes_remaining} کد بازیابی باقی مانده است.</p>}
    <p style={{ fontSize: 13 }}>اگر نه گوشی و نه کد بازیابی دارید، از مدیر ارشد دیگری بخواهید ورود دومرحله‌ای حساب شما را بازنشانی کند.</p>
    {error && <p role="alert">{error}</p>}
  </section>;
}
