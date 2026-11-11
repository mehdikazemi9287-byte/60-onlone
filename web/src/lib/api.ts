/**
 * Vambi API client. Vambi has no backend of its own: it reads the 60Online ecosystem API (catalog, sellers, prices,
 * accounts). Requests are same-origin (/api/v1/…) and next.config.mjs proxies them to VAMBI_API_ORIGIN.
 */
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";
export const TOKEN_KEY = "vambi_token";

export interface AuthUser { id: number; email: string; full_name: string; phone?: string | null; role: string }

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: Record<string, string>) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(path: string, options: RequestInit & { token?: string } = {}): Promise<T> {
  const { token: explicit, ...rest } = options;
  // Prices can be members-only: send the stored session on Vambi searches too.
  let token = explicit;
  if (!token && typeof window !== "undefined" && path.startsWith("/vambi")) {
    try { token = window.localStorage.getItem(TOKEN_KEY) ?? undefined; } catch {}
  }
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(rest.headers as Record<string, string>),
  };
  const res = await fetch(`${BASE}/api/v1${path}`, { ...rest, headers });
  if (!res.ok) {
    if (res.status === 401 && token && typeof window !== "undefined")
      window.dispatchEvent(new CustomEvent("vambi:session-invalid", { detail: token }));
    let code = "UNKNOWN", message = res.statusText, details: Record<string, string> | undefined;
    try {
      const body = await res.json(), err = body.error;
      if (err && typeof err === "object") { code = err.code ?? code; message = err.message ?? message; details = err.details; }
      else if (typeof err === "string") { code = err; message = body.message ?? message; }
    } catch {}
    throw new ApiError(res.status, code, message, details);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const auth = {
  me: (token: string) => apiRequest<{ user: AuthUser }>("/auth/me", { token }),
  logout: (token: string) => apiRequest<unknown>("/auth/logout", { method: "POST", token }),
};
