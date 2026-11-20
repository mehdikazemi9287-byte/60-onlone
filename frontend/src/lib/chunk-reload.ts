// Pure helpers for recovering from a failed JS chunk / dynamic import (ChunkLoadError).
// Typical causes: an edge/CDN 502/503 on /_next/static/* for one request, or HTML from an older
// deploy that references chunks no longer on the server. One reload usually fixes both.
// The guard allows at most one automatic reload per page path within RELOAD_WINDOW_MS, so a
// persistent failure can never turn into a reload loop.

export const RELOAD_KEY = "60online_chunk_reload";
export const RELOAD_WINDOW_MS = 5 * 60 * 1000;

const CHUNK_MESSAGE =
  /ChunkLoadError|Loading (?:CSS )?chunk [^\s]+ failed|Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i;

/** True when an error / rejection reason looks like a failed chunk or dynamic import. */
export function isChunkLoadError(reason: unknown): boolean {
  if (!reason) return false;
  if (typeof reason === "string") return CHUNK_MESSAGE.test(reason);
  if (typeof reason === "object") {
    const r = reason as { name?: unknown; message?: unknown };
    if (r.name === "ChunkLoadError") return true;
    if (typeof r.message === "string") return CHUNK_MESSAGE.test(r.message);
  }
  return false;
}

/** True for a <script> element whose source is one of our build chunks. */
export function isOwnChunkScriptUrl(src: string, origin: string): boolean {
  try {
    const u = new URL(src, origin);
    return u.origin === origin && u.pathname.startsWith("/_next/static/");
  } catch {
    return false;
  }
}

type Store = Pick<Storage, "getItem" | "setItem">;

/**
 * Decide whether to reload now, and record the attempt. Returns false (no reload) when a reload
 * for the same path already happened inside the window, or when storage is unavailable
 * (without storage we cannot prove we are not looping, so we do nothing).
 */
export function claimReload(store: Store | null | undefined, path: string, now: number): boolean {
  if (!store) return false;
  try {
    const raw = store.getItem(RELOAD_KEY);
    let last: { path?: unknown; t?: unknown } | null = null;
    if (raw) {
      try { last = JSON.parse(raw) as { path?: unknown; t?: unknown }; } catch { last = null; } // corrupt value: overwrite
    }
    {
      if (last && last.path === path && typeof last.t === "number" && now - last.t >= 0 && now - last.t < RELOAD_WINDOW_MS) {
        return false;
      }
    }
    store.setItem(RELOAD_KEY, JSON.stringify({ path, t: now }));
    // Read back: if the write silently failed (quota / privacy mode) do not reload.
    const check = store.getItem(RELOAD_KEY);
    return !!check && check.includes(`"t":${now}`);
  } catch {
    return false;
  }
}
