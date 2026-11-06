"use client";

import { useState } from "react";
import { apiRequest, ApiError } from "@/lib/api";
import { latinDigits } from "@/lib/shops";

/** Seller's optional extra referral commission (paid from the seller's share, after Basalam). */
export function SellerAffiliateBonus({ token }: { token: string }) {
  const [pct, setPct] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const save = async (e: React.FormEvent) => {
    e.preventDefault(); setMsg(null);
    const v = Number(pct);
    try {
      await apiRequest("/supplier/affiliate-bonus", { method: "PUT", token, body: JSON.stringify({ bonus_bps: Math.round(v * 100) }) });
      setMsg({ ok: true, text: "ذخیره شد." });
    } catch (x) { setMsg({ ok: false, text: x instanceof ApiError ? x.message : "ذخیره ناموفق بود" }); }
  };
  return (
    <section id="affiliate" aria-labelledby="aff-h" className="rounded-2xl border border-neutral-200 p-4">
      <h2 id="aff-h" className="font-black text-neutral-900">کمیسیون اضافه برای معرف‌ها</h2>
      <p className="mt-1 text-sm text-neutral-600">با کمیسیون اضافه، معرف‌ها بیشتر کالاهای تو را معرفی می‌کنند. فقط وقتی پرداخت می‌شود که فروش انجام و نهایی شود.</p>
      <form onSubmit={save} className="mt-3 flex flex-wrap items-end gap-2 text-sm">
        <label>درصد (۰ تا ۲۰)
          <input inputMode="decimal" dir="ltr" className="mt-1 block w-24 rounded-xl border p-2" value={pct}
            onChange={(e) => setPct(latinDigits(e.target.value).replace(/[^\d.]/g, ""))} />
        </label>
        <button type="submit" disabled={pct === "" || Number(pct) > 20} className="rounded-xl bg-neutral-900 px-4 py-2 font-bold text-white disabled:opacity-50">ذخیره</button>
        {msg && <span role="status" className={msg.ok ? "text-emerald-700" : "text-red-600"}>{msg.text}</span>}
      </form>
    </section>
  );
}
