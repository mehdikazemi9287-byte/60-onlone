"use client";

// Vambi header login: always through the 60Online account (lib/sso.ts).
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { needsSso, startLogin } from "@/lib/sso";

export function VambiLoginButton() {
  const { user, loading, logout } = useAuth();
  const [viaMain, setViaMain] = useState(false);
  useEffect(() => setViaMain(needsSso()), []);
  const cls = "rounded-full bg-[#102B7A] px-4 py-2 text-sm font-bold text-white";

  if (loading) return <span className="h-9 w-28" aria-hidden />;
  if (user) return (
    <span className="flex items-center gap-2">
      <span className="max-w-[9rem] truncate text-sm font-bold text-[#102B7A]">{user.full_name}</span>
      <button type="button" onClick={logout} className="text-xs font-bold text-neutral-600 underline">خروج</button>
    </span>
  );
  return <button type="button" onClick={() => startLogin()} className={cls}>ورود<span className="hidden sm:inline"> با حساب شصت آنلاین</span></button>;
}
