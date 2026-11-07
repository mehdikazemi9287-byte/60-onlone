"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function JoinSellerPage({ params }: { params: Promise<{ code: string }> }) {
  const [code, setCode] = useState<string | null>(null);
  const [seller, setSeller] = useState<string | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "invalid" | "done" | "error">("loading");
  const [msg, setMsg] = useState("");
  const { token } = useAuth();
  useEffect(() => { params.then((p) => setCode(p.code)); }, [params]);
  useEffect(() => {
    if (!code) return;
    apiRequest<{ seller: string }>(`/direct-invites/${encodeURIComponent(code)}`)
      .then((r) => { setSeller(r.seller); setState("ready"); })
      .catch(() => setState("invalid"));
  }, [code]);
  const claim = async () => {
    try { await apiRequest(`/me/direct-invites/${encodeURIComponent(code!)}/claim`, { token: token!, method: "POST", body: "{}" }); setState("done"); }
    catch (e) { setMsg(e instanceof ApiError ? e.message : "ناموفق بود"); setState("error"); }
  };
  return (
    <main className="mx-auto max-w-md px-4 py-16 text-center">
      {state === "loading" && <p>در حال بررسی دعوت…</p>}
      {state === "invalid" && <p>این دعوت معتبر نیست یا قبلاً استفاده شده است.</p>}
      {(state === "ready" || state === "error") && (
        <>
          <h1 className="text-xl font-black">{seller} شما را به خرید آنلاین دعوت کرده است</h1>
          <p className="mt-3 text-sm leading-7 text-neutral-600">با پذیرش، می‌توانید سفارش‌هایتان از این فروشنده را آنلاین ثبت کنید.</p>
          {token
            ? <button className="mt-6 rounded-xl bg-primary-600 px-6 py-3 font-bold text-white" onClick={claim}>می‌پذیرم</button>
            : <Link className="mt-6 inline-block rounded-xl bg-primary-600 px-6 py-3 font-bold text-white" href="/login">ورود و پذیرش دعوت</Link>}
          {state === "error" && <p role="alert" className="mt-4 text-sm text-red-700">{msg}</p>}
        </>
      )}
      {state === "done" && <p className="font-bold">انجام شد. حالا از <Link className="underline" href="/shops">غرفه‌ها</Link> سفارش دهید.</p>}
    </main>
  );
}
