"use client";
import { MODES, useShoppingMode } from "@/lib/shopping-mode";
import { cn } from "@/lib/utils";

/** Three-mode shopping switch. Changing it only changes what the page offers; nothing is cleared or reloaded. */
export function ModeSwitch({ tone = "dark", className }: { tone?: "dark" | "light"; className?: string }) {
  const [mode, setMode] = useShoppingMode();
  return (
    <div role="radiogroup" aria-label="حالت خرید" className={cn("inline-flex items-center gap-1 rounded-lg p-1", tone === "dark" ? "bg-white/10" : "bg-[#EEF2F6]", className)}>
      {MODES.map((m) => {
        const on = m.key === mode;
        return (
          <button key={m.key} type="button" role="radio" aria-checked={on} onClick={() => setMode(m.key)}
            className={cn("inline-flex flex-1 items-center", tone === "dark" ? "min-h-9" : "min-h-11", " justify-center gap-1.5 whitespace-nowrap rounded-md px-3 text-[13px] font-bold transition",
              on ? "bg-honey text-mm-deep shadow-sm"
                : tone === "dark" ? "text-white/80 hover:bg-white/10 hover:text-white" : "text-mm-muted hover:bg-white hover:text-mm-text")}>
            {on && <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-mm-deep" />}
            {m.label}
          </button>);
      })}
    </div>
  );
}
