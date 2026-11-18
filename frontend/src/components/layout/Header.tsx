"use client";

// Site header — Google Stitch screens 30 (desktop 1440) and 16 (mobile 390), mega menu from screen 15/22,
// theme pill from screen 33. Layout, spacing, tokens and icons follow the Stitch markup; every value shown
// is real: the user's own name, their active organization (GET /organizations), the live cart count and the
// real taxonomy. Logged-out visitors get a login pill where Stitch shows the user chip, and no org chip.
import Link from "next/link";
import Image from "next/image";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { cn, toPersianNum } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";
import { apiRequest, cart as cartApi } from "@/lib/api";
import { MegaMenu, useTaxonomy } from "./MegaMenu";
import { categorySymbol } from "./categoryIcon";
import { DashThemeToggle, useDashTheme } from "@/components/ui/DashTheme";

const Icon = ({ name, className = "" }: { name: string; className?: string }) => <span aria-hidden className={cn("material-symbols-outlined", className)}>{name}</span>;
export const SITE_W = "mx-auto w-full max-w-[1280px] px-4 md:px-6 xl:px-8";

function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/" aria-label="شصت‌آنلاین، صفحهٔ اول" className="flex shrink-0 select-none items-center gap-st-space-sm">
      <Image src="/brand/60online-mark.png" alt="" width={256} height={241} priority className={cn("brand-mark w-auto shrink-0", compact ? "h-8" : "h-9")} />
      <span className="flex flex-col">
        <span className={cn("font-bold tracking-tight text-st-primary", compact ? "text-st-title-md leading-tight" : "text-st-title-lg")}>شصت‌آنلاین</span>
        <span className="text-st-label-sm font-normal text-st-on-surface-variant">تامین کالای سازمانی و خانگی</span>
      </span>
    </Link>
  );
}

function SearchBox({ id, mobile = false }: { id: string; mobile?: boolean }) {
  return (
    <form action="/search" method="get" role="search" className={cn("relative", mobile ? "w-full" : "max-w-xl flex-1")}>
      <label htmlFor={id} className="sr-only">جستجو</label>
      <div className={cn("flex items-center transition-colors",
        mobile ? "rounded-full bg-st-surface-container-lowest px-4 py-2 shadow-st-card"
          : "h-11 rounded-full border border-st-hairline-border bg-st-surface-container-low px-4 focus-within:border-st-secondary focus-within:bg-st-surface-container-lowest")}>
        <Icon name="search" className={cn("ml-st-space-sm text-st-outline", mobile && "ml-st-space-xs text-[22px]")} />
        <input id={id} type="search" name="q" autoComplete="off"
          placeholder={mobile ? "جستجو در میان کالاها، برندها و غرفه‌ها..." : "جستجوی کالا، برند، غرفه یا دسته‌بندی..."}
          className={cn("w-full border-0 bg-transparent p-0 text-st-on-surface outline-none placeholder:text-st-outline focus:ring-0", mobile ? "pr-1 text-st-body-sm" : "")} />
        <button type="submit" aria-label="جستجو" className={cn("flex items-center justify-center text-st-outline transition-colors hover:text-st-on-surface", mobile ? "p-1" : "mr-st-space-sm")}>
          <Icon name="arrow_back" className={mobile ? "text-[20px]" : ""} />
        </button>
      </div>
    </form>
  );
}

const NAV: [string, string][] = [
  ["پک‌های رفاهی سازمانی", "/packs"],
  ["کالاهای مصرفی و اساسی", "/business/catalog"],
  ["تخفیف‌های ویژه تیراژ", "/requests/new"],
  ["فروش ویژه همکار", "/sell"],
  ["درخواست فاکتور رسمی", "/me/proformas"],
  ["قراردادهای دوره‌ای تامین", "/organization/supply-contracts"],
];

type OrgRow = { id: number; display_name: string; membership?: { status?: string } };

