"use client";

// «زیر نظر بگیر»: watch a product at the viewer's OWN level (decided by the server from the account).
import { useState } from "react";
import { Eye } from "lucide-react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { priceWatch } from "@/lib/priceWatch";

export function WatchButton({ slug, loginBase = "", className = "" }: { slug: string; loginBase?: string; className?: string }) {
  const { token } = useAuth();
  const [state, setState] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const watch = async () => {
    if (!token) { window.location.href = `${loginBase}/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`; return; }
    setBusy(true); setState(null);
    try {
      const { watch: w } = await priceWatch.create(token, { slug });
      setState({ ok: true, text: `زیر نظر است · سطح ${w.level_fa}` });
    } catch (e) {
      setState({ ok: false, text: e instanceof ApiError && e.code === "seller_alerts_automatic"
        ? "هشدار فروشنده‌ها خودکار است؛ در پنل فروشنده ببینید."
        : e instanceof ApiError ? e.message : "ثبت ناموفق بود" });
    } finally { setBusy(false); }
  };

  return (
    <div className={className}>
      {state?.ok ? (
        <a href={`${loginBase}/me/price-alerts`} className="inline-flex min-h-10 items-center gap-1 rounded-xl bg-emerald-50 px-3 text-sm font-bold text-emerald-800">
          <Eye className="h-4 w-4" aria-hidden /> {state.text} · مدیریت هشدارها
        </a>
      ) : (
        <button type="button" onClick={watch} disabled={busy}
          className="inline-flex min-h-10 items-center gap-1 rounded-xl border border-[#1748C9] px-3 text-sm font-bold text-[#1748C9] disabled:opacity-60">
          <Eye className="h-4 w-4" aria-hidden /> {busy ? "در حال ثبت…" : "زیر نظر بگیر"}
        </button>
      )}
      {state && !state.ok && <p role="alert" className="mt-1 text-xs text-red-700">{state.text}</p>}
    </div>
  );
}
