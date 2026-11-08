"use client";

// Shipment tracking timeline for a customer's own order (GET /me/orders/:id/tracking).
import { useEffect, useState } from "react";
import { Truck } from "lucide-react";
import { apiRequest, SHIP_STATUS_FA } from "@/lib/commerce";
import { ApiError } from "@/lib/api";

type Tracking = { order_number: string; shipments: { tracking_number: string; direction: "forward" | "return"; status: string;
  deliver_by_at: string | null; delivered_at: string | null; events: { status: string; occurred_at: string; location: string | null }[] }[] };

const dt = (v: string | null) => {
  if (!v) return "";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("fa-IR-u-ca-persian", { dateStyle: "medium", timeStyle: "short" });
};

export function OrderTracking({ token, orderId }: { token: string; orderId: number }) {
  const [data, setData] = useState<Tracking | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null); setError(null);
    apiRequest<Tracking>(`/me/orders/${orderId}/tracking`, { token })
      .then((r) => { if (!cancelled) setData(r); })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError && e.status === 404 ? null : "پیگیری مرسوله در دسترس نیست."); });
    return () => { cancelled = true; };
  }, [token, orderId]);

  if (error) return <p role="alert" className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>;
  if (!data || !data.shipments.length) return null;

  return (
    <section aria-label="پیگیری مرسوله" className="mt-4 rounded-2xl border border-neutral-200 bg-white p-4">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-black text-neutral-900"><Truck className="h-4 w-4" aria-hidden="true" />پیگیری مرسوله</h2>
      <div className="space-y-4">
        {data.shipments.map((s) => (
          <div key={s.tracking_number}>
            <p className="mb-2 flex flex-wrap justify-between gap-2 text-xs text-neutral-600">
              <span>{s.direction === "return" ? "مرسولهٔ مرجوعی" : "کد رهگیری"}: <span dir="ltr" className="font-bold text-neutral-900">{s.tracking_number}</span></span>
              <span>{s.delivered_at ? `تحویل: ${dt(s.delivered_at)}` : s.deliver_by_at ? `تحویل تا ${dt(s.deliver_by_at)}` : ""}</span>
            </p>
            <ol className="relative space-y-3 border-r-2 border-neutral-200 pr-4">
              {(s.events.length ? s.events : [{ status: s.status, occurred_at: "", location: null }]).map((e, i, all) => (
                <li key={`${e.status}-${i}`} className="relative">
                  <span aria-hidden="true" className={`absolute -right-[23px] top-1 h-3 w-3 rounded-full ${i === all.length - 1 ? "bg-emerald-500" : "bg-neutral-300"}`} />
                  <p className="text-sm font-bold text-neutral-900">{SHIP_STATUS_FA[e.status] ?? e.status}</p>
                  <p className="text-xs text-neutral-500">{[dt(e.occurred_at), e.location].filter(Boolean).join(" · ")}</p>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
    </section>
  );
}
