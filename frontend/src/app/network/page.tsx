"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import NetworkMap, { type MapBubble, type MapPoint } from "@/components/network/NetworkMap";
import { TruncatedNote } from "@/components/network/BranchList";
import { network, type CoverageResponse, type NetworkBranch, type PublicChain, type Sector } from "@/lib/network";
import { toPersianNum } from "@/lib/utils";

const chip = (on: boolean) =>
  `rounded-full px-3 py-1 text-sm font-bold ${on ? "bg-[#102B7A] text-white" : "bg-white ring-1 ring-neutral-300 text-neutral-700"}`;

export default function NetworkPage() {
  const [sectors, setSectors] = useState<Sector[] | null>(null);
  const [sector, setSector] = useState("");
  const [chain, setChain] = useState("");
  const [coverage, setCoverage] = useState<CoverageResponse | null>(null);
  const [chains, setChains] = useState<PublicChain[] | null>(null);
  const [branches, setBranches] = useState<{ items: NetworkBranch[]; truncated: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    network.sectors().then((r) => setSectors(r.items)).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setCoverage(null); setChains(null); setError(null);
    Promise.all([network.coverage(sector || undefined), network.chains(sector || undefined)])
      .then(([c, ch]) => {
        if (cancelled) return;
        setCoverage(c); setChains(ch.items);
        if (chain && !ch.items.some((x) => x.slug === chain)) setChain("");
      })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sector]);

  useEffect(() => {
    let cancelled = false;
    setBranches(null);
    network.branches({ sector: sector || undefined, chain: chain || undefined, limit: 1000 })
      .then((r) => { if (!cancelled) setBranches(r); })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [sector, chain]);

  // With a chain selected the coverage endpoint (sector-only) does not apply; count that chain's branches per province.
  const provinceRows = useMemo(() => {
    if (!coverage) return null;
    if (!chain) return coverage.provinces.map((p) => ({ ...p, count: p.branches }));
    if (!branches) return null;
    const counts = new Map<string, number>();
    for (const b of branches.items) counts.set(b.province.slug, (counts.get(b.province.slug) ?? 0) + 1);
    return coverage.provinces.map((p) => ({ ...p, count: counts.get(p.slug) ?? 0 }));
  }, [coverage, chain, branches]);

  const bubbles: MapBubble[] = (provinceRows ?? []).map((p) => ({
    lat: p.center[0], lng: p.center[1], count: p.count, href: `/network/${p.slug}`,
    label: `${p.name}: ${p.count ? `${toPersianNum(p.count)} شعبه` : "هنوز شعبه‌ای ثبت نشده"}`,
  }));
  const points: MapPoint[] = (branches?.items ?? []).filter((b) => b.latitude != null && b.longitude != null)
    .map((b) => ({ lat: b.latitude!, lng: b.longitude!, label: `${b.title} — ${b.city ?? b.province.name}` }));
  const total = provinceRows?.reduce((s, p) => s + p.count, 0) ?? 0;
  const covered = provinceRows?.filter((p) => p.count > 0).length ?? 0;

  return (
    <div className="internal-page container-page py-6 md:py-8" dir="rtl">
      <h1 className="mb-2 text-xl md:text-2xl font-black text-neutral-900">شبکهٔ فروشگاه‌های طرف قرارداد</h1>
      <p className="mb-5 max-w-3xl text-sm text-neutral-600">
        این صفحه فقط شعبه‌هایی را نشان می‌دهد که زنجیرهٔ آن‌ها با شصت‌آنلاین قرارداد فعال دارد. زنجیره‌های در حال مذاکره یا بدون قرارداد اینجا نمایش داده نمی‌شوند.
      </p>

      {sectors && sectors.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="حوزه">
          <button type="button" className={chip(!sector)} aria-pressed={!sector} onClick={() => setSector("")}>همهٔ حوزه‌ها</button>
          {sectors.map((s) => (
            <button key={s.slug} type="button" className={chip(sector === s.slug)} aria-pressed={sector === s.slug}
              onClick={() => setSector(s.slug)}>{s.name}</button>
          ))}
        </div>
      )}
      {chains && chains.length > 0 && (
        <label className="mb-5 block max-w-xs text-sm font-bold">زنجیره
          <select className="mt-1 w-full rounded-xl border p-2 font-normal" value={chain} onChange={(e) => setChain(e.target.value)}>
            <option value="">همهٔ زنجیره‌ها</option>
            {chains.map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
          </select>
        </label>
      )}

      {error && <p role="alert" className="mb-4 text-red-600">{error}</p>}

      <section className="mb-8">
        {provinceRows && (
          <p className="mb-2 text-sm text-neutral-700">
            {total > 0
              ? `${toPersianNum(total)} شعبه در ${toPersianNum(covered)} استان از ${toPersianNum(provinceRows.length)} استان`
              : "هنوز هیچ شعبهٔ طرف قراردادی در این فهرست ثبت نشده است."}
          </p>
        )}
        <NetworkMap bubbles={bubbles} points={points} label="نقشهٔ پوشش استان‌ها" />
        {coverage?.center_note && <p className="mt-2 text-xs text-neutral-500">{coverage.center_note}</p>}
        {branches && <TruncatedNote truncated={branches.truncated} />}
      </section>

      <section className="mb-8" aria-labelledby="provinces-h">
        <h2 id="provinces-h" className="mb-3 text-lg font-black">استان‌ها</h2>
        {!provinceRows && !error && <p className="text-neutral-400">در حال بارگذاری…</p>}
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {provinceRows?.map((p) => (
            <li key={p.slug}>
              <Link href={`/network/${p.slug}`}
                className={`flex items-center justify-between rounded-xl border p-3 text-sm ${p.count ? "border-neutral-300 bg-white" : "border-dashed border-neutral-200 text-neutral-500"}`}>
                <span className="font-bold">{p.name}</span>
                <span className="tabular-nums">{p.count ? `${toPersianNum(p.count)} شعبه` : "بدون شعبه"}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="chains-h">
        <h2 id="chains-h" className="mb-3 text-lg font-black">زنجیره‌های طرف قرارداد</h2>
        {chains === null && !error && <p className="text-neutral-400">در حال بارگذاری…</p>}
        {chains?.length === 0 && <p className="text-neutral-500">هنوز زنجیره‌ای با قرارداد فعال {sector ? "در این حوزه " : ""}ثبت نشده است.</p>}
        <ul className="grid gap-3 sm:grid-cols-2">
          {chains?.map((c) => (
            <li key={c.slug} className="rounded-2xl border border-neutral-200 bg-white p-4">
              <Link href={`/network/chain/${encodeURIComponent(c.slug)}`} className="font-bold text-neutral-900 underline-offset-2 hover:underline">{c.name}</Link>
              {c.sectors.length > 0 && <p className="mt-1 text-xs text-neutral-500">{c.sectors.map((s) => s.name).join("، ")}</p>}
              <p className="mt-1 text-sm text-neutral-700">{toPersianNum(c.branches)} شعبه در {toPersianNum(c.provinces)} استان</p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
