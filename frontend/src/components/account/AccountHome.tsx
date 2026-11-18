"use client";

// /account — Stitch screen 17 (حساب کاربری, mobile 390) rebuilt faithfully; on desktop the same cards sit in
// a centred column. Real data only: the signed-in user, /me/credit (organization credit), /checkout/welfare
// (employee welfare wallet), /me/loyalty (60Coin), /orders (status counts + latest open order). Stitch blocks
// without a backend (cash wallet top-up, saved addresses, profile edit, app version) are not rendered.

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { apiRequest, orders as ordersApi, checkout as checkoutApi } from "@/lib/api";
import type { Order } from "@/lib/types";
import { toPersianNum } from "@/lib/utils";
// clsx, not twMerge: tailwind-merge does not know the st- font-size tokens and drops them next to st- colors.
import { clsx as cn } from "clsx";
import { OrgInvitations } from "@/components/account/OrgInvitations";
import { Icon, stRoot, toman } from "@/components/checkout/st";

type Credit = {
  has_organization?: boolean;
  total_available_minor?: number;
  organizations?: { id: number; display_name: string; role: string; membership_status: string }[];
  allocations: { id: number }[];
};
type Loyalty = { balance_coins: number; tier: { name_fa: string } | null };

const ROLE_FA: Record<string, string> = { organization_admin: "مدیر حساب سازمان", organization_finance: "مالی سازمان", procurement_agent: "کارپرداز", employee: "کارمند" };
const ACCOUNT_ROLE_FA: Record<string, string> = { customer: "حساب خریدار", supplier: "حساب تأمین‌کننده", admin: "مدیر سامانه" };

const OPEN = ["pending", "paid", "processing", "shipped"] as const;
const STATUS: Record<string, { label: string; step: number }> = {
  pending: { label: "در انتظار پرداخت", step: 1 },
  paid: { label: "پرداخت‌شده", step: 2 },
  processing: { label: "در حال پردازش", step: 3 },
  shipped: { label: "ارسال شده", step: 4 },
  delivered: { label: "تحویل داده شده", step: 5 },
  cancelled: { label: "لغو شده", step: 0 },
};

export default function AccountHome() {
  const { user } = useAuth();
  return <AccountHomeBody key={user?.id ?? "guest"} />;
}

