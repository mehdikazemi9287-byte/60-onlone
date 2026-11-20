"use client";

// Root error boundary. A ChunkLoadError (e.g. CDN 502/503 on a /_next/static chunk) is retried with
// one guarded page reload; any other error, or a repeat failure, shows a minimal retry screen.
import { useEffect, useState } from "react";
import { isChunkLoadError } from "@/lib/chunk-reload";
import { reloadOnceForChunkError } from "@/components/system/ChunkReloadGuard";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const [reloading, setReloading] = useState(false);
  useEffect(() => {
    if (isChunkLoadError(error) && reloadOnceForChunkError()) setReloading(true);
  }, [error]);
  return (
    <html lang="fa" dir="rtl">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0, minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#fff", color: "#111" }}>
        <main style={{ textAlign: "center", padding: 24, maxWidth: 420 }}>
          {reloading ? (
            <p>در حال بارگذاری دوبارهٔ صفحه…</p>
          ) : (
            <>
              <h1 style={{ fontSize: 18 }}>بارگذاری صفحه کامل نشد</h1>
              <p style={{ fontSize: 14, color: "#555" }}>ممکن است اتصال لحظه‌ای قطع شده باشد. دوباره تلاش کنید.</p>
              <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
                <button type="button" onClick={() => reset()} style={{ padding: "8px 16px" }}>تلاش دوباره</button>
                <button type="button" onClick={() => window.location.reload()} style={{ padding: "8px 16px" }}>بارگذاری مجدد صفحه</button>
              </div>
            </>
          )}
        </main>
      </body>
    </html>
  );
}
