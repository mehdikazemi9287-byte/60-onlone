"use client";

// Vambi session. Sign-in always happens on the 60Online account (lib/sso.ts); this only reads the stored token.
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { auth, ApiError, TOKEN_KEY, type AuthUser } from "@/lib/api";

interface AuthValue { user: AuthUser | null; token: string | null; loading: boolean; logout: () => void }
const Ctx = createContext<AuthValue | null>(null);
const read = () => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } };
const drop = () => { try { localStorage.removeItem(TOKEN_KEY); } catch {} };

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true, generation = 0;
    const refresh = () => {
      const version = ++generation, stored = read();
      setToken(null); setUser(null); setLoading(!!stored);
      if (!stored) return;
      auth.me(stored)
        .then((res) => { if (alive && version === generation && read() === stored) { setToken(stored); setUser(res.user); } })
        // A transient outage must not destroy a valid stored session.
        .catch((err) => { if (err instanceof ApiError && err.status === 401 && read() === stored) drop(); })
        .finally(() => { if (alive && version === generation) setLoading(false); });
    };
    const storage = (e: StorageEvent) => { if (e.storageArea === localStorage && (e.key === TOKEN_KEY || e.key === null)) refresh(); };
    const invalid = (e: Event) => { const expired = (e as CustomEvent<string>).detail; if (expired && read() === expired) { drop(); refresh(); } };
    refresh();
    window.addEventListener("storage", storage);
    window.addEventListener("vambi:session-invalid", invalid);
    return () => { alive = false; generation++; window.removeEventListener("storage", storage); window.removeEventListener("vambi:session-invalid", invalid); };
  }, []);

  const logout = useCallback(() => {
    const t = token;
    drop(); setToken(null); setUser(null);
    if (t) auth.logout(t).catch(() => {});
  }, [token]);

  return <Ctx.Provider value={{ user, token, loading, logout }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
