// «ویترین سازمانی گرم» — shared layout primitives (2026-11-18).
// One visual body for every storefront/account/org page: compact 1280px container, section headers with an
// orange accent bar + «مشاهده همه», tinted bands (mint / sand / info / navy), coloured icon tiles, stat chips,
// consistent page headers with breadcrumb and guiding empty states. Presentation only — no data, no API.
import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Site container: max 1280px, compact gutters. */
export const ST_W = "mx-auto w-full max-w-[1280px] px-4 md:px-6 xl:px-8";
/** Card body: white, 16px radius, hairline + soft layered shadow (dark: hairline ring). */
export const ST_CARD = "rounded-xl bg-st-surface-container-lowest shadow-st-card";

export type Tone = "navy" | "brand" | "accent" | "mint" | "sand" | "info" | "plain";

export function StIcon({ name, className = "", fill = false }: { name: string; className?: string; fill?: boolean }) {
  return <span aria-hidden className={cn("material-symbols-outlined", fill && "icon-fill", className)}>{name}</span>;
}

const TILE: Record<Tone, string> = {
  navy: "bg-st-navy text-white",
  brand: "bg-st-secondary-fixed text-st-secondary",
  accent: "bg-st-tertiary-fixed text-st-on-tertiary-container",
  mint: "bg-st-mint text-st-mint-ink",
  sand: "bg-st-sand text-st-sand-ink",
  info: "bg-st-info text-st-secondary",
  plain: "bg-st-surface-container-low text-st-primary",
};
/** Rotating tones so a row of tiles reads as a coloured set instead of a grey list. */
export const TONE_CYCLE: Tone[] = ["brand", "accent", "mint", "sand", "info", "navy"];

export function IconTile({ icon, tone = "brand", size = "md", className = "" }: { icon: string; tone?: Tone; size?: "sm" | "md" | "lg"; className?: string }) {
  const s = size === "sm" ? "h-8 w-8 rounded-lg text-[18px]" : size === "lg" ? "h-14 w-14 rounded-xl text-[28px]" : "h-11 w-11 rounded-xl text-[22px]";
  return <span className={cn("flex shrink-0 items-center justify-center", TILE[tone], s, className)}><StIcon name={icon} className="text-[length:inherit]" /></span>;
}

const BAND: Record<Tone, string> = {
  navy: "bg-st-navy text-white",
  brand: "bg-st-secondary-fixed",
  accent: "bg-st-tertiary-fixed",
  mint: "bg-st-mint",
  sand: "bg-st-sand",
  info: "bg-st-info",
  plain: "bg-st-surface-container-lowest",
};
/** Full-width tinted band that separates page sections. */
export function Band({ tone = "mint", className = "", children, ...rest }: { tone?: Tone; className?: string; children: ReactNode } & React.HTMLAttributes<HTMLElement>) {
  return <section className={cn("w-full", BAND[tone], className)} {...rest}>{children}</section>;
}

/** Section title row: orange accent bar, optional eyebrow, title and a «مشاهده همه» link. */
export function SectionHeader({ title, eyebrow, href, linkLabel = "مشاهده همه", icon, id, onNavy = false, className = "", extra }: {
  title: ReactNode; eyebrow?: ReactNode; href?: string; linkLabel?: string; icon?: string; id?: string; onNavy?: boolean; className?: string; extra?: ReactNode;
}) {
  return (
    <div className={cn("mb-3 flex items-end justify-between gap-3 md:mb-4", className)}>
      <div className="flex min-w-0 items-center gap-2.5">
        <span aria-hidden className="h-7 w-1.5 shrink-0 rounded-full bg-st-accent md:h-8" />
        <div className="flex min-w-0 flex-col">
          {eyebrow && <span className={cn("flex items-center gap-1 text-st-label-md", onNavy ? "text-st-on-navy-muted" : "text-st-secondary")}>{icon && <StIcon name={icon} className="text-[16px]" />}{eyebrow}</span>}
          <h2 id={id} className={cn("truncate text-st-title-lg font-extrabold md:text-st-headline-md", onNavy ? "text-white" : "text-st-primary")}>{title}</h2>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {extra}
        {href && <Link href={href} className={cn("inline-flex h-8 items-center gap-1 rounded-full px-3 text-st-label-md font-semibold transition-colors",
          onNavy ? "bg-white/10 text-white hover:bg-white/20" : "bg-st-secondary-fixed text-st-secondary hover:bg-st-secondary hover:text-white")}>
          <span>{linkLabel}</span><StIcon name="arrow_back" className="text-[16px]" /></Link>}
      </div>
    </div>
  );
}

/** Section = container + header + body, optionally on a tinted band. */
export function Section({ title, eyebrow, href, linkLabel, icon, id, band, className = "", bodyClassName = "", children, extra, ...rest }: {
  title?: ReactNode; eyebrow?: ReactNode; href?: string; linkLabel?: string; icon?: string; id?: string; band?: Tone; className?: string; bodyClassName?: string; children: ReactNode; extra?: ReactNode;
} & Omit<React.HTMLAttributes<HTMLElement>, "title">) {
  const inner = <div className={cn(ST_W, "py-5 md:py-8", bodyClassName)}>
    {title && <SectionHeader title={title} eyebrow={eyebrow} href={href} linkLabel={linkLabel} icon={icon} id={id} onNavy={band === "navy"} extra={extra} />}
    {children}
  </div>;
  return band ? <Band tone={band} className={className} aria-labelledby={id} {...rest}>{inner}</Band>
    : <section className={className} aria-labelledby={id} {...rest}>{inner}</section>;
}