function AccountHomeBody() {
  const { user, token, loading, logout } = useAuth();
  const [credit, setCredit] = useState<Credit | null>(null);
  const [welfare, setWelfare] = useState<{ available: boolean; remaining_minor: number } | null>(null);
  const [loyalty, setLoyalty] = useState<Loyalty | null>(null);
  const [orders, setOrders] = useState<{ items: Order[]; total: number } | null>(null);
  const [tab, setTab] = useState<"open" | "delivered" | "cancelled">("open");

  useEffect(() => {
    if (!token || !user) return;
    if (user.role === "customer") {
      apiRequest<Credit>("/me/credit", { token }).then(setCredit).catch(() => setCredit(null));
      checkoutApi.welfare(token).then(setWelfare).catch(() => setWelfare(null));
    }
    apiRequest<Loyalty>("/me/loyalty", { token }).then(setLoyalty).catch(() => setLoyalty(null));
    ordersApi.list(token, 1, 50).then((r) => setOrders({ items: r.items, total: r.total })).catch(() => setOrders(null));
  }, [token, user]);

  if (loading) return <p className="p-8">در حال بررسی ورود…</p>;
  if (!user) {
    return (
      <main className={cn(stRoot, "min-h-[60vh] px-st-margin py-24 text-center")} dir="rtl">
        <div className="mx-auto max-w-md bg-st-surface-container-lowest rounded-xl p-st-space-lg shadow-sm">
          <h1 className="text-st-headline-lg-mobile text-st-primary-container">حساب من</h1>
          <Link className="mt-st-space-md inline-flex h-12 items-center px-6 rounded-xl bg-st-primary-container text-st-on-primary text-st-label-lg hover:bg-st-secondary" href={"/login?next=" + encodeURIComponent("/account")}>
            ورود به حساب
          </Link>
        </div>
      </main>
    );
  }

  const org = credit?.organizations?.[0];
  const items = orders?.items ?? [];
  const count = {
    open: items.filter((o) => (OPEN as readonly string[]).includes(o.status)).length,
    delivered: items.filter((o) => o.status === "delivered").length,
    cancelled: items.filter((o) => o.status === "cancelled").length,
  };
  const shown = items.filter((o) => (tab === "open" ? (OPEN as readonly string[]).includes(o.status) : o.status === tab));
  const latest = shown[0];
  const initials = user.full_name.trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("");

  const quick = [
    { href: "/account/packs", icon: "bookmark", title: "بسته‌های ذخیره شده", sub: "پک‌های ساخته‌شده در پک‌ساز" },
    { href: "/me/proformas", icon: "receipt_long", title: "پیش‌فاکتورها", sub: "پیش‌فاکتورهای ۷۲ ساعته شما" },
    { href: "/requests", icon: "request_quote", title: "درخواست‌های تأمین", sub: "استعلام و درخواست‌های خرید" },
    { href: "/me/recurring", icon: "sync_saved_locally", title: "خرید دوره‌ای", sub: "تأمین مستمر و تکرار سفارش" },
  ];
  const rows: { href: string; icon: string; title: string; sub: string; accent?: boolean }[] = [
    { href: "/org", icon: "group", title: "میز کار سازمانی", sub: "خرید و درخواست برای سازمان" },
    { href: "/contact", icon: "support_agent", title: "پشتیبانی", sub: "تماس با پشتیبانی شصت‌آنلاین", accent: true },
    { href: "/notifications", icon: "notifications", title: "اعلان‌ها", sub: "پیام‌ها و تغییرات حساب شما" },
    { href: "/60club", icon: "workspace_premium", title: "60Club", sub: "سطح باشگاه و مزایا" },
    { href: "/benefits", icon: "card_giftcard", title: "مزایای کارکنان", sub: "برنامه‌های رفاهی سازمان" },
    ...(user.role === "supplier" ? [{ href: "/supplier", icon: "storefront", title: "پنل تأمین‌کننده", sub: "کالا، قیمت و سفارش‌ها" }] : []),
    ...(user.role === "admin"
      ? [{ href: "/admin", icon: "settings", title: "مدیریت کالا", sub: "پنل مدیریت" }, { href: "/crm", icon: "contact_phone", title: "پیگیری مشتریان", sub: "CRM" }]
      : []),
  ];

  return (
    <main className={cn(stRoot, "min-h-[60vh]")} dir="rtl">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-st-space-lg px-st-margin pt-st-space-md pb-st-space-xl lg:pt-st-space-xl">
        {token && <OrgInvitations token={token} />}

        {/* 1. Profile header */}
        <section className="w-full bg-st-surface-container-lowest rounded-xl p-st-space-lg shadow-sm relative overflow-hidden">
          <div className="flex items-start gap-st-space-md">
            <div className="relative shrink-0">
              <div className="w-16 h-16 rounded-full bg-st-surface-container p-0.5 shadow-sm flex items-center justify-center text-st-title-lg text-st-primary-container">
                {initials}
              </div>
              {org && (
                <span className="absolute bottom-0 left-0 bg-st-secondary text-st-on-secondary rounded-full p-0.5 shadow-sm flex items-center justify-center">
                  <Icon name="verified" className="text-[14px]" />
                </span>
              )}
            </div>
            <div className="flex flex-col min-w-0 flex-1">
              <h1 className="text-st-headline-lg-mobile text-st-primary-container truncate">{user.full_name}</h1>
              <div className="inline-flex items-center gap-1.5 self-start mt-1 px-2.5 py-1 bg-st-surface-container-low rounded-full">
                <span className="w-2 h-2 rounded-full bg-st-secondary" />
                <span className="text-st-label-sm text-st-secondary font-medium">
                  {org ? `${ROLE_FA[org.role] ?? org.role} | ${org.display_name}` : ACCOUNT_ROLE_FA[user.role] ?? user.role}
                </span>
              </div>
              <div className="flex items-center gap-st-space-xs mt-2 text-st-on-surface-variant text-st-body-sm">
                <span className="truncate" dir="ltr">{user.email}</span>
              </div>
            </div>
          </div>
        </section>

        {/* 2. Balances */}
        <section className="w-full">
          <div className="flex items-center justify-between mb-st-space-sm">
            <span className="text-st-title-md text-st-primary-container">دارایی و اعتبارات</span>
            <Link href="/wallet" className="text-st-label-md text-st-secondary hover:underline flex items-center gap-0.5">
              گردش حساب
              <Icon name="arrow_forward" className="text-[16px] -scale-x-100" />
            </Link>
          </div>
          <div className="flex gap-st-space-sm overflow-x-auto pb-2 snap-x [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {welfare?.available && (
              <div className="min-w-[210px] flex-1 bg-st-surface-container-lowest p-st-space-md rounded-xl shadow-sm flex flex-col justify-between shrink-0 snap-start">
                <div className="flex items-center justify-between mb-st-space-sm">
                  <span className="text-st-label-md text-st-on-surface-variant">کیف پول رفاهی</span>
                  <div className="w-8 h-8 rounded-full bg-st-surface-container-low flex items-center justify-center text-st-primary-container">
                    <Icon name="account_balance_wallet" className="text-[18px]" />
                  </div>
                </div>
                <div>
                  <div className="text-st-headline-lg-mobile text-st-primary-container font-bold tracking-tight tabular-nums">{toman(welfare.remaining_minor)}</div>
                  <span className="text-st-label-sm text-st-on-surface-variant mt-1 block">تومان مانده سهم رفاهی</span>
                </div>
              </div>
            )}
            {user.role === "customer" && (
              <Link href="/wallet" className="min-w-[210px] flex-1 bg-st-primary-container text-st-on-primary p-st-space-md rounded-xl shadow-sm flex flex-col justify-between shrink-0 snap-start">
                <div className="flex items-center justify-between mb-st-space-sm">
                  <span className="text-st-label-md text-st-primary-fixed">اعتبار سازمانی</span>
                  <div className="w-8 h-8 rounded-full bg-st-on-primary/10 flex items-center justify-center text-st-secondary-container">
                    <Icon name="domain_verification" className="text-[18px]" />
                  </div>
                </div>
                <div>
                  <div className="text-st-headline-lg-mobile text-st-on-primary font-bold tracking-tight tabular-nums">
                    {credit ? toman(credit.total_available_minor ?? 0) : "…"}
                  </div>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-st-label-sm text-st-primary-fixed-dim">تومان مانده اعتبار</span>
                    {credit && (
                      <span className={cn("text-st-label-sm px-2 py-0.5 rounded-full", credit.allocations.length ? "bg-st-secondary text-st-on-secondary" : "bg-st-on-primary/10 text-st-primary-fixed")}>
                        {credit.allocations.length ? "فعال" : "بدون تخصیص"}
                      </span>
                    )}
                  </div>
                </div>
              </Link>
            )}
            <Link href="/60coin" className="min-w-[210px] flex-1 bg-st-surface-container-lowest p-st-space-md rounded-xl shadow-sm flex flex-col justify-between shrink-0 snap-start">
              <div className="flex items-center justify-between mb-st-space-sm">
                <span className="text-st-label-md text-st-on-surface-variant">۶۰کوین (امتیاز باشگاه)</span>
                <div className="w-8 h-8 rounded-full bg-st-tertiary-fixed flex items-center justify-center text-st-on-tertiary-container">
                  <Icon name="loyalty" className="text-[18px]" />
                </div>
              </div>
              <div>
                <div className="flex items-baseline gap-1">
                  <span className="text-st-headline-lg-mobile text-st-on-tertiary-container font-bold tabular-nums">{loyalty ? loyalty.balance_coins.toLocaleString("fa-IR") : "…"}</span>
                  <span className="text-st-label-sm text-st-on-surface-variant">سکه</span>
                </div>
                <div className="flex items-center justify-between mt-1">
                  <span className="text-st-label-sm text-st-on-surface-variant">{loyalty?.tier?.name_fa ?? "سطح باشگاه"}</span>
                  <span className="text-st-label-sm text-st-on-tertiary-container font-semibold">گردش ›</span>
                </div>
              </div>
            </Link>
          </div>
        </section>

        {/* 3. Orders */}
        <section className="w-full bg-st-surface-container-lowest rounded-xl p-st-space-lg shadow-sm flex flex-col gap-st-space-md">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Icon name="inventory_2" className="text-st-primary-container text-[20px]" />
              <h2 className="text-st-title-md text-st-primary-container">سفارش‌های من</h2>
            </div>
            <Link className="text-st-label-md text-st-secondary hover:underline flex items-center gap-0.5" href="/orders">
              <span>همه سفارش‌ها{orders ? ` (${toPersianNum(orders.total)})` : ""}</span>
              <Icon name="chevron_right" className="text-[16px] -scale-x-100" />
            </Link>
          </div>
          <div className="grid grid-cols-3 gap-2" role="tablist" aria-label="وضعیت سفارش‌ها">
            {([["open", "جاری"], ["delivered", "تحویل شده"], ["cancelled", "لغو شده"]] as const).map(([k, label]) => (
              <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                className={cn("flex flex-col items-center justify-center py-2 px-1 rounded-xl text-center",
                  tab === k ? "bg-st-secondary text-st-on-secondary" : "bg-st-surface-container-low text-st-on-surface-variant")}>
                <span className={cn("text-st-label-md", tab === k && "font-bold")}>{label} ({toPersianNum(count[k])})</span>
                {tab === k && <span className="w-1.5 h-1.5 rounded-full bg-st-on-secondary mt-1" />}
              </button>
            ))}
          </div>
          {orders === null ? (
            <div className="h-24 rounded-xl bg-st-surface-container-low animate-pulse" />
          ) : latest ? (
            <Link href={`/orders/${latest.order_number}`} className="bg-st-surface-container-low rounded-xl p-st-space-md mt-1 flex flex-col gap-2 hover:bg-st-surface-container transition-colors">
              <div className="flex items-center justify-between gap-2">
                <span className="text-st-title-md text-st-primary-container">سفارش شماره {latest.order_number}</span>
                <span className="text-st-label-sm px-2.5 py-0.5 rounded-full bg-st-tertiary-fixed text-st-on-tertiary-container font-semibold shrink-0">
                  {STATUS[latest.status]?.label ?? latest.status}
                </span>
              </div>
              <p className="text-st-body-sm text-st-on-surface-variant">
                {latest.items?.length ? `${toPersianNum(latest.items.length)} قلم • ${latest.items[0].title_fa} • ` : ""}{toman(latest.total_minor)} تومان
              </p>
              {STATUS[latest.status]?.step > 0 && (
                <div className="w-full bg-st-surface-container-highest h-1.5 rounded-full overflow-hidden mt-1">
                  <div className="bg-st-secondary h-full rounded-full" style={{ width: `${(STATUS[latest.status].step / 5) * 100}%` }} />
                </div>
              )}
              <div className="flex items-center gap-1.5 text-st-secondary text-st-label-md mt-1">
                <Icon name="schedule" className="text-[16px]" />
                <span>ثبت: {new Date(latest.placed_at).toLocaleDateString("fa-IR")}</span>
              </div>
            </Link>
          ) : (
            <p className="rounded-xl bg-st-surface-container-low p-st-space-md text-st-body-sm text-st-on-surface-variant">سفارشی در این وضعیت ندارید.</p>
          )}
        </section>

        {/* 4. Quick actions */}
        <section className="w-full">
          <h2 className="text-st-title-md text-st-primary-container mb-st-space-sm">پنل امور خرید و تدارکات</h2>
          <div className="grid grid-cols-2 gap-st-space-sm">
            {quick.map((q) => (
              <Link key={q.href} href={q.href} className="bg-st-surface-container-lowest p-st-space-md rounded-xl shadow-sm flex flex-col justify-between hover:bg-st-surface-container-low transition-colors">
                <div className="flex items-center justify-between mb-st-space-sm">
                  <div className="w-10 h-10 rounded-full bg-st-surface-container-low flex items-center justify-center text-st-primary-container">
                    <Icon name={q.icon} className="text-[20px]" />
                  </div>
                  <Icon name="chevron_right" className="text-st-outline-variant -scale-x-100 text-[18px]" />
                </div>
                <div>
                  <span className="text-st-title-md text-st-primary-container block">{q.title}</span>
                  <span className="text-st-body-sm text-st-on-surface-variant mt-0.5 block">{q.sub}</span>
                </div>
              </Link>
            ))}
          </div>
        </section>

        {/* 5. Settings, support, role panels, logout */}
        <section className="w-full bg-st-surface-container-lowest rounded-xl p-st-space-md shadow-sm flex flex-col">
          {rows.map((r) => (
            <div key={r.href}>
              <Link className="flex items-center justify-between py-3.5 px-st-space-xs hover:bg-st-surface-container-low rounded-lg transition-colors" href={r.href}>
                <div className="flex items-center gap-st-space-sm">
                  <div className={cn("w-9 h-9 rounded-full bg-st-surface-container-low flex items-center justify-center", r.accent ? "text-st-secondary" : "text-st-primary-container")}>
                    <Icon name={r.icon} className="text-[20px]" />
                  </div>
                  <div className="flex flex-col">
                    <span className="text-st-title-md text-st-primary-container">{r.title}</span>
                    <span className={cn("text-st-body-sm", r.accent ? "text-st-secondary" : "text-st-on-surface-variant")}>{r.sub}</span>
                  </div>
                </div>
                <Icon name="chevron_right" className="text-st-on-surface-variant -scale-x-100 text-[20px]" />
              </Link>
              <div className="h-[1px] w-full bg-st-surface-container my-1" />
            </div>
          ))}
          <button type="button" onClick={logout} className="flex items-center justify-between py-3.5 px-st-space-xs hover:bg-st-error-container/20 rounded-lg transition-colors text-right w-full">
            <div className="flex items-center gap-st-space-sm">
              <div className="w-9 h-9 rounded-full bg-st-surface-container-low flex items-center justify-center text-st-error">
                <Icon name="logout" className="text-[20px]" />
              </div>
              <span className="text-st-title-md text-st-error">خروج از حساب کاربری</span>
            </div>
          </button>
        </section>
      </div>
    </main>
  );
}
