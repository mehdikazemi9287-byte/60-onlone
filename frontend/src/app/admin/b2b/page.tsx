"use client";

import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatPrice, toPersianNum } from "@/lib/utils";

type Account = { id: number; legal_name: string; buyer_kind: "organization" | "retailer"; status: string; city: string | null;
  national_id: string; active_members: number; pending_invites: number;
  contract: { title: string; contract_reference: string } | null;
  credit_contract: { limit_minor: number; outstanding_minor: number; due_days: number; status: string; overdue: boolean } | null };
type App = { id: number; buyer_kind: "organization" | "retailer"; legal_name: string; national_id: string | null;
  business_license_no: string | null; contact_name: string; phone: string; city: string | null; staff_band: string | null;
  monthly_band: string | null; message: string | null; created_at: string };
type Invite = { phone: string; role: string };

const KIND_FA = { organization: "سازمان", retailer: "فروشگاه" } as const;
const ROLE_FA: Record<string, string> = { organization_admin: "مدیر حساب", procurement_agent: "کارشناس خرید",
  organization_finance: "مالی", employee: "کارمند" };
const field = "mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm";
const btn = "rounded-lg bg-[#102B7A] px-4 py-2 text-sm font-bold text-white disabled:opacity-50";

export default function B2BAdmin() {
  const { token } = useAuth();
  const [tab, setTab] = useState<"accounts" | "new" | "apps">("accounts");
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [apps, setApps] = useState<App[] | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const blank = { buyer_kind: "organization", legal_name: "", national_id: "", business_license_no: "", city: "",
    contract_title: "", contract_ref: "", limit_toman: "", due_days: "14", application_id: "" };
  const [f, setF] = useState(blank);
  const [invites, setInvites] = useState<Invite[]>([{ phone: "", role: "organization_admin" }]);
  const [key, setKey] = useState(() => crypto.randomUUID());

  const load = async () => {
    if (!token) return;
    try {
      const [a, p] = await Promise.all([
        apiRequest<{ items: Account[] }>("/admin/b2b/accounts", { token }),
        apiRequest<{ items: App[] }>("/admin/b2b/applications", { token }),
      ]);
      setAccounts(a.items); setApps(p.items);
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };
  useEffect(() => { void load(); }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  const fromApp = (a: App) => {
    setF({ ...blank, buyer_kind: a.buyer_kind, legal_name: a.legal_name, national_id: a.national_id ?? "",
      business_license_no: a.business_license_no ?? "", city: a.city ?? "", application_id: String(a.id) });
    setInvites([{ phone: a.phone, role: "organization_admin" }]);
    setKey(crypto.randomUUID()); setTab("new"); setMsg(null);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setBusy(true); setMsg(null);
    const limit = Math.round(Number(f.limit_toman.replace(/[,،\s]/g, "") || "0") * 10);
    try {
      await apiRequest("/admin/b2b/accounts", { token, method: "POST", headers: { "Idempotency-Key": key },
        body: JSON.stringify({ buyer_kind: f.buyer_kind, legal_name: f.legal_name, national_id: f.national_id,
          business_license_no: f.business_license_no || undefined, city: f.city || undefined,
          contract: f.contract_title ? { title: f.contract_title, reference: f.contract_ref } : undefined,
          credit: { limit_minor: limit, due_days: Number(f.due_days) || 7 },
          invites: invites.filter((i) => i.phone.trim()),
          application_id: f.application_id ? Number(f.application_id) : undefined }) });
      setMsg({ ok: true, text: "حساب باز شد. افراد دعوت‌شده با ورود پیامکی با همان شماره، خودکار عضو می‌شوند." });
      setF(blank); setInvites([{ phone: "", role: "organization_admin" }]); setKey(crypto.randomUUID()); setTab("accounts");
      await load();
    } catch (err) { setMsg({ ok: false, text: (err as Error).message }); }
    finally { setBusy(false); }
  };

  const reject = async (id: number) => {
    if (!token) return;
    const note = window.prompt("دلیل رد (اختیاری)") ?? "";
    try { await apiRequest(`/admin/b2b/applications/${id}/reject`, { token, method: "POST", body: JSON.stringify({ note }) }); await load(); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };

  const set = (k: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });

  return (
    <section dir="rtl" className="space-y-4 p-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-black">حساب‌های سازمانی و فروشگاهی</h1>
        <div className="flex gap-2" role="tablist">
          {([["accounts", "حساب‌ها"], ["new", "باز کردن حساب"], ["apps", `درخواست‌ها${apps?.length ? ` (${toPersianNum(apps.length)})` : ""}`]] as const).map(([k, l]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
              className={`rounded-full px-4 py-1.5 text-sm font-bold ${tab === k ? "bg-[#102B7A] text-white" : "bg-white ring-1 ring-neutral-300"}`}>{l}</button>
          ))}
        </div>
      </header>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`rounded-lg p-3 text-sm ${msg.ok ? "bg-green-50 text-green-800" : "bg-red-50 text-red-700"}`}>{msg.text}</p>}

      {tab === "accounts" && (
        <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-neutral-200">
          <table className="w-full text-right text-sm">
            <thead className="text-xs text-neutral-500"><tr>{["نام", "نوع", "قرارداد", "سقف اعتبار", "بدهی جاری", "سررسید", "وضعیت اعتبار", "اعضا"].map((h) => <th key={h} className="p-3 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {accounts?.map((a) => (
                <tr key={a.id} className="border-t border-neutral-100">
                  <td className="p-3 font-bold">{a.legal_name}<div className="text-xs font-normal text-neutral-500">{a.city ?? ""}</div></td>
                  <td className="p-3">{KIND_FA[a.buyer_kind]}</td>
                  <td className="p-3">{a.contract ? `${a.contract.title} (${a.contract.contract_reference})` : "—"}</td>
                  <td className="p-3 tabular-nums">{a.credit_contract ? formatPrice(a.credit_contract.limit_minor) : "—"}</td>
                  <td className="p-3 tabular-nums">{a.credit_contract ? formatPrice(a.credit_contract.outstanding_minor) : "—"}</td>
                  <td className="p-3">{a.credit_contract ? `${toPersianNum(a.credit_contract.due_days)} روز` : "—"}</td>
                  <td className="p-3">{!a.credit_contract ? "بدون اعتبار" : a.credit_contract.overdue ? <span className="font-bold text-red-700">معوق</span> : a.credit_contract.status === "frozen" ? "مسدود" : "فعال"}</td>
                  <td className="p-3">{toPersianNum(a.active_members)}{a.pending_invites ? <span className="text-xs text-neutral-500"> (+{toPersianNum(a.pending_invites)} دعوت)</span> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {accounts?.length === 0 && <p className="p-6 text-center text-sm text-neutral-500">هنوز حسابی باز نشده است.</p>}
        </div>
      )}

      {tab === "new" && (
        <form onSubmit={submit} className="grid gap-4 rounded-xl bg-white p-4 ring-1 ring-neutral-200 md:grid-cols-2">
          <label className="text-sm">نوع خریدار
            <select className={field} value={f.buyer_kind} onChange={set("buyer_kind")}><option value="organization">سازمان / شرکت</option><option value="retailer">فروشگاه (خرید عمده)</option></select></label>
          <label className="text-sm">نام حقوقی<input className={field} required value={f.legal_name} onChange={set("legal_name")} /></label>
          <label className="text-sm">شناسهٔ ملی<input className={field} required inputMode="numeric" dir="ltr" value={f.national_id} onChange={set("national_id")} /></label>
          <label className="text-sm">شمارهٔ جواز کسب{f.buyer_kind === "retailer" ? " (الزامی)" : ""}<input className={field} required={f.buyer_kind === "retailer"} dir="ltr" value={f.business_license_no} onChange={set("business_license_no")} /></label>
          <label className="text-sm">شهر<input className={field} value={f.city} onChange={set("city")} /></label>
          <label className="text-sm">عنوان قرارداد<input className={field} value={f.contract_title} onChange={set("contract_title")} /></label>
          <label className="text-sm">شمارهٔ قرارداد<input className={field} required={!!f.contract_title} dir="ltr" value={f.contract_ref} onChange={set("contract_ref")} /></label>
          <label className="text-sm">سقف اعتبار (تومان؛ صفر = بدون اعتبار)<input className={field} inputMode="numeric" dir="ltr" value={f.limit_toman} onChange={set("limit_toman")} /></label>
          <label className="text-sm">مهلت پرداخت صورت‌حساب هفتگی (روز)<input className={field} type="number" min={0} max={90} value={f.due_days} onChange={set("due_days")} /></label>
          <fieldset className="md:col-span-2">
            <legend className="text-sm font-bold">دعوت با شمارهٔ موبایل (دست‌کم یک مدیر حساب)</legend>
            {invites.map((inv, i) => (
              <div key={i} className="mt-2 flex gap-2">
                <input aria-label="شمارهٔ موبایل" className={field} dir="ltr" placeholder="09xxxxxxxxx" value={inv.phone}
                  onChange={(e) => setInvites(invites.map((x, j) => (j === i ? { ...x, phone: e.target.value } : x)))} />
                <select aria-label="نقش" className={field} value={inv.role}
                  onChange={(e) => setInvites(invites.map((x, j) => (j === i ? { ...x, role: e.target.value } : x)))}>
                  {Object.entries(ROLE_FA).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
              </div>
            ))}
            <button type="button" className="mt-2 text-sm font-bold text-[#1748C9]" onClick={() => setInvites([...invites, { phone: "", role: "procurement_agent" }])}>+ نفر دیگر</button>
          </fieldset>
          <div className="md:col-span-2"><button className={btn} disabled={busy}>{busy ? "در حال ثبت…" : "باز کردن حساب"}</button></div>
        </form>
      )}

      {tab === "apps" && (
        <ul className="space-y-3">
          {apps?.length === 0 && <li className="rounded-xl bg-white p-6 text-center text-sm text-neutral-500 ring-1 ring-neutral-200">درخواست تازه‌ای نیست.</li>}
          {apps?.map((a) => (
            <li key={a.id} className="rounded-xl bg-white p-4 ring-1 ring-neutral-200">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-bold">{a.legal_name} <span className="text-xs font-normal text-neutral-500">· {KIND_FA[a.buyer_kind]}{a.city ? ` · ${a.city}` : ""}</span></p>
                  <p className="text-sm text-neutral-600">{a.contact_name} · <span dir="ltr">{a.phone}</span>{a.monthly_band ? ` · خرید ماهانه: ${a.monthly_band}` : ""}{a.staff_band ? ` · کارکنان: ${a.staff_band}` : ""}</p>
                  {a.message && <p className="mt-1 text-sm">{a.message}</p>}
                </div>
                <div className="flex gap-2">
                  <button className={btn} onClick={() => fromApp(a)}>بررسی و باز کردن حساب</button>
                  <button className="rounded-lg px-4 py-2 text-sm ring-1 ring-neutral-300" onClick={() => reject(a.id)}>رد</button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
