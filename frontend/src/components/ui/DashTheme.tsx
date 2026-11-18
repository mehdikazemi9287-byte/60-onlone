"use client";
// Site-wide light/dark theme (storefront, product, checkout and the admin/organization dashboards).
// One preference per browser (localStorage "60online_theme"); default is light. The inline script in
// app/layout.tsx applies it before first paint, so there is no flash. Switching uses the View Transitions API
// for a circular reveal from the toggle; reduced-motion users (or browsers without it) get an instant switch.
import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
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

/** Day/night pill switch: the knob slides and the sun/moon morph (rotate + scale). */
export function DashThemeToggle({ theme, onToggle, className = "", size = "md" }: { theme: DashTheme; onToggle: (origin?: HTMLElement | null) => void; className?: string; size?: "sm" | "md" }) {
  const dark = theme === "dark", sm = size === "sm";
  return (
    <button type="button" role="switch" aria-checked={dark} onClick={(e) => onToggle(e.currentTarget)}
      aria-label="حالت تیره" title={dark ? "رفتن به حالت روشن" : "رفتن به حالت تیره"}
      className={cn(sm ? "theme-switch relative inline-flex h-7 w-[48px] shrink-0" : "theme-switch relative inline-flex h-8 w-[58px] shrink-0",
        "items-center rounded-full border p-[3px] transition-colors duration-300",
        dark ? "border-[#2C3E48] bg-[#16252C]" : "border-line-strong bg-canvas-sunken", className)}>
      <span aria-hidden className={cn("absolute inset-y-0 flex w-1/2 items-center justify-center transition-opacity duration-300", dark ? "right-0 opacity-40" : "left-0 opacity-50")}>
        {dark ? <Sun className="h-3.5 w-3.5 text-[#E8EEF1]" /> : <Moon className="h-3.5 w-3.5 text-ink" />}
      </span>
      <span aria-hidden className={cn(sm ? "relative z-10 flex h-[20px] w-[20px] items-center" : "relative z-10 flex h-[24px] w-[24px] items-center",
        " justify-center rounded-full shadow-sm transition-all duration-500 [transition-timing-function:cubic-bezier(.5,1.6,.4,1)]",
        dark ? (sm ? "-translate-x-[20px]" : "-translate-x-[26px]") + " bg-[#E8EEF1] text-[#0B1418]" : "translate-x-0 bg-white text-[#FF6D41]")}>
        <Sun className={cn("absolute h-3.5 w-3.5 transition-all duration-500", dark ? "rotate-90 scale-0 opacity-0" : "rotate-0 scale-100 opacity-100")} />
        <Moon className={cn("absolute h-3.5 w-3.5 transition-all duration-500", dark ? "rotate-0 scale-100 opacity-100" : "-rotate-90 scale-0 opacity-0")} />
      </span>
    </button>
  );
}
