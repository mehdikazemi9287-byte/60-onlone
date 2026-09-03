"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const { register } = useAuth();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    full_name: "",
    phone: "",
    email: "",
    password: "",
    confirm_password: "",
  });

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (form.password !== form.confirm_password) {
      setError("رمز عبور و تکرار آن یکسان نیستند");
      return;
    }
    if (!form.email.trim()) {
      setError("ایمیل الزامی است");
      return;
    }
    setLoading(true);
    try {
      await register(form.email.trim(), form.password, form.full_name.trim(), form.phone.trim() || undefined);
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ثبت‌نام ناموفق بود");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[calc(100vh-160px)] flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-lg">
        <div className="card p-7 md:p-8">
          {/* Logo */}
          <div className="flex justify-center mb-6">
            <div className="relative w-12 h-12 bg-primary-600 rounded-2xl flex items-center justify-center shadow-md">
              <span className="text-white font-black text-2xl leading-none">۶۰</span>
              <div className="absolute -bottom-1 -left-1 w-4 h-4 bg-accent-500 rounded-full" />
            </div>
          </div>
          <h1 className="text-xl font-black text-neutral-900 text-center mb-1">ثبت‌نام در 60Online</h1>
          <p className="text-sm text-neutral-500 text-center mb-6">ساخت حساب رایگان — بدون کارمزد اشتراک</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <p className="text-sm text-center text-danger-600 bg-danger-50 rounded-xl p-3">{error}</p>
            )}
            <div>
              <label className="form-label">نام کامل <span className="text-danger-500">*</span></label>
              <input type="text" value={form.full_name} onChange={set("full_name")} placeholder="نام و نام خانوادگی" required className="form-input mt-1" />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="form-label">شماره موبایل <span className="text-danger-500">*</span></label>
                <input type="tel" value={form.phone} onChange={set("phone")} placeholder="09xxxxxxxxx" required className="form-input mt-1" dir="ltr" />
              </div>
              <div>
                <label className="form-label">ایمیل <span className="text-danger-500">*</span></label>
                <input type="email" value={form.email} onChange={set("email")} placeholder="name@example.com" required className="form-input mt-1" dir="ltr" />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="form-label">رمز عبور <span className="text-danger-500">*</span></label>
                <input type="password" value={form.password} onChange={set("password")} placeholder="حداقل ۸ کاراکتر" required minLength={8} className="form-input mt-1" dir="ltr" />
              </div>
              <div>
                <label className="form-label">تکرار رمز <span className="text-danger-500">*</span></label>
                <input type="password" value={form.confirm_password} onChange={set("confirm_password")} placeholder="تکرار رمز" required className="form-input mt-1" dir="ltr" />
              </div>
            </div>

            <p className="text-xs text-neutral-400">
              با ثبت‌نام،{" "}
              <Link href="/help/terms" className="text-primary-600 hover:underline">شرایط استفاده</Link>
              {" "}و{" "}
              <Link href="/help/privacy" className="text-primary-600 hover:underline">حریم خصوصی</Link>
              {" "}را می‌پذیرید.
            </p>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl bg-primary-600 text-white font-semibold text-sm hover:bg-primary-700 transition-colors flex items-center justify-center gap-2 disabled:opacity-70"
            >
              {loading && (
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
              )}
              ثبت‌نام
            </button>
          </form>

          <p className="text-center text-sm text-neutral-500 mt-4">
            حساب دارید؟{" "}
            <Link href="/login" className="text-primary-600 font-semibold hover:text-primary-700">ورود</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
