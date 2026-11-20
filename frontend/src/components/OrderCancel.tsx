"use client";
// Customer cancellation before shipment (POST /orders/:n/cancel). The server decides whether the order can still
// be cancelled (state machine, carrier label, returns, installments) and returns the exact amounts given back.
import { useState } from "react";
import { orders as ordersApi, ApiError } from "@/lib/api";
import { formatPrice, toPersianNum } from "@/lib/utils";
import type { Order, OrderCancellation, OrderCancellationStatus } from "@/lib/types";

const REFUND_FA = { pending_finance: "در انتظار واریز توسط واحد مالی", paid: "واریز شد" } as const;

function Summary({ c }: { c: OrderCancellation }) {
  const rows: [string, string][] = [];
  if (c.card_refund_minor > 0) rows.push(["بازگشت مبلغ پرداختی با کارت", formatPrice(c.card_refund_minor)]);
  if (c.credit_restored_minor > 0) rows.push(["برگشت به اعتبار سازمانی", formatPrice(c.credit_restored_minor)]);
  if (c.welfare_restored_minor > 0) rows.push(["برگشت به کیف پول رفاهی", formatPrice(c.welfare_restored_minor)]);
  if (c.coins_restored > 0) rows.push(["۶۰کوین بازگشتی", `${toPersianNum(c.coins_restored)} کوین`]);
  if (c.coins_clawed_back > 0) rows.push(["۶۰کوین کسرشدهٔ این خرید", `${toPersianNum(c.coins_clawed_back)} کوین`]);
  return (
    <div className="space-y-2 text-sm">
      <p className="font-bold text-danger-700">این سفارش لغو شده است.</p>
      {c.reason && <p className="text-neutral-600">علت: {c.reason}</p>}
      {rows.length > 0 && (
        <dl className="space-y-1">
          {rows.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-3"><dt className="text-neutral-500">{k}</dt><dd className="tabular-nums">{v}</dd></div>
          ))}
        </dl>
      )}
      {c.refunds.map((r) => (
        <p key={r.id} className="rounded-lg bg-neutral-50 px-3 py-2 text-xs leading-6 text-neutral-700">
          بازپرداخت {formatPrice(r.amount_minor)}: {REFUND_FA[r.status]}
          {r.status === "pending_finance" && " — بازگشت پول به کارت به‌صورت خودکار انجام نمی‌شود؛ واحد مالی آن را واریز و ثبت می‌کند."}
        </p>
      ))}
      {c.coins_clawback_shortfall > 0 && (
        <p className="text-xs text-neutral-500">{toPersianNum(c.coins_clawback_shortfall)} کوین از کوین‌های این خرید پیش‌تر خرج شده بود و کسر نشد.</p>
      )}
    </div>
  );
}

export function OrderCancel({ token, orderNumber, status, onCancelled }: {
  token: string; orderNumber: string; status: OrderCancellationStatus | null | undefined;
  onCancelled: (order: Order, cancellation: OrderCancellation) => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!status) return null;
  if (status.cancellation) {
    return <section aria-label="لغو سفارش" className="card mt-4 p-4 md:p-5"><Summary c={status.cancellation} /></section>;
  }
  if (!status.cancellable) return null;

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const res = await ordersApi.cancel(token, orderNumber, reason.trim() || undefined);
      onCancelled(res.order, res.cancellation);
      setOpen(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "لغو سفارش انجام نشد؛ دوباره تلاش کنید.");
    } finally { setBusy(false); }
  };

  return (
    <section aria-labelledby="cancel-h" className="card mt-4 p-4 md:p-5">
      <h2 id="cancel-h" className="font-black text-neutral-900">لغو سفارش</h2>
      <p className="mt-1 text-sm leading-7 text-neutral-600">تا پیش از آماده‌شدن مرسوله برای ارسال می‌توانید این سفارش را لغو کنید. موجودی کالا، اعتبار، کیف پول رفاهی و ۶۰کوین مصرف‌شده برمی‌گردد و مبلغ کارت پس از بررسی واحد مالی بازپرداخت می‌شود.</p>
      {!open ? (
        <button type="button" onClick={() => setOpen(true)} className="mt-3 min-h-11 rounded-xl border border-danger-300 px-4 text-sm font-bold text-danger-700 hover:bg-danger-50">لغو این سفارش</button>
      ) : (
        <div className="mt-3 space-y-3">
          <label className="block text-sm text-neutral-700">
            علت لغو (اختیاری)
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} rows={2} className="form-input mt-1" />
          </label>
          <p className="text-sm font-bold text-neutral-800">لغو قابل بازگشت نیست. مطمئن هستید؟</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={submit} className="min-h-11 rounded-xl bg-danger-600 px-4 text-sm font-bold text-white disabled:opacity-50">{busy ? "در حال لغو…" : "بله، سفارش لغو شود"}</button>
            <button type="button" disabled={busy} onClick={() => { setOpen(false); setError(null); }} className="min-h-11 rounded-xl border border-neutral-200 px-4 text-sm font-bold text-neutral-700">انصراف</button>
          </div>
        </div>
      )}
      {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
    </section>
  );
}
