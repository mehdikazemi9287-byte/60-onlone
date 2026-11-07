"use client";

import { useCallback, useEffect, useState } from "react";
import { apiRequest, errText } from "@/lib/commerce";
import { Card, btnCls } from "@/components/commerce/ui";
import { faDate } from "@/lib/utils";

type Customers = { items: { user_id: number; full_name: string; linked_at: string; orders: number }[]; open_invites: number };

/** Bring your own customer: a link the seller sends to its offline buyers; their orders from this seller pay 0% commission. */
export function SellerDirect({ token }: { token: string }) {
  const [data, setData] = useState<Customers | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    apiRequest<Customers>("/supplier/direct-customers", { token }).then(setData).catch(() => setData(null));
  }, [token]);
  useEffect(load, [load]);
  const make = async () => {
    setErr(null);
    try {
      const r = await apiRequest<{ path: string }>("/supplier/direct-invites", { token, method: "POST", body: "{}" });
      setLink(`${window.location.origin}${r.path}`); load();
    } catch (e) { setErr(errText(e)); }
  };
  return (
    <Card title="مشتری خودت را بیاور — کارمزد صفر">
      <p className="text-sm leading-7 text-neutral-600">برای مشتری‌هایی که از قبل حضوری از شما می‌خرند لینک دعوت بسازید. وقتی دعوت را بپذیرند، روی خریدشان از شما هیچ کارمزدی کم نمی‌شود. هر لینک یک‌بار مصرف است و ۳۰ روز اعتبار دارد؛ مشتری‌ای که قبلاً از طریق سایت از شما خریده مشمول نمی‌شود.</p>
      <button className={btnCls} onClick={make}>ساخت لینک دعوت</button>
      {link && <p className="break-all rounded-xl bg-neutral-50 p-3 text-sm" dir="ltr">{link}</p>}
      {err && <p role="alert" className="text-sm text-red-700">{err}</p>}
      {data && (
        <p className="text-xs text-neutral-500">{data.items.length} مشتری مستقیم · {data.open_invites} دعوت باز</p>
      )}
      {data && data.items.length > 0 && (
        <ul className="divide-y text-sm">{data.items.map((c) => (
          <li key={c.user_id} className="flex justify-between py-2"><span>{c.full_name}</span><span className="text-neutral-500">{c.orders} سفارش · از {faDate(c.linked_at)}</span></li>
        ))}</ul>
      )}
    </Card>
  );
}
