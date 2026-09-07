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
};
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
export default function SupplierPanel() {
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
        <Link href="/login" className="btn-primary inline-block mt-5">
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
      {error && <p role="alert">{error}</p>}
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
        {orders.map((o) => (
          <article className="border rounded-xl p-4" key={o.id}>
            <p>سفارش {o.order_number}</p>
            <p>وضعیت: {o.status}</p>
          </article>
        ))}
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
