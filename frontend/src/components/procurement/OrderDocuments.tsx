"use client";
// Delivery evidence and order documents: list, authenticated download and validated upload
// (PDF/JPEG/PNG/WebP, max 5 MB; records are append-only on the server).
import { useRef, useState } from "react";
import { FileText, Paperclip, Upload } from "lucide-react";
import { newIdempotencyKey } from "@/lib/api";
import { formatJalaliDateTime } from "@/lib/procurement/jalali";
import { cx } from "./ui";
import s from "./proc.module.css";

export type OrderDoc = { id: number; kind: string; kind_fa: string; filename: string; content_type: string; size_bytes: number; uploader: string;
  uploader_side: "supplier" | "buyer"; destination_index: number | null; note: string | null; created_at: string; url: string };

export function OrderDocuments({ token, docs, uploadPath, destinations, onUploaded }: {
  token: string; docs: OrderDoc[]; uploadPath?: string; destinations?: { index: number; label: string }[]; onUploaded?: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState("delivery_evidence"), [dest, setDest] = useState(""), [busy, setBusy] = useState(false), [msg, setMsg] = useState("");
  const open = async (d: OrderDoc) => {
    const r = await fetch(d.url, { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) { setMsg("دریافت سند ناموفق بود"); return; }
    const url = URL.createObjectURL(await r.blob());
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  };
  const upload = async (file: File) => {
    if (file.size > 5 * 1024 * 1024) { setMsg("حجم فایل باید حداکثر ۵ مگابایت باشد"); return; }
    setBusy(true); setMsg("");
    const fd = new FormData();
    fd.append("file", file); fd.append("kind", kind);
    if (dest) fd.append("destination_index", dest);
    try {
      const r = await fetch(`/api/v1${uploadPath}`, { method: "POST", body: fd, headers: { Authorization: `Bearer ${token}`, "Idempotency-Key": newIdempotencyKey() } });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j?.error?.message ?? "بارگذاری ناموفق بود");
      setMsg("سند ثبت شد."); onUploaded?.();
    } catch (e) { setMsg(e instanceof Error ? e.message : "بارگذاری ناموفق بود"); } finally { setBusy(false); if (input.current) input.current.value = ""; }
  };
  return (
    <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px dashed var(--line)" }}>
      <b className={s.small}><Paperclip size={14} /> اسناد و مدارک تحویل</b>
      {!docs.length ? <p className={s.small} style={{ color: "var(--muted)" }}>سندی ثبت نشده است.</p> : (
        <ul className={s.small} style={{ margin: "6px 0", display: "grid", gap: 4 }}>{docs.map((d) => (
          <li key={d.id} className={s.row}><button type="button" className={cx(s.btn, s.sm, s.ghost)} onClick={() => open(d)}><FileText size={14} /> {d.kind_fa}: {d.filename}</button>
            <span style={{ color: "var(--muted)" }}>{d.uploader_side === "supplier" ? "تأمین‌کننده" : "خریدار"} · {d.uploader} · {formatJalaliDateTime(d.created_at)}</span></li>))}</ul>
      )}
      {uploadPath && (
        <div className={s.row} style={{ marginTop: 6 }}>
          <select className={cx(s.select, s.inputSm)} style={{ width: "auto" }} aria-label="نوع سند" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="delivery_evidence">مدرک تحویل</option><option value="waybill">بارنامه</option><option value="supplier_invoice">صورت‌حساب تأمین‌کننده</option><option value="other">سایر</option></select>
          {destinations && destinations.length > 1 && <select className={cx(s.select, s.inputSm)} style={{ width: "auto" }} aria-label="مقصد" value={dest} onChange={(e) => setDest(e.target.value)}>
            <option value="">همه مقصدها</option>{destinations.map((d) => <option key={d.index} value={d.index}>{d.label}</option>)}</select>}
          <input ref={input} type="file" accept="application/pdf,image/jpeg,image/png,image/webp" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          <button type="button" className={cx(s.btn, s.sm)} disabled={busy} onClick={() => input.current?.click()}><Upload size={14} /> {busy ? "در حال بارگذاری…" : "بارگذاری سند"}</button>
        </div>
      )}
      {msg && <p className={s.small} role="status">{msg}</p>}
    </div>
  );
}
