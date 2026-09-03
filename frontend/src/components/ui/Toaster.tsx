"use client";
// Minimal toast provider — wraps Radix Toast
import * as ToastPrimitive from "@radix-ui/react-toast";
import { cn } from "@/lib/utils";

export function Toaster() {
  return (
    <ToastPrimitive.Provider swipeDirection="right">
      <ToastPrimitive.Viewport
        className={cn(
          "fixed bottom-4 left-4 z-50 flex flex-col gap-2",
          "w-full max-w-sm outline-none"
        )}
      />
    </ToastPrimitive.Provider>
  );
}

export function Toast({
  title,
  description,
  variant = "default",
}: {
  title: string;
  description?: string;
  variant?: "default" | "success" | "error";
}) {
  const colors = {
    default: "bg-neutral-900 text-white border-neutral-700",
    success: "bg-success-600 text-white border-success-700",
    error:   "bg-danger-600 text-white border-danger-700",
  };

  return (
    <ToastPrimitive.Root
      className={cn(
        "flex items-start gap-3 p-4 rounded-xl border shadow-lg",
        "data-[state=open]:animate-slide-up",
        colors[variant]
      )}
    >
      <div className="flex-1 min-w-0">
        <ToastPrimitive.Title className="font-semibold text-sm">{title}</ToastPrimitive.Title>
        {description && (
          <ToastPrimitive.Description className="mt-0.5 text-xs opacity-80">
            {description}
          </ToastPrimitive.Description>
        )}
      </div>
      <ToastPrimitive.Close className="opacity-60 hover:opacity-100 transition-opacity text-current">
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </ToastPrimitive.Close>
    </ToastPrimitive.Root>
  );
}
