// Small presentation helpers shared by the Stitch-faithful cart, checkout and account screens (group C).
// No data logic lives here: amounts arrive from the server in minor units (Rial) and are only formatted.
import { clsx as cn } from "clsx";
import dark from "./stitchDark.module.css";

/** Material Symbols icon (self-hosted subset, see tools/stitch/icons-included.txt). */
export function Icon({ name, className, fill }: { name: string; className?: string; fill?: boolean }) {
  return (
    <span aria-hidden="true" className={cn("material-symbols-outlined", fill && "icon-fill", className)}>
      {name}
    </span>
  );
}

/** Rial (minor) → grouped Persian Toman digits, without the unit (same ÷10 conversion as formatPrice). */
export function toman(minor: number): string {
  return Math.round(minor / 10).toLocaleString("fa-IR", { maximumFractionDigits: 0 });
}

/** Root class for group-C pages: Stitch background + scoped dark mapping (html[data-theme=dark]). */
export const stRoot = cn(dark.root, "bg-st-background text-st-on-surface");
