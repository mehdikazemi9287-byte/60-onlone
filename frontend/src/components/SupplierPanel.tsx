"use client";
import Link from "next/link";
import SupplierRFQs from "./SupplierRFQs";
import { FormEvent, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { apiRequest } from "@/lib/api";
type Offer = {
  id: number;
  product_name: string;
  selling_price_minor: number;
  stock_quantity: number;
  stock_reserved: number;
  city: string;
  status: string;
  last_price_confirmed_at?: string;
  last_inventory_confirmed_at?: string;
};
type Order = {
  id: number;
  order_number: string;
  status: string;
  created_at: string;
  shipping_city?: string | null;
  shipping_province?: string | null;
  rejection_reason?: string | null;
};
// Persian labels for fulfillment-order statuses (backend fulfillment_engine.VALID_TRANSITIONS).
const FO_STATUS_FA: Record<string, string> = {
  pending_assignment: "در انتظار تخصیص",
  assigned: "در انتظار پذیرش شما",
  accepted: "پذیرفته‌شده",
  preparing: "در حال آماده‌سازی",
  ready: "آماده‌ی تحویل",
  dispatched: "ارسال‌شده",
  delivered: "تحویل‌شده",
  rejected: "ردشده",
  cancelled: "لغوشده",
  failed: "ناموفق",
};
type OrderAction = "accept" | "reject" | "prepare" | "ready" | "dispatch" | "deliver";
// Only transitions the backend allows a supplier to make from each status.
const FO_ACTIONS: Record<string, { action: OrderAction; label: string }[]> = {
  assigned: [
    { action: "accept", label: "پذیرش سفارش" },
    { action: "reject", label: "رد سفارش" },
  ],
  accepted: [{ action: "prepare", label: "شروع آماده‌سازی" }],
  preparing: [{ action: "ready", label: "آماده‌ی تحویل شد" }],
  ready: [
    { action: "dispatch", label: "ارسال شد" },
    { action: "deliver", label: "تحویل حضوری انجام شد" },
  ],
  dispatched: [{ action: "deliver", label: "تحویل مشتری شد" }],
};
function SupplierOrderCard({
  order,
  token,
  onChanged,
}: {
  order: Order;
  token: string;
  onChanged: (o: Order) => void;
}) {
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState(""),
    [rejecting, setRejecting] = useState(false),
    [reason, setReason] = useState("");
  async function run(action: OrderAction) {
    if (action === "reject") {
      if (!reason.trim()) {
        setMessage("دلیل رد سفارش را بنویسید.");
        return;
      }
      if (!window.confirm("سفارش " + order.order_number + " رد شود؟ این کار برگشت‌پذیر نیست و سفارش به تأمین‌کننده‌ی دیگری سپرده می‌شود.")) return;
    }
    setBusy(true);
    setMessage("");
    try {
      const res = await apiRequest<{ fulfillment_order: Order }>(
        "/supplier/orders/" + order.id + "/" + action,
        {
          token,
          method: "POST",
          body: JSON.stringify(action === "reject" ? { reason: reason.trim() } : {}),
        },
      );
      setRejecting(false);
      setReason("");
      setMessage("ثبت شد.");
      onChanged({ ...order, ...res.fulfillment_order, order_number: order.order_number });
    } catch (e) {
      setMessage((e as Error).message || "ثبت انجام نشد؛ دوباره تلاش کنید.");
    } finally {
      setBusy(false);
    }
  }
  const actions = FO_ACTIONS[order.status] ?? [];
  const place = [order.shipping_province, order.shipping_city].filter(Boolean).join("، ");
  return (
    <article className="border rounded-xl p-4 space-y-2">
      <p className="font-bold">سفارش {order.order_number}</p>
      <p>وضعیت: {FO_STATUS_FA[order.status] ?? "نامشخص"}</p>
      {place && <p>مقصد: {place}</p>}
      {order.status === "rejected" && order.rejection_reason && (
        <p>دلیل رد: {order.rejection_reason}</p>
      )}
      {actions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {actions.map((a) =>
            a.action === "reject" ? (
              <button
                key={a.action}
                type="button"
                className="rounded-xl border border-red-300 px-3 py-1 text-red-700"
                disabled={busy}
                onClick={() => setRejecting((v) => !v)}
              >
                {a.label}
              </button>
            ) : (
              <button
                key={a.action}
                type="button"
                className="btn-primary"
                disabled={busy}
                onClick={() => run(a.action)}
              >
                {a.label}
              </button>
            ),
          )}
        </div>
      )}
      {rejecting && (
        <div className="space-y-2">
          <label className="block">
            دلیل رد (الزامی)
            <textarea
              className="block w-full border rounded-xl p-2"
              rows={2}
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="rounded-xl bg-red-700 px-3 py-1 text-white"
            disabled={busy || !reason.trim()}
            onClick={() => run("reject")}
          >
            تأیید رد سفارش
          </button>
        </div>
      )}
      {busy && <p role="status">در حال ثبت…</p>}
      {message && <p role="status">{message}</p>}
    </article>
  );
}
type Summary = {
  unbatched_minor: number;
  in_batch_minor: number;
  settled_minor: number;
};
function OfferEditor({
  offer,
  token,
  refresh,
}: {
  offer: Offer;
  token: string;
  refresh: () => void;
}) {
  const [price, setPrice] = useState(""),
    [stock, setStock] = useState(""),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  async function save(e: FormEvent, kind: "price" | "stock") {
    e.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const value = Number(kind === "price" ? price : stock);
      if (!Number.isSafeInteger(value) || value < 0)
        throw new Error("عدد صحیح معتبر وارد کنید");
      await apiRequest("/supplier/offers/" + offer.id + "/" + kind, {
        token,
        method: "PATCH",
        body: JSON.stringify(
          kind === "price"
            ? { selling_price_minor: value }
            : { stock_quantity: value },
        ),
      });
      setMessage("اصلاح ثبت شد؛ تأیید فروش مستقل است.");
      refresh();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="border rounded-2xl p-4 space-y-3">
      <h2 className="font-bold">{offer.product_name}</h2>
      <p>
        {offer.city} · وضعیت ثبت‌شده: {offer.status}
      </p>
      <p>
        قیمت ثبت‌شده: {offer.selling_price_minor.toLocaleString("fa-IR")} ریال ·
        موجودی ثبت‌شده: {offer.stock_quantity} · رزرو: {offer.stock_reserved}
      </p>
      <p>
        تأیید قیمت: {offer.last_price_confirmed_at ?? "ثبت نشده"} · تأیید
        موجودی: {offer.last_inventory_confirmed_at ?? "ثبت نشده"}
      </p>
      <form
        className="flex flex-wrap gap-3 items-end"
        onSubmit={(e) => save(e, "price")}
      >
        <label>
          قیمت جدید (ریال)
          <input
            className="block border rounded-xl p-2"
            type="number"
            required
            min={0}
            step={1}
            value={price}
            onChange={(e) => setPrice(e.target.value)}
          />
        </label>
        <button className="btn-primary" disabled={busy || price === ""}>
          ثبت قیمت
        </button>
      </form>
      <form
        className="flex flex-wrap gap-3 items-end"
        onSubmit={(e) => save(e, "stock")}
      >
        <label>
          موجودی کل واقعی
          <input
            className="block border rounded-xl p-2"
            type="number"
            required
            min={offer.stock_reserved}
            step={1}
            value={stock}
            onChange={(e) => setStock(e.target.value)}
          />
        </label>
        <button className="btn-primary" disabled={busy || stock === ""}>
          ثبت موجودی
        </button>
      </form>
      {message && <p role="status">{message}</p>}
    </article>
  );
}
export default function SupplierPanel() { const {user}=useAuth(); return <SupplierPanelBody key={user?.id??"guest"}/>; }
function SupplierPanelBody() {
  const { user, token, loading } = useAuth();
  const [offers, setOffers] = useState<Offer[]>([]),
    [orders, setOrders] = useState<Order[]>([]),
    [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState(""),
    [name, setName] = useState(""),
    [page, setPage] = useState(1),
    [reload, setReload] = useState(0),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!token || user?.role !== "supplier") return;
    setError("");
    setOffers([]); setOrders([]); setSummary(null); setName("");
    let active = true;
    setBusy(true);
    Promise.all([
      apiRequest<{ supplier: { display_name: string } }>("/supplier/me", {
        token,
      }),
      apiRequest<{ offers: Offer[] }>(
        "/supplier/offers?limit=25&offset=" + (page - 1) * 25,
        { token },
      ),
      apiRequest<{ fulfillment_orders: Order[] }>(
        "/supplier/orders?limit=25&offset=" + (page - 1) * 25,
        { token },
      ),
      apiRequest<Summary>("/supplier/payables/summary", { token }),
    ])
      .then(([me, o, orders, s]) => {
        if (active) {
          setName(me.supplier.display_name);
          setOffers(o.offers);
          setOrders(orders.fulfillment_orders);
          setSummary(s);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [token, user?.role, page, reload]);
  if (loading) return <p className="p-8">در حال بررسی ورود…</p>;
  if (!user)
    return (
      <main className="container-page py-12">
        <h1 className="text-2xl">پنل تأمین‌کننده</h1>
        <Link href="/login?next=/supplier" className="btn-primary inline-block mt-5">
          ورود به حساب تأمین‌کننده
        </Link>
      </main>
    );
  if (user.role !== "supplier")
    return (
      <main className="container-page py-12">
        <p>این بخش به حساب متصل به تأمین‌کننده نیاز دارد.</p>
        <Link href="/requests/new">ارتباط با پشتیبانی</Link>
      </main>
    );
  return (
    <main className="container-page py-8 space-y-6">
      <h1 className="text-2xl font-bold">پنل تأمین‌کننده {name}</h1>
      <Link href="/account">حساب من</Link>
      {error && <div role="alert" className="rounded-xl bg-red-50 p-4 text-red-800">{error}<button type="button" className="mr-4 underline" onClick={()=>setReload(v=>v+1)}>تلاش مجدد</button></div>}
      {busy && <p role="status">در حال دریافت…</p>}
      {summary && (
        <section className="border rounded-2xl p-4 space-y-2">
          <h2 className="font-bold">دفتر تسویه</h2>
          <p>
            در انتظار صورت تسویه:{" "}
            {summary.unbatched_minor.toLocaleString("fa-IR")} ریال
          </p>
          <p>
            در صورت تسویه: {summary.in_batch_minor.toLocaleString("fa-IR")} ریال
          </p>
          <p>
            تسویه‌شده ثبت‌شده: {summary.settled_minor.toLocaleString("fa-IR")}{" "}
            ریال
          </p>
        </section>
      )}
      <SupplierRFQs token={token!} />
      <section className="space-y-4">
        <h2 className="text-xl font-bold">پیشنهادهای من</h2>
        {!busy && !offers.length && !error && (
          <p>پیشنهادی در این صفحه ثبت نشده است.</p>
        )}
        {offers.map((o) => (
          <OfferEditor
            key={o.id}
            offer={o}
            token={token!}
            refresh={() => setReload((v) => v + 1)}
          />
        ))}
      </section>
      <section>
        <h2 className="text-xl font-bold mb-4">سفارش‌های تأمین</h2>
        {!busy && !orders.length && !error && (
          <p>سفارشی در این صفحه ثبت نشده است.</p>
        )}
        <div className="space-y-3">
          {orders.map((o) => (
            <SupplierOrderCard
              key={o.id}
              order={o}
              token={token!}
              onChanged={(next) =>
                setOrders((list) => list.map((x) => (x.id === next.id ? next : x)))
              }
            />
          ))}
        </div>
      </section>
      <nav className="flex justify-between">
        <button
          disabled={page <= 1 || busy}
          onClick={() => setPage((v) => v - 1)}
        >
          صفحه قبل
        </button>
        <span>{page}</span>
        <button
          disabled={busy || (offers.length < 25 && orders.length < 25)}
          onClick={() => setPage((v) => v + 1)}
        >
          صفحه بعد
        </button>
      </nav>
    </main>
  );
}
