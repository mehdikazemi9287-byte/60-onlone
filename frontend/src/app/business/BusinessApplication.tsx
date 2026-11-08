"use client";

import { useState } from "react";
import { apiRequest, ApiError } from "@/lib/api";

const field = "mt-1 w-full rounded-xl border border-neutral-300 bg-white px-3 py-2.5 text-sm focus:border-primary-600 outline-none";

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
    return <p role="status" className="mt-8 rounded-2xl bg-green-50 p-6 text-green-800">درخواست شما ثبت شد. همکاران ما برای قرارداد و باز کردن حساب با شما تماس می‌گیرند.</p>;
  }
  return (
    <form onSubmit={submit} className="mt-8 grid gap-4 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-neutral-200 md:grid-cols-2">
      {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700 md:col-span-2">{error}</p>}
      <fieldset className="md:col-span-2">
        <legend className="text-sm font-bold">شما</legend>
        <div className="mt-2 flex gap-3">
          {[["organization", "سازمان یا شرکت"], ["retailer", "فروشگاه (خرید عمده)"]].map(([v, l]) => (
            <label key={v} className={`flex-1 cursor-pointer rounded-xl px-4 py-3 text-center text-sm font-bold ring-1 ${f.buyer_kind === v ? "bg-primary-50 ring-primary-600" : "ring-neutral-300"}`}>
              <input type="radio" name="kind" value={v} checked={f.buyer_kind === v} onChange={set("buyer_kind")} className="sr-only" />{l}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="text-sm">نام {f.buyer_kind === "retailer" ? "فروشگاه" : "سازمان"}<input className={field} required minLength={2} maxLength={200} value={f.legal_name} onChange={set("legal_name")} /></label>
      <label className="text-sm">شناسهٔ ملی شرکت/سازمان — ۱۱ رقمی (اختیاری)<input className={field} inputMode="numeric" dir="ltr" value={f.national_id} onChange={set("national_id")} /></label>
      {f.buyer_kind === "retailer" && <label className="text-sm">شمارهٔ جواز کسب (اختیاری)<input className={field} dir="ltr" value={f.business_license_no} onChange={set("business_license_no")} /></label>}
      <label className="text-sm">نام و نام خانوادگی رابط<input className={field} required minLength={2} maxLength={120} autoComplete="name" value={f.contact_name} onChange={set("contact_name")} /></label>
      <label className="text-sm">موبایل رابط<input className={field} required type="tel" inputMode="numeric" dir="ltr" autoComplete="tel" placeholder="09xxxxxxxxx" value={f.phone} onChange={set("phone")} /></label>
      <label className="text-sm">شهر<input className={field} maxLength={60} value={f.city} onChange={set("city")} /></label>
      <label className="text-sm">تعداد کارکنان
        <select className={field} value={f.staff_band} onChange={set("staff_band")}><option value="">—</option>{["1-10", "11-50", "51-200", "201-1000", "1000+"].map((b) => <option key={b} value={b}>{b}</option>)}</select></label>
      <label className="text-sm">حجم خرید ماهانه (تومان)
        <select className={field} value={f.monthly_band} onChange={set("monthly_band")}><option value="">—</option>
          <option value="<100m">کمتر از ۱۰ میلیون</option><option value="100m-500m">۱۰ تا ۵۰ میلیون</option><option value="500m-2b">۵۰ تا ۲۰۰ میلیون</option><option value="2b+">بیش از ۲۰۰ میلیون</option></select></label>
      <label className="text-sm md:col-span-2">توضیح (اختیاری)<textarea className={field} rows={3} maxLength={1000} value={f.message} onChange={set("message")} /></label>
      <label className="flex items-start gap-2 text-xs leading-6 text-neutral-600 md:col-span-2">
        <input type="checkbox" required className="mt-1.5" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        <span>موافقم شصت آنلاین برای بررسی درخواست و عقد قرارداد با رابط معرفی‌شده تماس بگیرد. این اطلاعات فقط برای همین منظور نگهداری می‌شود و اگر قراردادی بسته نشود حداکثر پس از ۱۸۰ روز حذف می‌شود (<a href="/privacy" className="underline">حریم خصوصی</a>).</span>
      </label>
      <div className="md:col-span-2"><button disabled={state === "busy" || !consent} className="w-full rounded-xl bg-primary-600 py-3 text-sm font-bold text-white disabled:opacity-60 md:w-auto md:px-10">{state === "busy" ? "در حال ارسال…" : "ارسال درخواست"}</button></div>
    </form>
  );
}
