"use client";
// Tracking of a customer purchase/price request: items, delivery note, status history and the team's answer.
import { useEffect, useState } from "react";
import Link from "next/link";
import { ClipboardList, Lock } from "lucide-react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatPrice, toPersianNum } from "@/lib/utils";
import { useRouter } from "next/navigation";

type Quote = { id: number; version: number; state: string; expires_at: string; total_minor: number; shipping_minor: number; tax_minor: number; note: string | null;
  lines: { slug: string; title_fa: string; quantity: number; unit_price_minor: number; line_total_minor: number }[] };
const Q_STATE: Record<string, string> = { sent: "معتبر", accepted: "پذیرفته شد", superseded: "جایگزین‌شده", withdrawn: "لغوشده", expired: "منقضی" };

function Quotes({ token, requestId, quotes }: { token: string; requestId: number; quotes: Quote[] }) {
  const router = useRouter();
  const [addr, setAddr] = useState({ recipient_name: "", recipient_phone: "", province: "", city: "", line1: "" }), [err, setErr] = useState(""), [busy, setBusy] = useState(false);
  const accept = async (q: Quote) => {
    setBusy(true); setErr("");
    try { const r = await apiRequest<{ order: { order_number: string } }>(`/requests/${requestId}/quotes/${q.id}/accept`, { token, method: "POST", body: JSON.stringify({ address: addr }) });
      router.push(`/orders/${r.order.order_number}`); }
    catch (e) { setErr(e instanceof Error ? e.message : "پذیرش ناموفق بود"); } finally { setBusy(false); }
  };
  const inp = "h-10 rounded-lg border px-2 text-sm";
  return (
    <section className="card mt-4 p-4">
      <h2 className="mb-2 font-black text-brand-navy">پیشنهادهای قیمت</h2>
      {quotes.map((q) => (
        <div key={q.id} className={`mb-3 rounded-xl p-3 text-sm ${q.state === "sent" ? "bg-emerald-50" : "bg-neutral-50 opacity-80"}`}>
          <p className="font-bold">نسخه {toPersianNum(q.version)} · {Q_STATE[q.state] ?? q.state}{q.state === "sent" ? ` · معتبر تا ${new Date(q.expires_at).toLocaleString("fa-IR")}` : ""}</p>
          <ul className="my-2 space-y-1">{q.lines.map((l) => <li key={l.slug} className="flex justify-between gap-2"><span className="min-w-0 truncate">{l.title_fa} × {toPersianNum(l.quantity)}</span><b>{formatPrice(l.line_total_minor)}</b></li>)}</ul>
          <p className="text-xs text-neutral-600">ارسال {formatPrice(q.shipping_minor)} · مالیات {formatPrice(q.tax_minor)} · <b>جمع {formatPrice(q.total_minor)}</b></p>
          {q.note && <p className="mt-1 text-xs">{q.note}</p>}
          {q.state === "sent" && <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {([["recipient_name", "نام گیرنده"], ["recipient_phone", "تلفن"], ["province", "استان"], ["city", "شهر"], ["line1", "نشانی"]] as const).map(([k, l]) => (
              <input key={k} aria-label={l} placeholder={l} className={inp} value={addr[k]} onChange={(e) => setAddr({ ...addr, [k]: e.target.value })} />))}
            <button type="button" disabled={busy} onClick={() => accept(q)} className="h-10 rounded-lg bg-brand-navy text-sm font-bold text-white disabled:opacity-60">پذیرش و ثبت سفارش</button>
            <p className="text-[11px] text-neutral-500 sm:col-span-2">با پذیرش، سفارش «در انتظار پرداخت» ثبت می‌شود؛ پرداختی انجام نمی‌شود.</p>
          </div>}
        </div>))}
      {err && <p role="alert" className="text-sm text-red-700">{err}</p>}
    </section>
  );
}

type Req = { id: number; kind: string; subject: string; message: string; status: string; response: string | null; created_at: string;
  items: { slug: string; name: string; quantity: number }[] };
const STATUS: Record<string, [string, string]> = { open: ["ثبت‌شده", "bg-sky-50 text-sky-800"], reviewing: ["در حال بررسی", "bg-amber-50 text-amber-800"],
  answered: ["پاسخ داده شد", "bg-emerald-50 text-emerald-800"], closed: ["بسته‌شده", "bg-neutral-100 text-neutral-700"] };
