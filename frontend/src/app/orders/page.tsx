"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { cn, formatPrice, toPersianNum } from "@/lib/utils";
import { orders as ordersApi, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { Order } from "@/lib/types";

const STATUS_MAP: Record<string, { label: string; color: string; bg: string; dot: string }> = {
  pending:    { label: "در انتظار پرداخت", color: "text-amber-700",   bg: "bg-amber-50",   dot: "bg-amber-400"   },
  paid:       { label: "پرداخت‌شده",        color: "text-blue-700",    bg: "bg-blue-50",    dot: "bg-blue-400"    },
  processing: { label: "در حال پردازش",    color: "text-blue-700",    bg: "bg-blue-50",    dot: "bg-blue-400"    },
  shipped:    { label: "ارسال شده",         color: "text-indigo-700",  bg: "bg-indigo-50",  dot: "bg-indigo-400"  },
  delivered:  { label: "تحویل داده شده",   color: "text-success-700", bg: "bg-success-50", dot: "bg-success-400" },
  cancelled:  { label: "لغو شده",          color: "text-danger-700",  bg: "bg-danger-50",  dot: "bg-danger-400"  },
};

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_MAP[status] ?? {label: status, color:"text-neutral-700", bg:"bg-neutral-100", dot:"bg-neutral-400"};
  return (
    <span className={cn("inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold", s.color, s.bg)}>
      <span className={cn("w-1.5 h-1.5 rounded-full", s.dot)} />
      {s.label}
    </span>
  );
}

function DashboardNav({ active }: { active: string }) {
  const { logout } = useAuth();
  const items = [
    { href: "/orders",  label: "سفارش‌ها",    icon: "📦" },
  ];
  return (
    <aside className="w-full lg:w-56 flex-shrink-0">
      <div className="card p-2">
        {items.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
              active === item.href ? "bg-primary-50 text-primary-700" : "text-neutral-600 hover:bg-neutral-50"
            )}
          >
            <span className="text-base">{item.icon}</span>
            {item.label}
          </Link>
        ))}
        <div className="border-t border-neutral-100 my-2" />
        <button
          onClick={logout}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-danger-600 hover:bg-danger-50 transition-colors"
        >
          <span className="text-base">🚪</span>
          خروج
        </button>
      </div>
    </aside>
  );
}

export default function OrdersPage() { const {user}=useAuth(); return <OrdersBody key={user?.id??"guest"}/>; }
function OrdersBody() {
  const { token, loading: authLoading } = useAuth();
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let live=true; setOrders(null); setError(null);
    if (!authLoading && token) ordersApi.list(token)
      .then(res=>{if(live)setOrders(res.items);})
      .catch(e=>{if(live)setError(e instanceof ApiError?e.message:"خطا در دریافت سفارش‌ها");});
    return ()=>{live=false};
  }, [token, authLoading, retry]);

  if (!authLoading && !token) {
    return (
      <div className="internal-page container-page py-24 text-center">
        <h2 className="text-lg font-bold text-neutral-900 mb-2">برای مشاهده سفارش‌ها وارد شوید</h2>
        <Link href="/login?next=/orders" className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-primary-600 text-white font-semibold text-sm hover:bg-primary-700 transition-colors mt-2">
          ورود به حساب کاربری
        </Link>
      </div>
    );
  }

  return (
    <div className="internal-page container-page py-6 md:py-8">
      <nav className="flex items-center gap-2 text-xs text-neutral-400 mb-6">
        <Link href="/" className="hover:text-primary-600">خانه</Link>
        <span>/</span>
        <span className="text-neutral-600">سفارش‌های من</span>
      </nav>

      <div className="flex gap-6">
        <div className="hidden lg:block">
          <DashboardNav active="/orders" />
        </div>

        <div className="flex-1 min-w-0 space-y-4">
          <div className="flex items-center justify-between">
            <h1 className="text-xl font-black text-neutral-900">سفارش‌های من</h1>
            {orders && <span className="text-sm text-neutral-500">{toPersianNum(orders.length)} سفارش</span>}
          </div>

          {error && <div role="alert" className="text-sm text-danger-600 bg-danger-50 rounded-xl p-3">{error}<button type="button" onClick={()=>setRetry(v=>v+1)} className="mr-4 underline">تلاش مجدد</button></div>}

          {error ? null : orders === null ? (
            <div className="space-y-3">
              {[0, 1, 2].map((i) => <div key={i} className="card h-20 animate-pulse bg-neutral-100" />)}
            </div>
          ) : orders.length === 0 ? (
            <div className="card text-center py-16">
              <p className="text-neutral-500 text-sm mb-4">هنوز سفارشی ثبت نکرده‌اید</p>
              <Link href="/search" className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-primary-600 text-white font-semibold text-sm hover:bg-primary-700 transition-colors">
                مشاهده محصولات
              </Link>
            </div>
          ) : (
            orders.map((order) => (
              <Link key={order.order_number} href={`/orders/${order.order_number}`} className="card overflow-hidden block hover:border-primary-200 transition-colors">
                <div className="p-4 md:p-5 flex flex-wrap items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className="text-sm font-bold text-neutral-900 tabular-nums">سفارش #{order.order_number}</span>
                      <StatusBadge status={order.status} />
                    </div>
                    <p className="text-xs text-neutral-400 mt-1">{order.placed_at}</p>
                  </div>
                  <div className="text-left">
                    <p className="text-base font-bold text-neutral-900 tabular-nums">{formatPrice(order.total_minor)}</p>
                  </div>
                </div>
              </Link>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
