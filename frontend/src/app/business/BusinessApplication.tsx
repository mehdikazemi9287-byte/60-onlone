"use client";

import { useState } from "react";
import { apiRequest, ApiError } from "@/lib/api";

const field = "mt-1 w-full rounded-xl border border-st-outline-variant bg-st-surface-container-lowest px-3 py-2.5 text-[14px] text-st-on-surface outline-none focus:border-st-secondary";

export function BusinessApplication() {
  const [f, setF] = useState({ buyer_kind: "organization", legal_name: "", national_id: "", business_license_no: "",
    contact_name: "", phone: "", city: "", staff_band: "", monthly_band: "", message: "" });
  const [consent, setConsent] = useState(false);
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setState("busy"); setError(null);
    const body: Record<string, string> = {};
    Object.entries(f).forEach(([k, v]) => { if (v.trim()) body[k] = v.trim(); });
    try {
      await apiRequest("/b2b/applications", { method: "POST", body: JSON.stringify({ ...body, privacy_consent: consent }) });
      setState("done");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ارسال ناموفق بود");
      setState("idle");
    }
  };

  if (state === "done") {
    return <p role="status" className="rounded-xl bg-st-secondary-fixed p-st-space-lg text-st-on-secondary-fixed">درخواست شما ثبت شد. همکاران ما برای قرارداد و باز کردن حساب با شما تماس می‌گیرند.</p>;
  }
  return (
    <form onSubmit={submit} className="grid gap-st-space-sm">
      {error && <p role="alert" className="rounded-xl bg-st-error-container p-3 text-[14px] text-st-on-error-container">{error}</p>}
      <fieldset>
        <legend className="text-[14px] font-bold text-st-primary">نوع خریدار</legend>
        <div className="mt-2 flex gap-3">
          {[["organization", "سازمان یا شرکت"], ["retailer", "فروشگاه (خرید عمده)"]].map(([v, l]) => (
            <label key={v} className={`flex-1 cursor-pointer rounded-xl px-4 py-3 text-center text-sm font-bold ring-1 ${f.buyer_kind === v ? "bg-st-primary-container text-st-on-primary ring-st-primary-container" : "ring-st-outline-variant text-st-on-surface-variant"}`}>
              <input type="radio" name="kind" value={v} checked={f.buyer_kind === v} onChange={set("buyer_kind")} className="sr-only" />{l}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="text-[13px] text-st-on-surface-variant">نام {f.buyer_kind === "retailer" ? "فروشگاه" : "سازمان"}<input className={field} required minLength={2} maxLength={200} value={f.legal_name} onChange={set("legal_name")} /></label>
      <label className="text-[13px] text-st-on-surface-variant">شناسهٔ ملی شرکت/سازمان — ۱۱ رقمی (اختیاری)<input className={field} inputMode="numeric" dir="ltr" value={f.national_id} onChange={set("national_id")} /></label>
      {f.buyer_kind === "retailer" && <label className="text-[13px] text-st-on-surface-variant">شمارهٔ جواز کسب (اختیاری)<input className={field} dir="ltr" value={f.business_license_no} onChange={set("business_license_no")} /></label>}
      <label className="text-[13px] text-st-on-surface-variant">نام و نام خانوادگی رابط<input className={field} required minLength={2} maxLength={120} autoComplete="name" value={f.contact_name} onChange={set("contact_name")} /></label>
      <label className="text-[13px] text-st-on-surface-variant">موبایل رابط<input className={field} required type="tel" inputMode="numeric" dir="ltr" autoComplete="tel" placeholder="09xxxxxxxxx" value={f.phone} onChange={set("phone")} /></label>
      <label className="text-[13px] text-st-on-surface-variant">شهر<input className={field} maxLength={60} value={f.city} onChange={set("city")} /></label>
      <label className="text-[13px] text-st-on-surface-variant">تعداد کارکنان
        <select className={field} value={f.staff_band} onChange={set("staff_band")}><option value="">—</option>{["1-10", "11-50", "51-200", "201-1000", "1000+"].map((b) => <option key={b} value={b}>{b}</option>)}</select></label>
      <label className="text-[13px] text-st-on-surface-variant">حجم خرید ماهانه (تومان)
        <select className={field} value={f.monthly_band} onChange={set("monthly_band")}><option value="">—</option>
          <option value="<100m">کمتر از ۱۰ میلیون</option><option value="100m-500m">۱۰ تا ۵۰ میلیون</option><option value="500m-2b">۵۰ تا ۲۰۰ میلیون</option><option value="2b+">بیش از ۲۰۰ میلیون</option></select></label>
      <label className="text-[13px] text-st-on-surface-variant">توضیح (اختیاری)<textarea className={field} rows={3} maxLength={1000} value={f.message} onChange={set("message")} /></label>
      <label className="flex items-start gap-2 text-[12px] leading-6 text-st-on-surface-variant">
        <input type="checkbox" required className="mt-1.5" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        <span>موافقم شصت آنلاین برای بررسی درخواست و عقد قرارداد با رابط معرفی‌شده تماس بگیرد. این اطلاعات فقط برای همین منظور نگهداری می‌شود و اگر قراردادی بسته نشود حداکثر پس از ۱۸۰ روز حذف می‌شود (<a href="/privacy" className="underline">حریم خصوصی</a>).</span>
      </label>
      <button disabled={state === "busy" || !consent} className="inline-flex h-12 w-full items-center justify-center gap-st-space-xs rounded-xl bg-st-primary-container font-bold text-st-on-primary disabled:opacity-60"><span aria-hidden className="material-symbols-outlined text-[20px]">send</span>{state === "busy" ? "در حال ارسال…" : "ارسال درخواست استعلام و حساب سازمانی"}</button>
      <p className="text-center text-[12px] text-st-outline">پس از بررسی، همکاران ما برای قرارداد و پیش‌فاکتور رسمی تماس می‌گیرند.</p>
    </form>
  );
}
