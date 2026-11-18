"use client";
// Site-wide light/dark theme (storefront, product, checkout and the admin/organization dashboards).
// One preference per browser (localStorage "60online_theme"); default is light. The inline script in
// app/layout.tsx applies it before first paint, so there is no flash. Switching uses the View Transitions API
// for a circular reveal from the toggle; reduced-motion users (or browsers without it) get an instant switch.
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

export const THEME_KEY = "60online_theme";
export type DashTheme = "light" | "dark";
const EVT = "60online:theme";

const current = (): DashTheme => (typeof document !== "undefined" && document.documentElement.dataset.theme === "dark" ? "dark" : "light");

function apply(next: DashTheme) {
  const html = document.documentElement;
  html.dataset.theme = next;
  html.style.colorScheme = next;
  try { localStorage.setItem(THEME_KEY, next); } catch {}
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", next === "dark" ? "#0B1418" : "#FFFFFF");
  window.dispatchEvent(new CustomEvent(EVT, { detail: next }));
}

type VT = { startViewTransition?: (cb: () => void) => { ready: Promise<void> } };

export function useDashTheme(): [DashTheme, (origin?: HTMLElement | null) => void] {
  const [theme, setTheme] = useState<DashTheme>("light");
  useEffect(() => {
    setTheme(current());
    const on = (e: Event) => setTheme((e as CustomEvent<DashTheme>).detail);
    window.addEventListener(EVT, on);
    return () => window.removeEventListener(EVT, on);
  }, []);
  const toggle = (origin?: HTMLElement | null) => {
    const next: DashTheme = current() === "dark" ? "light" : "dark";
    const doc = document as Document & VT;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!doc.startViewTransition || reduce) { apply(next); return; }
    const r = origin?.getBoundingClientRect();
    const x = r ? r.left + r.width / 2 : innerWidth / 2, y = r ? r.top + r.height / 2 : 0;
    const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    const html = document.documentElement;
    html.style.setProperty("--vt-x", `${x}px`); html.style.setProperty("--vt-y", `${y}px`); html.style.setProperty("--vt-r", `${radius}px`);
    html.classList.add("theme-vt");
    doc.startViewTransition(() => apply(next)).ready.finally(() => setTimeout(() => html.classList.remove("theme-vt"), 600));
  };
  return [theme, toggle];
}

/** Day/night pill switch — Google Stitch screen 33: light = white pill with a golden sun knob (end side),
 *  dark = petrol pill with a night knob (start side). The knob slides and rotates (350ms); the page switch
 *  itself is the circular reveal from the toggle (useDashTheme). */
export function DashThemeToggle({ theme, onToggle, className = "", size = "md" }: { theme: DashTheme; onToggle: (origin?: HTMLElement | null) => void; className?: string; size?: "sm" | "md" }) {
  const dark = theme === "dark", sm = size === "sm";
  return (
    <button type="button" role="switch" aria-checked={dark} onClick={(e) => onToggle(e.currentTarget)}
      aria-label="حالت تیره" title={dark ? "رفتن به حالت روشن" : "رفتن به حالت تیره"}
      className={cn("theme-switch relative inline-flex shrink-0 items-center rounded-full transition-colors duration-300",
        sm ? "h-6 w-11 p-0.5" : "h-7 w-14 p-1",
        dark ? "bg-[#004E72] shadow-inner" : "bg-[#fffffe] shadow-md ring-1 ring-black/5", className)}>
      <span aria-hidden className={cn("flex h-5 w-5 items-center justify-center rounded-full shadow-sm transition-all duration-[350ms] [transition-timing-function:cubic-bezier(.5,1.4,.4,1)]",
        dark ? "translate-x-0 rotate-0 bg-[#0C1519] text-[#C9E6FF]" : (sm ? "-translate-x-5" : "-translate-x-7") + " rotate-[360deg] bg-[#FFA000] text-[#fffffe]")}>
        <span className="material-symbols-outlined icon-fill" style={{ fontSize: sm ? 13 : 14 }}>{dark ? "dark_mode" : "light_mode"}</span>
      </span>
    </button>
  );
}
