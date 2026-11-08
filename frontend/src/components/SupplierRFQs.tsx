"use client";
import { FormEvent, useEffect, useState } from "react";
import { apiRequest, newIdempotencyKey } from "@/lib/api";
type Item = {
  id: number;
  product_name_fa?: string;
  free_text_description?: string;
  quantity: number;
  unit: string;
};
type RFQ = {
  id: number;
  title: string;
  rfq_number: string;
  status: string;
  deadline_at?: string;
  items: Item[];
};
function QuoteForm({ rfq, token }: { rfq: RFQ; token: string }) {
  const [values, setValues] = useState<
    Record<number, { price: string; quantity: string }>
  >({});
  const [shipping, setShipping] = useState(""),
    [terms, setTerms] = useState(""),
    [lead, setLead] = useState(""),
    [validity, setValidity] = useState("");
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState(""),
    [key, setKey] = useState("");
  useEffect(() => setKey(newIdempotencyKey()), []);
  const integer = (s: string) => {
    if (!s.trim() || !Number.isSafeInteger(Number(s)) || Number(s) < 0)
      throw new Error("مبلغ و تعداد باید عدد صحیح معتبر باشند");
    return Number(s);
  };
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      const items = rfq.items
        .filter(
          (i) =>
            values[i.id]?.price !== undefined && values[i.id]?.price !== "",
        )
        .map((i) => ({
          rfq_item_id: i.id,
          unit_price_minor: integer(values[i.id].price),
          quantity: integer(values[i.id].quantity),
        }));
      if (!items.length || items.some((i) => i.quantity < 1))
        throw new Error("حداقل یک ردیف با قیمت و تعداد قابل تأمین لازم است");
      const response = await apiRequest<{ quote: { quote_number: string } }>(
        "/supplier/rfqs/" + rfq.id + "/quotes",
        {
          token,
          method: "POST",
          headers: { "Idempotency-Key": key },
          body: JSON.stringify({
            items,
            shipping_cost_minor: integer(shipping),
            payment_terms: terms,
            delivery_lead_days: integer(lead),
            validity_days: integer(validity),
          }),
        },
      );
      setMessage(
        "پیشنهاد " +
          response.quote.quote_number +
          " ثبت شد؛ این ثبت تأیید قرارداد یا پرداخت نیست.",
      );
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="border rounded-2xl p-4 space-y-3">
      <h3 className="font-bold">{rfq.title}</h3>
      <p>
        {rfq.rfq_number} · {rfq.status}
        {rfq.deadline_at ? " · مهلت: " + rfq.deadline_at : ""}
      </p>
      {rfq.status === "open" ? (
        <form onSubmit={submit} onChange={() => setKey(newIdempotencyKey())}>
          <fieldset disabled={busy} className="space-y-4">
            <p>
              فقط ردیف‌های قابل تأمین را با قیمت و تعداد واقعی تکمیل کنید.
              مبلغ‌ها به ریال هستند؛ خالی گذاشتن قیمت یعنی آن ردیف در پیشنهاد
              شما نیست.
            </p>
            {rfq.items.map((i) => (
              <div className="border rounded-xl p-3 space-y-2" key={i.id}>
                <p>
                  {i.product_name_fa ||
                    i.free_text_description ||
                    "ردیف " + i.id}{" "}
                  · مقدار درخواست: {i.quantity} {i.unit}
                </p>
                <div className="grid sm:grid-cols-2 gap-3">
                  <label>
                    قیمت واحد (ریال)
                    <input
                      aria-label={"قیمت ردیف " + i.id}
                      className="block border rounded-xl p-2 w-full"
                      type="number"
                      min={0}
                      step={1}
                      value={values[i.id]?.price ?? ""}
                      onChange={(e) =>
                        setValues((v) => ({
                          ...v,
                          [i.id]: {
                            quantity: v[i.id]?.quantity ?? "",
                            price: e.target.value,
                          },
                        }))
                      }
                    />
                  </label>
                  <label>
                    تعداد قابل تأمین
                    <input
                      aria-label={"تعداد ردیف " + i.id}
                      className="block border rounded-xl p-2 w-full"
                      type="number"
                      min={1}
                      step={1}
                      required={!!values[i.id]?.price}
                      value={values[i.id]?.quantity ?? ""}
                      onChange={(e) =>
                        setValues((v) => ({
                          ...v,
                          [i.id]: {
                            price: v[i.id]?.price ?? "",
                            quantity: e.target.value,
                          },
                        }))
                      }
                    />
                  </label>
                </div>
              </div>
            ))}
            <label className="block">
              هزینه واقعی ارسال (ریال)
              <input
                className="block border rounded-xl p-2 w-full"
                type="number"
                min={0}
                step={1}
                required
                value={shipping}
                onChange={(e) => setShipping(e.target.value)}
              />
            </label>
            <label className="block">
              شرایط پرداخت
              <textarea
                className="block border rounded-xl p-2 w-full"
                required
                maxLength={2000}
                value={terms}
                onChange={(e) => setTerms(e.target.value)}
              />
            </label>
            <div className="grid sm:grid-cols-2 gap-3">
              <label>
                زمان تحویل (روز)
                <input
                  className="block border rounded-xl p-2 w-full"
                  required
                  type="number"
                  min={0}
                  step={1}
                  value={lead}
                  onChange={(e) => setLead(e.target.value)}
                />
              </label>
              <label>
                اعتبار پیشنهاد (روز)
                <input
                  className="block border rounded-xl p-2 w-full"
                  required
                  type="number"
                  min={1}
                  step={1}
                  value={validity}
                  onChange={(e) => setValidity(e.target.value)}
                />
              </label>
            </div>
            <button className="btn-primary" disabled={!key}>
              ثبت پیشنهاد تأمین
            </button>
          </fieldset>
        </form>
      ) : (
        <p>این استعلام برای دریافت پیشنهاد باز نیست.</p>
      )}
      {message && <p role="status">{message}</p>}
    </article>
  );
}
export default function SupplierRFQs({ token }: { token: string }) {
  const [items, setItems] = useState<RFQ[]>([]),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    apiRequest<{ items: RFQ[] }>("/supplier/rfqs", { token })
      .then((r) => {
        if (active) setItems(r.items);
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [token]);
  return (
    <section className="space-y-4">
      <h2 className="text-xl font-bold">استعلام‌های دعوت‌شده</h2>
      {error && <p role="alert">{error}</p>}
      {loading ? (
        <p>در حال دریافت…</p>
      ) : !items.length && !error ? (
        <p>دعوتی برای این حساب ثبت نشده است.</p>
      ) : null}
      {items.map((r) => (
        <QuoteForm key={r.id} rfq={r} token={token} />
      ))}
    </section>
  );
}
