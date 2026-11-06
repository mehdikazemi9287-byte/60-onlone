"use client";

import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { downloadAuthed } from "@/lib/commerce";
import { formatPrice, toPersianNum } from "@/lib/utils";

type Row = { affiliate_id: number; code: string; amount_minor: number; sheba: string | null; holder: string | null; reason?: string };
type Unv = { affiliate_id: number; code: string; sheba: string; holder: string; user_name: string };
type Batch = { id: number; reference: string; status: string; total_minor: number; payout_count: number; created_at: string };
type Payout = { id: number; reference: string; code: string; amount_minor: number; sheba: string; holder: string; status: string; bank_reference: string | null };
type Preview = { min_payout_minor: number; ready: Row[]; waiting: Row[]; ready_total_minor: number; unverified: Unv[]; batches: Batch[] };
const REASON_FA: Record<string, string> = { no_sheba: "بدون شبا", sheba_unverified: "شبا تأیید نشده", below_minimum: "کمتر از حداقل" };
const STATUS_FA: Record<string, string> = { open: "باز", exported: "فایل گرفته شد", closed: "بسته", pending: "در انتظار", paid: "واریز شد", failed: "ناموفق" };
const btn = "rounded-lg bg-[#102B7A] px-3 py-1.5 text-sm font-bold text-white disabled:opacity-50";

export default function AffiliatePayoutsAdmin() {
  const { token } = useAuth();
  const [p, setP] = useState<Preview | null>(null);
  const [open, setOpen] = useState<{ id: number; payouts: Payout[] } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = async () => { if (token) try { setP(await apiRequest<Preview>("/admin/affiliate-payouts/preview", { token })); } catch (e) { setMsg((e as Error).message); } };
  useEffect(() => { void load(); }, [token]); // eslint-disable-line react-hooks/exhaustive-deps
  const act = async (fn: () => Promise<unknown>) => { setMsg(null); try { await fn(); await load(); } catch (e) { setMsg((e as Error).message); } };
  const showBatch = (id: number) => act(async () => setOpen(await apiRequest<{ id: number; payouts: Payout[] }>(`/admin/affiliate-payouts/batches/${id}`, { token: token! })));
  if (!token || !p) return <p className="p-6 text-sm text-neutral-500">{msg ?? "در حال بارگذاری…"}</p>;
  return (
    <section dir="rtl" className="space-y-5 p-4">
      <h1 className="text-xl font-black">تسویه با همکاران فروش</h1>
      {msg && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{msg}</p>}

      <div className="rounded-xl bg-white p-4 ring-1 ring-neutral-200">
        <h2 className="font-bold">شباهای منتظر تأیید ({toPersianNum(p.unverified.length)})</h2>
        <p className="text-xs text-neutral-500">پیش از تأیید، نام صاحب حساب را با استعلام شبا در بانک مقایسه کنید.</p>
        <ul className="mt-2 space-y-2 text-sm">
          {p.unverified.map((u) => (
            <li key={u.affiliate_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-neutral-50 p-2">
              <span>{u.user_name} · کد {u.code} · <span dir="ltr">{u.sheba}</span> · {u.holder}</span>
              <button className={btn} onClick={() => act(() => apiRequest(`/admin/affiliates/${u.affiliate_id}/verify-sheba`, { token, method: "POST", body: JSON.stringify({ sheba: u.sheba }) }))}>تأیید شبا</button>
            </li>
          ))}
        </ul>
      </div>

      <div className="rounded-xl bg-white p-4 ring-1 ring-neutral-200">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-bold">آمادهٔ واریز: {toPersianNum(p.ready.length)} نفر · {formatPrice(p.ready_total_minor)}</h2>
          <button className={btn} disabled={!p.ready.length} onClick={() => act(async () => { const b = await apiRequest<{ id: number }>("/admin/affiliate-payouts/batches", { token, method: "POST" }); await showBatch(b.id); })}>ساخت دستهٔ واریز</button>
        </div>
        <p className="text-xs text-neutral-500">حداقل مبلغ واریز: {formatPrice(p.min_payout_minor)}</p>
        {p.waiting.length > 0 && <p className="mt-2 text-sm text-neutral-600">منتظر: {p.waiting.map((w) => `${w.code} (${REASON_FA[w.reason ?? ""] ?? w.reason}، ${formatPrice(w.amount_minor)})`).join("، ")}</p>}
      </div>

      <div className="rounded-xl bg-white p-4 ring-1 ring-neutral-200">
        <h2 className="font-bold">دسته‌های واریز</h2>
        <ul className="mt-2 space-y-2 text-sm">
          {p.batches.map((b) => (
            <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-neutral-50 p-2">
              <span dir="ltr" className="text-xs">{b.reference}</span><span>{toPersianNum(b.payout_count)} واریز · {formatPrice(b.total_minor)} · {STATUS_FA[b.status]}</span>
              <span className="flex gap-2">
                <button className={btn} onClick={() => showBatch(b.id)}>جزئیات</button>
                <button className={btn} onClick={() => act(() => downloadAuthed(`/admin/affiliate-payouts/batches/${b.id}/export.csv`, token, `affiliate-payouts-${b.id}.csv`))}>فایل بانک</button>
              </span>
            </li>
          ))}
        </ul>
        {open && (
          <table className="mt-3 w-full text-right text-sm">
            <thead className="text-xs text-neutral-500"><tr><th className="p-2">همکار</th><th>مبلغ</th><th>شبا</th><th>وضعیت</th><th /></tr></thead>
            <tbody>
              {open.payouts.map((x) => (
                <tr key={x.id} className="border-t">
                  <td className="p-2">{x.code} · {x.holder}</td><td className="tabular-nums">{formatPrice(x.amount_minor)}</td>
                  <td dir="ltr" className="text-xs">{x.sheba}</td><td>{STATUS_FA[x.status]}{x.bank_reference ? ` · ${x.bank_reference}` : ""}</td>
                  <td className="space-x-1">{x.status === "pending" && <>
                    <button className={btn} onClick={() => { const r = window.prompt("شمارهٔ پیگیری بانک"); if (r) void act(async () => { await apiRequest(`/admin/affiliate-payouts/${x.id}/paid`, { token, method: "POST", body: JSON.stringify({ bank_reference: r }) }); await showBatch(open.id); }); }}>واریز شد</button>
                    <button className="rounded-lg px-3 py-1.5 text-sm ring-1 ring-neutral-300" onClick={() => { const r = window.prompt("دلیل ناموفق بودن") ?? ""; void act(async () => { await apiRequest(`/admin/affiliate-payouts/${x.id}/failed`, { token, method: "POST", body: JSON.stringify({ reason: r }) }); await showBatch(open.id); }); }}>ناموفق</button>
                  </>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
