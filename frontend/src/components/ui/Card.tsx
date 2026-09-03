import { cn } from "@/lib/utils";

// ── Card ─────────────────────────────────────────────────────────────────────

interface CardProps {
  hover?:    boolean;
  padding?:  "none" | "sm" | "md" | "lg";
  className?: string;
  children:  React.ReactNode;
  onClick?:  () => void;
}

const paddings = {
  none: "",
  sm:   "p-3",
  md:   "p-4 md:p-5",
  lg:   "p-5 md:p-6",
};

export function Card({ hover, padding = "md", className, children, onClick }: CardProps) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "card",
        hover && "card-hover cursor-pointer",
        paddings[padding],
        className
      )}
    >
      {children}
    </div>
  );
}

// ── Card sections ─────────────────────────────────────────────────────────────

export function CardHeader({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn("mb-4", className)}>{children}</div>;
}

export function CardTitle({ className, children }: { className?: string; children: React.ReactNode }) {
  return <h3 className={cn("text-lg font-semibold text-neutral-900", className)}>{children}</h3>;
}

export function CardDescription({ className, children }: { className?: string; children: React.ReactNode }) {
  return <p className={cn("text-sm text-neutral-500 mt-1", className)}>{children}</p>;
}

export function CardContent({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn(className)}>{children}</div>;
}

export function CardFooter({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("mt-4 pt-4 border-t border-neutral-100 flex items-center gap-3", className)}>
      {children}
    </div>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────

interface StatCardProps {
  label:    string;
  value:    React.ReactNode;
  sub?:     React.ReactNode;
  icon?:    React.ReactNode;
  color?:   "primary" | "success" | "warning" | "danger" | "neutral";
  className?: string;
}

const statColors = {
  primary: { bg: "bg-primary-50", icon: "text-primary-600", border: "border-primary-100" },
  success: { bg: "bg-success-50", icon: "text-success-600", border: "border-green-100" },
  warning: { bg: "bg-amber-50",   icon: "text-amber-600",   border: "border-amber-100" },
  danger:  { bg: "bg-danger-50",  icon: "text-danger-600",  border: "border-red-100" },
  neutral: { bg: "bg-neutral-50", icon: "text-neutral-500", border: "border-neutral-100" },
};

export function StatCard({ label, value, sub, icon, color = "primary", className }: StatCardProps) {
  const c = statColors[color];
  return (
    <div className={cn("card p-4 md:p-5", className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-neutral-500 mb-1">{label}</p>
          <p className="text-2xl font-bold text-neutral-900 tabular-nums">{value}</p>
          {sub && <p className="text-xs text-neutral-400 mt-1">{sub}</p>}
        </div>
        {icon && (
          <div className={cn("flex-shrink-0 p-2.5 rounded-xl border", c.bg, c.border, c.icon)}>
            {icon}
          </div>
        )}
      </div>
    </div>
  );
}
