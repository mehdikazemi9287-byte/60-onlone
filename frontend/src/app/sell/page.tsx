"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { shops, HEALTH_LABEL, type Shop, type ShopApplication, type ShopBalance } from "@/lib/shops";
import { formatPrice } from "@/lib/utils";

const EMPTY: ShopApplication = {
  seller_kind: "shop", legal_name: "", shop_title: "", shop_slug: "", national_id: "",
  mobile: "", province: "", city: "", sheba: "", shop_bio: "", accept_terms: false,
};

const FIELDS: [keyof ShopApplication, string, string?][] = [
  ["shop_title", "نام غرفه"], ["shop_slug", "آدرس غرفه (لاتین، مثل karen-crafts)", "ltr"],
  ["legal_name", "نام صاحب یا شرکت"], ["national_id", "کد ملی یا شناسهٔ ملی", "ltr"],
  ["mobile", "شمارهٔ همراه", "ltr"], ["province", "استان"], ["city", "شهر"],
  ["sheba", "شمارهٔ شبا (IR…)", "ltr"],
];

export default function SellPage() {
  const { token, loading } = useAuth();
  const [mine, setMine] = useState<{ shop: Shop; balance: ShopBalance } | null | undefined>(undefined);
  const [form, setForm] = useState<ShopApplication>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [holdDays, setHoldDays] = useState(7);

  useEffect(() => { shops.terms().then((t) => setHoldDays(t.hold_days)).catch(() => {}); }, []);
  useEffect(() => {
    if (!token) { setMine(null); return; }
    shops.mine(token).then(setMine).catch(() => setMine(null));
  }, [token]);

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
          <Stat label={`در امانت (${holdDays} روز بعد از تحویل)`} value={formatPrice(balance.held_minor)} />
          <Stat label="تسویه‌شده" value={formatPrice(balance.settled_minor)} />
          <Stat label="سلامت حساب" value={HEALTH_LABEL[shop.health_status ?? "good"]} />
        </dl>
        <p className="text-sm text-neutral-600">
          کارمزد پایه: {((shop.commission_rate_bps ?? 0) / 100).toLocaleString("fa-IR")}٪ ·{" "}
          {shop.url && <Link className="underline" href={shop.url}>دیدن صفحهٔ غرفه</Link>} ·{" "}
          <Link className="underline" href="/supplier/offers">مدیریت کالاها و قیمت‌ها</Link>
        </p>
      </div>
    );
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const body = { ...form, sheba: form.sheba || undefined, shop_bio: form.shop_bio || undefined };
      setMine({ shop: (await shops.apply(token, body)).shop, balance: { ready_minor: 0, held_minor: 0, settled_minor: 0, hold_days: holdDays } });
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا در ثبت غرفه");
    } finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} className="internal-page container-page max-w-xl py-6 md:py-8 space-y-4">
      <h1 className="text-xl md:text-2xl font-black text-neutral-900">ساخت غرفه</h1>
      <p className="text-sm text-neutral-600">
        ساخت غرفه رایگان است. کارمزد فقط از فروش موفق کم می‌شود و پول هر فروش {holdDays.toLocaleString("fa-IR")} روز بعد از تحویل قابل تسویه است.
      </p>
      <label className="block text-sm font-bold">نوع فروشنده
        <select className="mt-1 w-full rounded-xl border p-2" value={form.seller_kind}
          onChange={(e) => setForm({ ...form, seller_kind: e.target.value as ShopApplication["seller_kind"] })}>
          <option value="shop">غرفه‌دار (کسب‌وکار کوچک و متوسط)</option>
          <option value="brand">برند رسمی (تولیدکننده یا نمایندهٔ رسمی)</option>
          <option value="partner">شریک (کسب‌وکارهای گروه)</option>
        </select>
      </label>
      {FIELDS.map(([key, label, dir]) => (
        <label key={key} className="block text-sm font-bold">{label}
          <input dir={dir} className="mt-1 w-full rounded-xl border p-2" value={String(form[key] ?? "")}
            required={key !== "sheba"} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
        </label>
      ))}
      <label className="block text-sm font-bold">معرفی کوتاه غرفه
        <textarea className="mt-1 w-full rounded-xl border p-2" rows={3} value={form.shop_bio}
          onChange={(e) => setForm({ ...form, shop_bio: e.target.value })} />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={form.accept_terms} onChange={(e) => setForm({ ...form, accept_terms: e.target.checked })} />
        قوانین غرفه‌داری، کارمزد و دورهٔ امانت را می‌پذیرم.
      </label>
      {error && <p className="text-sm text-red-600">{error}</p>}
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
