"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatPrice } from "@/lib/utils";

type Dash = { code: string; status: string; link_path: string; pending_minor: number; available_minor: number; in_payout_minor: number; paid_minor: number;
  items: { id: number; reference: string; amount_minor: number; state: string; available_at: string }[] };
const STATE_FA: Record<string, string> = { pending: "در انتظار پایان مهلت انصراف", on_hold: "مرجوعی باز", available: "قابل برداشت",
  reversed: "برگشت خورد", paid: "پرداخت‌شده", in_payout: "در حال واریز" };

export default function AffiliatePage() {
  const { token, loading } = useAuth();
  const [d, setD] = useState<Dash | null | undefined>(undefined);
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const load = useCallback(() => {
    if (!token) return;
    apiRequest<Dash>("/me/affiliate", { token }).then(setD)
      .catch((e) => setD(e instanceof ApiError && e.status === 404 ? null : undefined));
  }, [token]);
  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="internal-page container-page py-20 text-center text-neutral-400">در حال بارگذاری…</div>;
  if (!token) {
    return (
      <div className="internal-page container-page py-16 text-center">
        <h1 className="mb-3 text-xl font-black">همکاری در فروش</h1>
        <p className="mb-6 text-neutral-600">کالاهای شصت‌آنلاین را معرفی کن و از هر خرید موفق کمیسیون بگیر.</p>
        <Link href="/login?next=/me/affiliate" className="rounded-xl bg-neutral-900 px-5 py-2 font-bold text-white">ورود</Link>
      </div>
    );
  }
  const join = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null);
    try { await apiRequest("/me/affiliate", { method: "POST", token, body: JSON.stringify(code ? { code } : {}) }); load(); }
    catch (x) { setErr(x instanceof ApiError ? x.message : "ثبت‌نام ناموفق بود"); }
  };
  if (d === null) {
    return (
      <form onSubmit={join} className="internal-page container-page max-w-md py-8 space-y-4">
        <h1 className="text-xl font-black">همکاری در فروش</h1>
        <ul className="rounded-2xl bg-neutral-50 p-4 text-sm leading-7 text-neutral-700">
          <li>لینک اختصاصی‌ات را در اینستاگرام، تلگرام یا گروه همکارانت بفرست.</li>
          <li>از هر خرید موفق تا ۷ روز بعد از کلیک، کمیسیون می‌گیری. بعضی غرفه‌ها کمیسیون اضافه هم می‌دهند.</li>
          <li>کمیسیون بعد از پایان مهلت انصراف خریدار قابل برداشت می‌شود.</li>
        </ul>
        <label className="block text-sm font-bold">کد دلخواه (اختیاری، لاتین)
          <input dir="ltr" className="mt-1 w-full rounded-xl border p-2" value={code} maxLength={24} autoCapitalize="off" spellCheck={false}
            onChange={(e) => setCode(e.target.value.replace(/[^A-Za-z0-9]/g, ""))} />
        </label>
        {err && <p role="alert" className="text-sm text-red-600">{err}</p>}
        <button type="submit" className="w-full rounded-xl bg-neutral-900 py-3 font-bold text-white">شروع همکاری</button>
      </form>
    );
  }
  if (!d) return <div className="internal-page container-page py-20 text-center text-neutral-500">بارگذاری ناموفق بود. دوباره تلاش کن.</div>;
  const link = typeof window !== "undefined" ? `${window.location.origin}${d.link_path}` : d.link_path;
  return (
    <div className="internal-page container-page py-6 md:py-8 space-y-5">
      <h1 className="text-xl md:text-2xl font-black text-neutral-900">همکاری در فروش</h1>
      <div className="flex flex-wrap items-center gap-2 rounded-2xl border p-3">
        <span className="text-sm text-neutral-600">لینک تو:</span>
        <code dir="ltr" className="rounded bg-neutral-100 px-2 py-1 text-sm">{link}</code>
        <button type="button" className="rounded-lg border px-3 py-1 text-sm"
          onClick={() => { navigator.clipboard?.writeText(link).then(() => setCopied(true)).catch(() => {}); }}>
          {copied ? "کپی شد" : "کپی"}
        </button>
      </div>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[["در انتظار", d.pending_minor], ["قابل برداشت", d.available_minor], ["در حال واریز", d.in_payout_minor], ["پرداخت‌شده", d.paid_minor]].map(([l, v]) => (
          <div key={l as string} className="rounded-2xl border p-4"><dt className="text-xs text-neutral-500">{l}</dt><dd className="mt-1 font-black">{formatPrice(v as number)}</dd></div>
        ))}
      </dl>
      {token && <PayoutCard token={token} />}
      {d.items.length === 0 ? <p className="text-sm text-neutral-500">هنوز خریدی از لینک تو ثبت نشده است.</p> : (
        <ul className="space-y-2 text-sm">
          {d.items.map((i) => (
            <li key={i.id} className="flex flex-wrap justify-between gap-2 rounded-xl bg-neutral-50 p-3">
              <span dir="ltr" className="text-xs text-neutral-500">{i.reference}</span><span>{formatPrice(i.amount_minor)}</span><span className="text-neutral-600">{STATE_FA[i.state] ?? i.state}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

type Payouts = { sheba: string | null; holder: string | null; verified: boolean; min_payout_minor: number;
  payouts: { reference: string; amount_minor: number; status: string; bank_reference: string | null; created_at: string }[] };
const PAYOUT_FA: Record<string, string> = { pending: "در حال واریز", paid: "واریز شد", failed: "ناموفق" };

function PayoutCard({ token }: { token: string }) {
  const [p, setP] = useState<Payouts | null>(null);
  const [sheba, setSheba] = useState("");
  const [holder, setHolder] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => { apiRequest<Payouts>("/me/affiliate/payouts", { token }).then(setP).catch(() => {}); }, [token]);
  useEffect(() => { load(); }, [load]);
  const save = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setMsg(null);
    try {
      await apiRequest("/me/affiliate/sheba", { token, method: "PUT", body: JSON.stringify({ sheba: sheba.replace(/\s/g, ""), holder }) });
      setSheba(""); setHolder(""); setMsg({ ok: true, text: "شبا ثبت شد و پس از تأیید کارشناس، واریزها به آن انجام می‌شود." }); load();
    } catch (err) { setMsg({ ok: false, text: err instanceof ApiError ? err.message : "ثبت ناموفق بود" }); }
    finally { setBusy(false); }
  };
  if (!p) return null;
  return (
    <section className="space-y-3 rounded-2xl border p-4">
      <h2 className="font-bold">حساب واریز پورسانت</h2>
      <p className="text-sm text-neutral-600">
        {p.sheba ? <>شبا: <span dir="ltr">{p.sheba}</span> ({p.holder}) · {p.verified ? <b className="text-green-700">تأییدشده</b> : <b className="text-amber-700">در انتظار تأیید</b>}</> : "هنوز شبا ثبت نکرده‌ای."}
        {" "}واریز وقتی انجام می‌شود که مبلغ قابل برداشت به {formatPrice(p.min_payout_minor)} برسد.
      </p>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`rounded-lg p-2 text-sm ${msg.ok ? "bg-green-50 text-green-800" : "bg-red-50 text-red-700"}`}>{msg.text}</p>}
      <form onSubmit={save} className="grid gap-2 sm:grid-cols-3">
        <label className="text-sm sm:col-span-2">شمارهٔ شبا<input className="mt-1 w-full rounded-lg border px-3 py-2" dir="ltr" placeholder="IR000000000000000000000000" required value={sheba} onChange={(e) => setSheba(e.target.value)} /></label>
        <label className="text-sm">نام صاحب حساب<input className="mt-1 w-full rounded-lg border px-3 py-2" required minLength={2} maxLength={120} value={holder} onChange={(e) => setHolder(e.target.value)} /></label>
        <div className="sm:col-span-3"><button disabled={busy} className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-60">{p.sheba ? "تغییر شبا" : "ثبت شبا"}</button></div>
      </form>
      {p.payouts.length > 0 && (
        <ul className="space-y-1 text-sm">
          {p.payouts.map((x) => (
            <li key={x.reference} className="flex flex-wrap justify-between gap-2 rounded-lg bg-neutral-50 p-2">
              <span dir="ltr" className="text-xs text-neutral-500">{x.reference}</span><span>{formatPrice(x.amount_minor)}</span>
              <span>{PAYOUT_FA[x.status] ?? x.status}{x.bank_reference ? <span className="text-xs text-neutral-500"> · پیگیری {x.bank_reference}</span> : null}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
