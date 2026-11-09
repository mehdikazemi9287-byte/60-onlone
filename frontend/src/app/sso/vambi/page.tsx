"use client";

// 60online.ir side of the shared login: a signed-in user gets a one-time code for the sister site and is sent
// back there. Only the URL the server returns is followed (the server checks `target` against its allow-list).
import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { sso } from "@/lib/sso";

export default function SsoVambiPage() {
  return (
    <Suspense fallback={null}>
      <SsoVambi />
    </Suspense>
  );
}

function SsoVambi() {
  const router = useRouter();
  const params = useSearchParams();
  const { token, loading } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);
  const target = params.get("target") ?? "";
  const state = params.get("state") ?? "";

  useEffect(() => {
    if (loading || started.current) return;
    if (!target || !state) { setError("لینک ورود ناقصه. از وامبی دوباره روی «ورود» بزن."); return; }
    const self = `/sso/vambi?${new URLSearchParams({ target, state })}`;
    if (!token) { started.current = true; router.replace(`/login?next=${encodeURIComponent(self)}`); return; }
    started.current = true;
    sso.issue(token, target, state)
      .then(({ redirect_url }) => {
        // Follow only a URL on the requested origin's callback path, exactly as the server built it.
        if (!redirect_url.startsWith(`${target}/sso/callback?`)) throw new Error("bad redirect");
        window.location.assign(redirect_url);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) { router.replace(`/login?next=${encodeURIComponent(self)}`); return; }
        setError(e instanceof ApiError && e.code === "sso_origin_not_allowed"
          ? "این سایت اجازهٔ ورود با حساب شصت آنلاین رو نداره."
          : e instanceof ApiError ? e.message : "ورود انجام نشد. یه بار دیگه امتحان کن.");
      });
  }, [loading, token, target, state, router]);

  return (
    <div className="flex min-h-[calc(100vh-160px)] items-center justify-center px-4 py-12">
      <div className="card w-full max-w-md p-7 text-center md:p-8">
        {error ? (
          <>
            <h1 className="text-lg font-bold text-neutral-900">ورود با حساب شصت آنلاین</h1>
            <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>
            <Link href="/" className="mt-5 inline-block text-sm font-bold text-primary-600 underline">برگشت به شصت آنلاین</Link>
          </>
        ) : (
          <p role="status" className="text-sm text-neutral-700">داری با حساب شصت آنلاینت وارد می‌شی…</p>
        )}
      </div>
    </div>
  );
}
