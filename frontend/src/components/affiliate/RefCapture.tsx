"use client";

import { useEffect } from "react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const KEY = "60o_ref";
const DAYS = 7;

/** همکاری در فروش: remember ?ref=CODE for 7 days and report it once the visitor is logged in. */
export function RefCapture() {
  const { token } = useAuth();
  useEffect(() => {
    try {
      const code = new URLSearchParams(window.location.search).get("ref");
      if (code && /^[A-Za-z0-9]{4,24}$/.test(code)) {
        localStorage.setItem(KEY, JSON.stringify({ code, at: Date.now() }));
      }
    } catch { /* storage may be unavailable */ }
  }, []);
  useEffect(() => {
    if (!token) return;
    let saved: { code: string; at: number } | null = null;
    try { saved = JSON.parse(localStorage.getItem(KEY) || "null"); } catch { saved = null; }
    if (!saved || Date.now() - saved.at > DAYS * 864e5) return;
    apiRequest("/me/referral", { method: "POST", token, body: JSON.stringify({ code: saved.code }) })
      .catch(() => {})
      .finally(() => { try { localStorage.removeItem(KEY); } catch { /* ignore */ } });
  }, [token]);
  return null;
}
