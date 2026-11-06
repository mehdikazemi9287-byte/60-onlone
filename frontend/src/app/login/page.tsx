"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";
import { ApiError, auth } from "@/lib/api";

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginPageInner />
    </Suspense>
  );
}

function LoginPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login } = useAuth();
  const [tab, setTab] = useState<"password" | "otp">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const go = () => {
    const requested = searchParams.get("next") || "/";
    const destination =
      requested.startsWith("/") && !requested.startsWith("//") && !/[\\\u0000-\u001f]/.test(requested) ? requested : "/";
    router.push(destination);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
      go();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ورود ناموفق بود");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[calc(100vh-160px)] flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        {/* Card */}
        <div className="card p-7 md:p-8">
          {/* Logo */}
          <div className="flex justify-center mb-6">
            <div className="relative w-12 h-12 bg-primary-600 rounded-2xl flex items-center justify-center shadow-md">
              <span className="text-white font-black text-2xl leading-none">
                ۶۰
              </span>
              <div className="absolute -bottom-1 -left-1 w-4 h-4 bg-accent-500 rounded-full" />
            </div>
          </div>

          <h1 className="text-xl font-black text-neutral-900 text-center mb-1">
            ورود به 60Online
          </h1>
          <p className="text-sm text-neutral-500 text-center mb-6">
            به بازار جامع هوشمند خوش آمدید
          </p>

          {/* Tab selector */}
          <div className="flex rounded-xl bg-neutral-100 p-1 mb-6">
            {(["password", "otp"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={cn(
                  "flex-1 py-2 rounded-lg text-sm font-medium transition-all",
                  tab === t
                    ? "bg-white text-neutral-900 shadow-sm"
                    : "text-neutral-500 hover:text-neutral-700",
                )}
              >
                {t === "password" ? "رمز عبور" : "کد پیامکی"}
              </button>
            ))}
          </div>

          {/* Password form */}
          {tab === "password" && (
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <p className="text-sm text-center text-danger-600 bg-danger-50 rounded-xl p-3">
                  {error}
                </p>
              )}
              <div>
                <label className="form-label">ایمیل</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@example.com"
                  required
                  autoComplete="email"
                  className="form-input mt-1"
                  dir="ltr"
                />
              </div>
              <div>
                <div className="flex justify-between items-center mb-1">
                  <label className="form-label">رمز عبور</label>
                  <Link
                    href="/forgot-password"
                    className="text-xs text-primary-600 hover:text-primary-700"
                  >
                    فراموشی رمز؟
                  </Link>
                </div>
                <div className="relative">
                  <input
                    type={showPass ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="رمز عبور"
                    required
                    autoComplete="current-password"
                    className="form-input pl-10"
                    dir="ltr"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPass(!showPass)}
                    className="absolute inset-y-0 left-3 flex items-center text-neutral-400 hover:text-neutral-600"
                  >
                    {showPass ? (
                      <svg
                        className="w-4 h-4"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={1.8}
                          d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88"
                        />
                      </svg>
                    ) : (
                      <svg
                        className="w-4 h-4"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={1.8}
                          d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z"
                        />
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={1.8}
                          d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                        />
                      </svg>
                    )}
                  </button>
                </div>
              </div>
              <button
                type="submit"
                disabled={loading}
                className="w-full py-3 rounded-xl bg-primary-600 text-white font-semibold text-sm hover:bg-primary-700 transition-colors flex items-center justify-center gap-2 disabled:opacity-70"
              >
                {loading ? (
                  <svg
                    className="w-4 h-4 animate-spin"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8v8H4z"
                    />
                  </svg>
                ) : null}
                ورود
              </button>
            </form>
          )}

          {/* OTP form */}
          {tab === "otp" && <OtpForm onDone={go} />}

          {/* Divider */}
          <div className="relative my-5">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-neutral-100" />
            </div>
            <div className="relative flex justify-center">
              <span className="px-3 bg-white text-xs text-neutral-400">یا</span>
            </div>
          </div>

          {/* Register link */}
          <p className="text-center text-sm text-neutral-500">
            حساب ندارید؟{" "}
            <Link
              href="/register"
              className="text-primary-600 font-semibold hover:text-primary-700"
            >
              ثبت‌نام کنید
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

const FA = (n: number) => n.toLocaleString("fa-IR");

function OtpForm({ onDone }: { onDone: () => void }) {
  const { loginWithOtp } = useAuth();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [step, setStep] = useState<"phone" | "code">("phone");
  const [needName, setNeedName] = useState(false);
  const [wait, setWait] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);

  const send = async () => {
    setError(null);
    setBusy(true);
    try {
      const r = await auth.otpRequest(phone);
      setStep("code");
      setWait(r.resend_in_seconds);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ارسال کد ناموفق بود");
    } finally {
      setBusy(false);
    }
  };

  const verify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (step === "phone") return send();
    setError(null);
    setBusy(true);
    try {
      await loginWithOtp(phone, code, needName ? name : undefined);
      onDone();
    } catch (err) {
      if (err instanceof ApiError && err.code === "full_name_required") {
        setNeedName(true);
        setError("این شماره هنوز حساب ندارد؛ نامت را بنویس تا حساب ساخته شود.");
      } else setError(err instanceof ApiError ? err.message : "ورود ناموفق بود");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={verify} className="space-y-4">
      {error && <p className="text-sm text-center text-danger-600 bg-danger-50 rounded-xl p-3" role="alert">{error}</p>}
      <div>
        <label className="form-label" htmlFor="otp-phone">شماره موبایل</label>
        <input id="otp-phone" type="tel" inputMode="numeric" autoComplete="tel" value={phone} disabled={step === "code"}
          onChange={(e) => setPhone(e.target.value)} placeholder="09xxxxxxxxx" required className="form-input mt-1" dir="ltr" />
      </div>
      {step === "code" && (
        <>
          <div>
            <div className="flex justify-between items-center mb-1">
              <label className="form-label" htmlFor="otp-code">کد ۶ رقمی پیامک‌شده</label>
              <button type="button" className="text-xs text-primary-600" onClick={() => { setStep("phone"); setCode(""); setNeedName(false); }}>
                تغییر شماره
              </button>
            </div>
            <input id="otp-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
              onChange={(e) => setCode(e.target.value)} required className="form-input tracking-[0.5em] text-center" dir="ltr" />
          </div>
          {needName && (
            <div>
              <label className="form-label" htmlFor="otp-name">نام و نام خانوادگی</label>
              <input id="otp-name" value={name} onChange={(e) => setName(e.target.value)} required minLength={2} maxLength={120}
                autoComplete="name" className="form-input mt-1" />
            </div>
          )}
        </>
      )}
      <button type="submit" disabled={busy}
        className="w-full py-3 rounded-xl bg-primary-600 text-white font-semibold text-sm hover:bg-primary-700 transition-colors disabled:opacity-70">
        {step === "phone" ? "دریافت کد" : needName ? "ساخت حساب و ورود" : "ورود"}
      </button>
      {step === "code" && (
        <button type="button" disabled={wait > 0 || busy} onClick={send} className="w-full text-xs text-neutral-500 disabled:opacity-60">
          {wait > 0 ? `ارسال دوباره تا ${FA(wait)} ثانیهٔ دیگر` : "ارسال دوبارهٔ کد"}
        </button>
      )}
    </form>
  );
}
