"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import NetworkMap from "@/components/network/NetworkMap";
import { BranchCard, TruncatedNote } from "@/components/network/BranchList";
import { ApiError } from "@/lib/api";
import { groupBy, network, type ProvinceDetail } from "@/lib/network";
import { toPersianNum } from "@/lib/utils";

export default function ProvincePage({ params }: { params: Promise<{ province: string }> }) {
  const { province } = use(params);
  const [data, setData] = useState<ProvinceDetail | null>(null);
  const [error, setError] = useState<{ notFound: boolean; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null); setError(null);
    network.province(province)
      .then((r) => { if (!cancelled) setData(r); })
      .catch((e) => { if (!cancelled) setError({ notFound: e instanceof ApiError && e.status === 404, text: e.message }); });
    return () => { cancelled = true; };
  }, [province]);

  useEffect(() => { if (data) document.title = `شبکهٔ فروشگاه‌ها در استان ${data.name} | شصت‌آنلاین`; }, [data]);

  const points = (data?.branches ?? []).filter((b) => b.latitude != null && b.longitude != null)
    .map((b) => ({ lat: b.latitude!, lng: b.longitude!, label: `${b.title} — ${b.city ?? ""}` }));

  return (
    <div className="internal-page container-page py-6 md:py-8" dir="rtl">
      <Link href="/network" className="text-sm underline">بازگشت به شبکهٔ فروشگاه‌ها</Link>
      {error && <p role="alert" className="mt-4 text-red-600">{error.notFound ? "این استان پیدا نشد." : error.text}</p>}
      {!data && !error && <p className="mt-4 text-neutral-400">در حال بارگذاری…</p>}
      {data && (
        <>
          <h1 className="mb-1 mt-3 text-xl md:text-2xl font-black text-neutral-900">استان {data.name}</h1>
          <p className="mb-5 text-sm text-neutral-600">
            مرکز استان: {data.capital} · {data.branches.length ? `${toPersianNum(data.branches.length)} شعبهٔ طرف قرارداد در ${toPersianNum(data.cities.length)} شهر` : "هنوز شعبهٔ طرف قراردادی در این استان ثبت نشده است."}
          </p>
          <NetworkMap center={data.center} zoom={points.length ? 8 : 7} points={points} label={`نقشهٔ استان ${data.name}`} />
          {points.length === 0 && data.branches.length > 0 && (
            <p className="mt-2 text-xs text-neutral-500">برای شعبه‌های این استان هنوز مختصات ثبت نشده است.</p>
          )}
          <TruncatedNote truncated={data.truncated} />
          <div className="mt-6 space-y-6">
            {groupBy(data.branches, (b) => b.city ?? "—").map(([city, items]) => (
              <section key={city}>
                <h2 className="mb-2 text-lg font-black">{city} <span className="text-sm font-normal text-neutral-500">({toPersianNum(items.length)})</span></h2>
                <ul className="grid gap-3 sm:grid-cols-2">{items.map((b) => <BranchCard key={b.id} b={b} />)}</ul>
              </section>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
