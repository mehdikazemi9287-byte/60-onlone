"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { apiRequest, newIdempotencyKey, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import styles from "./requests.module.css";

type Org = { id: number; display_name: string; currency: string; membership: { status: string; role: string } };
type Item = { kind: "text" | "catalog"; description: string; quantity: string; unit: string; notes: string };
type Destination = { label: string; province: string; city: string; address: string; quantities: string[] };
type RequestRecord = { id: number; organization_id: number; title: string; request_number: string; status: string; next_action: string; items?: { free_text_description: string | null; master_product_id: number | null; quantity: number; unit: string | null }[]; destinations?: { label: string | null; province: string; city: string; address: string; allocations: { item_index: number; quantity: number }[] }[] };
const item = (): Item => ({ kind: "text", description: "", quantity: "1", unit: "", notes: "" });
const destination = (count: number): Destination => ({ label: "", province: "", city: "", address: "", quantities: Array(count).fill("0") });
const statusLabels: Record<string, string> = { draft: "پیش‌نویس", submitted: "ارسال‌شده", under_review: "در حال بررسی", approved: "تأیید درخواست", sourcing: "در حال تأمین", quoted: "پیشنهاد ارائه‌شده", rejected: "ردشده", cancelled: "لغوشده", completed: "تکمیل‌شده", awarded: "انتخاب پیشنهاد" };

