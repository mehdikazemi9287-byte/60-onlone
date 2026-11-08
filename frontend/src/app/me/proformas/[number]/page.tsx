"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatPrice, faDate } from "@/lib/utils";

type Proforma = { number: string; organization: string | null; created_at: string; valid_until: string; expired: boolean; used: boolean;
  items: { product_id: number; title_fa: string; sku: string; quantity: number; unit_price_minor: number; line_total_minor: number }[];
  subtotal_minor: number; shipping_fee_minor: number; tax_minor: number; total_minor: number };

export default function ProformaPage({ params }: { params: Promise<{ number: string }> }) {
  const { token } = useAuth();
  const [pf, setPf] = useState<Proforma | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    if (!token) return;
    params.then((p) => apiRequest<Proforma>(`/me/proformas/${encodeURIComponent(p.number)}`, { token }).then(setPf).catch(() => setErr(true)));
  }, [params, token]);
  if (err) return <main className="p-10 text-center">پیش‌فاکتور یافت نشد.</main>;
  if (!pf) return <main className="p-10 text-center">…</main>;
  return (
    <main className="mx-auto max-w-3xl px-4 py-8 print:py-0">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-black">پیش‌فاکتور شصت آنلاین</h1>
          <p className="mt-1 text-sm text-neutral-600">شماره <span dir="ltr">{pf.number}</span>{pf.organization ? ` · ${pf.organization}` : ""}</p>
          <p className="text-sm text-neutral-600">صدور {faDate(pf.created_at)} · معتبر تا {faDate(pf.valid_until)}</p>
        </div>
        <button className="rounded-xl border px-4 py-2 text-sm print:hidden" onClick={() => window.print()}>چاپ / PDF</button>
      </div>
      {pf.expired && <p role="alert" className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">مهلت این پیش‌فاکتور تمام شده است.</p>}
      <table className="mt-6 w-full text-sm">
        <thead><tr className="border-b text-right text-neutral-500"><th className="p-2">کالا</th><th className="p-2">تعداد</th><th className="p-2">فی</th><th className="p-2">جمع</th></tr></thead>
        <tbody>{pf.items.map((i) => (
          <tr key={i.product_id} className="border-b"><td className="p-2">{i.title_fa}</td><td className="p-2">{i.quantity}</td>
            <td className="p-2">{formatPrice(i.unit_price_minor)}</td><td className="p-2">{formatPrice(i.line_total_minor)}</td></tr>))}</tbody>
      </table>
      <dl className="mt-4 space-y-1 text-sm">
        <div className="flex justify-between"><dt>جمع کالاها</dt><dd>{formatPrice(pf.subtotal_minor)}</dd></div>
        <div className="flex justify-between"><dt>ارسال</dt><dd>{formatPrice(pf.shipping_fee_minor)}</dd></div>
        <div className="flex justify-between"><dt>مالیات بر ارزش افزوده</dt><dd>{formatPrice(pf.tax_minor)}</dd></div>
        <div className="flex justify-between text-base font-black"><dt>مبلغ قابل پرداخت</dt><dd>{formatPrice(pf.total_minor)}</dd></div>
      </dl>
      <p className="mt-4 text-xs text-neutral-500">اگر هنگام پرداخت مبلغ سبد از این پیش‌فاکتور بیشتر شده باشد، پرداخت انجام نمی‌شود تا بی‌خبر بیشتر نپردازید.</p>
      {!pf.expired && !pf.used && <Link href={`/checkout?proforma=${encodeURIComponent(pf.number)}`} className="mt-6 inline-block rounded-xl bg-primary-600 px-6 py-3 font-bold text-white print:hidden">پرداخت با همین پیش‌فاکتور</Link>}
    </main>
  );
}
