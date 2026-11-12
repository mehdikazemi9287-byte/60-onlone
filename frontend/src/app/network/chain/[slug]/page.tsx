"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import NetworkMap from "@/components/network/NetworkMap";
import { BranchCard, TruncatedNote } from "@/components/network/BranchList";
import { ApiError } from "@/lib/api";
import { groupBy, network, type ChainDetail } from "@/lib/network";
import { toPersianNum } from "@/lib/utils";

export default function ChainPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const [data, setData] = useState<ChainDetail | null>(null);
  const [error, setError] = useState<{ notFound: boolean; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null); setError(null);
    network.chain(slug)
      .then((r) => { if (!cancelled) setData(r); })
      .catch((e) => { if (!cancelled) setError({ notFound: e instanceof ApiError && e.status === 404, text: e.message }); });
    return () => { cancelled = true; };
  }, [slug]);

  useEffect(() => { if (data) document.title = `${data.name} — شبکهٔ فروشگاه‌ها | شصت‌آنلاین`; }, [data]);

  const points = (data?.branches ?? []).filter((b) => b.latitude != null && b.longitude != null)
    .map((b) => ({ lat: b.latitude!, lng: b.longitude!, label: `${b.title} — ${b.city ?? b.province.name}` }));
  const groups = data ? groupBy(data.branches, (b) => b.province.slug) : [];

  return (
    <div className="internal-page container-page py-6 md:py-8" dir="rtl">
      <Link href="/network" className="text-sm underline">بازگشت به شبکهٔ فروشگاه‌ها</Link>
      {error && (
        <p role="alert" className="mt-4 text-red-600">
          {error.notFound ? "این زنجیره در فهرست طرف‌های قرارداد فعال نیست." : error.text}
        </p>
      )}
      {!data && !error && <p className="mt-4 text-neutral-400">در حال بارگذاری…</p>}
      {data && (
        <>
          <h1 className="mb-1 mt-3 text-xl md:text-2xl font-black text-neutral-900">{data.name}</h1>
          {data.brand_name && data.brand_name !== data.name && <p className="text-sm text-neutral-600">{data.brand_name}</p>}
          {data.sectors.length > 0 && (
            <p className="mt-2 flex flex-wrap gap-2 text-xs">
              {data.sectors.map((s) => <span key={s.slug} className="rounded-full bg-neutral-100 px-2 py-0.5">{s.name}</span>)}
            </p>
          )}
          {data.website && (
            <p className="mt-2 text-sm"><a href={data.website} target="_blank" rel="noopener noreferrer nofollow" className="underline" dir="ltr">{data.website}</a></p>
          )}
          <p className="mb-5 mt-3 text-sm text-neutral-600">
            {data.branches.length
              ? `${toPersianNum(data.branches.length)} شعبهٔ طرف قرارداد در ${toPersianNum(groups.length)} استان`
              : "هنوز شعبه‌ای از این زنجیره در فهرست ثبت نشده است."}
          </p>
          {points.length > 0
            ? <NetworkMap points={points} label={`نقشهٔ شعبه‌های ${data.name}`} />
            : data.branches.length > 0 && <p className="text-xs text-neutral-500">برای شعبه‌های این زنجیره هنوز مختصات ثبت نشده است.</p>}
          <TruncatedNote truncated={data.truncated} />
          <div className="mt-6 space-y-6">
            {groups.map(([pslug, items]) => (
              <section key={pslug}>
                <h2 className="mb-2 text-lg font-black">
                  <Link href={`/network/${pslug}`} className="hover:underline">{items[0].province.name}</Link>{" "}
                  <span className="text-sm font-normal text-neutral-500">({toPersianNum(items.length)})</span>
                </h2>
                <ul className="grid gap-3 sm:grid-cols-2">{items.map((b) => <BranchCard key={b.id} b={b} showChain={false} />)}</ul>
              </section>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
