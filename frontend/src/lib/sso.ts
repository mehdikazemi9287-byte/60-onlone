/**
 * ورود مشترک vambi.ir ↔ 60online.ir (backend: /api/v1/auth/sso/issue + /exchange, see backend/app/services/sso_service.py).
 *
 * Sister site (vambi.ir): startSso() keeps a random `state` and the relative return path in sessionStorage and sends
 * the browser to `${NEXT_PUBLIC_MAIN_SITE}/sso/vambi`. The main site asks the server for a one-time code and the
 * server sends the browser back to `<origin>/sso/callback`, which checks `state` and swaps the code for a session.
 * When this page already runs on the main site's origin (dev, or 60online.ir/vambi) the plain /login is used.
 */
import { apiRequest, type AuthUser } from "@/lib/api";

export const MAIN_SITE = (process.env.NEXT_PUBLIC_MAIN_SITE ?? "").replace(/\/+$/, "");
const KEY = "60online_sso";
const TOKEN_KEY = "60online_token"; // same key AuthProvider reads (lib/auth-context.tsx)

/** A same-site relative path only ("/x?y"), never "//host" or a scheme; anything else falls back to "/". */
export function safeRelative(path: string | null | undefined): string {
  return path && path.startsWith("/") && !path.startsWith("//") && !/[\\\u0000-\u001f]/.test(path) ? path : "/";
}

/** True when login must go through the main site (we are on a different origin than NEXT_PUBLIC_MAIN_SITE). */
export function needsSso(): boolean {
  if (typeof window === "undefined" || !MAIN_SITE) return false;
  try { return new URL(MAIN_SITE).origin !== window.location.origin; } catch { return false; }
}

function randomState(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Where a "login" action should go from this page. Starts SSO on a sister site; plain /login otherwise. */
export function startLogin(returnPath = window.location.pathname + window.location.search): void {
  const back = safeRelative(returnPath);
  if (!needsSso()) { window.location.href = `/login?next=${encodeURIComponent(back)}`; return; }
  const state = randomState();
  try { sessionStorage.setItem(KEY, JSON.stringify({ state, back })); } catch { /* storage blocked: callback will refuse */ }
  const qs = new URLSearchParams({ target: window.location.origin, state });
  window.location.assign(`${MAIN_SITE}/sso/vambi?${qs}`);
}

/** Read and forget what startLogin() stored. */
export function takePending(): { state: string; back: string } | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    const v = raw ? JSON.parse(raw) : null;
    return v && typeof v.state === "string" ? { state: v.state, back: safeRelative(v.back) } : null;
  } catch { return null; }
}

export const sso = {
  issue: (token: string, target_origin: string, state: string) =>
    apiRequest<{ redirect_url: string; expires_in: number }>("/auth/sso/issue", {
      method: "POST", token, body: JSON.stringify({ target_origin, state }),
    }),
  exchange: (code: string, state: string) =>
    apiRequest<{ access_token: string; token_type: string; expires_in: number; user: AuthUser }>("/auth/sso/exchange", {
      method: "POST", body: JSON.stringify({ code, state }),
    }),
  /** Store the session exactly where password/OTP login stores it; AuthProvider picks it up on the next page load. */
  store: (accessToken: string) => localStorage.setItem(TOKEN_KEY, accessToken),
};