export default function OrganizationRequests() {
  const { token, user, loading } = useAuth();
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [selected, setSelected] = useState("");
  const [orgLoading, setOrgLoading] = useState(true);
  const [requests, setRequests] = useState<RequestRecord[]>([]);
  const [receipt, setReceipt] = useState<RequestRecord | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const [title, setTitle] = useState("");
  const [items, setItems] = useState<Item[]>([item()]);
  const [destinations, setDestinations] = useState<Destination[]>([destination(1)]);
  const [needed, setNeeded] = useState("");
  const [budget, setBudget] = useState("");
  const [substitution, setSubstitution] = useState("require_approval");
  const [attemptPending, setAttemptPending] = useState(false);
  const attempt = useRef<{ key: string; body: string; org: string } | null>(null);
  const lock = useRef(false);
  const deepLink = useRef<{ org: string; request: string } | null>((() => { if (typeof window === "undefined") return null; const q = new URLSearchParams(window.location.search); const org = q.get("org"), request = q.get("request"); return org && request && /^\d+$/.test(request) ? { org, request } : null; })());
  const selectedOrg = orgs.find(o => String(o.id) === selected);
  const scope = `${token ?? ""}:${selected}`;
  const currentScope = useRef(scope);
  currentScope.current = scope;

  useEffect(() => {
    const controller = new AbortController();
    setOrgs([]); setSelected(""); setRequests([]); setReceipt(null); setError("");
    setTitle(""); setItems([item()]); setDestinations([destination(1)]); setBudget(""); setNeeded(""); setSubstitution("require_approval");
    attempt.current = null; setAttemptPending(false);
    if (!token) { setOrgLoading(false); return () => controller.abort(); }
    setOrgLoading(true);
    apiRequest<{ items: Org[] }>("/organizations", { token, signal: controller.signal })
      .then(r => { if (!controller.signal.aborted) { const active = r.items.filter(o => o.membership.status === "active"); setOrgs(active); const wanted = deepLink.current?.org; setSelected(active.some(o => String(o.id) === wanted) ? wanted! : active.length ? String(active[0].id) : ""); } })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setOrgLoading(false); });
    return () => controller.abort();
  }, [token]);

  useEffect(() => {
    const controller = new AbortController();
    setRequests([]); setReceipt(null);
    if (!token || !selected) return () => controller.abort();
    setListLoading(true);
    apiRequest<{ items: RequestRecord[] }>(`/orgs/${selected}/procurement/requests`, { token, signal: controller.signal })
      .then(r => { if (!controller.signal.aborted) setRequests(r.items); })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setListLoading(false); });
    return () => controller.abort();
  }, [token, selected, reload]);

  const updateItem = (index: number, field: keyof Item, value: string) => setItems(old => old.map((i, n) => n === index ? { ...i, [field]: value } : i));
  const updateDestination = (index: number, field: keyof Omit<Destination, "quantities">, value: string) => setDestinations(old => old.map((d, n) => n === index ? { ...d, [field]: value } : d));
  function selectOrg(value: string) {
    currentScope.current = `${token ?? ""}:${value}`;
    setSelected(value); setRequests([]); setReceipt(null); setError(""); attempt.current = null; setAttemptPending(false);
    setTitle(""); setItems([item()]); setDestinations([destination(1)]); setBudget(""); setNeeded("");
  }
  async function create(e: FormEvent) {
    e.preventDefault();
    if (!token || !selected || lock.current) return;
    const startedScope = scope;
    lock.current = true; setBusy(true); setError("");
    try {
      const body = JSON.stringify({ title, items: items.map(i => ({ ...(i.kind === "catalog" ? { master_product_id: Number(i.description) } : { free_text_description: i.description }), quantity: Number(i.quantity), unit: i.unit || null, notes: i.notes || null })), destinations: destinations.map(d => ({ label: d.label || null, province: d.province, city: d.city, address: d.address, allocations: d.quantities.map((q, item_index) => ({ item_index, quantity: Number(q) })).filter(a => a.quantity > 0) })), needed_by_date: needed || null, budget_minor: selectedOrg?.currency !== "IRR" || budget === "" ? null : Number(budget), substitution_policy: substitution });
      if (items.some((i, n) => destinations.reduce((sum, d) => sum + Number(d.quantities[n]), 0) > Number(i.quantity))) throw new Error("جمع سهم مقصدها از تعداد درخواستی یک قلم بیشتر است.");
      if (attempt.current && (attempt.current.body !== body || attempt.current.org !== selected)) throw new Error("برای تغییر درخواستِ در انتظار پاسخ، ابتدا نتیجه تلاش قبلی را از فهرست بررسی کنید.");
      if (!attempt.current) attempt.current = { key: newIdempotencyKey(), body, org: selected };
      setAttemptPending(true);
      const result = await apiRequest<{ purchase_request: RequestRecord }>(`/orgs/${selected}/procurement/requests`, { token, method: "POST", headers: { "Idempotency-Key": attempt.current.key }, body });
      if (currentScope.current !== startedScope) return;
      setReceipt(result.purchase_request); setRequests(old => [result.purchase_request, ...old.filter(r => r.id !== result.purchase_request.id)]);
      attempt.current = null; setAttemptPending(false);
    } catch (e) {
      if (currentScope.current === startedScope) {
        setError(e instanceof Error ? e.message : "ثبت درخواست ناموفق بود");
        if (e instanceof ApiError && [400, 401, 403, 404, 422].includes(e.status)) {
          attempt.current = null; setAttemptPending(false);
        }
      }
    }
    finally { lock.current = false; setBusy(false); }
  }
  useEffect(() => {
    const link = deepLink.current;
    if (!link || !token || orgLoading || !selected || link.org !== selected) return;
    deepLink.current = null;
    void act(Number(link.request), "detail");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, orgLoading, selected]);

  async function act(id: number, action: "detail" | "submit" | "cancel") {
    if (!token || lock.current) return;
    const startedScope = scope;
    lock.current = true; setBusy(true); setError("");
    try {
      const r = await apiRequest<{ purchase_request: RequestRecord }>(`/orgs/${selected}/procurement/requests/${id}${action === "detail" ? "" : `/${action}`}`, { token, method: action === "detail" ? "GET" : "POST" });
      if (currentScope.current !== startedScope) return;
      setReceipt(r.purchase_request); setRequests(old => old.map(p => p.id === id ? r.purchase_request : p));
    } catch (e) { if (currentScope.current === startedScope) setError(e instanceof Error ? e.message : "عملیات ناموفق بود"); }
    finally { lock.current = false; setBusy(false); }
  }
  if (loading || orgLoading) return <div className={styles.shell} role="status">در حال دریافت عضویت‌های شما…</div>;
  if (!user || !token) return <section className={styles.shell}><h1>درخواست تأمین سازمانی</h1><p>برای مشاهده و ثبت درخواست، وارد حساب خود شوید.</p><Link href="/login">ورود به حساب</Link></section>;
  return <section className={styles.shell} dir="rtl">
    <header className={styles.header}><strong>60Online / خرید سازمانی</strong><p>سازمان فعال: {orgs.find(o => String(o.id) === selected)?.display_name ?? "عضویت فعالی یافت نشد"}</p></header>
    <h1>درخواست تأمین سازمانی</h1>
    <p>نیاز سازمان را ثبت کنید؛ تیم تأمین برای پیشنهاد قیمت آن را بررسی می‌کند.</p>
    {error && <div role="alert" className={styles.error}>{error}</div>}
    {!orgs.length ? <div className={styles.card}><h2>عضویت فعال لازم است</h2><p>برای دسترسی به درخواست‌ها، عضویت شما باید توسط مسئول سازمان تأیید شود.</p></div> : <>
      <label className={styles.selector}>سازمان دارای عضویت فعال<select aria-label="سازمان دارای عضویت فعال" value={selected} disabled={busy || attemptPending} onChange={e => selectOrg(e.target.value)}>{orgs.map(o => <option key={o.id} value={o.id}>{o.display_name}</option>)}</select></label>
      {receipt && receipt.organization_id === Number(selected) && <section className={styles.card} aria-label="رسید درخواست">
        <h2>پیگیری درخواست</h2><p role="status">شماره پیگیری: <b dir="ltr">{receipt.request_number}</b> — {statusLabels[receipt.status] ?? receipt.status}</p>
        <h3>{receipt.title}</h3>
        <p>{receipt.status === "draft" ? "پیش‌نویس ذخیره شد. اقلام و مقصدها را بازبینی و سپس برای بررسی ارسال کنید." : receipt.status === "submitted" ? "درخواست ارسال شد؛ منتظر بررسی مسئول سازمان بمانید." : "وضعیت درخواست را از همین صفحه پیگیری کنید."}</p>
        {receipt.items?.map((i, n) => <p key={n}>{i.free_text_description ?? `کالای مرجع ${i.master_product_id}`} — {i.quantity} {i.unit}</p>)}
        {receipt.destinations?.map((d, n) => <div key={n}><strong>{d.label || `مقصد ${n + 1}`}</strong><p>{d.province}، {d.city}، {d.address}</p><p>{d.allocations.map(a => `قلم ${a.item_index + 1}: ${a.quantity}`).join(" / ")}</p></div>)}
        <div className={styles.actions}>{receipt.status === "draft" && <Button className={styles.primary} disabled={busy} onClick={() => act(receipt.id, "submit")}>ارسال برای بررسی</Button>}{["draft", "submitted"].includes(receipt.status) && <Button variant="outline" disabled={busy} onClick={() => act(receipt.id, "cancel")}>لغو درخواست</Button>}<Button variant="outline" disabled={busy} onClick={() => { setReceipt(null); setTitle(""); setItems([item()]); setDestinations([destination(1)]); setNeeded(""); setBudget(""); }}>درخواست جدید</Button></div>
        <p>ثبت و ارسال درخواست، سفارش قطعی، رزرو موجودی یا پرداخت ایجاد نمی‌کند.</p>
      </section>}
      {!receipt && <form onSubmit={create}>
        <fieldset disabled={busy || attemptPending} className={styles.fields}>
          <section className={styles.card}><h2>۱. سازمان و موضوع درخواست</h2><Input label="عنوان درخواست" required maxLength={200} value={title} onChange={e => setTitle(e.target.value)} /></section>
          <section className={styles.card}><h2>۲. اقلام موردنیاز</h2><p>نام کالا یا شناسه کالای مرجع را وارد کنید. قلم بدون قیمت نیز قابل درخواست است.</p>
            {items.map((i, n) => <fieldset key={n} className={styles.group}><legend>قلم {n + 1}</legend><label>نوع قلم<select aria-label={`نوع قلم ${n + 1}`} value={i.kind} onChange={e => { updateItem(n, "kind", e.target.value); updateItem(n, "description", ""); }}><option value="text">نام آزاد کالا</option><option value="catalog">شناسه کالای مرجع</option></select></label><Input id={`item-${n}`} label={i.kind === "text" ? "نام کالا" : "شناسه کالای مرجع"} required type={i.kind === "catalog" ? "number" : "text"} min={i.kind === "catalog" ? 1 : undefined} maxLength={2000} value={i.description} onChange={e => updateItem(n, "description", e.target.value)} /><Input id={`quantity-${n}`} label="تعداد موردنیاز" required type="number" min={1} max={100000} step={1} value={i.quantity} onChange={e => updateItem(n, "quantity", e.target.value)} /><Input id={`unit-${n}`} label="واحد (در صورت مشخص بودن)" maxLength={50} value={i.unit} onChange={e => updateItem(n, "unit", e.target.value)} /><Input id={`notes-${n}`} label="مشخصات و توضیحات" maxLength={2000} value={i.notes} onChange={e => updateItem(n, "notes", e.target.value)} />{items.length > 1 && <Button variant="outline" type="button" onClick={() => { setItems(old => old.filter((_, x) => x !== n)); setDestinations(old => old.map(d => ({ ...d, quantities: d.quantities.filter((_, x) => x !== n) }))); }}>حذف قلم {n + 1}</Button>}</fieldset>)}
            <Button className={styles.primary} type="button" disabled={items.length >= 50} onClick={() => { setItems(old => [...old, item()]); setDestinations(old => old.map(d => ({ ...d, quantities: [...d.quantities, "0"] }))); }}>افزودن قلم</Button>
          </section>
          <section className={styles.card}><h2>۳. مقصدها و زمان تحویل</h2>
            {destinations.map((d, n) => <fieldset key={n} className={styles.group}><legend>مقصد {n + 1}</legend>{([['label', 'عنوان مقصد'], ['province', 'استان'], ['city', 'شهر'], ['address', 'نشانی']] as const).map(([field, label]) => <Input key={field} id={`destination-${n}-${field}`} label={label} required={field !== "label"} maxLength={field === "address" ? 2000 : 100} value={d[field]} onChange={e => updateDestination(n, field, e.target.value)} />)}{items.map((i, j) => <Input key={j} id={`allocation-${n}-${j}`} label={`سهم قلم ${j + 1} در مقصد ${n + 1}`} required type="number" min={0} max={100000} step={1} value={d.quantities[j]} onChange={e => setDestinations(old => old.map((a, x) => x === n ? { ...a, quantities: a.quantities.map((q, y) => y === j ? e.target.value : q) } : a))} />)}{destinations.length > 1 && <Button variant="outline" type="button" onClick={() => setDestinations(old => old.filter((_, x) => x !== n))}>حذف مقصد {n + 1}</Button>}</fieldset>)}
            <div aria-label="خلاصهٔ تخصیص">{items.map((i, n) => { const got = destinations.reduce((sum, d) => sum + (Number(d.quantities[n]) || 0), 0), total = Number(i.quantity) || 0; return <p key={n}>قلم {n + 1}: کل {total.toLocaleString("fa-IR")} · تخصیص‌یافته {got.toLocaleString("fa-IR")} · {got > total ? <strong style={{ color: "#b91c1c" }}>بیش از تعداد درخواست</strong> : <>بدون مقصد {(total - got).toLocaleString("fa-IR")}</>}</p>; })}</div>
            <p>اگر مقصد بخشی از مقدار هنوز معلوم نیست، آن را خالی بگذارید؛ بعداً در پرونده ثبت می‌شود. تا مقصد همهٔ مقدار مشخص نشود، سفارش خرید صادر نمی‌شود.</p><Button className={styles.primary} type="button" disabled={destinations.length >= 20} onClick={() => setDestinations(old => [...old, destination(items.length)])}>افزودن مقصد</Button><Input label="موعد موردنیاز (میلادی)" type="date" value={needed} onChange={e => setNeeded(e.target.value)} />
          </section>
          <section className={styles.card}><h2>۴. بودجه و جایگزینی</h2><Input label={selectedOrg?.currency === "IRR" ? "بودجه اختیاری (ریال)" : `بودجه برای ارز ${selectedOrg?.currency ?? "نامشخص"} در این فرم فعال نیست`} disabled={selectedOrg?.currency !== "IRR"} type="number" min={0} max={9000000000000000} step={1} value={budget} onChange={e => setBudget(e.target.value)} /><label>جایگزینی کالا<select aria-label="جایگزینی کالا" value={substitution} onChange={e => setSubstitution(e.target.value)}><option value="require_approval">فقط با تأیید شما</option><option value="disallow">ممنوع</option></select></label><p>پیوست امن: تا آماده‌شدن مسیر بارگذاری، غیرفعال است.</p></section>
        </fieldset>
        <section className={`${styles.card} ${styles.notice}`}><p>ثبت درخواست، سفارش قطعی، رزرو موجودی یا پرداخت ایجاد نمی‌کند.</p><Button className={styles.primary} type="submit" disabled={busy}>{busy ? "در حال ثبت…" : attemptPending ? "تلاش مجدد با همان درخواست" : "ثبت پیش‌نویس"}</Button><p>پس از بازبینی، درخواست را برای بررسی مسئول سازمان ارسال کنید.</p>{attemptPending && !busy && <p>نتیجه تلاش قبلی مشخص نیست. برای دریافت همان رسید، دوباره تلاش کنید؛ درخواست جدیدی ایجاد نمی‌شود.</p>}</section>
      </form>}
      <section className={styles.card}><h2>درخواست‌های قابل مشاهده</h2><Button variant="outline" disabled={busy || listLoading} onClick={() => setReload(x => x + 1)}>به‌روزرسانی فهرست</Button>{listLoading ? <p role="status">در حال دریافت درخواست‌ها…</p> : !requests.length ? <p>هنوز درخواستی برای نمایش وجود ندارد.</p> : requests.filter(r => r.organization_id === Number(selected)).map(r => <div className={styles.row} key={r.id}><div><strong>{r.title}</strong><p><span dir="ltr">{r.request_number}</span> — {statusLabels[r.status] ?? r.status}</p></div><Button variant="outline" disabled={busy} onClick={() => act(r.id, "detail")}>مشاهده {r.request_number}</Button><Link href={`/organization/requests/${r.id}?org=${selected}`}>میز پرونده ←</Link></div>)}</section>
    </>}
  </section>;
}
