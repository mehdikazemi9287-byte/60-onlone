"use client";
import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { ApiError, apiRequest, newIdempotencyKey } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import css from "./operations.module.css";

type Scope = { id: number; display_name: string; capabilities: string[] };
type Case = { id: number; purchase_request_id: number; assignee_user_id: number | null; status: string; version: number };
type Detail = Case & { capabilities: string[]; purchase_request: { request_number: string; title: string; status: string; needed_by_date: string | null; substitution_policy: string; destinations: { label?: string; province: string; city: string; address: string; allocations: { item_index: number; quantity: number }[] }[]; items: { id: number; master_product_id: number | null; free_text_description: string | null; quantity: number; unit: string | null; notes: string | null }[] }; events: { id: number; actor_user_id: number; action: string; reason: string; created_at: string }[] };
type Attempt = { path: string; body: string; key: string; scope: string };
const states: Record<string, string> = { unassigned: "بدون مسئول", triage: "بررسی اولیه", sourcing: "در حال تأمین", waiting_customer: "منتظر پاسخ مشتری", blocked: "متوقف", closed: "بسته" };
const transitions: Record<string, string[]> = { unassigned: [], triage: ["sourcing", "waiting_customer", "blocked", "closed"], sourcing: ["waiting_customer", "blocked", "closed"], waiting_customer: ["triage", "sourcing", "blocked", "closed"], blocked: ["triage", "sourcing", "waiting_customer", "closed"], closed: [] };

