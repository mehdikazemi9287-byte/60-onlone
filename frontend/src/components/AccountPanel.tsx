"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { apiRequest } from "@/lib/api";
import { OrgInvitations } from "@/components/account/OrgInvitations";
type Tier = {
  id: number;
  name_fa: string;
  min_lifetime_coins: number;
  benefit_note_fa?: string | null;
  coins_to_next_tier?: number;
};
type CoinEntry = {
  id: number;
  amount_coins: number;
  entry_type: string;
  created_at: string;
  note?: string;
};
type Loyalty = {
  balance_coins: number;
  tier: Tier | null;
  recent_entries: CoinEntry[];
};
type Credit = {
  total_available: string;
  total_reserved: string;
  currency: string;
  allocations: {
    id: number;
    status: string;
    available?: string;
    available_minor: number;
    expires_at?: string;
    organization_name?: string;
  }[];
};
export default function AccountPanel(props: {section?: string}) {
 const {user}=useAuth();
 return <AccountPanelBody key={user?.id ?? "guest"} {...props}/>;
}
function AccountPanelBody({
  section = "account",
}: {
  section?: string;
}) {
  const { user, token, loading, logout } = useAuth();
  const [credit, setCredit] = useState<Credit | null>(null),
    [loyalty, setLoyalty] = useState<Loyalty | null>(null),
    [tiers, setTiers] = useState<Tier[]>([]);
  const [entries, setEntries] = useState<CoinEntry[]>([]),
    [page, setPage] = useState(1),
    [total, setTotal] = useState(0),
    [error, setError] = useState("");
  useEffect(() => {
    if (!token) return;
    setError("");
    if (section === "wallet" && user?.role === "customer")
      apiRequest<Credit>("/me/credit", { token })
        .then(setCredit)
        .catch((e) => setError(e.message));
    if (section === "60coin" || section === "60club") {
      apiRequest<Loyalty>("/me/loyalty", { token })
        .then(setLoyalty)
        .catch((e) => setError(e.message));
      apiRequest<{ items: Tier[] }>("/loyalty/tiers", { token })
        .then((r) => setTiers(r.items))
        .catch((e) => setError(e.message));
    }
  }, [token, section, user?.role]);
  useEffect(() => {
    if (!token || section !== "60coin") return;
    apiRequest<{ items: CoinEntry[]; total: number }>(
      "/me/loyalty/transactions?page=" + page,
      { token },
    )
      .then((r) => {
        setEntries(r.items);
        setTotal(r.total);
      })
      .catch((e) => setError(e.message));
  }, [token, section, page]);
  const titles: Record<string, string> = {
    account: "حساب من",
    wallet: "اعتبار سازمانی",
    "60coin": "60Coin",
    "60club": "60Club",
  };
  if (loading) return <p className="p-8">در حال بررسی ورود…</p>;
  if (!user)
    return (
      <main className="container-page py-12">
        <h1 className="text-2xl">{titles[section]}</h1>
        <Link className="btn-primary mt-5 inline-block" href={"/login?next="+encodeURIComponent("/"+section)}>
          ورود به حساب
        </Link>
      </main>
    );
  return (
    <main className="container-page max-w-5xl py-8" dir="rtl">
      <h1 className="text-2xl font-bold">{titles[section]}</h1>
      {token && <div className="mt-4"><OrgInvitations token={token} /></div>}
      <nav aria-label="بخش‌های حساب کاربری" className="my-6 flex flex-wrap gap-3 rounded-2xl border border-neutral-200 bg-white p-4">
        {Object.entries(titles).map(([path, title]) => (
          <Link key={path} href={"/" + path} aria-current={path===section?"page":undefined} className={path===section?"rounded-lg bg-brand-navy px-3 py-2 text-sm font-bold text-white":"rounded-lg bg-neutral-50 px-3 py-2 text-sm text-brand-navy"}>
            {title}
          </Link>
        ))}
        <Link href="/requests">درخواست‌ها</Link>
        <Link href="/orders">سفارش‌ها</Link>
        <Link href="/notifications">اعلان‌ها</Link>
        <Link href="/benefits">مزایای کارکنان</Link>
        <Link href="/pack-builder">پک‌ساز</Link>
        <Link href="/org">سازمان</Link>
        {user.role === "supplier" && (
          <Link href="/supplier">پنل تأمین‌کننده</Link>
        )}
        {user.role === "admin" && (
          <>
            <Link href="/admin">مدیریت کالا</Link>
            <Link href="/crm">پیگیری مشتریان</Link>
          </>
        )}
      </nav>
      {error && (
        <p role="alert" className="border rounded-xl p-4">
          {error}
        </p>
      )}
      {section === "account" && <div className="space-y-6">
        <section className="flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-[#edf2eb] p-6"><div><p className="text-xs font-bold text-[#52616a]">حساب کاربری شما</p><h2 className="mt-2 text-xl font-black text-brand-navy">{user.full_name}</h2><p className="mt-2 text-sm text-neutral-600" dir="ltr">{user.email}</p></div><button type="button" className="min-h-11 rounded-xl border border-neutral-300 bg-white px-4 text-sm font-bold" onClick={logout}>خروج از حساب</button></section>
        <section className="rounded-2xl bg-brand-navy p-6 text-white"><p className="text-xs text-white/70">ویژه اعضای سازمان‌ها و شرکت‌ها</p><h2 className="mt-2 text-xl font-black">درخواست خرید برای چند مجموعه و چند شهر</h2><p className="mt-3 text-sm leading-7 text-white/80">از کاتالوگ چند مجموعه انتخاب کنید، مقصدها را مشخص کنید و وضعیت درخواست‌های سازمان خود را پیگیری کنید.</p><div className="mt-5 flex flex-wrap gap-3"><Link href="/business/catalog" className="inline-flex min-h-12 items-center rounded-xl bg-white px-5 text-sm font-bold text-brand-navy">انتخاب کالا و ثبت درخواست</Link><Link href="/org" className="inline-flex min-h-12 items-center rounded-xl border border-white/30 px-5 text-sm font-bold">میز کار سازمانی</Link></div></section>
        <div className="grid gap-4 sm:grid-cols-2">{[{href:"/orders",title:"سفارش‌های شخصی",description:"شماره سفارش، وضعیت پرداخت و پیگیری سفارش‌های مجاز حساب شما."},{href:"/requests",title:"درخواست‌های تأمین",description:"استعلام‌ها و درخواست‌های شخصی ثبت‌شده برای این حساب."},{href:"/wallet",title:"اعتبار سازمانی",description:"اعتبار و تخصیص‌های ثبت‌شده؛ نمایش مانده واقعی پس از دریافت از سرور."},{href:"/notifications",title:"اعلان‌ها",description:"پیام‌ها و تغییرات مربوط به حساب شما."}].map(i=><Link key={i.href} href={i.href} className="rounded-2xl border border-neutral-200 bg-white p-5 hover:border-brand-blue"><h3 className="text-base font-bold text-brand-navy">{i.title}</h3><p className="mt-2 text-sm leading-7 text-neutral-600">{i.description}</p><span className="mt-3 block text-xs font-bold text-brand-blue">مشاهده و پیگیری ←</span></Link>)}</div>
      </div>}
      {section === "wallet" &&
        (user.role !== "customer" ? (
          <p>اعتبار کارکنان برای حساب مشتری قابل مشاهده است.</p>
        ) : credit ? (
          <section className="space-y-5">
            <p>
              اعتبار قابل استفاده ثبت‌شده:{" "}
              <strong>{credit.total_available} ریال</strong>
            </p>
            <p>اعتبار رزروشده: {credit.total_reserved} ریال</p>
            <p>استفاده از اعتبار تابع شرایط تخصیص و تأیید سبد است.</p>
            {!credit.allocations.length && <p>تخصیص اعتباری ثبت نشده است.</p>}
            {credit.allocations.map((a) => (
              <article className="border rounded-xl p-4" key={a.id}>
                <p>
                  تخصیص {a.id} · {a.organization_name}
                </p>
                <p>
                  مانده ثبت‌شده:{" "}
                  {a.available ?? a.available_minor.toLocaleString("fa-IR")}{" "}
                  ریال
                </p>
                <p>وضعیت: {a.status}</p>
                {a.expires_at && (
                  <p>
                    اعتبار تا:{" "}
                    {new Date(a.expires_at).toLocaleDateString("fa-IR")}
                  </p>
                )}
              </article>
            ))}
          </section>
        ) : (
          !error && <p role="status">در حال دریافت اعتبار…</p>
        ))}
      {(section === "60coin" || section === "60club") && loyalty && (
        <section className="space-y-5">
          <p>
            مانده کوین:{" "}
            <strong>{loyalty.balance_coins.toLocaleString("fa-IR")}</strong>
          </p>
          <p>
            سطح ثبت‌شده: {loyalty.tier?.name_fa ?? "سطحی تخصیص داده نشده است"}
          </p>
          {section === "60club" ? (
            <div>
              {tiers.length === 0 ? (
                <p>سطح فعالی تعریف نشده است.</p>
              ) : (
                tiers.map((t) => (
                  <article key={t.id} className="border rounded-xl p-4 my-3">
                    <h2 className="font-bold">{t.name_fa}</h2>
                    <p>
                      حداقل امتیاز کسب‌شده:{" "}
                      {t.min_lifetime_coins.toLocaleString("fa-IR")}
                    </p>
                    {t.benefit_note_fa && <p>{t.benefit_note_fa}</p>}
                  </article>
                ))
              )}
            </div>
          ) : (
            <>
              {!entries.length && <p>گردش کوین ثبت نشده است.</p>}
              <ul>
                {entries.map((e) => (
                  <li key={e.id} className="border-b py-3">
                    {e.amount_coins.toLocaleString("fa-IR")} کوین ·{" "}
                    {new Date(e.created_at).toLocaleDateString("fa-IR")}{" "}
                    {e.note && <p>{e.note}</p>}
                  </li>
                ))}
              </ul>
              <nav className="flex justify-between">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  قبلی
                </button>
                <span>{page}</span>
                <button
                  disabled={page * 25 >= total}
                  onClick={() => setPage((p) => p + 1)}
                >
                  بعدی
                </button>
              </nav>
            </>
          )}
        </section>
      )}
    </main>
  );
}
