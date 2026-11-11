"use client";

// 60online.ir side of the shared login: a signed-in user confirms with a click, then gets a one-time code for the
// sister site and is sent back there. Nothing is issued without that click, so a link from elsewhere cannot mint a
// code silently. Only the URL the server returns is followed (the server checks `target` against its allow-list).
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, type AuthUser } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { sso } from "@/lib/sso";

export default function SsoVambiPage() {
  return (
    <Suspense fallback={null}>
      <SsoVambi />
    </Suspense>
  );
}

/** Name if we have one; otherwise the phone with its middle hidden (0912•••4567). */
function who(user: AuthUser): string {
  if (user.full_name?.trim()) return user.full_name.trim();
  const p = user.phone ?? "";
  return p.length >= 8 ? `${p.slice(0, 4)}•••${p.slice(-4)}` : "شصت آنلاین";
}

function SsoVambi() {
  const router = useRouter();
  const params = useSearchParams();
  const { token, user, loading } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const target = params.get("target") ?? "";
  const state = params.get("state") ?? "";
  const self = `/sso/vambi?${new URLSearchParams({ target, state })}`;
  const incomplete = !target || !state;

  useEffect(() => {
    if (!loading && !token && !incomplete) router.replace(`/login?next=${encodeURIComponent(self)}`);
  }, [loading, token, incomplete, self, router]);

  const go = async () => {
    if (!token) return;
    setBusy(true); setError(null);
    try {
      const { redirect_url } = await sso.issue(token, target, state);
      // Follow only a URL on the requested origin's callback path, exactly as the server built it.
      if (!redirect_url.startsWith(`${target}/sso/callback?`)) throw new Error("bad redirect");
      window.location.assign(redirect_url);
    } catch (e) {
      setBusy(false);
      if (e instanceof ApiError && e.status === 401) { router.replace(`/login?next=${encodeURIComponent(self)}`); return; }
      setError(e instanceof ApiError && e.code === "sso_origin_not_allowed"
        ? "این سایت اجازهٔ ورود با حساب شصت آنلاین رو نداره."
        : e instanceof ApiError ? e.message : "ورود انجام نشد. یه بار دیگه امتحان کن.");
    }
  };

  let host = "";
  try { host = target ? new URL(target).host : ""; } catch { /* shown as incomplete below */ }

  return (
    <div className="flex min-h-[calc(100vh-160px)] items-center justify-center px-4 py-12">
      <div className="card w-full max-w-md p-7 text-center md:p-8">
        <h1 className="text-lg font-bold text-neutral-900">ورود با حساب شصت آنلاین</h1>
        {incomplete || !host ? (
          <p role="alert" className="mt-3 text-sm text-red-700">لینک ورود ناقصه. از وامبی دوباره روی «ورود» بزن.</p>
        ) : loading || !user ? (
          <p role="status" className="mt-3 text-sm text-neutral-700">یه لحظه صبر کن…</p>
        ) : (
          <>
            <p className="mt-3 text-sm text-neutral-700">
              می‌خوای با همین حساب وارد وامبی (<span dir="ltr">{host}</span>) بشی؟
            </p>
            <button type="button" onClick={go} disabled={busy}
              className="mt-5 w-full rounded-xl bg-primary-600 px-4 py-3 text-sm font-bold text-white disabled:opacity-60">
              {busy ? "در حال انتقال…" : `ادامه در وامبی با حساب ${who(user)}`}
            </button>
          </>
        )}
        {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
        <Link href="/" className="mt-5 inline-block text-sm font-bold text-primary-600 underline">نه، برگرد به شصت آنلاین</Link>
      </div>
    </div>
  );
}
