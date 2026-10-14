"use client";
// Retail returns on an order: request (items + reason), status timeline, cancel while unreviewed.
import { useCallback, useEffect, useState } from "react";
import { RotateCcw } from "lucide-react";
import { apiRequest, newIdempotencyKey } from "@/lib/api";
import { formatPrice, toPersianNum } from "@/lib/utils";

type Ret = { id: number; status: string; status_fa: string; reason: string; refund_amount_minor: number | null; refund_reference: string | null;
  items: { product_id: number; title_fa: string; quantity: number }[]; events: { status: string; note: string | null; created_at: string; actor: string }[] };
const STEPS = ["requested", "approved", "received", "refund_pending", "refunded"];
const FA: Record<string, string> = { requested: "ثبت", approved: "تأیید", received: "دریافت کالا", refund_pending: "در انتظار بازپرداخت", refunded: "بازپرداخت" };

export function OrderReturns({ token, orderNumber, status, items }: { token: string; orderNumber: string; status: string;
  items: { product_id: number; title_fa: string; quantity: number }[] }) {
  const [list, setList] = useState<Ret[]>([]), [open, setOpen] = useState(false), [qty, setQty] = useState<Record<number, number>>({});
  const [reason, setReason] = useState(""), [busy, setBusy] = useState(false), [err, setErr] = useState(""), [key] = useState(newIdempotencyKey);
  const load = useCallback(() => apiRequest<{ items: Ret[] }>(`/orders/${orderNumber}/returns`, { token }).then((r) => setList(r.items)).catch(() => {}), [token, orderNumber]);
  useEffect(() => { void load(); }, [load]);
  const eligible = ["paid", "fulfilling", "delivered"].includes(status) && !list.some((r) => ["requested", "approved", "received", "refund_pending"].includes(r.status));
  const submit = async () => {
    setBusy(true); setErr("");
    try {
      await apiRequest(`/orders/${orderNumber}/returns`, { token, method: "POST", headers: { "Idempotency-Key": key },
        body: JSON.stringify({ reason, items: Object.entries(qty).filter(([, q]) => q > 0).map(([id, q]) => ({ product_id: Number(id), quantity: q })) }) });
      setOpen(false); await load();
    } catch (e) { setErr(e instanceof Error ? e.message : "ثبت ناموفق بود"); } finally { setBusy(false); }
  };
  const cancel = async (id: number) => { await apiRequest(`/returns/${id}/cancel`, { token, method: "POST" }).catch(() => {}); await load(); };
  return (
    <section className="card mt-4 p-4" dir="rtl" aria-label="مرجوعی">
      <div className="flex items-center justify-between gap-2"><h2 className="flex items-center gap-2 font-black text-neutral-900"><RotateCcw className="h-4 w-4" /> مرجوعی و بازپرداخت</h2>
        {eligible && !open && <button type="button" onClick={() => setOpen(true)} className="rounded-xl border px-3 py-2 text-sm font-bold">درخواست مرجوعی</button>}</div>
      {open && <div className="mt-3 space-y-2">
        {items.map((i) => <label key={i.product_id} className="flex items-center justify-between gap-2 text-sm"><span className="min-w-0 truncate">{i.title_fa}</span>
          <input type="number" min={0} max={i.quantity} value={qty[i.product_id] ?? 0} aria-label={`تعداد مرجوعی ${i.title_fa}`}
            onChange={(e) => setQty({ ...qty, [i.product_id]: Math.min(i.quantity, Math.max(0, Math.floor(Number(e.target.value)) || 0)) })} className="h-10 w-20 rounded-lg border text-center" /></label>)}
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="علت مرجوعی" aria-label="علت مرجوعی" className="w-full rounded-xl border p-3 text-sm" rows={3} />
        {err && <p role="alert" className="text-sm text-red-700">{err}</p>}
        <div className="flex gap-2"><button type="button" onClick={submit} disabled={busy || reason.trim().length < 3} className="rounded-xl bg-brand-navy px-4 py-2 text-sm font-bold text-white disabled:opacity-50">ثبت درخواست</button>
          <button type="button" onClick={() => setOpen(false)} className="rounded-xl border px-4 py-2 text-sm">انصراف</button></div>
      </div>}
      {!list.length && !open && <p className="mt-2 text-xs text-neutral-500">درخواستی ثبت نشده است.</p>}
      {list.map((r) => (
        <div key={r.id} className="mt-3 rounded-xl bg-neutral-50 p-3 text-sm">
          <p className="font-bold">{r.status_fa}{r.refund_amount_minor ? ` · ${formatPrice(r.refund_amount_minor)}` : ""}{r.refund_reference ? ` · مرجع ${r.refund_reference}` : ""}</p>
          <p className="text-xs text-neutral-600">{r.items.map((i) => `${i.title_fa} ×${toPersianNum(i.quantity)}`).join("، ")} — {r.reason}</p>
          {!["rejected", "cancelled"].includes(r.status) && <ol className="mt-2 grid grid-cols-5 gap-1 text-center text-[10px]">{STEPS.map((s, i) => (
            <li key={s} className={`rounded px-1 py-1 font-bold ${i <= STEPS.indexOf(r.status) ? "bg-brand-navy text-white" : "bg-white text-neutral-500"}`}>{FA[s]}</li>))}</ol>}
          {r.status === "requested" && <button type="button" onClick={() => cancel(r.id)} className="mt-2 text-xs font-bold text-red-700">لغو درخواست</button>}
        </div>))}
    </section>
  );
}
