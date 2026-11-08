"use client";

import { useEffect, type ReactNode } from "react";
import { Minus, Plus, X } from "lucide-react";
import { toPersianNum } from "@/lib/utils";
import s from "./proc.module.css";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export type Tone = "ok" | "warn" | "bad" | "info" | "violet" | "muted";
export function Chip({ tone = "muted", dot, children, title }: { tone?: Tone; dot?: boolean; children: ReactNode; title?: string }) {
  return <span title={title} className={cx(s.chip, tone !== "muted" && s[tone], dot && s.dot)}>{children}</span>;
}

export function Drawer({ open, title, onClose, children, footer }: { open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <>
      <div className={s.scrim} onClick={onClose} aria-hidden />
      <aside className={s.drawer} role="dialog" aria-modal="true" aria-label={title} dir="rtl">
        <div className={s.drawerHead}>
          <h3>{title}</h3>
          <button type="button" className={cx(s.btn, s.ghost, s.icon)} onClick={onClose} aria-label="بستن"><X /></button>
        </div>
        <div className={s.drawerBody}>{children}</div>
        {footer && <div className={s.drawerFoot}>{footer}</div>}
      </aside>
    </>
  );
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className={s.empty}>
      {icon}
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function Notice({ tone = "warn", icon, children }: { tone?: "warn" | "info" | "bad"; icon?: ReactNode; children: ReactNode }) {
  return <div className={cx(s.notice, tone === "info" && s.noticeInfo, tone === "bad" && s.noticeBad)}>{icon}<div>{children}</div></div>;
}

export function Journey({ steps, current, compact }: { steps: string[]; current: number; compact?: boolean }) {
  return (
    <div className={cx(s.journey, compact && s.journeyCompact)} aria-label="مراحل">
      {steps.map((label, i) => (
        <div key={label} className={cx(s.jStep, i < current && s.jDone, i === current && s.jNow)} aria-current={i === current ? "step" : undefined}>
          <i />{label}
        </div>
      ))}
    </div>
  );
}

export function QtyStepper({ value, onChange, label, min = 1 }: { value: number; onChange: (v: number) => void; label: string; min?: number }) {
  return (
    <span className={s.qty}>
      <button type="button" aria-label={`افزایش ${label}`} onClick={() => onChange(value + 1)}><Plus size={14} /></button>
      <input type="number" inputMode="numeric" min={min} value={value} aria-label={label}
        onChange={(e) => onChange(Math.max(min, Math.floor(Number(e.target.value)) || min))} />
      <button type="button" aria-label={`کاهش ${label}`} onClick={() => onChange(Math.max(min, value - 1))} disabled={value <= min}><Minus size={14} /></button>
    </span>
  );
}

export const n = (v: number | null | undefined) => (v == null ? "—" : toPersianNum(v.toLocaleString("en-US")));
