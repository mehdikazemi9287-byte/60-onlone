"use client";

// «زیر نظر بگیر»: watch a product at the viewer's OWN level (decided by the server from the account).
// variant "vambi" is the default palette here.
import { useEffect, useRef, useState } from "react";
const Eye = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" />
  </svg>
);
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { priceWatch } from "@/lib/priceWatch";
import { startLogin } from "@/lib/sso";

const STYLES = {
  main: { btn: "border-brand-navy text-brand-navy", link: "text-brand-blue" },
  vambi: { btn: "border-[#1748C9] text-[#1748C9]", link: "text-[#1748C9]" },
} as const;

export function WatchButton({ slug, variant = "vambi", fullWidth = false, className = "" }:
  { slug: string; variant?: keyof typeof STYLES; fullWidth?: boolean; className?: string }) {
  const { token } = useAuth();
  const [watched, setWatched] = useState<string | null>(null); // level label once watched
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const manageRef = useRef<HTMLAnchorElement>(null);
  const focusAfter = useRef(false);
  const st = STYLES[variant];

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    priceWatch.forProduct(token, slug)
      .then((r) => { const w = r.items.find((x) => x.active); if (!cancelled && w) setWatched(w.level_fa); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [token, slug]);

  useEffect(() => {
    if (watched && focusAfter.current) { focusAfter.current = false; manageRef.current?.focus(); }
  }, [watched]);

  const watch = async () => {
    // Logged out: sign in through the 60Online account (lib/sso.ts).
    if (!token) { startLogin(); return; }
    setBusy(true); setError(null);
    try {
      const { watch: w } = await priceWatch.create(token, { slug });
      focusAfter.current = true;
      setWatched(w.level_fa);
    } catch (e) {
      setError(e instanceof ApiError && e.code === "seller_alerts_automatic"
        ? "هشدار فروشنده‌ها خودکار است؛ در پنل فروشنده ببینید."
        : e instanceof ApiError ? e.message : "ثبت ناموفق بود");
    } finally { setBusy(false); }
  };

  const size = fullWidth ? "h-11 w-full justify-center" : "min-h-10";
  return (
    <div className={className}>
      {watched ? (
        <div className={`flex flex-wrap items-center gap-2 ${fullWidth ? "min-h-11" : ""}`}>
          <p role="status" className="inline-flex items-center gap-1 rounded-xl bg-emerald-50 px-3 py-2 text-sm font-bold text-emerald-800">
            <Eye className="h-4 w-4" /> زیر نظر گرفته شد · سطح: {watched}
          </p>
          <a ref={manageRef} href="/alerts" className={`text-sm font-bold underline ${st.link}`}>مدیریت</a>
        </div>
      ) : (
        <button type="button" onClick={watch} disabled={busy}
          className={`inline-flex items-center gap-1 rounded-xl border px-3 text-sm font-bold disabled:opacity-60 ${st.btn} ${size}`}>
          <Eye className="h-4 w-4" /> {busy ? "در حال ثبت…" : "زیر نظر بگیر"}
        </button>
      )}
      {error && <p role="alert" className="mt-1 text-xs text-red-700">{error}</p>}
    </div>
  );
}
