"use client";
// Organization panel shell — faithful to Stitch screen 26 (light) / 21 (dark): white right sidebar (w-64) with brand
// block, icon nav with a navy active pill, account status + user card at the bottom; white top bar with breadcrumb,
// notifications and the primary «ثبت سفارش سازمانی جدید» action.
// Real data only: organization name/role come from GET /organizations (active memberships); the user from auth.
// /operations keeps the older PanelShell (another group's route).
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";
import { useOrganization } from "./Dashboard";
import st from "./stitch.module.css";

export const ROLE_FA: Record<string, string> = {
  organization_admin: "مدیر سازمان", organization_finance: "مالی سازمان", employee: "کارمند",
};

type Item = { href: string; title: string; icon: string };
/** The five Stitch sidebar entries, mapped to the real routes. */
const PRIMARY: Item[] = [
  { href: "/org", title: "میز کار سازمانی", icon: "dashboard" },
  { href: "/organization/b2b-orders", title: "سفارش‌ها و پیش‌فاکتورها", icon: "receipt_long" },
  { href: "/organization/supply-contracts", title: "قراردادهای تامین دوره‌ای", icon: "history_edu" },
  { href: "/organization/credit", title: "اعتبار و اسناد مالیاتی", icon: "account_balance_wallet" },
  { href: "/organization/members", title: "تنظیمات و دسترسی‌ها", icon: "tune" },
];
/** Every other existing organization route stays reachable (no route removed). */
const MORE: Item[] = [
  { href: "/organization/compose", title: "سفارش سازمانی هوشمند", icon: "add_circle" },
  { href: "/organization/requests", title: "درخواست‌های خرید", icon: "request_quote" },
  { href: "/organization/workflow", title: "گردش سفارش", icon: "sync" },
  { href: "/organization/cases", title: "پرونده‌های خرید", icon: "inventory_2" },
  { href: "/organization/orders", title: "سفارش خرید از تأمین‌کننده", icon: "local_mall" },
  { href: "/organization/review", title: "بررسی و تأیید درخواست", icon: "fact_check" },
  { href: "/organization/finance", title: "مالی و تعهدات", icon: "payments" },
  { href: "/organization/statement", title: "صورت‌حساب ماهانه", icon: "description" },
  { href: "/organization/welfare", title: "طرح‌های رفاهی", icon: "volunteer_activism" },
  { href: "/organization/benefits", title: "مزایای کارکنان", icon: "groups" },
  { href: "/organization/payment-policy", title: "سیاست پرداخت", icon: "policy" },
  { href: "/organization/policy", title: "سیاست خرید و تأیید", icon: "rule" },
  { href: "/organization/buying-rules", title: "فروشندگان ترجیحی و قواعد تأیید", icon: "storefront" },
  { href: "/organization/delivery", title: "تحویل و مرجوعی", icon: "local_shipping" },
  { href: "/me/proformas", title: "پیش‌فاکتورهای من", icon: "picture_as_pdf" },
  { href: "/operations", title: "میز کار عملیات", icon: "apartment" },
];
const ALL = [...PRIMARY, ...MORE];

const loginHref = (path: string) => "/login?next=" + encodeURIComponent(path);
const hardLogin = (e: React.MouseEvent) => {
  e.preventDefault();
  window.location.href = loginHref(window.location.pathname + window.location.search);
};

function NavLink({ item, active, small }: { item: Item; active: boolean; small?: boolean }) {
  return (
    <Link href={item.href} aria-current={active ? "page" : undefined}
      className={cn("flex items-center gap-st-space-sm rounded-xl px-st-space-md transition-colors",
        small ? "py-1.5 text-[14px]" : "whitespace-nowrap py-st-space-sm text-[15px]",
        active ? "bg-white font-bold text-[#112D46] shadow-st-card"
          : "text-st-on-navy-muted hover:bg-white/10 hover:text-white")}>
      <span aria-hidden className={cn("material-symbols-outlined", small ? "text-[18px]" : "text-[20px]")}>{item.icon}</span>
      <span>{item.title}</span>
    </Link>
  );
}

