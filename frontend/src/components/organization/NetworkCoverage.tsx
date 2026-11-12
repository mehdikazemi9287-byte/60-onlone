"use client";
/**
 * Organization panel: how well the contracted retail network covers the places this organization's orders ship to.
 * Data: GET /organizations/<id>/network-coverage (organization_admin only). Built only from the org's real orders.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { MapPin } from "lucide-react";
import { useOrganization, OrgSelector } from "@/components/organization/Dashboard";
import { apiRequest, ApiError } from "@/lib/api";
import type { OrgCoverage } from "@/lib/network";
import s from "./panel.module.css";

const COVERAGE_FA = { city: "شعبه در همان شهر", province: "شعبه در همان استان", none: "بدون شعبهٔ طرف قرارداد" } as const;
const COVERAGE_CLASS = { city: "text-green-700", province: "text-amber-700", none: "text-neutral-500" } as const;
const fa = (n: number) => n.toLocaleString("fa-IR");

export default function NetworkCoverage() {
  const a = useOrganization();
  const [data, setData] = useState<OrgCoverage | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const isAdmin = a.org?.membership.role === "organization_admin";

  useEffect(() => {
    const c = new AbortController();
    setData(null); setError("");
    if (!a.token || !a.selected || !isAdmin) return;
    setBusy(true);
    apiRequest<OrgCoverage>(`/organizations/${a.selected}/network-coverage`, { token: a.token, signal: c.signal })
      .then((r) => { if (!c.signal.aborted) setData(r); })
      .catch((e) => { if (!c.signal.aborted) setError(e instanceof ApiError && e.status === 403 ? "فقط مدیر سازمان به این گزارش دسترسی دارد." : (e as Error).message); })
      .finally(() => { if (!c.signal.aborted) setBusy(false); });
    return () => c.abort();
  }, [a.token, a.selected, isAdmin, retry]);

  const empty = data && data.places.length === 0 && data.unresolved_places.length === 0;
  return (
    <section className={s.card}>
      <div className={s.sectionHead}>
        <div><h2>پوشش شبکهٔ فروشگاه‌های طرف قرارداد</h2>
          <p>آیا در شهرها و استان‌هایی که سفارش‌های این سازمان به آن‌ها ارسال می‌شود، شعبهٔ طرف قرارداد هست؟</p></div>
        <Link className={s.badge} href="/network">نقشهٔ کامل شبکه ←</Link>
      </div>
      <OrgSelector state={a} />
      {a.org && !isAdmin && <p className={s.notice}>این گزارش فقط برای مدیر سازمان نمایش داده می‌شود.</p>}
      {error && <div role="alert" className={s.error}>{error} <button onClick={() => setRetry((v) => v + 1)}>دریافت دوباره</button></div>}
      {busy && <p role="status">در حال دریافت گزارش پوشش…</p>}
      {data && (
        <>
          <p className={s.muted}>مبنای گزارش: {data.basis}{data.organization_city ? ` · شهر ثبت‌شدهٔ سازمان: ${data.organization_city}` : ""}</p>
          {empty ? (
            <div className={s.empty}><div className={s.iconBox}><MapPin /></div><h3>هنوز سفارشی برای این سازمان ثبت نشده است</h3>
              <p>گزارش پوشش از مقصد سفارش‌های واقعی سازمان ساخته می‌شود؛ پس از ثبت نخستین سفارش اینجا نمایش داده می‌شود.</p></div>
          ) : (
            <>
              <div className={s.kpis}>
                {(["city", "province", "none"] as const).map((k) => (
                  <div className={s.kpi} key={k}><div><strong>{fa(data.summary[k])}</strong><small>مقصد · {COVERAGE_FA[k]}</small></div></div>
                ))}
              </div>
              {data.places.length > 0 && (
                <div className={s.tableWrap}>
                  <table className={s.table}>
                    <thead><tr><th>استان</th><th>شهر</th><th>سفارش</th><th>شعبه در شهر</th><th>شعبه در استان</th><th>پوشش</th></tr></thead>
                    <tbody>
                      {data.places.map((p) => (
                        <tr key={`${p.province.slug}|${p.city}`}>
                          <td><Link href={`/network/${p.province.slug}`}>{p.province.name}</Link></td>
                          <td>{p.city || "—"}</td>
                          <td>{fa(p.orders)}</td>
                          <td>{fa(p.branches_in_city)}</td>
                          <td>{fa(p.branches_in_province)}</td>
                          <td className={COVERAGE_CLASS[p.coverage]}>{COVERAGE_FA[p.coverage]}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {data.unresolved_places.length > 0 && (
                <div className={s.notice}>
                  <div>
                    <strong>مقصدهایی که استان آن‌ها شناخته نشد ({fa(data.unresolved_places.length)})</strong>
                    <ul>{data.unresolved_places.map((u, i) => <li key={i}>{u.province || "—"} / {u.city || "—"} · {fa(u.orders)} سفارش</li>)}</ul>
                    <p>نام استان در نشانی این سفارش‌ها با فهرست ۳۱ استان مطابقت ندارد و در شمارش پوشش نیامده است.</p>
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