export default function OperationsRequests() {
  const { token, user, loading } = useAuth();
  const [scopes, setScopes] = useState<Scope[]>([]), [org, setOrg] = useState("");
  const [rows, setRows] = useState<Case[]>([]), [cursor, setCursor] = useState<number | null>(null);
  const [caseId, setCaseId] = useState<number | null>(null), [detail, setDetail] = useState<Detail | null>(null);
  const [discoveryRetry, setDiscoveryRetry] = useState(0), [detailReading, setDetailReading] = useState(false);
  const [refresh, setRefresh] = useState(0), [reading, setReading] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [requestId, setRequestId] = useState(""), [assignee, setAssignee] = useState(""), [reason, setReason] = useState(""), [nextState, setNextState] = useState("");
  const [pending, setPending] = useState<Attempt | null>(null);
  const lock = useRef(false), context = `${token ?? ""}:${org}`, current = useRef(context);
  current.current = context;
  const manager = scopes.find(s => String(s.id) === org)?.capabilities.includes("case_manager");
  const base = `/internal/organizations/${org}/cases`;
  useEffect(() => {
    const c = new AbortController();
    setScopes([]); setOrg(""); setRows([]); setDetail(null); setCaseId(null); setPending(null); setError(""); setNotice(""); setReason(""); setAssignee(""); setRequestId("");
    if (!token) return () => c.abort();
    setReading(true);
    apiRequest<{ items: Scope[] }>("/internal/organizations", { token, signal: c.signal })
      .then(r => { if (!c.signal.aborted) { setScopes(r.items); const query = new URLSearchParams(window.location.search); const requested = query.get("org");
        if (requested && !r.items.some(s => String(s.id) === requested)) { setError("مجوز عملیات این سازمان را ندارید"); return; }
        setOrg(requested || (r.items.length ? String(r.items[0].id) : ""));
        const target = Number(query.get("case")); if (Number.isSafeInteger(target) && target > 0) setCaseId(target); } })
      .catch(e => { if (!c.signal.aborted) setError(`دریافت مجوز عملیات ناموفق است: ${e.message}`); })
      .finally(() => { if (!c.signal.aborted) setReading(false); });
    return () => c.abort();
  }, [token, discoveryRetry]);
  useEffect(() => {
    const c = new AbortController(); setRows([]); setCursor(null); setDetail(null);
    if (!token || !org) return () => c.abort();
    setReading(true);
    apiRequest<{ items: Case[]; next_cursor: number | null }>(base, { token, signal: c.signal })
      .then(r => { if (!c.signal.aborted) { setRows(r.items); setCursor(r.next_cursor); } })
      .catch(e => { if (!c.signal.aborted) setError(e.message); })
      .finally(() => { if (!c.signal.aborted) setReading(false); });
    return () => c.abort();
  }, [token, org, base, refresh]);
  useEffect(() => {
    const c = new AbortController(); setDetail(null); setNextState(""); setReason(""); setAssignee(""); setDetailReading(false);
    if (!token || !org || caseId === null) return () => c.abort();
    setDetailReading(true);
    apiRequest<{ case: Detail }>(`${base}/${caseId}`, { token, signal: c.signal })
      .then(r => { if (!c.signal.aborted) setDetail(r.case); })
      .catch(e => { if (!c.signal.aborted) setError(e.message); })
      .finally(() => { if (!c.signal.aborted) setDetailReading(false); });
    return () => c.abort();
  }, [token, org, base, caseId, refresh]);
  useEffect(() => { if (org) { const u = new URL(window.location.href); u.searchParams.set("org", org); if (caseId) u.searchParams.set("case", String(caseId)); else u.searchParams.delete("case"); window.history.replaceState(null, "", u); } }, [org, caseId]);
  function changeOrg(value: string) { current.current = `${token ?? ""}:${value}`; setOrg(value); setCaseId(null); setDetail(null); setRows([]); setError(""); setNotice(""); setReason(""); setAssignee(""); setRequestId(""); }
  async function send(a: Attempt) {
    if (!token || lock.current || a.scope !== context) return;
    lock.current = true; setBusy(true); setPending(a); setError(""); setNotice("");
    try {
      const r = await apiRequest<{ case: Case }>(a.path, { token, method: "POST", body: a.body, headers: { "Idempotency-Key": a.key } });
      if (current.current !== a.scope) return;
      setPending(null); setCaseId(r.case.id); setReason(""); setNotice("اقدام ثبت شد؛ اطلاعات پرونده به‌روز می‌شود."); setRefresh(x => x + 1);
    } catch (e) {
      if (current.current !== a.scope) return;
      setError(e instanceof Error ? e.message : "ارتباط برقرار نشد");
      if (e instanceof ApiError && [400, 401, 403, 404, 409, 422].includes(e.status)) {
        setPending(null);
        if (e.status === 403 || e.status === 401) { setDetail(null); setRows([]); }
      }
    } finally { lock.current = false; setBusy(false); }
  }
  function mutate(e: FormEvent, action: "create" | "assign" | "transition") {
    e.preventDefault(); if (pending || busy || !org || (action !== "create" && !detail)) return;
    const data = action === "create" ? { purchase_request_id: Number(requestId), reason } : action === "assign" ? { assignee_user_id: Number(assignee), expected_version: detail!.version, reason } : { status: nextState, expected_version: detail!.version, reason };
    void send({ path: action === "create" ? base : `${base}/${detail!.id}/${action}`, body: JSON.stringify(data), key: newIdempotencyKey(), scope: context });
  }
  async function more() {
    if (!token || cursor === null || lock.current) return;
    const scope = context; lock.current = true; setBusy(true);
    try { const r = await apiRequest<{ items: Case[]; next_cursor: number | null }>(`${base}?after=${cursor}`, { token }); if (scope === current.current) { setRows(old => [...old, ...r.items.filter(x => !old.some(o => o.id === x.id))]); setCursor(r.next_cursor); } }
    catch (e) { if (scope === current.current) setError(e instanceof Error ? e.message : "دریافت ناموفق بود"); }
    finally { lock.current = false; setBusy(false); }
  }
  if (loading) return <div className={css.shell} role="status">در حال بررسی حساب…</div>;
  if (!token || !user) return <div className={css.shell}><h1>صندوق عملیات 60Online</h1><Link href="/login?next=/operations/requests">ورود به حساب</Link></div>;
  return <section className={css.shell} dir="rtl">
    <header className={css.header}><strong>60Online / صندوق عملیات</strong><p>دسترسی بر پایه مجوز فعال عملیات داخلی</p></header>
    <h1>صندوق عملیات 60Online</h1>
    {error && <div role="alert" className={css.error}>{error}<Button disabled={busy || !!pending} onClick={() => { setError(""); if (!org) setDiscoveryRetry(x => x + 1); else setRefresh(x => x + 1); }}>تلاش مجدد</Button><a href="/operations/requests">انتخاب دوباره سازمان</a></div>}{notice && <p role="status">{notice}</p>}
    {(reading || detailReading) && <p role="status">در حال دریافت اطلاعات…</p>}
    {!reading && !error && !scopes.length && <section className={css.card}><h2>مجوز عملیات فعال ندارید</h2><p>عضویت مشتری یا مدیریت سازمان، مجوز عملیات داخلی ایجاد نمی‌کند.</p></section>}
    {!!scopes.length && <>
      <label>سازمان<select aria-label="سازمان عملیات" value={org} disabled={busy || !!pending} onChange={e => changeOrg(e.target.value)}>{scopes.map(s => <option value={s.id} key={s.id}>{s.display_name}</option>)}</select></label>
      <section className={css.card}><h2>پرونده‌های مجاز</h2><Button variant="outline" disabled={busy || !!pending || reading} onClick={() => { setError(""); setRefresh(x => x + 1); }}>به‌روزرسانی</Button>{!reading && !error && !rows.length && <p>پرونده‌ای برای نمایش وجود ندارد.</p>}{rows.map(r => <Button variant="outline" key={r.id} disabled={busy || !!pending} onClick={() => setCaseId(r.id)}>پرونده {r.id} — {states[r.status]} — مسئول {r.assignee_user_id ?? "تعیین نشده"}</Button>)}{cursor !== null && <Button disabled={busy || !!pending} onClick={more}>نمایش بیشتر</Button>}</section>
      {pending && !busy && <section className={css.card}><p>نتیجه اقدام مشخص نیست؛ با همان شناسه دوباره نتیجه را دریافت کنید.</p><Button onClick={() => send(pending)}>دریافت نتیجه همان اقدام</Button></section>}
      {manager && <form className={css.card} onSubmit={e => mutate(e, "create")}><h2>دریافت و تعیین مسئول</h2><fieldset disabled={busy || !!pending}><Input label="شناسه درخواست واقعی" type="number" min={1} step={1} required value={requestId} onChange={e => setRequestId(e.target.value)} /><Input label="دلیل ایجاد پرونده" required maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} /><Button type="submit">ایجاد پرونده</Button></fieldset></form>}
      {detail && <section className={css.card}><h2>پرونده {detail.id} — {states[detail.status]}</h2><h3>{detail.purchase_request.title}</h3><p dir="ltr">{detail.purchase_request.request_number}</p><p>موعد: {detail.purchase_request.needed_by_date ?? "ثبت نشده"}</p><p>جایگزینی: {detail.purchase_request.substitution_policy === "disallow" ? "ممنوع" : "نیازمند تأیید مشتری"}</p>{detail.purchase_request.items.map((i,n) => <p key={i.id}>قلم {n+1}: {i.free_text_description ?? `کالای مرجع ${i.master_product_id}`} — {i.quantity} {i.unit}{i.notes ? ` / ${i.notes}` : ""}</p>)}{detail.purchase_request.destinations.map((d,n) => <div key={n}><h3>{d.label || `مقصد ${n+1}`}</h3><p>{d.province}، {d.city}، {d.address}</p><p>{d.allocations.map(a => `قلم ${a.item_index+1}: ${a.quantity}`).join(" / ")}</p></div>)}
        {detail.capabilities.includes("case_manager") && detail.status !== "closed" && <form onSubmit={e => mutate(e,"assign")}><fieldset disabled={busy || !!pending}><Input label="شناسه مسئول دارای مجوز" type="number" min={1} step={1} required value={assignee} onChange={e => setAssignee(e.target.value)} /><Input label="دلیل واگذاری" required maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} /><Button type="submit">واگذاری پرونده</Button></fieldset></form>}
        {!!transitions[detail.status]?.length && <form onSubmit={e => mutate(e,"transition")}><fieldset disabled={busy || !!pending}><label>وضعیت بعدی<select aria-label="وضعیت بعدی" required value={nextState} onChange={e => setNextState(e.target.value)}><option value="">انتخاب کنید</option>{transitions[detail.status].map(s => <option key={s} value={s}>{states[s]}</option>)}</select></label><Input label="دلیل تغییر وضعیت" required maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} /><Button type="submit">ثبت تغییر وضعیت</Button></fieldset></form>}
        <h2>ردپای تغییر</h2>{detail.events.map(e => <div key={e.id}><p>{e.created_at} — عامل {e.actor_user_id} — {({create:"ایجاد",assign:"واگذاری",transition:"تغییر وضعیت"} as Record<string,string>)[e.action] ?? e.action}</p><p>{e.reason}</p></div>)}
      </section>}
      <section className={css.card}><h2>تأمین و تحویل</h2><p>وضعیت پرونده صرفاً هماهنگی عملیات را ثبت می‌کند. ثبت خرید، پرداخت، تحویل و برگشت در این پنل فعال نیست.</p></section>
    </>}
  </section>;
}
