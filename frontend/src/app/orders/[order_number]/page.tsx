"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { cn, formatPrice, toPersianNum } from "@/lib/utils";
import { orders as ordersApi, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { OrderReturns } from "@/components/OrderReturns";
import { Package } from "lucide-react";
import type { FulfillmentOrder, Order } from "@/lib/types";

const FO_STATUS_FA: Record<string, string> = {
  assigned: "ارجاع‌شده", accepted: "پذیرفته‌شده", preparing: "در حال آماده‌سازی",
  ready: "آماده ارسال", dispatched: "ارسال‌شده", delivered: "تحویل‌شده",
};

export default function OrderDetailPage() {
  const params = useParams<{ order_number: string }>();
  const { token, loading: authLoading } = useAuth();
  const [order, setOrder] = useState<Order | null>(null);
  const [fulfillmentOrders, setFulfillmentOrders] = useState<FulfillmentOrder[]>([]);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (authLoading || !token) return;
    ordersApi
      .get(token, params.order_number)
      .then((res) => {
        setOrder(res.order);
        setFulfillmentOrders(res.fulfillment_orders);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) setNotFound(true);
        else setError(e instanceof ApiError ? e.message : "خطا در دریافت سفارش");
      });
  }, [token, authLoading, params.order_number]);

  if (!authLoading && !token) {
    return (
      <div className="internal-page container-page py-24 text-center">
        <h2 className="text-lg font-bold text-neutral-900 mb-2">برای مشاهده این سفارش وارد شوید</h2>
        <Link href={`/login?next=/orders/${params.order_number}`} className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-primary-600 text-white font-semibold text-sm hover:bg-primary-700 transition-colors mt-2">
          ورود به حساب کاربری
        </Link>
      </div>
    );
  }

  if (notFound) {
    return <div className="internal-page container-page py-24 text-center text-neutral-400">این سفارش یافت نشد</div>;
  }
  if (error) {
    return <div className="internal-page container-page py-24 text-center text-danger-600">{error}</div>;
  }
  if (!order) {
    return (
      <div className="internal-page container-page py-6 md:py-8">
        <div className="card p-6 h-64 animate-pulse bg-neutral-100" />
      </div>
    );
  }

  return (
    <div className="internal-page container-page py-6 md:py-8 max-w-3xl">
      <nav className="flex items-center gap-2 text-xs text-neutral-400 mb-6">
        <Link href="/" className="hover:text-primary-600">خانه</Link>
        <span>/</span>
        <Link href="/orders" className="hover:text-primary-600">سفارش‌های من</Link>
        <span>/</span>
        <span className="text-neutral-600">#{order.order_number}</span>
      </nav>

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-black text-neutral-900">سفارش #{order.order_number}</h1>
        <span className="text-xs text-neutral-400">{order.placed_at}</span>
      </div>

      {/* Items */}
      <div className="card p-4 md:p-5 mb-4 space-y-3">
        {order.items.map((item) => (
          <div key={item.product_id} className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-lg bg-neutral-50 text-neutral-400 flex items-center justify-center flex-shrink-0" aria-label="تصویر محصول موجود نیست">
              <Package className="h-5 w-5" aria-hidden="true" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-neutral-900 line-clamp-1">{item.title_fa}</p>
              <p className="text-xs text-neutral-400">× {toPersianNum(item.quantity)}</p>
            </div>
            <p className="text-sm font-semibold tabular-nums">{formatPrice(item.line_total_minor)}</p>
          </div>
        ))}
      </div>

      {/* Shipping address */}
      {order.shipping_address && (
        <div className="card p-4 md:p-5 mb-4">
          <p className="text-xs font-semibold text-neutral-500 uppercase mb-1.5">آدرس تحویل</p>
          <p className="text-sm font-medium text-neutral-900">
            {order.shipping_address.recipient_name} — {order.shipping_address.recipient_phone}
          </p>
          <p className="text-xs text-neutral-500 mt-0.5">
            {order.shipping_address.province}، {order.shipping_address.city}، {order.shipping_address.line1}
          </p>
        </div>
      )}

      {/* Internal fulfillment progress only; public supplier identity is withheld until verified. */}
      {fulfillmentOrders.length > 0 && (
        <div className="card p-4 md:p-5 mb-4">
          <p className="text-xs font-semibold text-neutral-500 uppercase mb-3">وضعیت پردازش سفارش</p>
          <div className="space-y-2">
            {fulfillmentOrders.map((fo) => (
              <div key={fo.id} className="flex items-center justify-between gap-3 text-sm">
                <span className="text-neutral-600">مرحله پردازش داخلی</span>
                <span className={cn("text-xs font-medium px-2 py-0.5 rounded-full", fo.status === "delivered" ? "bg-success-50 text-success-700" : "bg-blue-50 text-blue-700")}>{FO_STATUS_FA[fo.status] ?? "در حال بررسی"}</span>
              </div>
            ))}
          </div>
          <p className="mt-3 border-t border-neutral-100 pt-3 text-xs leading-6 text-neutral-500">اطلاعات تأمین‌کننده و رهگیری شرکت حمل هنوز برای نمایش عمومی تأیید نشده است. این بخش فقط مرحله پردازش داخلی سفارش را نشان می‌دهد.</p>
        </div>
      )}

      {/* Totals */}
      <div className="card p-4 md:p-5 space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-neutral-500">جمع کالاها</span>
          <span className="tabular-nums">{formatPrice(order.subtotal_minor)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-neutral-500">هزینه ارسال</span>
          <span className={order.shipping_fee_minor === 0 ? "text-success-600" : ""}>
            {order.shipping_fee_minor === 0 ? "رایگان" : formatPrice(order.shipping_fee_minor)}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-neutral-500">مالیات</span>
          <span className="tabular-nums">{formatPrice(order.tax_minor)}</span>
        </div>
        {order.credit_minor > 0 && (
          <div className="flex justify-between text-success-600">
            <span>اعتبار سازمانی</span>
            <span className="tabular-nums">−{formatPrice(order.credit_minor)}</span>
          </div>
        )}
        <div className="border-t border-neutral-100 pt-2 flex justify-between font-bold text-neutral-900">
          <span>مجموع پرداخت‌شده</span>
          <span className="text-primary-700 text-base tabular-nums">{formatPrice(order.total_minor)}</span>
        </div>
      </div>
      {token && <OrderReturns token={token} orderNumber={order.order_number} status={order.status}
        items={(order.items as unknown as { product_id: number; title_fa: string; quantity: number }[])} />}
    </div>
  );
}
