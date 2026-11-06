"use client";

import { useCallback, useEffect, useState } from "react";
import { apiRequest, ApiError } from "@/lib/api";

type Window = {
  delivered_at: string | null; deadline: string | null; open: boolean; working_days: number; notice_fa: string;
  items: { product_id: number; title_fa: string; quantity: number; eligible: boolean; exempt_reason_fa: string | null }[];
};

/** Statutory 7-working-day withdrawal (E-commerce Law art. 37): no reason needed. */
export function OrderWithdrawal({ token, orderNumber, onDone }: { token: string; orderNumber: string; onDone?: () => void }) {
  const [w, setW] = useState<Window | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const load = useCallback(() => apiRequest<Window>(`/me/orders/${encodeURIComponent(orderNumber)}/withdrawal`, { token })
    .then(setW).catch(() => setW(null)), [token, orderNumber]);
  useEffect(() => { void load(); }, [load]);

  if (!w || !w.delivered_at) return null;
  const deadline = w.deadline ? new Date(w.deadline).toLocaleDateString("fa-IR", { dateStyle: "long" }) : "";
  const exempt = w.items.filter((i) => !i.eligible);

  const submit = async () => {
    setBusy(true); setMsg(null);
    try {
      await apiRequest(`/me/orders/${encodeURIComponent(orderNumber)}/withdrawal`, { method: "POST", token, body: "{}" });
      setMsg({ ok: true, text: "انصراف ثبت و پذیرفته شد. کالا را بازگردان؛ مبلغ در مهلت اعلام‌شده برمی‌گردد." });
      onDone?.(); void load();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof ApiError ? e.message : "ثبت انصراف ناموفق بود" });
    } finally { setBusy(false); }
  };

  return (
    <section aria-labelledby="withdrawal-h" className="mt-6 rounded-2xl border border-neutral-200 p-4">
      <h2 id="withdrawal-h" className="font-black text-neutral-900">انصراف از خرید</h2>
      <p className="mt-2 text-sm leading-7 text-neutral-700">{w.notice_fa}</p>
      {w.open ? <p className="mt-1 text-sm text-neutral-600">مهلت تا پایان {deadline}</p>
        : <p className="mt-1 text-sm text-neutral-500">مهلت انصراف تمام شده است. برای کالای معیوب از «مرجوعی» استفاده کن.</p>}
      {exempt.length > 0 && (
        <ul className="mt-2 text-xs text-neutral-500">
          {exempt.map((i) => <li key={i.product_id}>«{i.title_fa}»: {i.exempt_reason_fa}، انصراف ندارد</li>)}
        </ul>
      )}
      {w.open && (
        <button type="button" disabled={busy} onClick={submit}
          className="mt-3 rounded-xl border border-neutral-900 px-4 py-2 text-sm font-bold disabled:opacity-50">
          {busy ? "در حال ثبت…" : "انصراف از این خرید"}
        </button>
      )}
      {msg && <p role="status" className={`mt-2 text-sm ${msg.ok ? "text-emerald-700" : "text-red-600"}`}>{msg.text}</p>}
    </section>
  );
}