export default function OrgShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { user, loading, logout } = useAuth();
  const org = useOrganization(!!user);
  const current = ALL.find((n) => n.href === path) ?? ALL.find((n) => n.href !== "/org" && path.startsWith(n.href));
  const title = current?.title ?? "پنل سازمانی";
  const inMore = MORE.some((m) => m === current);
  const [more, setMore] = useState(inMore);
  const guest = !loading && !user && path !== "/org";
  const role = org.org ? ROLE_FA[org.org.membership.role] ?? org.org.membership.role : null;

  return (
    <div dir="rtl" className={cn(st.shell, "mx-auto flex min-h-[calc(100vh-4rem)] max-w-[1280px] bg-st-background text-st-on-surface")}>
      {/* Sidebar (right, RTL) */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col justify-between overflow-y-auto bg-st-navy px-3 py-5 text-white lg:flex">
        <div className="flex flex-col gap-st-space-lg">
          <div className="flex items-center gap-st-space-sm px-st-space-xs">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-st-accent"><span className="font-bold leading-none text-white">۶۰</span></div>
            <div className="flex flex-col leading-tight"><span className="font-bold text-white">پرتال سازمانی ۶۰</span>
              <span className="text-[13px] text-st-on-navy-muted">سامانه مدیریت تدارکات B2B</span></div>
          </div>
          <nav aria-label="ناوبری پنل سازمانی" className="flex flex-col gap-st-space-xs">
            {PRIMARY.map((n) => <NavLink key={n.href} item={n} active={current === n} />)}
            <button type="button" onClick={() => setMore((v) => !v)} aria-expanded={more}
              className="mt-st-space-xs flex items-center justify-between rounded-xl px-st-space-md py-st-space-xs text-[13px] text-st-on-navy-muted hover:text-white">
              <span>بخش‌های بیشتر</span>
              <span aria-hidden className="material-symbols-outlined text-[18px]">{more ? "expand_less" : "expand_more"}</span>
            </button>
            {more && MORE.map((n) => <NavLink key={n.href} item={n} active={current === n} small />)}
          </nav>
        </div>
        <div className="mt-st-space-lg flex flex-col gap-st-space-md border-t border-white/10 pt-st-space-md text-[14px]">
          {org.org && (
            <div className="flex flex-col gap-st-space-xs rounded-xl bg-white/[0.06] p-st-space-sm ring-1 ring-white/10">
              <div className="flex items-center justify-between"><span className="text-st-on-navy-muted">نقش شما در سازمان</span>
                <span className="font-bold text-st-accent">{role}</span></div>
              <span className="truncate font-bold text-white">{org.org.display_name}</span>
            </div>)}
          {user && (
            <div className="flex items-center justify-between px-st-space-xs">
              <div className="flex min-w-0 items-center gap-st-space-sm">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/15"><span aria-hidden className="material-symbols-outlined text-[18px] text-white">person</span></div>
                <div className="flex min-w-0 flex-col"><span className="truncate font-semibold text-white">{user.full_name || user.email}</span>
                  <span className="text-st-on-navy-muted">{role ?? "حساب کاربری"}</span></div>
              </div>
              <button type="button" onClick={logout} title="خروج" aria-label="خروج از حساب" className="flex items-center justify-center text-st-on-navy-muted transition-colors hover:text-st-accent">
                <span aria-hidden className="material-symbols-outlined text-[20px]">logout</span></button>
            </div>)}
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        {/* Top bar */}
        <header className="flex h-14 items-center justify-between gap-st-space-md border-b border-st-hairline-border bg-st-surface-container-lowest px-st-space-md lg:px-6">
          <nav aria-label="مسیر" className="flex min-w-0 items-center gap-st-space-sm text-st-on-surface-variant">
            <Link href="/org" className="hidden text-st-outline sm:inline">سامانه سازمانی</Link>
            <span aria-hidden className="material-symbols-outlined hidden text-[16px] text-st-outline sm:inline">chevron_left</span>
            <span className="truncate font-bold text-st-primary">{title}</span>
          </nav>
          <div className="flex shrink-0 items-center gap-st-space-sm lg:gap-st-space-lg">
            {user && <Link href="/notifications" aria-label="اعلان‌ها" className="flex h-10 w-10 items-center justify-center rounded-xl bg-st-surface text-st-on-surface-variant transition-colors hover:bg-st-surface-container">
              <span aria-hidden className="material-symbols-outlined text-[20px]">notifications</span></Link>}
            {user ? <Link href="/organization/compose" className="flex h-10 items-center gap-st-space-xs rounded-full bg-st-secondary px-st-space-md text-[14px] font-bold text-white transition-colors hover:bg-st-navy">
              <span aria-hidden className="material-symbols-outlined text-[18px]">add</span><span className="hidden sm:inline">ثبت سفارش سازمانی جدید</span></Link>
              : <Link href={loginHref(path)} onClick={hardLogin} className="flex h-10 items-center gap-st-space-xs rounded-xl bg-st-primary-container px-st-space-md text-st-on-primary">
                <span aria-hidden className="material-symbols-outlined text-[18px]">person</span>ورود به حساب سازمانی</Link>}
          </div>
        </header>
        {/* Mobile nav (sidebar is lg+) */}
        <nav aria-label="بخش‌های پنل" className="flex gap-st-space-xs overflow-x-auto border-b border-st-surface-container bg-st-surface-container-lowest px-st-space-md py-st-space-xs lg:hidden">
          {ALL.map((n) => <Link key={n.href} href={n.href} aria-current={current === n ? "page" : undefined}
            className={cn("shrink-0 rounded-full px-st-space-md py-1.5 text-[13px]", current === n ? "bg-st-navy font-bold text-white" : "bg-st-surface-container-low text-st-on-surface-variant")}>{n.title}</Link>)}
        </nav>

        <main className="px-st-space-md py-4 lg:p-6">
          {loading ? <div role="status" className="rounded-xl bg-st-surface-container-lowest p-st-space-lg shadow-sm">در حال بررسی حساب و دسترسی‌ها…</div>
            : guest ? <GuestGate title={title} path={path} />
            : <div key={user?.id ?? "guest"}>{children}</div>}
        </main>
      </div>
    </div>
  );
}

