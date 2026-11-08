"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { shops, HEALTH_LABEL, latinDigits, type Shop, type ShopApplication, type ShopBalance } from "@/lib/shops";
import { ApiError } from "@/lib/api";
import { formatPrice } from "@/lib/utils";
import { SellerTools } from "@/components/seller/SellerTools";

const EMPTY: ShopApplication = {
  seller_kind: "shop", legal_name: "", shop_title: "", shop_slug: "", national_id: "",
  mobile: "", province: "", city: "", sheba: "", shop_bio: "", accept_terms: false,
};

type Field = { key: keyof ShopApplication; label: string; numeric?: boolean; ltr?: boolean; optional?: boolean;
  max?: number; type?: string; auto?: string; hint?: string };

// Identity first, then the shop, then payout — the order a seller has the information at hand.
const FIELDS: Field[] = [
  { key: "legal_name", label: "نام صاحب غرفه یا شرکت", max: 200 },
  { key: "national_id", label: "کد ملی (۱۰ رقم) یا شناسهٔ ملی شرکت (۱۱ رقم)", numeric: true, ltr: true, max: 11 },
  { key: "mobile", label: "شمارهٔ همراه", numeric: true, ltr: true, max: 11, type: "tel", auto: "tel" },
  { key: "shop_title", label: "نام غرفه", max: 120 },
  { key: "shop_slug", label: "آدرس غرفه", ltr: true, max: 40, hint: "حروف لاتین کوچک، عدد و خط تیره" },
  { key: "province", label: "استان", max: 100 },
  { key: "city", label: "شهر", max: 100 },
  { key: "sheba", label: "شمارهٔ شبا", ltr: true, max: 26, optional: true, hint: "برای تسویه لازم است؛ بعداً هم می‌توانی وارد کنی" },
];

