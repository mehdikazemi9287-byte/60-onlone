"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

type Store = { id: number; title: string; shop_slug: string | null; province: string; city: string; address: string | null;
  phone: string | null; opening_hours: string | null; pickup: boolean; walk_in: boolean; appointments: boolean };

const PURPOSES: [string, string][] = [["showroom", "بازدید از نمایشگاه"], ["samples", "دیدن نمونهٔ کالا (سازمانی)"],
  ["consultation", "مشاوره"], ["other", "سایر"]];

export default function StoresPage() {
  const { token } = useAuth();
  const [city, setCity] = useState("");
  const [items, setItems] = useState<Store[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [booking, setBooking] = useState<Store | null>(null);

  useEffect(() => {
    let cancelled = false;
    setItems(null); setError(null);
    const t = setTimeout(() => {
      apiRequest<{ items: Store[] }>(`/stores${city.trim() ? `?city=${encodeURIComponent(city.trim())}` : ""}`)
        .then((r) => { if (!cancelled) setItems(r.items); })
        .catch((e) => { if (!cancelled) setError(e.message); });
    }, 300);
    return () => { cancelled = true; clearTimeout(t); };
  }, [city]);

  return (
    <div className="internal-page container-page py-6 md:py-8">
      <h1 className="mb-2 text-xl md:text-2xl font-black text-neutral-900">مراجعهٔ حضوری</h1>
      <p className="mb-5 text-sm text-neutral-600">خرید حضوری، دریافت سفارش از فروشگاه، یا رزرو نوبت برای دیدن کالا و نمونه‌ها.</p>
      <label className="mb-5 block max-w-xs text-sm font-bold">شهر
        <input className="mt-1 w-full rounded-xl border p-2" value={city} onChange={(e) => setCity(e.target.value)} placeholder="مثلاً تهران" />
      </label>
      {error && <p className="text-red-600">{error}</p>}
      {items === null && !error && <p className="text-neutral-400">در حال بارگذاری…</p>}
      {items?.length === 0 && <p className="text-neutral-500">فعلاً فروشگاه حضوری در این شهر ثبت نشده است.</p>}
      <ul className="grid gap-4 sm:grid-cols-2">
        {items?.map((s) => (
          <li key={s.id} className="rounded-2xl border border-neutral-200 p-4">
            <p className="font-bold text-neutral-900">{s.shop_slug ? <Link href={`/shops/${encodeURIComponent(s.shop_slug)}`}>{s.title}</Link> : s.title}</p>
            <p className="mt-1 text-sm text-neutral-600">{s.province}، {s.city}{s.address ? `، ${s.address}` : ""}</p>
            {s.phone && <p className="text-sm" dir="ltr">{s.phone}</p>}
            <p className="mt-2 flex flex-wrap gap-2 text-xs">
              {s.walk_in && <span className="rounded-full bg-neutral-100 px-2 py-0.5">خرید حضوری</span>}
              {s.pickup && <span className="rounded-full bg-neutral-100 px-2 py-0.5">دریافت سفارش از فروشگاه</span>}
              {s.appointments && <span className="rounded-full bg-neutral-100 px-2 py-0.5">رزرو نوبت</span>}
            </p>
            {s.appointments && (token
              ? <button type="button" onClick={() => setBooking(s)} className="mt-3 rounded-xl border border-neutral-900 px-3 py-1.5 text-sm font-bold">رزرو نوبت مراجعه</button>
              : <Link href="/login?next=/stores" className="mt-3 inline-block text-sm underline">برای رزرو نوبت وارد شو</Link>)}
          </li>
        ))}
      </ul>
      {booking && token && <BookVisit token={token} store={booking} onClose={() => setBooking(null)} />}
    </div>
  );
}

function BookVisit({ token, store, onClose }: { token: string; store: Store; onClose: () => void }) {
  const [when, setWhen] = useState("");
  const [purpose, setPurpose] = useState("showroom");
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!when) return;
    setBusy(true); setMsg(null);
    try {
      await apiRequest("/me/visits", { method: "POST", token, body: JSON.stringify({
        location_id: store.id, starts_at: new Date(when).toISOString().replace(/\.\d{3}Z$/, "Z"), purpose, note: note || undefined }) });
      setMsg({ ok: true, text: "درخواست نوبت ثبت شد. بعد از تأیید فروشگاه خبرت می‌کنیم." });
    } catch (err) { setMsg({ ok: false, text: err instanceof ApiError ? err.message : "ثبت نوبت ناموفق بود" }); }
    finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} aria-label={`رزرو نوبت در ${store.title}`} className="mt-6 max-w-md space-y-3 rounded-2xl border border-neutral-900 p-4">
      <p className="font-bold">رزرو نوبت در {store.title}</p>
      <label className="block text-sm">زمان مراجعه
        <input type="datetime-local" required className="mt-1 w-full rounded-xl border p-2" value={when} onChange={(e) => setWhen(e.target.value)} />
      </label>
      <label className="block text-sm">هدف مراجعه
        <select className="mt-1 w-full rounded-xl border p-2" value={purpose} onChange={(e) => setPurpose(e.target.value)}>
          {PURPOSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </label>
      <label className="block text-sm">توضیح (اختیاری)
        <textarea className="mt-1 w-full rounded-xl border p-2" rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-emerald-700" : "text-red-600"}`}>{msg.text}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy || !when} className="rounded-xl bg-neutral-900 px-4 py-2 text-sm font-bold text-white disabled:opacity-50">{busy ? "…" : "ثبت درخواست"}</button>
        <button type="button" onClick={onClose} className="rounded-xl border px-4 py-2 text-sm">بستن</button>
      </div>
    </form>
  );
}
