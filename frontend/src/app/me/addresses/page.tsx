"use client";
// Address book (دفترچهٔ نشانی) — Stitch screen 89 (address-book tab). Data: /me/addresses (owner-scoped).
// The server validates the Iranian mobile and the 10-digit postal code and turns Persian/Arabic digits into ASCII.
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { MapPin, Pencil, Star, Trash2 } from "lucide-react";
import { addresses as addressesApi, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { cn, toPersianNum } from "@/lib/utils";
import type { SavedAddress, SavedAddressInput } from "@/lib/types";

const EMPTY: SavedAddressInput = { title: "", recipient: "", phone: "", province: "", city: "", postal_code: "", line1: "" };
const FIELDS: [keyof SavedAddressInput, string, { ltr?: boolean; wide?: boolean; numeric?: boolean }][] = [
  ["title", "عنوان (مثلاً خانه یا محل کار)", {}],
  ["recipient", "نام گیرنده", {}],
  ["phone", "موبایل گیرنده", { ltr: true, numeric: true }],
  ["postal_code", "کد پستی ۱۰ رقمی", { ltr: true, numeric: true }],
  ["province", "استان", {}],
  ["city", "شهر", {}],
  ["line1", "نشانی کامل", { wide: true }],
];

function AddressForm({ initial, busy, errors, onSubmit, onCancel }: {
  initial: SavedAddressInput; busy: boolean; errors: Record<string, string>;
  onSubmit: (v: SavedAddressInput) => void; onCancel: () => void;
}) {
  const [v, setV] = useState<SavedAddressInput>(initial);
  return (
    <form className="card space-y-4 p-4 md:p-5" onSubmit={(e) => { e.preventDefault(); onSubmit(v); }}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {FIELDS.map(([k, label, o]) => (
          <div key={k} className={o.wide ? "sm:col-span-2" : undefined}>
            <label className="form-label" htmlFor={`addr-${k}`}>{label}</label>
            {o.wide
              ? <textarea id={`addr-${k}`} rows={3} value={String(v[k] ?? "")} onChange={(e) => setV({ ...v, [k]: e.target.value })} className="form-input mt-1" />
              : <input id={`addr-${k}`} value={String(v[k] ?? "")} dir={o.ltr ? "ltr" : undefined} inputMode={o.numeric ? "numeric" : undefined}
                  onChange={(e) => setV({ ...v, [k]: e.target.value })} className="form-input mt-1" />}
            {errors[k] && <p className="mt-1 text-2xs text-danger-600">{errors[k]}</p>}
          </div>
        ))}
      </div>
      <label className="flex items-center gap-2 text-sm text-neutral-700">
        <input type="checkbox" checked={!!v.is_default} onChange={(e) => setV({ ...v, is_default: e.target.checked })} />
        نشانی پیش‌فرض باشد
      </label>
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={busy} className="min-h-11 rounded-xl bg-primary-600 px-5 text-sm font-bold text-white disabled:opacity-50">{busy ? "در حال ذخیره…" : "ذخیره"}</button>
        <button type="button" disabled={busy} onClick={onCancel} className="min-h-11 rounded-xl border border-neutral-200 px-5 text-sm font-bold text-neutral-700">انصراف</button>
      </div>
    </form>
  );
}

export default function AddressBookPage() {
  const { token, loading } = useAuth();
  const [items, setItems] = useState<SavedAddress[] | null>(null);
  const [max, setMax] = useState(20);
  const [editing, setEditing] = useState<SavedAddress | "new" | null>(null);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    if (!token) return;
    addressesApi.list(token).then((r) => { setItems(r.items); setMax(r.max); })
      .catch((e) => setMsg({ ok: false, text: e instanceof ApiError ? e.message : "دریافت نشانی‌ها ناموفق بود" }));
  }, [token]);
  useEffect(() => { load(); }, [load]);

  const fail = (e: unknown, fallback: string) => {
    if (e instanceof ApiError && e.details) setErrors(e.details);
    setMsg({ ok: false, text: e instanceof ApiError ? e.message : fallback });
  };

  const save = async (v: SavedAddressInput) => {
    if (!token || !editing) return;
    setBusy(true); setErrors({}); setMsg(null);
    try {
      if (editing === "new") await addressesApi.create(token, v);
      else await addressesApi.update(token, editing.id, v);
      setEditing(null); setMsg({ ok: true, text: "نشانی ذخیره شد." }); load();
    } catch (e) { fail(e, "ذخیرهٔ نشانی ناموفق بود"); } finally { setBusy(false); }
  };
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true); setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); load(); } catch (e) { fail(e, "انجام نشد"); } finally { setBusy(false); }
  };

  if (!loading && !token) {
    return (
      <div className="internal-page container-page py-24 text-center">
        <h2 className="mb-2 text-lg font-bold text-neutral-900">برای مدیریت نشانی‌ها وارد شوید</h2>
        <Link href="/login?next=/me/addresses" className="mt-2 inline-flex items-center gap-2 rounded-full bg-ink px-6 py-3 text-sm font-semibold text-white">ورود به حساب کاربری</Link>
      </div>
    );
  }

  return (
    <div className="internal-page container-page max-w-3xl py-6 md:py-8" dir="rtl">
      <nav className="mb-6 flex items-center gap-2 text-xs text-neutral-400">
        <Link href="/" className="hover:text-primary-600">خانه</Link><span>/</span>
        <Link href="/account" className="hover:text-primary-600">حساب کاربری</Link><span>/</span>
        <span className="text-neutral-600">دفترچهٔ نشانی</span>
      </nav>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-black text-neutral-900">دفترچهٔ نشانی</h1>
        {editing === null && items && items.length < max && (
          <button type="button" onClick={() => { setEditing("new"); setErrors({}); setMsg(null); }} className="min-h-11 rounded-xl bg-primary-600 px-4 text-sm font-bold text-white">افزودن نشانی</button>
        )}
      </div>
      <p className="mb-4 text-sm text-neutral-500">نشانی پیش‌فرض هنگام پرداخت خودکار انتخاب می‌شود. تغییر یا حذف نشانی، سفارش‌های ثبت‌شده را تغییر نمی‌دهد.</p>
      {msg && <p role={msg.ok ? "status" : "alert"} className={cn("mb-4 rounded-xl px-3 py-2 text-sm", msg.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800")}>{msg.text}</p>}

      {editing !== null && (
        <div className="mb-4">
          <AddressForm key={editing === "new" ? "new" : editing.id} busy={busy} errors={errors}
            initial={editing === "new" ? { ...EMPTY, is_default: !items?.length } : { ...editing }}
            onSubmit={save} onCancel={() => { setEditing(null); setErrors({}); }} />
        </div>
      )}

      {items === null ? <div className="card h-40 animate-pulse bg-neutral-100" /> : items.length === 0 ? (
        <div className="card p-8 text-center text-sm text-neutral-500">هنوز نشانی ذخیره نکرده‌اید.</div>
      ) : (
        <ul className="space-y-3">
          {items.map((a) => (
            <li key={a.id} className={cn("card p-4", a.is_default && "ring-2 ring-primary-200")}>
              <div className="flex items-start gap-3">
                <MapPin className="mt-1 h-5 w-5 flex-shrink-0 text-primary-600" aria-hidden />
                <div className="min-w-0 flex-1 text-sm">
                  <p className="font-bold text-neutral-900">{a.title}{a.is_default && <span className="mr-2 rounded-full bg-primary-50 px-2 py-0.5 text-2xs text-primary-700">پیش‌فرض</span>}</p>
                  <p className="mt-1 text-neutral-700">{a.recipient} — <span dir="ltr">{toPersianNum(a.phone)}</span></p>
                  <p className="mt-0.5 text-neutral-500">{a.province}، {a.city}، {a.line1}</p>
                  <p className="mt-0.5 text-xs text-neutral-500">کد پستی: <span dir="ltr">{toPersianNum(a.postal_code)}</span></p>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-2 border-t border-neutral-100 pt-3">
                {!a.is_default && <button type="button" disabled={busy} onClick={() => token && act(() => addressesApi.setDefault(token, a.id), "نشانی پیش‌فرض تغییر کرد.")} className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-neutral-200 px-3 text-xs font-bold text-neutral-700"><Star className="h-3.5 w-3.5" />پیش‌فرض شود</button>}
                <button type="button" disabled={busy} onClick={() => { setEditing(a); setErrors({}); setMsg(null); }} className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-neutral-200 px-3 text-xs font-bold text-neutral-700"><Pencil className="h-3.5 w-3.5" />ویرایش</button>
                <button type="button" disabled={busy} onClick={() => { if (token && window.confirm("این نشانی حذف شود؟")) void act(() => addressesApi.remove(token, a.id), "نشانی حذف شد."); }} className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-red-200 px-3 text-xs font-bold text-red-700"><Trash2 className="h-3.5 w-3.5" />حذف</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
