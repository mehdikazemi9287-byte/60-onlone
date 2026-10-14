"use client";
import { useState } from "react";
import { apiRequest } from "@/lib/api";
type PO = {
  po_number: string;
  status: string;
  total_amount_minor: number;
  shipping_cost_minor: number;
  vat_amount_minor: number;
  grand_total_minor: number;
  payment_terms?: string;
  delivery_lead_days?: number;
  delivery_address?: string;
  items: {
    id: number;
    master_product_id?: number;
    free_text_description?: string;
    quantity: number;
    unit: string;
    unit_price_minor: number;
    total_price_minor: number;
    vat_amount_minor: number;
  }[];
};
const money = (n: number) => n.toLocaleString("fa-IR") + " ریال";
export default function PurchaseDocument({
  organizationId,
  id,
  token,
}: {
  organizationId: string;
  id: number;
  token: string;
}) {
  const [doc, setDoc] = useState<PO | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function show() {
    if (doc) {
      setDoc(null);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const r = await apiRequest<{ purchase_order: PO }>(
        "/orgs/" + organizationId + "/procurement/purchase-orders/" + id,
        { token },
      );
      setDoc(r.purchase_order);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-3 mt-3">
      <button className="btn-primary" disabled={busy} onClick={show}>
        {doc ? "بستن جزئیات" : "مشاهده سند و ردیف‌ها"}
      </button>
      {error && <p role="alert">{error}</p>}
      {doc && (
        <section className="space-y-3">
          <h3 className="font-bold">سند خرید {doc.po_number}</h3>
          <p>
            مبالغ ثبت‌شده در سند؛ این نمایش تأیید پرداخت یا صورتحساب مالیاتی
            نیست.
          </p>
          {doc.items.map((i) => (
            <article className="border rounded-xl p-3 space-y-2" key={i.id}>
              <p>
                {i.free_text_description ||
                  "کالای مرجع شماره " + i.master_product_id}
              </p>
              <p>
                تعداد: {i.quantity} {i.unit} · قیمت واحد:{" "}
                {money(i.unit_price_minor)}
              </p>
              <p>
                مبلغ ردیف: {money(i.total_price_minor)} · مالیات ثبت‌شده:{" "}
                {money(i.vat_amount_minor)}
              </p>
            </article>
          ))}
          <p>جمع کالاها: {money(doc.total_amount_minor)}</p>
          <p>ارسال: {money(doc.shipping_cost_minor)}</p>
          <p>مالیات ثبت‌شده: {money(doc.vat_amount_minor)}</p>
          <p className="font-bold">جمع نهایی: {money(doc.grand_total_minor)}</p>
          <p>شرایط پرداخت: {doc.payment_terms || "ثبت نشده"}</p>
          <p>
            زمان تحویل:{" "}
            {doc.delivery_lead_days === null ||
            doc.delivery_lead_days === undefined
              ? "ثبت نشده"
              : doc.delivery_lead_days + " روز"}
          </p>
          <p>نشانی تحویل: {doc.delivery_address || "ثبت نشده"}</p>
        </section>
      )}
    </div>
  );
}
