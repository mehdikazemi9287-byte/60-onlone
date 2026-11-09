"use client";

// Vambi header login. On vambi.ir it signs in through the 60online account (lib/sso.ts); on the main site's own
// origin (dev, 60online.ir/vambi) it stays the plain /login link.
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { needsSso, startLogin } from "@/lib/sso";

export function VambiLoginButton() {
  const { user, loading } = useAuth();
  const [viaMain, setViaMain] = useState(false);
  useEffect(() => setViaMain(needsSso()), []);
  const cls = "rounded-full bg-[#102B7A] px-4 py-2 text-sm font-bold text-white";

  if (loading) return <span className="h-9 w-28" aria-hidden />;
  if (user) return <span className="max-w-[12rem] truncate text-sm font-bold text-[#102B7A]">{user.full_name}</span>;
  if (!viaMain) return <a href="/login?next=%2Fvambi" className={cls}>ورود مشتریان</a>;
  return <button type="button" onClick={() => startLogin()} className={cls}>ورود با حساب شصت آنلاین</button>;
}
