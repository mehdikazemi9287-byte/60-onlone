"use client";

// Payment plan, finance approval, collection, refund and supplier settlement
// for one purchase order. Every action is a record confirmed by finance under
// the organization's approved policy; nothing here moves money. TEST-policy
// records are labelled as such.

import { useMemo, useState } from "react";
import { Banknote, Check, Plus, Receipt, Trash2, X } from "lucide-react";
import { FIN_EVENT, PART_STATUS, PAY_METHOD, PLAN_STATUS, money, type Order, type PayMethod, type Workspace } from "@/lib/procurement/api";
import { formatJalali, formatJalaliDateTime } from "@/lib/procurement/jalali";
import { Chip, Notice, cx } from "./ui";
import s from "./proc.module.css";

type Act = (label: string, path: string, body?: unknown, idem?: boolean) => Promise<boolean>;
type Row = { method: PayMethod; toman: string; due: string; ref: string };

export default function CaseFinance({ ws, po, base, act, busy }: { ws: Workspace; po: Order; base: string; act: Act; busy: boolean }) {
  const f = po.finance, cur = ws.organization.currency, p = ws.permissions;
  const isFinance = ["organization_finance", "organization_admin"].includes(p.role);
  const canPlan = p.can_procure || isFinance;
  const url = `${base}/purchase-orders/${po.id}`;
  // Every financial action carries a fresh Idempotency-Key; a network retry cannot record it twice.
  const fact = (label: string, path: string, body?: unknown) => act(label, path, body, true);
  const total = po.grand_total_minor ?? 0;
  const methods = f.policy?.methods ?? [];
  const [rows, setRows] = useState<Row[]>(() => f.plan?.parts.map((x) => ({ method: x.method, toman: String(x.amount_minor / 10), due: x.due_date ?? "", ref: x.reference ?? "" }))
    ?? [{ method: methods[0] ?? "cash", toman: String(total / 10), due: "", ref: "" }]);
  const [note, setNote] = useState("");
  const [refs, setRefs] = useState<Record<number, string>>({});
  const [refund, setRefund] = useState({ toman: "", note: "" });
  const [settleRef, setSettleRef] = useState("");
  const sum = useMemo(() => rows.reduce((a, r) => a + Math.round(Number(r.toman || 0) * 10), 0), [rows]);
  const editable = canPlan && (!f.plan || ["draft", "rejected"].includes(f.plan.status)) && po.status !== "draft";

  if (!f.policy) {
    return <Notice icon={<Banknote />}>سیاست پرداخت این سازمان تصویب نشده است؛ ثبت برنامه پرداخت، وصول و تسویه تا تصویب سیاست غیرفعال است. هیچ تراکنشی شبیه‌سازی نمی‌شود.</Notice>;
  }
  const envChip = <Chip tone={f.policy.environment === "test" ? "warn" : "ok"} dot>{f.policy.environment === "test" ? "محیط آزمایشی (TEST)" : "سیاست مصوب (REAL)"}</Chip>;
  const setRow = (i: number, patch: Partial<Row>) => setRows((x) => x.map((r, k) => (k === i ? { ...r, ...patch } : r)));
  const payload = () => ({ parts: rows.map((r) => ({ method: r.method, amount_minor: Math.round(Number(r.toman || 0) * 10),
    due_date: ["cheque", "bill"].includes(r.method) ? r.due || null : null, reference: r.ref.trim() || null })) });

  return (
    <div className={s.stack} style={{ gap: 12 }}>
      <div className={s.spread}>
        <b className={s.row} style={{ gap: 6 }}><Receipt size={16} /> پرداخت سفارش {po.po_number}</b>
        <div className={s.row}>{envChip}{f.plan && <Chip tone={f.plan.status === "approved" ? "ok" : f.plan.status === "rejected" ? "bad" : "info"} dot>{PLAN_STATUS[f.plan.status]}</Chip>}</div>
      </div>
      <div className={s.grid4}>
        {[["مبلغ سفارش", money(total, cur)], ["وصول‌شده", money(f.collected_minor, cur)], ["مانده", money(Math.max(0, total - f.collected_minor), cur)],
          ["بازپرداخت", money(f.refunded_minor, cur)]].map(([k, v]) => (
          <div key={k} className={s.sumTile}><span>{k}</span><b className={s.num}>{v}</b></div>
        ))}
      </div>

      {editable && (
        <div className={s.cardFlat}>
          <div className={s.spread} style={{ marginBottom: 8 }}>
            <b>برنامه پرداخت {rows.length > 1 ? "(ترکیبی)" : ""}</b>
            <span className={cx(s.small)} style={{ color: sum === total ? "var(--green)" : "var(--red)" }}>جمع: {money(sum, cur)} از {money(total, cur)}</span>
          </div>
          {f.plan?.status === "rejected" && f.plan.decision_note && <Notice tone="bad" icon={<X />}>علت رد مالی: {f.plan.decision_note}</Notice>}
          {rows.map((r, i) => (
            <div key={i} className={s.row} style={{ marginTop: 8, alignItems: "flex-end" }}>
              <label className={s.field} style={{ width: 130 }}>روش
                <select className={cx(s.select, s.inputSm)} value={r.method} onChange={(e) => setRow(i, { method: e.target.value as PayMethod })}>
                  {methods.map((m) => <option key={m} value={m}>{PAY_METHOD[m]}</option>)}
                </select>
              </label>
              <label className={s.field} style={{ width: 150 }}>مبلغ (تومان)
                <input className={cx(s.input, s.inputSm)} type="number" min={0} value={r.toman} onChange={(e) => setRow(i, { toman: e.target.value })} />
              </label>
              {["cheque", "bill"].includes(r.method) && (
                <>
                  <label className={s.field} style={{ width: 150 }}>سررسید<input className={cx(s.input, s.inputSm)} type="date" value={r.due} onChange={(e) => setRow(i, { due: e.target.value })} /></label>
                  <label className={s.field} style={{ width: 150 }}>شماره/مرجع<input className={cx(s.input, s.inputSm)} value={r.ref} onChange={(e) => setRow(i, { ref: e.target.value })} /></label>
                </>
              )}
              {rows.length > 1 && <button type="button" className={cx(s.btn, s.sm, s.icon, s.danger)} aria-label="حذف بخش" onClick={() => setRows((x) => x.filter((_, k) => k !== i))}><Trash2 /></button>}
            </div>
          ))}
          <div className={s.row} style={{ marginTop: 10 }}>
            {rows.length < 12 && <button type="button" className={cx(s.btn, s.sm)} onClick={() => setRows((x) => [...x, { method: methods[0] ?? "cash", toman: String(Math.max(0, total - sum) / 10), due: "", ref: "" }])}><Plus /> بخش دیگر (ترکیبی)</button>}
            <button type="button" className={cx(s.btn, s.sm)} disabled={busy || sum !== total} onClick={() => fact("plan", `${url}/payment-plan`, payload())}>ذخیره برنامه</button>
            {f.plan?.status === "draft" && <button type="button" className={cx(s.btn, s.sm, s.primary)} disabled={busy} onClick={() => fact("submitPlan", `${url}/payment-plan/submit`)}>ارسال برای تأیید مالی</button>}
          </div>
          {f.policy.credit_limit_minor != null && methods.includes("credit") && <p className={s.small} style={{ color: "var(--muted)", marginTop: 6 }}>سقف اعتبار مصوب: {money(f.policy.credit_limit_minor, cur)}؛ مصرف اعتبار فقط پس از تأیید مالی لحاظ می‌شود.</p>}
        </div>
      )}

      {f.plan?.status === "submitted" && (
        isFinance ? (
          <div className={s.cardFlat}>
            <b>تأیید مالی</b>
            <div className={s.row} style={{ marginTop: 8 }}>
              <input className={cx(s.input, s.inputSm)} style={{ flex: 1, minWidth: 180 }} placeholder="توضیح (برای رد الزامی)" value={note} onChange={(e) => setNote(e.target.value)} />
              <button type="button" className={cx(s.btn, s.sm, s.primary)} disabled={busy} onClick={() => fact("approvePlan", `${url}/payment-plan/decision`, { action: "approve", note: note || null })}><Check /> تأیید</button>
              <button type="button" className={cx(s.btn, s.sm, s.danger)} disabled={busy || !note.trim()} onClick={() => fact("rejectPlan", `${url}/payment-plan/decision`, { action: "reject", note })}><X /> رد</button>
            </div>
            <p className={s.small} style={{ color: "var(--muted)" }}>ثبت‌کنندهٔ برنامه نمی‌تواند همان را تأیید کند.</p>
          </div>
        ) : <Notice tone="info" icon={<Receipt />}>برنامه پرداخت در انتظار تأیید واحد مالی است.</Notice>
      )}

      {f.plan && f.plan.status !== "draft" && (
        <div className={s.tableWrap}>
          <table className={cx(s.table, s.cards)}>
            <thead><tr><th>روش</th><th>مبلغ</th><th>سررسید / مرجع</th><th>وضعیت</th><th /></tr></thead>
            <tbody>
              {f.plan.parts.map((x) => {
                const instrument = ["cheque", "bill"].includes(x.method);
                return (
                  <tr key={x.id}>
                    <td data-label="روش"><b>{PAY_METHOD[x.method]}</b></td>
                    <td data-label="مبلغ" className={s.num}>{money(x.amount_minor, cur)}</td>
                    <td data-label="سررسید / مرجع" className={s.small}>{x.due_date ? formatJalali(x.due_date) : "—"}{x.reference ? ` · ${x.reference}` : ""}</td>
                    <td data-label="وضعیت"><Chip tone={x.status === "cleared" || (x.status === "received" && !instrument) ? "ok" : x.status === "bounced" ? "bad" : "info"} dot>{PART_STATUS[x.status]}</Chip></td>
                    <td className={s.full}>
                      {isFinance && f.plan!.status === "approved" && (
                        <div className={s.row}>
                          {x.status === "pending" && <>
                            {x.method === "cash" && <input className={cx(s.input, s.inputSm)} style={{ width: 140 }} placeholder="شماره پیگیری بانکی" value={refs[x.id] ?? ""} onChange={(e) => setRefs({ ...refs, [x.id]: e.target.value })} />}
                            <button type="button" className={cx(s.btn, s.sm)} disabled={busy || (x.method === "cash" && !refs[x.id]?.trim())} onClick={() => fact("received", `${url}/payment-parts/${x.id}/received`, { reference: refs[x.id] || null })}>ثبت دریافت</button>
                          </>}
                          {x.status === "received" && instrument && <>
                            <button type="button" className={cx(s.btn, s.sm)} disabled={busy} onClick={() => fact("cleared", `${url}/payment-parts/${x.id}/cleared`, {})}>وصول شد</button>
                            <button type="button" className={cx(s.btn, s.sm, s.danger)} disabled={busy} onClick={() => fact("bounced", `${url}/payment-parts/${x.id}/bounced`, {})}>برگشت خورد</button>
                          </>}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {isFinance && f.plan?.status === "approved" && (
        <div className={s.grid2}>
          <div className={s.cardFlat}>
            <b>بازپرداخت (مرجوعی/اصلاحیه)</b>
            <div className={s.row} style={{ marginTop: 8 }}>
              <input className={cx(s.input, s.inputSm)} style={{ width: 130 }} type="number" min={0} placeholder="مبلغ (تومان)" value={refund.toman} onChange={(e) => setRefund({ ...refund, toman: e.target.value })} />
              <input className={cx(s.input, s.inputSm)} style={{ flex: 1, minWidth: 120 }} placeholder="علت" value={refund.note} onChange={(e) => setRefund({ ...refund, note: e.target.value })} />
              <button type="button" className={cx(s.btn, s.sm)} disabled={busy || !Number(refund.toman) || !refund.note.trim()} onClick={async () => { if (await fact("refund", `${url}/refunds`, { amount_minor: Math.round(Number(refund.toman) * 10), note: refund.note.trim() })) setRefund({ toman: "", note: "" }); }}>ثبت</button>
            </div>
          </div>
          <div className={s.cardFlat}>
            <b>تسویه با تأمین‌کننده</b>
            {f.settlement ? (
              <p className={s.small} style={{ marginTop: 8 }}><Chip tone="ok" dot>تسویه شد</Chip> {money(f.settlement.amount_minor, cur)} · {f.settlement.reference} · {formatJalaliDateTime(f.settlement.created_at)}</p>
            ) : (
              <div className={s.row} style={{ marginTop: 8 }}>
                <input className={cx(s.input, s.inputSm)} style={{ flex: 1, minWidth: 140 }} placeholder="مرجع تسویه (شماره سند/انتقال)" value={settleRef} onChange={(e) => setSettleRef(e.target.value)} />
                <button type="button" className={cx(s.btn, s.sm, s.primary)} disabled={busy || !f.fully_paid || !settleRef.trim()} onClick={() => fact("settle", `${url}/settlement`, { reference: settleRef.trim() })}>ثبت تسویه</button>
              </div>
            )}
            {!f.settlement && !f.fully_paid && <p className={s.small} style={{ color: "var(--muted)" }}>پس از وصول کامل همهٔ بخش‌ها فعال می‌شود.</p>}
          </div>
        </div>
      )}

      {f.ledger.length > 0 && (
        <div className={s.timeline}>
          {f.ledger.slice().reverse().map((e, i) => (
            <div key={i} className={s.tItem}><span className={s.tDot} /><div><b>{FIN_EVENT[e.kind] ?? e.kind}</b> {e.amount_minor ? `· ${money(e.amount_minor, cur)}` : ""}{e.environment === "test" && <span className={s.small} style={{ color: "var(--amber)" }}> · TEST</span>}{e.actor && <span className={s.muted}> · {e.actor}</span>}{e.note && <div className={s.small} style={{ color: "var(--ink2)" }}>{e.note}</div>}</div><time>{formatJalaliDateTime(e.created_at)}</time></div>
          ))}
        </div>
      )}
    </div>
  );
}
