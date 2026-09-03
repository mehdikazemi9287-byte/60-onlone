"use client";

import { forwardRef } from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/utils";

// ── Types ────────────────────────────────────────────────────────────────────

type Variant = "primary" | "secondary" | "outline" | "ghost" | "danger" | "accent";
type Size    = "xs" | "sm" | "md" | "lg" | "xl";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?:  Variant;
  size?:     Size;
  loading?:  boolean;
  asChild?:  boolean;
  iconOnly?: boolean;
}

// ── Variants ─────────────────────────────────────────────────────────────────

const variants: Record<Variant, string> = {
  primary: [
    "bg-primary-600 text-white shadow-sm",
    "hover:bg-primary-700 active:bg-primary-800",
    "disabled:bg-neutral-300 disabled:text-neutral-500 disabled:shadow-none",
  ].join(" "),

  secondary: [
    "bg-primary-50 text-primary-700 border border-primary-200",
    "hover:bg-primary-100 active:bg-primary-200",
    "disabled:bg-neutral-100 disabled:text-neutral-400 disabled:border-neutral-200",
  ].join(" "),

  outline: [
    "bg-white text-neutral-700 border border-neutral-300 shadow-xs",
    "hover:bg-neutral-50 hover:border-neutral-400 active:bg-neutral-100",
    "disabled:bg-neutral-50 disabled:text-neutral-400",
  ].join(" "),

  ghost: [
    "bg-transparent text-neutral-600",
    "hover:bg-neutral-100 hover:text-neutral-800 active:bg-neutral-200",
    "disabled:text-neutral-400",
  ].join(" "),

  danger: [
    "bg-danger-600 text-white shadow-sm",
    "hover:bg-danger-700 active:bg-danger-800",
    "disabled:bg-neutral-300 disabled:text-neutral-500",
  ].join(" "),

  accent: [
    "bg-accent-500 text-white shadow-sm font-semibold",
    "hover:bg-accent-600 active:bg-accent-700",
    "disabled:bg-neutral-300 disabled:text-neutral-500",
  ].join(" "),
};

const sizes: Record<Size, string> = {
  xs: "h-7  px-2.5 text-xs  gap-1   rounded",
  sm: "h-8  px-3   text-sm  gap-1.5 rounded",
  md: "h-9  px-4   text-sm  gap-2   rounded-lg",
  lg: "h-10 px-5   text-base gap-2  rounded-lg",
  xl: "h-12 px-6   text-base gap-2  rounded-xl font-semibold",
};

const iconOnlySizes: Record<Size, string> = {
  xs: "h-7  w-7  rounded",
  sm: "h-8  w-8  rounded",
  md: "h-9  w-9  rounded-lg",
  lg: "h-10 w-10 rounded-lg",
  xl: "h-12 w-12 rounded-xl",
};

// ── Component ─────────────────────────────────────────────────────────────────

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = "primary",
      size = "md",
      loading = false,
      asChild = false,
      iconOnly = false,
      className,
      children,
      disabled,
      ...props
    },
    ref
  ) => {
    const Comp = asChild ? Slot : "button";
    const isDisabled = disabled || loading;

    return (
      <Comp
        ref={ref}
        disabled={isDisabled}
        className={cn(
          // base
          "inline-flex items-center justify-center font-medium",
          "transition-all duration-150 cursor-pointer select-none",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2",
          "disabled:cursor-not-allowed disabled:opacity-60",
          // variant + size
          variants[variant],
          iconOnly ? iconOnlySizes[size] : sizes[size],
          className
        )}
        {...props}
      >
        {loading ? (
          <>
            <span className="block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
            {!iconOnly && <span className="opacity-70">لطفاً صبر کنید…</span>}
          </>
        ) : (
          children
        )}
      </Comp>
    );
  }
);
Button.displayName = "Button";

export { Button };
export type { ButtonProps };
