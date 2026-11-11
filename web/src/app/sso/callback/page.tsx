"use client";

// Sister-site side (e.g. vambi.ir) of the shared login: check `state` against what this browser stored, swap the
// one-time code for a session, store it like any login, then go back to the saved relative path.
// Vambi has no login form of its own: this page finishes the sign-in started on the 60Online account.
import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ApiError } from "@/lib/api";
import { burnCode, sso, takePending } from "@/lib/sso";

export default function SsoCallbackPage() {
  return (
    <Suspense fallback={null}>
      <SsoCallback />
    </Suspense>
  );
}

function SsoCallback() {
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const code = params.get("code") ?? "";
    const state = params.get("state") ?? "";
    // Drop the one-time code from the address bar and history right away.
    try { window.history.replaceState(null, "", "/sso/callback"); } catch {}
    const pending = takePending();
    if (!code || !state || !pending || pending.state !== state) {
      const msg = "این لینک ورود مال این مرورگر نیست یا قبلاً استفاده شده. دوباره روی «ورود» بزن.";
      burnCode(code).finally(() => setError(msg));
      return;
    }
    sso.exchange(code, pending.state)
      .then((res) => { sso.store(res.access_token); window.location.replace(pending.back); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "ورود انجام نشد. یه بار دیگه امتحان کن."));
  }, [params]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-white px-4">
      <div className="w-full max-w-md rounded-2xl border border-neutral-200 p-7 text-center">
        {error ? (
          <>
            <h1 className="text-lg font-bold text-neutral-900">ورود با حساب شصت آنلاین</h1>
            <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>
            <Link href="/" className="mt-5 inline-block text-sm font-bold underline">برگشت به صفحهٔ اول</Link>
          </>
        ) : (
          <p role="status" className="text-sm text-neutral-700">داری وارد می‌شی…</p>
        )}
      </div>
    </div>
  );
}