/** Compact stat / value chip (hero KPIs, page summaries). `onNavy` = translucent on dark panels. */
export function StatChip({ icon, value, label, tone = "brand", href, onNavy = false, className = "" }: {
  icon: string; value: ReactNode; label?: ReactNode; tone?: Tone; href?: string; onNavy?: boolean; className?: string;
}) {
  const body = <>
    <IconTile icon={icon} tone={onNavy ? "accent" : tone} size="sm" className={onNavy ? "bg-white/10 text-st-accent" : ""} />
    <span className="flex min-w-0 flex-col leading-tight">
      <span className={cn("truncate text-st-label-lg font-bold", onNavy ? "text-white" : "text-st-primary")}>{value}</span>
      {label && <span className={cn("truncate text-st-label-sm", onNavy ? "text-st-on-navy-muted" : "text-st-on-surface-variant")}>{label}</span>}
    </span>
  </>;
  const cls = cn("flex min-w-0 items-center gap-2 rounded-xl p-2 pl-3 transition-colors",
    onNavy ? "bg-white/[0.06] ring-1 ring-white/10 hover:bg-white/10" : "bg-st-surface-container-lowest shadow-st-card hover:shadow-st-raise", className);
  return href ? <Link href={href} className={cls}>{body}</Link> : <div className={cls}>{body}</div>;
}

export type Crumb = [label: string, href?: string];
/** Consistent page header: breadcrumb, icon tile, title, subtitle, actions — on a soft sand band. */
export function PageHeader({ title, subtitle, crumbs = [], icon, actions, tone = "sand", className = "", innerClassName = "" }: {
  title: ReactNode; subtitle?: ReactNode; crumbs?: Crumb[]; icon?: string; actions?: ReactNode; tone?: Tone; className?: string; innerClassName?: string;
}) {
  return (
    <Band tone={tone} className={cn("border-b border-st-hairline-border", className)}>
      <div className={cn(ST_W, "flex flex-col gap-2 py-3 md:py-5", innerClassName)}>
        {crumbs.length > 0 && <nav aria-label="مسیر صفحه" className="flex flex-wrap items-center gap-1 text-st-label-md text-st-on-surface-variant">
          <Link href="/" className="flex items-center hover:text-st-secondary"><StIcon name="home" className="text-[16px]" /><span className="sr-only">خانه</span></Link>
          {crumbs.map(([l, h], i) => <span key={i} className="flex items-center gap-1">
            <StIcon name="chevron_left" className="text-[16px] text-st-outline" />
            {h ? <Link href={h} className="hover:text-st-secondary">{l}</Link> : <span className="font-semibold text-st-primary">{l}</span>}
          </span>)}
        </nav>}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            {icon && <IconTile icon={icon} tone="navy" />}
            <div className="flex min-w-0 flex-col">
              <h1 className="text-st-title-lg font-extrabold text-st-primary md:text-st-headline-md">{title}</h1>
              {subtitle && <p className="text-st-body-sm text-st-on-surface-variant">{subtitle}</p>}
            </div>
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      </div>
    </Band>
  );
}

/** Empty state that always points at the next useful action. */
export function EmptyState({ icon, title, body, action, secondary, className = "" }: {
  icon: string; title: ReactNode; body?: ReactNode; action?: { href: string; label: string; icon?: string }; secondary?: { href: string; label: string }; className?: string;
}) {
  return (
    <div className={cn(ST_CARD, "flex flex-col items-center gap-3 px-6 py-10 text-center", className)}>
      <span className="relative flex h-16 w-16 items-center justify-center rounded-2xl bg-st-info text-st-secondary">
        <StIcon name={icon} className="text-[32px]" />
        <span aria-hidden className="absolute -left-1 -top-1 h-3 w-3 rounded-full bg-st-accent" />
      </span>
      <h2 className="text-st-title-lg font-bold text-st-primary">{title}</h2>
      {body && <p className="max-w-md text-st-body-md text-st-on-surface-variant">{body}</p>}
      <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
        {action && <Link href={action.href} className="inline-flex h-11 items-center gap-1.5 rounded-full bg-st-secondary px-5 text-st-label-lg font-bold text-white shadow-st-card hover:bg-st-navy">
          {action.icon && <StIcon name={action.icon} className="text-[18px]" />}{action.label}</Link>}
        {secondary && <Link href={secondary.href} className="inline-flex h-11 items-center rounded-full bg-st-surface-container-low px-5 text-st-label-lg font-semibold text-st-primary hover:bg-st-surface-container">{secondary.label}</Link>}
      </div>
    </div>
  );
}

/** Horizontal step indicator (checkout etc.). `current` is 0-based; steps before it are done. */
export function StepBar({ steps, current, className = "" }: { steps: { label: string; icon: string }[]; current: number; className?: string }) {
  return (
    <ol className={cn("flex items-center gap-1.5", className)} aria-label="مراحل">
      {steps.map((s, i) => {
        const done = i < current, on = i === current;
        return <li key={s.label} className="flex flex-1 items-center gap-1.5" aria-current={on ? "step" : undefined}>
          <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[16px] transition-colors",
            done ? "bg-st-secondary text-white" : on ? "bg-st-navy text-white ring-4 ring-st-accent/25" : "bg-st-surface-container text-st-outline")}>
            <StIcon name={done ? "check" : s.icon} className="text-[18px]" />
          </span>
          <span className={cn("whitespace-nowrap text-st-label-md", on ? "font-bold text-st-primary" : done ? "text-st-secondary" : "text-st-outline")}>{s.label}</span>
          {i < steps.length - 1 && <span aria-hidden className={cn("mx-1 h-0.5 flex-1 rounded-full", done ? "bg-st-secondary" : "bg-st-surface-container")} />}
        </li>;
      })}
    </ol>
  );
}
