import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "success" | "warning" | "danger" | "neutral" | "outline";
type Size    = "sm" | "md" | "lg";

interface BadgeProps {
  variant?:  Variant;
  size?:     Size;
  dot?:      boolean;
  className?: string;
  children:  React.ReactNode;
}

const variants: Record<Variant, string> = {
  primary:   "bg-primary-50  text-primary-700  border-primary-200",
  secondary: "bg-neutral-100 text-neutral-600  border-neutral-200",
  success:   "bg-success-50  text-success-700  border-green-200",
  warning:   "bg-amber-50    text-amber-700    border-amber-200",
  danger:    "bg-danger-50   text-danger-700   border-red-200",
  neutral:   "bg-neutral-100 text-neutral-500  border-neutral-200",
  outline:   "bg-transparent text-neutral-600  border-neutral-300",
};

const dotColors: Record<Variant, string> = {
  primary:   "bg-primary-500",
  secondary: "bg-neutral-400",
  success:   "bg-success-500",
  warning:   "bg-amber-500",
  danger:    "bg-danger-500",
  neutral:   "bg-neutral-400",
  outline:   "bg-neutral-400",
};

const sizes: Record<Size, string> = {
  sm: "text-2xs px-1.5 py-0.5 gap-1",
  md: "text-xs  px-2   py-1   gap-1.5",
  lg: "text-sm  px-2.5 py-1   gap-1.5",
};

export function Badge({
  variant = "secondary",
  size = "md",
  dot = false,
  className,
  children,
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center font-medium rounded-full border",
        variants[variant],
        sizes[size],
        className
      )}
    >
      {dot && (
        <span
          className={cn("block rounded-full flex-shrink-0", dotColors[variant],
            size === "sm" ? "w-1.5 h-1.5" : "w-2 h-2"
          )}
        />
      )}
      {children}
    </span>
  );
}

// Order status badge helper
export function OrderStatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; variant: Variant }> = {
    pending:    { label: "در انتظار پرداخت",  variant: "warning" },
    paid:       { label: "پرداخت شده",         variant: "primary" },
    processing: { label: "در حال پردازش",     variant: "primary" },
    shipped:    { label: "ارسال شده",          variant: "secondary" },
    delivered:  { label: "تحویل داده شده",    variant: "success" },
    cancelled:  { label: "لغو شده",            variant: "danger" },
  };
  const { label, variant } = map[status] ?? { label: status, variant: "neutral" as Variant };
  return <Badge variant={variant} dot>{label}</Badge>;
}
