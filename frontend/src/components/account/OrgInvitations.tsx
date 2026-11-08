"use client";

import { useCallback, useEffect, useState } from "react";
import { apiRequest, ApiError } from "@/lib/api";

type Invite = { membership_id: number; role: string; organization_id: number; organization: string; buyer_kind: string; invited_by: string | null };

const ROLE_FA: Record<string, string> = { organization_admin: "مدیر حساب", organization_finance: "مالی", procurement_agent: "کارپرداز", employee: "کارمند" };

/** An org invite claimed by phone waits here for an explicit yes — a recycled number must not land someone in a stranger's account. */
export function OrgInvitations({ token }: { token: string }) {
  const [items, setItems] = useState<Invite[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    apiRequest<{ items: Invite[] }>("/me/org-invitations", { token }).then((r) => setItems(r.items)).catch(() => setItems([]));
  }, [token]);
  useEffect(load, [load]);
  if (!items.length) return null;
  const answer = async (id: number, a: "accept" | "decline") => {
    setErr(null);
    try { await apiRequest(`/me/org-invitations/${id}/${a}`, { token, method: "POST", body: "{}" }); load(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "ناموفق بود"); }
  };
  return (
    <section className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 p-4" aria-label="دعوت‌های سازمانی">
      <h2 className="font-bold text-amber-900">دعوت به حساب سازمانی</h2>
      {err && <p role="alert" className="mt-2 text-sm text-red-700">{err}</p>}
      <ul className="mt-2 space-y-2">
        {items.map((i) => (
          <li key={i.membership_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-white p-3 text-sm">
            <span><b>{i.organization}</b> شما را با نقش «{ROLE_FA[i.role] ?? i.role}» دعوت کرده{i.invited_by ? ` (${i.invited_by})` : ""}. اگر این سازمان را نمی‌شناسید، رد کنید.</span>
            <span className="flex gap-2">
              <button className="rounded-lg bg-primary-600 px-3 py-1.5 font-bold text-white" onClick={() => answer(i.membership_id, "accept")}>می‌پذیرم</button>
              <button className="rounded-lg bg-neutral-100 px-3 py-1.5" onClick={() => answer(i.membership_id, "decline")}>رد</button>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
