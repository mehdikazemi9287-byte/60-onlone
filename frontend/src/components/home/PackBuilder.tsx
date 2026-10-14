"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Boxes } from "lucide-react";
import { RequestProductPicker, RequestSelection, PACK_REQUEST_KEY } from "../catalog/RequestProductPicker";
export function PackBuilder() {
  const [items, setItems] = useState<RequestSelection[]>([]);
  const router = useRouter();
  function requestQuote() {
    sessionStorage.setItem(PACK_REQUEST_KEY, JSON.stringify(items));
    router.push("/org");
  }
  return <section id="pack-builder" className="section-shell scroll-mt-28" aria-labelledby="pack-builder-title"><div className="container-page"><div className="rounded-2xl border bg-white p-5 sm:p-8">
    <span className="section-kicker">پک‌ساز 60Online</span><h2 id="pack-builder-title" className="text-2xl font-bold mb-4"><Boxes className="inline ml-2" aria-hidden="true" />انتخاب کالاهای پک برای تأمین</h2>
    <RequestProductPicker value={items} onChange={setItems} />
    <button type="button" className="mt-5 rounded-xl bg-brand-navy text-white p-3" disabled={!items.length || items.some(i => !Number.isInteger(i.quantity) || i.quantity<1 || i.quantity>100000)} onClick={requestQuote}>ادامه برای درخواست قیمت سازمانی</button>
  </div></div></section>;
}
