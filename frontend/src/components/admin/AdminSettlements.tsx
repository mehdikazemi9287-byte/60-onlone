"use client";
// Platform finance: retail marketplace supplier settlement. Batches are built only from REAL unbatched payables
// (created when a fulfillment order is delivered). Completing a batch records the accounting entry with the bank
// reference of a transfer made outside the system; no bank payout is triggered from here (no bank integration).
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest, newIdempotencyKey } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatPrice, toPersianNum } from "@/lib/utils";

type Supplier = { id: number; display_name: string; status: string };
type Payable = { id: number; fulfillment_order_id: number; order_id: number | null; gross_minor: number; created_at: string };
type Batch = { id: number; supplier_id: number; status: string; gross_minor: number; commission_minor: number; shipping_charge_minor: number;
  net_minor: number; items_count: number; commission_rate_bps: number; created_at: string; completed_at?: string | null };

const BATCH_FA: Record<string, string> = { pending: "در انتظار پرداخت", completed: "پرداخت‌شده", cancelled: "لغوشده" };
const faDigits = (v: string) => v.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))).replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)));

export function AdminSettlements() {
  const { token, user, loading } = useAuth();
  const [suppliers, setSuppliers] = useState<Supplier[]>([]), [sid, setSid] = useState<number | null>(null);
  const [payables, setPayables] = useState<Payable[]>([]), [batches, setBatches] = useState<Batch[]>([]);
  const [picked, setPicked] = useState<number[]>([]), [commission, setCommission] = useState("10"), [refs, setRefs] = useState<Record<number, string>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null), [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    apiRequest<{ suppliers?: Supplier[]; items?: Supplier[] }>("/admin/suppliers?limit=200", { token })
      .then((r) => setSuppliers(r.suppliers ?? r.items ?? [])).catch((e) => setMsg({ ok: false, text: e.message }));
  }, [token]);
  const load = useCallback(async () => {
    if (!token || !sid) return;
    const [p, b] = await Promise.all([
      apiRequest<{ payables: Payable[] }>(`/admin/suppliers/${sid}/payables`, { token }),
      apiRequest<{ batches: Batch[] }>(`/admin/settlement-batches?supplier_id=${sid}`, { token }),
    ]);
    setPayables(p.payables); setBatches(b.batches); setPicked([]);
  }, [token, sid]);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: e.message })); }, [load]);

  if (loading) return <div className="h-40 animate-pulse rounded-xl bg-neutral-100" />;
  if (user?.role !== "admin") return <p className="p-8">دسترسی مدیریت لازم است.</p>;

  const create = async () => {
    const pct = Number(faDigits(commission));
    if (!picked.length || !Number.isFinite(pct) || pct < 0 || pct > 100) { setMsg({ ok: false, text: "اقلام و درصد کارمزد معتبر را مشخص کنید" }); return; }
    setBusy(true); setMsg(null);
    try {
      await apiRequest("/admin/settlement-batches", { token: token!, method: "POST", body: JSON.stringify({
        supplier_id: sid, payable_entry_ids: picked, commission_rate_bps: Math.round(pct * 100), idempotency_key: newIdempotencyKey() }) });
      setMsg({ ok: true, text: "دسته تسویه ساخته شد." }); await load();
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "ساخت دسته ناموفق بود" }); } finally { setBusy(false); }
  };
  const complete = async (b: Batch) => {
    const ref = (refs[b.id] || "").trim();
    if (!ref) { setMsg({ ok: false, text: "شماره پیگیری انتقال بانکی الزامی است" }); return; }
    setBusy(true); setMsg(null);
    try {
      await apiRequest(`/admin/settlement-batches/${b.id}/complete`, { token: token!, method: "POST", body: JSON.stringify({ payment_reference: ref }) });
      setMsg({ ok: true, text: `پرداخت دسته ${toPersianNum(b.id)} ثبت شد.` }); await load();
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "ثبت پرداخت ناموفق بود" }); } finally { setBusy(false); }
  };

  return (
    <main className="container-page space-y-5 py-8" dir="rtl">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">تسویه با تأمین‌کنندگان (فروش خرد)</h1>
        <Link href="/admin" className="text-sm font-bold text-brand-blue">بازگشت به مدیریت</Link>
      </div>
      <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">اتصال بانکی وجود ندارد: انتقال وجه بیرون از سامانه انجام می‌شود و اینجا فقط ثبت حسابداری آن با شماره پیگیری بانک انجام می‌شود.</p>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`rounded-xl p-3 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"}`}>{msg.text}</p>}
      <label className="grid max-w-md gap-1 text-sm font-bold">تأمین‌کننده
        <select aria-label="تأمین‌کننده" value={sid ?? ""} onChange={(e) => setSid(e.target.value ? Number(e.target.value) : null)} className="h-11 rounded-xl border px-3">
          <option value="">انتخاب کنید</option>
          {suppliers.map((s) => <option key={s.id} value={s.id}>{s.display_name}</option>)}
        </select></label>
      {sid && <>
        <section className="card space-y-3 p-4" aria-label="بدهی‌های تسویه‌نشده">
          <h2 className="font-bold">بدهی‌های تسویه‌نشده ({toPersianNum(payables.length)})</h2>
          {!payables.length ? <p className="text-sm text-neutral-600">برای این تأمین‌کننده بدهی تسویه‌نشده‌ای ثبت نشده است (بدهی پس از تحویل سفارش ایجاد می‌شود).</p> : <>
            <div className="overflow-x-auto"><table className="w-full min-w-[480px] text-sm"><thead><tr className="text-right text-neutral-500"><th className="p-2">انتخاب</th><th className="p-2">سفارش تأمین</th><th className="p-2">مبلغ ناخالص</th><th className="p-2">تاریخ</th></tr></thead>
              <tbody>{payables.map((p) => <tr key={p.id} className="border-t">
                <td className="p-2"><input type="checkbox" aria-label={`انتخاب ${p.id}`} checked={picked.includes(p.id)} onChange={(e) => setPicked((x) => e.target.checked ? [...x, p.id] : x.filter((i) => i !== p.id))} /></td>
                <td className="p-2">{toPersianNum(p.fulfillment_order_id)}</td><td className="p-2">{formatPrice(p.gross_minor)}</td>
                <td className="p-2">{new Date(p.created_at).toLocaleDateString("fa-IR")}</td></tr>)}</tbody></table></div>
            <div className="flex flex-wrap items-end gap-3">
              <label className="grid gap-1 text-xs font-bold">کارمزد (درصد)<input inputMode="decimal" value={commission} onChange={(e) => setCommission(e.target.value)} className="h-10 w-24 rounded-xl border px-3" /></label>
              <button type="button" disabled={busy || !picked.length} onClick={create} className="h-10 rounded-xl bg-brand-navy px-4 text-sm font-bold text-white disabled:opacity-50">ساخت دسته تسویه ({toPersianNum(picked.length)} قلم)</button>
            </div></>}
        </section>
        <section className="card space-y-3 p-4" aria-label="دسته‌های تسویه">
          <h2 className="font-bold">دسته‌های تسویه</h2>
          {!batches.length ? <p className="text-sm text-neutral-600">دسته‌ای ثبت نشده است.</p> : (
            <ul className="divide-y">{batches.map((b) => <li key={b.id} className="grid gap-2 py-3 text-sm md:grid-cols-[1fr_auto] md:items-center">
              <div><b>دسته {toPersianNum(b.id)}</b> · {BATCH_FA[b.status] ?? b.status} · {toPersianNum(b.items_count)} قلم
                <div className="text-xs text-neutral-600">ناخالص {formatPrice(b.gross_minor)} · کارمزد {formatPrice(b.commission_minor)} · ارسال {formatPrice(b.shipping_charge_minor)} · <b>خالص پرداختی {formatPrice(b.net_minor)}</b></div></div>
              {b.status === "pending" && <div className="flex flex-wrap gap-2">
                <input aria-label={`شماره پیگیری بانکی دسته ${b.id}`} placeholder="شماره پیگیری انتقال بانکی" value={refs[b.id] ?? ""} onChange={(e) => setRefs((r) => ({ ...r, [b.id]: e.target.value }))} className="h-10 min-w-0 flex-1 rounded-xl border px-3" />
                <button type="button" disabled={busy} onClick={() => complete(b)} className="h-10 rounded-xl border border-brand-navy px-3 text-xs font-bold text-brand-navy">ثبت پرداخت</button>
              </div>}
            </li>)}</ul>)}
        </section></>}
    </main>
  );
}