export default function SellPage() {
  const { token, loading } = useAuth();
  const [mine, setMine] = useState<{ shop: Shop; balance: ShopBalance } | null | undefined>(undefined);
  const [form, setForm] = useState<ShopApplication>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [holdDays, setHoldDays] = useState(7);

  useEffect(() => { shops.terms().then((t) => setHoldDays(t.hold_days)).catch(() => {}); }, []);
  useEffect(() => {
    if (!token) { setMine(null); return; }
    // Only "no shop yet" (403/404) shows the sign-up form; other failures must not invite a second shop.
    shops.mine(token).then(setMine).catch((e) => {
      if (e instanceof ApiError && (e.status === 403 || e.status === 404)) setMine(null);
      else setError("بارگذاری غرفه ناموفق بود. صفحه را دوباره باز کن.");
    });
  }, [token]);

  if (mine === undefined && error) {
    return <div className="internal-page container-page py-20 text-center text-red-600">{error}</div>;
  }
  if (loading || mine === undefined) {
    return <div className="internal-page container-page py-20 text-center text-neutral-400">در حال بارگذاری…</div>;
  }
  if (!token) {
    return (
      <div className="internal-page container-page py-16 text-center">
        <h1 className="mb-3 text-xl font-black">غرفه‌ات را در شصت آنلاین بساز</h1>
        <p className="mb-6 text-neutral-600">برای ساخت غرفه اول وارد حساب شو.</p>
        <Link href="/login?next=/sell" className="rounded-xl bg-neutral-900 px-5 py-2 font-bold text-white">ورود</Link>
      </div>
    );
  }

  if (mine) {
    const { shop, balance } = mine;
    return (
      <div className="internal-page container-page py-6 md:py-8 space-y-6">
        <h1 className="text-xl md:text-2xl font-black text-neutral-900">غرفهٔ من: {shop.title}</h1>
        {shop.onboarding_stage !== "approved" && (
          <p className="rounded-xl bg-amber-50 p-4 text-amber-800">
            {shop.onboarding_stage === "rejected" ? "درخواست غرفه رد شد. با پشتیبانی تماس بگیر." : "درخواست غرفه ثبت شده و در انتظار بررسی است."}
          </p>
        )}
        <dl className="grid gap-4 sm:grid-cols-4">
          <Stat label="قابل تسویه" value={formatPrice(balance.ready_minor)} />
          <Stat label={`در امانت (${holdDays.toLocaleString("fa-IR")} روز بعد از تحویل)`} value={formatPrice(balance.held_minor)} />
          <Stat label="تسویه‌شده" value={formatPrice(balance.settled_minor)} />
          <Stat label="سلامت حساب" value={HEALTH_LABEL[shop.health_status ?? "good"]} />
        </dl>
        <p className="text-sm text-neutral-600">
          کارمزد پایه: {((shop.commission_rate_bps ?? 0) / 100).toLocaleString("fa-IR")}٪ ·{" "}
          {shop.url && <Link className="underline" href={shop.url}>دیدن صفحهٔ غرفه</Link>} ·{" "}
          <Link className="underline" href="/supplier/offers">مدیریت کالاها و قیمت‌ها</Link>
        </p>
        {shop.onboarding_stage === "approved" && <SellerTools token={token} isBrand={shop.kind === "brand"} />}
      </div>
    );
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null); setFieldErrors({});
    try {
      const body = { ...form, sheba: form.sheba || undefined, shop_bio: form.shop_bio || undefined };
      setMine({ shop: (await shops.apply(token, body)).shop, balance: { ready_minor: 0, held_minor: 0, settled_minor: 0, hold_days: holdDays } });
    } catch (err) {
      const field = err instanceof ApiError ? err.details?.field : undefined;
      if (field) setFieldErrors({ [field]: err instanceof Error ? err.message : "" });
      setError(err instanceof Error ? err.message : "خطا در ثبت غرفه");
    } finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} className="internal-page container-page max-w-xl py-6 md:py-8 space-y-4">
      <h1 className="text-xl md:text-2xl font-black text-neutral-900">ساخت غرفه</h1>
      <ul className="grid gap-2 rounded-2xl bg-neutral-50 p-4 text-sm text-neutral-700 sm:grid-cols-3">
        <li><b>رایگان</b> — ساخت غرفه هزینه ندارد</li>
        <li><b>کارمزد فقط از فروش</b> — غرفه‌دار ۹٪، فروش سازمانی ۵٪</li>
        <li><b>تسویه</b> — {holdDays.toLocaleString("fa-IR")} روز بعد از تحویل</li>
      </ul>
      <label className="block text-sm font-bold">نوع فروشنده
        <select className="mt-1 w-full rounded-xl border p-2" value={form.seller_kind}
          onChange={(e) => setForm({ ...form, seller_kind: e.target.value as ShopApplication["seller_kind"] })}>
          <option value="shop">غرفه‌دار (کسب‌وکار کوچک و متوسط)</option>
          <option value="brand">برند رسمی (تولیدکننده یا نمایندهٔ رسمی)</option>
          <option value="partner">شریک (کسب‌وکارهای گروه)</option>
        </select>
      </label>
      {FIELDS.map((f) => {
        const err = fieldErrors[f.key];
        const id = `f-${f.key}`;
        return (
          <label key={f.key} htmlFor={id} className="block text-sm font-bold">
            {f.label}{f.optional && <span className="font-normal text-neutral-500"> (اختیاری)</span>}
            <input id={id} dir={f.ltr ? "ltr" : undefined} type={f.type ?? "text"} inputMode={f.numeric ? "numeric" : undefined}
              autoComplete={f.auto} maxLength={f.max} autoCapitalize={f.ltr ? "off" : undefined} spellCheck={f.ltr ? false : undefined}
              aria-invalid={!!err} aria-describedby={err || f.hint ? `${id}-note` : undefined}
              className={`mt-1 w-full rounded-xl border p-2 ${err ? "border-red-500" : ""}`} value={String(form[f.key] ?? "")}
              required={!f.optional}
              onChange={(e) => {
                let v = latinDigits(e.target.value);
                if (f.key === "shop_slug") v = v.toLowerCase();
                if (f.key === "sheba") v = v.toUpperCase().replace(/\s/g, "");
                setForm({ ...form, [f.key]: v });
              }} />
            {f.key === "shop_slug" && form.shop_slug && (
              <span dir="ltr" className="mt-1 block text-xs font-normal text-neutral-500">60online.ir/shops/{form.shop_slug}</span>
            )}
            {(err || f.hint) && <span id={`${id}-note`} className={`mt-1 block text-xs font-normal ${err ? "text-red-600" : "text-neutral-500"}`}>{err || f.hint}</span>}
          </label>
        );
      })}
      <label className="block text-sm font-bold">معرفی کوتاه غرفه
        <textarea className="mt-1 w-full rounded-xl border p-2" rows={3} value={form.shop_bio}
          onChange={(e) => setForm({ ...form, shop_bio: e.target.value })} />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={form.accept_terms} onChange={(e) => setForm({ ...form, accept_terms: e.target.checked })} />
        <span><Link href="/terms" className="underline">قوانین غرفه‌داری</Link>، کارمزد و دورهٔ امانت را می‌پذیرم.</span>
      </label>
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      {!form.accept_terms && <p className="text-xs text-neutral-500">برای ثبت، پذیرفتن قوانین لازم است.</p>}
      <button disabled={busy || !form.accept_terms} className="w-full rounded-xl bg-neutral-900 py-3 font-bold text-white disabled:opacity-50">
        {busy ? "در حال ثبت…" : "ثبت درخواست غرفه"}
      </button>
    </form>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-neutral-200 p-4">
      <dt className="text-xs text-neutral-500">{label}</dt>
      <dd className="mt-1 font-black text-neutral-900">{value}</dd>
    </div>
  );
}