function GuestGate({ title, path }: { title: string; path: string }) {
  return (
    <div className="flex flex-col gap-st-space-xl">
      <section className="rounded-xl bg-st-surface-container-lowest p-st-space-lg shadow-sm">
        <div className="flex items-center gap-st-space-xs"><span className="h-2 w-2 rounded-full bg-st-secondary" /><span className="font-bold text-st-secondary">فضای اختصاصی اعضای مجاز سازمان</span></div>
        <h1 className="mt-st-space-xs text-[24px] font-bold text-st-primary">{title}</h1>
        <p className="mt-st-space-xs max-w-2xl text-st-on-surface-variant">درخواست‌ها، سفارش‌ها و اسناد سازمان فقط پس از ورود با حساب دارای عضویت فعال نمایش داده می‌شوند.</p>
        <div className="mt-st-space-md flex flex-wrap gap-st-space-sm">
          <Link href={loginHref(path)} onClick={hardLogin} className="inline-flex items-center gap-st-space-xs rounded-full bg-st-primary-container px-st-space-lg py-st-space-sm text-st-on-primary">
            <span aria-hidden className="material-symbols-outlined text-[20px]">login</span>ورود و ادامه</Link>
          <Link href="/org" className="inline-flex items-center gap-st-space-xs rounded-full bg-st-surface-container-low px-st-space-md py-st-space-sm text-st-primary">نمای کلی پنل</Link>
        </div>
      </section>
    </div>
  );
}