const KIND: Record<string, string> = { price: "استعلام قیمت", procurement: "درخواست خرید", support: "پشتیبانی" };
const STEPS = ["open", "reviewing", "answered", "closed"];

export default function RequestTracking({ id }: { id: string }) {
  const { token, user, loading } = useAuth();
  const [d, setD] = useState<{ request: Req; events: { status: string; message: string; created_at: string }[]; quotes?: Quote[] } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { if (token) apiRequest<typeof d>(`/requests/${id}`, { token }).then(setD).catch((e) => setError(e.message)); }, [token, id]);
  if (loading) return <div className="container-page py-8"><div className="h-48 animate-pulse rounded-xl bg-neutral-100" /></div>;
  if (!user) return <div className="container-page py-8 text-center"><Lock className="mx-auto mb-2" /><Link href={`/login?next=/requests/${id}`} className="font-bold text-brand-blue">برای پیگیری وارد شوید</Link></div>;
  if (error) return <div className="container-page py-8"><p role="alert" className="rounded-xl bg-red-50 p-4 text-red-800">{error}</p></div>;
  if (!d) return <div className="container-page py-8"><div className="h-48 animate-pulse rounded-xl bg-neutral-100" /></div>;
  const r = d.request, [label, tone] = STATUS[r.status] ?? [r.status, "bg-neutral-100"];
  const step = STEPS.indexOf(r.status);
  return (
    <div className="container-page max-w-3xl py-8" dir="rtl">
      <Link href="/requests" className="text-sm text-brand-blue">درخواست‌های من</Link>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <ClipboardList className="h-6 w-6 text-brand-navy" />
        <h1 className="text-xl font-black text-brand-navy">{r.subject}</h1>
        <span className={`rounded-full px-3 py-1 text-xs font-bold ${tone}`}>{label}</span>
      </div>
      <p className="mt-1 text-xs text-neutral-500">{KIND[r.kind] ?? r.kind} · شماره پیگیری {toPersianNum(r.id)} · {new Date(r.created_at).toLocaleDateString("fa-IR")}</p>
      <ol className="my-5 grid grid-cols-4 gap-1 text-center text-[11px]" aria-label="مراحل">
        {STEPS.map((s, i) => <li key={s} className={`rounded-lg px-1 py-2 font-bold ${i <= step ? "bg-brand-navy text-white" : "bg-neutral-100 text-neutral-500"}`}>{STATUS[s][0]}</li>)}
      </ol>
      <section className="card p-4">
        <h2 className="mb-2 font-black text-brand-navy">اقلام</h2>
        <ul className="divide-y divide-neutral-100 text-sm">{r.items.map((i) => <li key={i.slug} className="flex justify-between gap-3 py-2"><Link href={`/products/${i.slug}`} className="min-w-0 truncate hover:text-brand-blue">{i.name}</Link><b>{toPersianNum(i.quantity)}</b></li>)}</ul>
        {r.message && <p className="mt-3 rounded-xl bg-neutral-50 p-3 text-xs leading-6 text-neutral-700">{r.message}</p>}
      </section>
      {!!d.quotes?.length && token && <Quotes token={token} requestId={r.id} quotes={d.quotes} />}
      {r.response && <section className="card mt-4 border-emerald-200 p-4"><h2 className="mb-1 font-black text-emerald-800">پاسخ کارشناس</h2><p className="text-sm leading-7">{r.response}</p></section>}
      <section className="mt-4">
        <h2 className="mb-2 font-black text-brand-navy">تاریخچه</h2>
        <ul className="space-y-2 text-sm">{d.events.map((e, i) => <li key={i} className="rounded-xl bg-white p-3 shadow-sm"><b>{STATUS[e.status]?.[0] ?? e.status}</b> — {e.message}<span className="mr-2 text-xs text-neutral-500">{new Date(e.created_at).toLocaleString("fa-IR")}</span></li>)}</ul>
      </section>
      <p className="mt-6 text-xs leading-6 text-neutral-500">این درخواست پرداخت یا سفارش قطعی نیست؛ پس از اعلام قیمت و موجودی توسط کارشناس، مرحله بعد به شما اطلاع داده می‌شود.</p>
    </div>
  );
}
