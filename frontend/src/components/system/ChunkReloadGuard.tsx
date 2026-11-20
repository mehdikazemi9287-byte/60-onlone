"use client";

// App-wide recovery from a failed JS chunk (ChunkLoadError / failed dynamic import / a /_next/static
// script that the CDN answered with 502/503). Reloads the page once per path within a time window;
// see src/lib/chunk-reload.ts. Renders nothing.
import { useEffect } from "react";
import { claimReload, isChunkLoadError, isOwnChunkScriptUrl } from "@/lib/chunk-reload";

export function reloadOnceForChunkError(): boolean {
  if (typeof window === "undefined") return false;
  let store: Storage | null = null;
  try { store = window.sessionStorage; } catch { store = null; }
  if (!claimReload(store, window.location.pathname, Date.now())) return false;
  window.location.reload();
  return true;
}

export function ChunkReloadGuard() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    const onError = (e: Event) => {
      // Resource load failures do not bubble; this listener runs in the capture phase.
      const t = e.target;
      if (t instanceof HTMLScriptElement) {
        if (t.src && isOwnChunkScriptUrl(t.src, window.location.origin)) reloadOnceForChunkError();
        return;
      }
      if (e instanceof ErrorEvent && (isChunkLoadError(e.error) || isChunkLoadError(e.message))) reloadOnceForChunkError();
    };
    const onRejection = (e: PromiseRejectionEvent) => {
      if (isChunkLoadError(e.reason)) reloadOnceForChunkError();
    };
    window.addEventListener("error", onError, true);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError, true);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);
  return null;
}