export function Header() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname() ?? "";
  const { user, token, loading } = useAuth();
  const [cartCount, setCartCount] = useState(0);
  const [org, setOrg] = useState<OrgRow | null>(null);
  const [theme, toggleTheme] = useDashTheme();
  const navCategories = (useTaxonomy() ?? []).slice(0, 6).map((n) => ({ slug: n.slug, name: n.name_fa }));
  useEffect(() => {
    if (!token) { setCartCount(0); return; }
    const refresh = () => cartApi.get(token).then((c) => setCartCount(c.item_count)).catch(() => {});
    refresh(); window.addEventListener("60online:cart-changed", refresh);
    return () => window.removeEventListener("60online:cart-changed", refresh);
  }, [token]);
  useEffect(() => {
    if (!token) { setOrg(null); return; }
    let off = false;
    apiRequest<{ items: OrgRow[] }>("/organizations", { token })
      .then((r) => !off && setOrg(r.items.find((o) => !o.membership?.status || o.membership.status === "active") ?? null))
      .catch(() => !off && setOrg(null));
    return () => { off = true; };
  }, [token]);
  useEffect(() => {
    if (!mobileOpen) return;
    const prev = document.body.style.overflow; document.body.style.overflow = "hidden";
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setMobileOpen(false); };
    window.addEventListener("keydown", esc);
    return () => { document.body.style.overflow = prev; window.removeEventListener("keydown", esc); };
  }, [mobileOpen]);
  useEffect(() => setMobileOpen(false), [pathname]);
  const accountHref = loading || !user ? "/login" : "/account";
  const close = () => setMobileOpen(false);
  const active = (href: string) => pathname === href || pathname.startsWith(href + "/");
  const badge = cartCount > 99 ? "۹۹+" : toPersianNum(cartCount);

  return <>
    <header className="sticky top-0 z-50 bg-st-surface-container-lowest shadow-[0_6px_20px_-16px_rgb(17_45_70/0.5)] max-md:bg-st-surface-container-lowest/90 max-md:backdrop-blur-xl max-md:border-b max-md:border-st-hairline-border">
      {/* Desktop (screen 30): white action row + navy navigation strip («ویترین سازمانی گرم») */}
      <div className="hidden md:block">
        <div className={cn(SITE_W, "flex h-16 items-center justify-between gap-6")}>
          <div className="flex flex-1 items-center gap-5">
            <button onClick={() => setMobileOpen(true)} className="flex h-10 w-10 items-center justify-center rounded-xl text-st-on-surface-variant hover:bg-st-surface-container-low lg:hidden" aria-label="باز کردن منوی اصلی" aria-expanded={mobileOpen}><Icon name="menu" /></button>
            <Logo />
            <SearchBox id="site-search" />
          </div>
          <div className="flex items-center gap-2.5">
            {org && <Link href="/organization" className="hidden items-center gap-1.5 rounded-full bg-st-secondary-fixed px-3 py-1.5 text-st-label-lg text-st-on-secondary-fixed transition-colors hover:bg-st-secondary-container xl:flex">
              <Icon name="corporate_fare" className="text-[18px]" /><span className="max-w-[12rem] truncate">{org.display_name}</span></Link>}
            <DashThemeToggle theme={theme} onToggle={toggleTheme} />
            <Link href="/cart" aria-label="سبد خرید" className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-st-surface-container-low transition-colors hover:bg-st-surface-container">
              <Icon name="shopping_bag" className="text-st-primary" />
              {cartCount > 0 && <span className="absolute -right-1.5 -top-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-st-accent px-1 text-st-label-sm font-bold text-white ring-2 ring-st-surface-container-lowest">{badge}</span>}
            </Link>
            <Link href={accountHref} className="flex h-10 items-center gap-2 rounded-full bg-st-navy py-1 pl-1 pr-3.5 text-white transition-colors hover:bg-st-secondary">
              <span className="max-w-[10rem] select-none truncate text-st-label-lg">{user ? user.full_name : "ورود / ثبت‌نام"}</span>
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white/15"><Icon name={user ? "person" : "login"} className="text-[18px] text-white" /></span>
            </Link>
          </div>
        </div>
        <div className="bg-st-navy">
          <nav aria-label="منوی اصلی" className={cn(SITE_W, "flex h-11 items-center justify-start gap-5 text-st-label-lg")}>
            <MegaMenu />
            {NAV.map(([label, href]) => (
              <Link key={href} href={href} aria-current={active(href) ? "page" : undefined}
                className={cn("relative whitespace-nowrap py-3 transition-colors hover:text-white", active(href) ? "font-bold text-white after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:rounded-full after:bg-st-accent" : "text-st-on-navy-muted", href === "/organization/supply-contracts" && "hidden xl:inline")}>{label}</Link>
            ))}
            <Link href="/pack-builder" className="mr-auto hidden items-center gap-1 whitespace-nowrap rounded-full bg-white/10 px-3 py-1 text-st-label-md text-white ring-1 ring-white/15 hover:bg-white/20 lg:flex"><Icon name="package_2" className="text-[16px]" />پک‌ساز</Link>
          </nav>
        </div>
      </div>
      {/* Mobile (screen 16): h-16 bar */}
      <div className="flex h-16 items-center justify-between px-st-gutter md:hidden">
        <Logo compact />
        <div className="flex items-center gap-st-space-xs">
          <DashThemeToggle theme={theme} onToggle={toggleTheme} size="sm" />
          <Link href="/notifications" aria-label="اعلان‌ها" className="flex min-h-[44px] min-w-[44px] items-center justify-center text-st-on-surface-variant transition-colors hover:text-st-primary"><Icon name="notifications" className="text-[22px]" /></Link>
          <button onClick={() => setMobileOpen(true)} aria-label="باز کردن منوی اصلی" aria-expanded={mobileOpen} className="flex min-h-[44px] min-w-[44px] items-center justify-center">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-st-navy text-white"><Icon name={user ? "person" : "menu"} className="text-[18px]" /></span>
          </button>
        </div>
      </div>
    </header>
    {/* Mobile search pill scrolls with the page, as in screen 16. Catalog pages (Stitch 14/27) have their own
        in-page search box, so the shared row is hidden there. */}
    {!/^\/(search|category|cart|checkout|account)(\/|$)/.test(pathname) && <div className="px-st-margin pb-st-space-xs pt-st-space-sm md:hidden"><SearchBox id="site-search-m" mobile /></div>}

    {mobileOpen && <div className="fixed inset-0 z-[80] lg:hidden" role="dialog" aria-modal="true" aria-label="منوی اصلی">
      <button className="absolute inset-0 bg-st-primary/40 backdrop-blur-[2px]" onClick={close} aria-label="بستن منو" />
      <aside className="absolute inset-y-0 right-0 flex w-[min(88vw,360px)] flex-col overflow-y-auto bg-st-surface-container-lowest p-st-space-md shadow-xl">
        <div className="flex items-center justify-between border-b border-st-surface-container pb-st-space-sm">
          <Logo compact />
          <button onClick={close} className="flex h-11 w-11 items-center justify-center rounded-full bg-st-surface-container-low text-st-on-surface" aria-label="بستن منو"><Icon name="close" /></button>
        </div>
        {org && <Link href="/organization" onClick={close} className="mt-st-space-md flex items-center gap-st-space-xs rounded-full bg-st-surface-container-low px-st-space-md py-st-space-xs text-st-label-lg text-st-on-surface"><Icon name="corporate_fare" className="text-[18px] text-st-secondary" />{org.display_name}</Link>}
        <nav className="mt-st-space-md flex flex-col gap-1">
          {([["home", "خانه", "/"], ["grid_view", "همه دسته‌بندی‌ها", "/category"], ...NAV.map(([l, h], i) => [["card_giftcard", "inventory_2", "local_offer", "storefront", "receipt_long", "event_repeat"][i], l, h]),
            ["package_2", "پک‌ساز", "/pack-builder"], ["store", "غرفه‌ها", "/shops"], ["location_on", "شبکهٔ فروشگاه‌ها", "/stores"], ["compare_arrows", "وامبی: مقایسهٔ قیمت", "/vambi"],
            ["auto_awesome", "60AI · دستیار خرید", "/assistant"], ["help", "راهنما و سوالات متداول", "/help/faq"], ["gavel", "قوانین و مقررات", "/terms"], ["privacy_tip", "حریم خصوصی", "/privacy"], ["contact_support", "تماس با ما", "/contact"], [user ? "person" : "login", user ? "حساب کاربری" : "ورود / ثبت‌نام", accountHref]] as string[][]).map(([icon, label, href]) => (
            <Link key={label} href={href} onClick={close} className={cn("flex min-h-11 items-center gap-st-space-sm rounded-xl px-st-space-sm text-st-body-md transition-colors hover:bg-st-surface-container-low", active(href) && href !== "/" ? "font-bold text-st-secondary" : "text-st-on-surface")}>
              <Icon name={icon} className="text-[20px] text-st-on-surface-variant" />{label}</Link>))}
        </nav>
        {navCategories.length > 0 && <>
          <p className="mb-st-space-xs mt-st-space-lg text-st-label-md text-st-outline">دسترسی سریع به دسته‌ها</p>
          <div className="flex flex-col gap-1">{navCategories.map((c) => (
            <Link key={c.slug} href={`/category/${c.slug}`} onClick={close} className="flex min-h-11 items-center gap-st-space-sm rounded-xl px-st-space-sm text-st-body-md text-st-on-surface hover:bg-st-surface-container-low">
              <Icon name={categorySymbol(c.slug, c.name)} className="text-[20px] text-st-on-surface-variant" />{c.name}</Link>))}</div>
        </>}
      </aside>
    </div>}

    {/* Bottom navigation (screen 16) */}
    <nav className="mobile-bottom-nav st-bottom-nav" aria-label="ناوبری اصلی موبایل">
      {([["/", "خانه", "home"], ["/category", "دسته‌بندی", "grid_view"], ["/cart", "سبد خرید", "shopping_bag"], ["/orders", "سفارش‌ها", "inventory_2"], [accountHref, "حساب کاربری", "person"]] as [string, string, string][]).map(([href, label, icon]) => {
        const on = href === "/" ? pathname === "/" : active(href);
        return <Link key={label} href={href} aria-current={on ? "page" : undefined}>
          <span className="relative flex items-center justify-center"><Icon name={icon} className="text-[24px]" />
            {href === "/cart" && cartCount > 0 && <b aria-label={`${toPersianNum(cartCount)} کالا در سبد`}>{badge}</b>}</span>
          <span className="text-st-label-sm">{label}</span></Link>;
      })}
    </nav>
  </>;
}
