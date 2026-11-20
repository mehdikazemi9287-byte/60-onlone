"use client";
// Three shopping modes (owner decision 2026-11-19): personal is the default for everyone; users switch freely and the
// last choice is remembered on this device only. Switching changes no server state. Each mode has its OWN cart on the
// server (migration 0084): lib/api.ts sends the active mode as X-Shopping-Mode on cart/checkout calls, and the server
// decides whether the user may use it. Employer credit and the welfare wallet apply only to the «پرسنل سازمان» cart.
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export type ShoppingMode = "personal" | "staff" | "org";
export const MODES: { key: ShoppingMode; label: string; short: string }[] = [
  { key: "personal", label: "شخصی", short: "شخصی" },
  { key: "staff", label: "پرسنل سازمان", short: "پرسنل" },
  { key: "org", label: "سازمانی و عمده", short: "سازمانی" },
];
const KEY = "60online_shopping_mode";
const EVENT = "60online:shopping-mode";

function read(): ShoppingMode {
  try { const v = window.localStorage.getItem(KEY); if (v === "staff" || v === "org") return v; } catch {}
  return "personal";
}
function subscribe(cb: () => void) {
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", cb);
  return () => { window.removeEventListener(EVENT, cb); window.removeEventListener("storage", cb); };
}

export function setShoppingMode(mode: ShoppingMode) {
  try { window.localStorage.setItem(KEY, mode); } catch {}
  window.dispatchEvent(new Event(EVENT));
  // The header badge and cart views re-read the cart of the newly active mode.
  window.dispatchEvent(new Event("60online:cart-changed"));
}

/** Current mode; "personal" on the server and before hydration. */
export function useShoppingMode(): [ShoppingMode, (m: ShoppingMode) => void] {
  const mode = useSyncExternalStore(subscribe, read, () => "personal" as ShoppingMode);
  return [mode, useCallback((m: ShoppingMode) => setShoppingMode(m), [])];
}

type Membership = { id: number; display_name: string; status: string; membership: { role: string; status: string } };
export type ModeAccess = {
  loading: boolean;
  signedIn: boolean;
  /** Active member of a contracted organization (any role) — can use /benefits. */
  staff: boolean;
  /** Active non-employee member (buyer/admin/finance) — can use the organization panel. */
  org: boolean;
  orgName: string | null;
  openPrograms: number;
};

let cache: { token: string; value: Promise<Omit<ModeAccess, "loading" | "signedIn">> } | null = null;
function load(token: string) {
  if (cache?.token === token) return cache.value;
  const value = Promise.all([
    apiRequest<{ items: Membership[] }>("/organizations", { token }).then((r) => r.items).catch(() => [] as Membership[]),
    apiRequest<{ items: { status: string }[] }>("/me/benefits", { token }).then((r) => r.items).catch(() => [] as { status: string }[]),
  ]).then(([orgs, programs]) => {
    const active = orgs.filter((o) => o.status === "active" && o.membership?.status === "active");
    const manager = active.find((o) => o.membership.role !== "employee");
    return { staff: active.length > 0, org: !!manager, orgName: (manager ?? active[0])?.display_name ?? null,
      openPrograms: programs.filter((p) => p.status === "open").length };
  });
  cache = { token, value };
  return value;
}

/** What the signed-in user may actually use in each mode (read-only checks against the real API). */
export function useModeAccess(): ModeAccess {
  const { token, loading: authLoading } = useAuth();
  const [state, setState] = useState<Omit<ModeAccess, "loading" | "signedIn"> | null>(null);
  useEffect(() => {
    let off = false;
    setState(null);
    if (!token) return;
    load(token).then((v) => !off && setState(v));
    return () => { off = true; };
  }, [token]);
  if (authLoading || (token && !state)) return { loading: true, signedIn: !!token, staff: false, org: false, orgName: null, openPrograms: 0 };
  return { loading: false, signedIn: !!token, ...(state ?? { staff: false, org: false, orgName: null, openPrograms: 0 }) };
}
