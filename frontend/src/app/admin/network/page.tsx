"use client";

import { useEffect, useState } from "react";
import { apiRequest, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { toPersianNum } from "@/lib/utils";
import {
  apiUrl, CONTRACT_STATUSES, DATA_SOURCE_FA, DATA_SOURCES, network, STATUS_CLASS, STATUS_FA,
  type AdminBranch, type AdminChain, type ContractStatus, type ImportResult, type NamedRef, type Sector,
  type SyncLocationsResult,
} from "@/lib/network";

const field = "mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm";
const btn = "rounded-lg bg-[#102B7A] px-4 py-2 text-sm font-bold text-white disabled:opacity-50";
const ghost = "rounded-lg px-3 py-1.5 text-sm ring-1 ring-neutral-300 disabled:opacity-50";
const MAX_CSV = 2 * 1024 * 1024;

type Msg = { ok: boolean; text: string } | null;
type Tab = "chains" | "new" | "branches" | "import" | "sectors";

function Badge({ s }: { s: ContractStatus }) {
  return <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-bold ${STATUS_CLASS[s]}`}>{STATUS_FA[s]}</span>;
}

export default function AdminNetwork() {
  const { token } = useAuth();
  const [tab, setTab] = useState<Tab>("chains");
  const [msg, setMsg] = useState<Msg>(null);
  const [chains, setChains] = useState<AdminChain[] | null>(null);
  const [sectors, setSectors] = useState<Sector[] | null>(null);

  const loadChains = async () => {
    if (!token) return;
    try { setChains((await apiRequest<{ items: AdminChain[] }>("/admin/network/chains", { token })).items); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };
  const loadSectors = async () => {
    if (!token) return;
    try { setSectors((await apiRequest<{ items: Sector[] }>("/admin/network/sectors", { token })).items); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };
  useEffect(() => { void loadChains(); void loadSectors(); }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  const tabs: [Tab, string][] = [["chains", `زنجیره‌ها${chains ? ` (${toPersianNum(chains.length)})` : ""}`], ["new", "زنجیرهٔ تازه"],
    ["branches", "شعبه‌ها"], ["import", "ورود CSV شعبه‌ها"], ["sectors", "حوزه‌ها"]];

  return (
    <section dir="rtl" className="space-y-4 p-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-black">شبکهٔ فروشگاه‌ها</h1>
          <p className="text-sm text-neutral-600">در صفحهٔ عمومی <a className="underline" href="/network" target="_blank" rel="noopener">/network</a> فقط شعبه‌های فعالِ زنجیره‌های با قرارداد فعال دیده می‌شوند.</p>
        </div>
        <div className="flex flex-wrap gap-2" role="tablist">
          {tabs.map(([k, l]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => { setTab(k); setMsg(null); }}
              className={`rounded-full px-4 py-1.5 text-sm font-bold ${tab === k ? "bg-[#102B7A] text-white" : "bg-white ring-1 ring-neutral-300"}`}>{l}</button>
          ))}
        </div>
      </header>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`rounded-lg p-3 text-sm ${msg.ok ? "bg-green-50 text-green-800" : "bg-red-50 text-red-700"}`}>{msg.text}</p>}

      {token && tab === "chains" && <ChainsTable token={token} chains={chains} sectors={sectors ?? []} onSaved={loadChains} setMsg={setMsg} />}
      {token && tab === "new" && <ChainForm token={token} sectors={sectors ?? []} setMsg={setMsg}
        onDone={async () => { await loadChains(); setTab("chains"); }} />}
      {token && tab === "branches" && <BranchesTable token={token} chains={chains ?? []} setMsg={setMsg} />}
      {token && tab === "import" && <CsvImport token={token} setMsg={setMsg} onCommitted={loadChains} />}
      {token && tab === "sectors" && <SectorsPanel token={token} sectors={sectors} reload={loadSectors} setMsg={setMsg} />}
    </section>
  );
}

/* ---------------------------------------------------------------- chains */

type ChainDraft = { slug: string; name: string; brand_name: string; website: string; contract_status: ContractStatus;
  contract_signed_on: string; contract_reference: string; notes: string; sectors: string[]; supplier_id: string };

const toDraft = (c?: AdminChain): ChainDraft => ({
  slug: c?.slug ?? "", name: c?.name ?? "", brand_name: c?.brand_name ?? "", website: c?.website ?? "",
  contract_status: c?.contract_status ?? "prospect", contract_signed_on: c?.contract_signed_on ?? "",
  contract_reference: c?.contract_reference ?? "", notes: c?.notes ?? "", sectors: c?.sectors.map((s) => s.slug) ?? [],
  supplier_id: c?.supplier_id != null ? String(c.supplier_id) : "",
});

const draftBody = (d: ChainDraft) => ({
  slug: d.slug.trim(), name: d.name, brand_name: d.brand_name || null, website: d.website.trim() || null,
  contract_status: d.contract_status, contract_signed_on: d.contract_signed_on || null,
  contract_reference: d.contract_reference || null, notes: d.notes || null, sectors: d.sectors,
  supplier_id: d.supplier_id.trim() ? Number(d.supplier_id.trim()) : null,
});

function ChainFields({ d, setD, sectors }: { d: ChainDraft; setD: (d: ChainDraft) => void; sectors: Sector[] }) {
  const set = (k: keyof ChainDraft) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setD({ ...d, [k]: e.target.value });
  const needsEvidence = d.contract_status === "active" && !d.contract_reference.trim() && !d.contract_signed_on;
  return (
    <>
      <label className="text-sm">نام زنجیره<input className={field} required value={d.name} onChange={set("name")} /></label>
      <label className="text-sm">شناسهٔ لاتین (slug)<input className={field} required dir="ltr" pattern="[a-z0-9]+(-[a-z0-9]+)*" placeholder="ofogh-koorosh" value={d.slug} onChange={set("slug")} /></label>
      <label className="text-sm">نام تجاری<input className={field} value={d.brand_name} onChange={set("brand_name")} /></label>
      <label className="text-sm">وبسایت<input className={field} dir="ltr" type="url" placeholder="https://" value={d.website} onChange={set("website")} /></label>
      <label className="text-sm">وضعیت قرارداد
        <select className={field} value={d.contract_status} onChange={set("contract_status")}>
          {CONTRACT_STATUSES.map((s) => <option key={s} value={s}>{STATUS_FA[s]}</option>)}
        </select></label>
      <label className="text-sm">شمارهٔ قرارداد<input className={field} dir="ltr" value={d.contract_reference} onChange={set("contract_reference")} /></label>
      <label className="text-sm">تاریخ امضا (میلادی)<input className={field} type="date" dir="ltr" value={d.contract_signed_on} onChange={set("contract_signed_on")} /></label>
      <label className="text-sm">شناسهٔ فروشندهٔ پلتفرم (supplier_id؛ خالی = وصل نیست)<input className={field} inputMode="numeric" dir="ltr" pattern="[0-9]*" value={d.supplier_id} onChange={set("supplier_id")} /></label>
      <label className="text-sm md:col-span-2">یادداشت<textarea className={field} rows={2} value={d.notes} onChange={set("notes")} /></label>
      {sectors.length > 0 && (
        <fieldset className="md:col-span-2">
          <legend className="text-sm font-bold">حوزه‌ها</legend>
          <div className="mt-1 flex flex-wrap gap-3">
            {sectors.map((s) => (
              <label key={s.slug} className="flex items-center gap-1 text-sm">
                <input type="checkbox" checked={d.sectors.includes(s.slug)}
                  onChange={(e) => setD({ ...d, sectors: e.target.checked ? [...d.sectors, s.slug] : d.sectors.filter((x) => x !== s.slug) })} />
                {s.name}{!s.active && <span className="text-xs text-neutral-400"> (غیرفعال)</span>}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      {needsEvidence && <p className="text-sm text-amber-700 md:col-span-2">برای «قرارداد فعال»، شمارهٔ قرارداد یا تاریخ امضا لازم است.</p>}
    </>
  );
}

function ChainForm({ token, sectors, setMsg, onDone }: { token: string; sectors: Sector[]; setMsg: (m: Msg) => void; onDone: () => Promise<void> }) {
  const [d, setD] = useState<ChainDraft>(toDraft());
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      await apiRequest("/admin/network/chains", { token, method: "POST", body: JSON.stringify(draftBody(d)) });
      setMsg({ ok: true, text: "زنجیره ثبت شد." }); setD(toDraft()); await onDone();
    } catch (err) { setMsg({ ok: false, text: (err as Error).message }); }
    finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} className="grid gap-4 rounded-xl bg-white p-4 ring-1 ring-neutral-200 md:grid-cols-2">
      <ChainFields d={d} setD={setD} sectors={sectors} />
      <div className="md:col-span-2"><button className={btn} disabled={busy}>{busy ? "در حال ثبت…" : "ثبت زنجیره"}</button></div>
    </form>
  );
}

function ChainsTable({ token, chains, sectors, onSaved, setMsg }: {
  token: string; chains: AdminChain[] | null; sectors: Sector[]; onSaved: () => Promise<void>; setMsg: (m: Msg) => void;
}) {
  const [editing, setEditing] = useState<number | null>(null);
  const [d, setD] = useState<ChainDraft>(toDraft());
  const [busy, setBusy] = useState(false);
  const [syncing, setSyncing] = useState<number | null>(null);
  const [syncResult, setSyncResult] = useState<SyncLocationsResult | null>(null);
  const sync = async (c: AdminChain) => {
    const ok = window.confirm(
      `برای شعبه‌های فعالِ «${c.name}» که هنوز مکان فروشنده ندارند، مکان فروشنده (فروشندهٔ #${c.supplier_id}) ساخته می‌شود.\n\n` +
      "مکان‌های تازه «غیرفعال» و با همهٔ گزینه‌های تحویل خاموش ساخته می‌شوند و هیچ چیزی سفارش‌پذیر نمی‌شود. " +
      "پس از تأیید با زنجیره که کدام شعبه ارسال، تحویل یا مراجعهٔ حضوری دارد، باید آن‌ها را در پنل فروشنده فعال کنید.\n\nادامه می‌دهید؟");
    if (!ok) return;
    setSyncing(c.id); setMsg(null); setSyncResult(null);
    try {
      const out = await apiRequest<SyncLocationsResult>(`/admin/network/chains/${c.id}/sync-locations`, { token, method: "POST", body: "{}" });
      setSyncResult(out); await onSaved();
    } catch (err) { setMsg({ ok: false, text: (err as Error).message }); }
    finally { setSyncing(null); }
  };
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (editing == null) return;
    setBusy(true); setMsg(null);
    try {
      await apiRequest(`/admin/network/chains/${editing}`, { token, method: "PUT", body: JSON.stringify(draftBody(d)) });
      setMsg({ ok: true, text: "تغییرات زنجیره ذخیره شد." }); setEditing(null); await onSaved();
    } catch (err) { setMsg({ ok: false, text: (err as Error).message }); }
    finally { setBusy(false); }
  };
  if (chains === null) return <p className="text-neutral-400">در حال بارگذاری…</p>;
  return (
    <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-neutral-200">
      <table className="w-full text-right text-sm">
        <thead className="text-xs text-neutral-500"><tr>{["زنجیره", "حوزه‌ها", "وضعیت قرارداد", "شمارهٔ / تاریخ قرارداد", "فروشندهٔ پلتفرم", "شعبهٔ فعال", "سایر شعبه‌ها", "استان", ""].map((h, i) => <th key={i} className="p-3 font-medium">{h}</th>)}</tr></thead>
        <tbody>
          {chains.map((c) => {
            const other = CONTRACT_STATUSES.filter((s) => s !== "active").reduce((n, s) => n + (c.branch_counts[s] ?? 0), 0);
            return [
              <tr key={c.id} className="border-t border-neutral-100 align-top">
                <td className="p-3 font-bold">{c.name}<div className="text-xs font-normal text-neutral-500" dir="ltr">{c.slug}</div>
                  {c.provenance === "test" && <div className="text-xs font-bold text-amber-700">داده آزمایشی (نمایش عمومی ندارد)</div>}</td>
                <td className="p-3 text-xs">{c.sectors.map((s) => s.name).join("، ") || "—"}</td>
                <td className="p-3"><Badge s={c.contract_status} /></td>
                <td className="p-3 text-xs" dir="ltr">{[c.contract_reference, c.contract_signed_on].filter(Boolean).join(" · ") || "—"}</td>
                <td className="p-3 text-xs" dir="ltr">{c.supplier_id != null ? `#${c.supplier_id}` : "—"}</td>
                <td className="p-3 tabular-nums">{toPersianNum(c.branch_counts.active ?? 0)}</td>
                <td className="p-3 text-xs">{other ? CONTRACT_STATUSES.filter((s) => s !== "active" && c.branch_counts[s])
                  .map((s) => `${STATUS_FA[s]}: ${toPersianNum(c.branch_counts[s])}`).join("، ") : "—"}</td>
                <td className="p-3 tabular-nums">{toPersianNum(c.province_count)}</td>
                <td className="p-3"><div className="flex flex-col gap-1">
                  <button className={ghost} onClick={() => { setEditing(editing === c.id ? null : c.id); setD(toDraft(c)); }}>{editing === c.id ? "بستن" : "ویرایش"}</button>
                  <button className={ghost} disabled={syncing === c.id || c.contract_status !== "active" || c.supplier_id == null}
                    title={c.contract_status !== "active" ? "فقط زنجیرهٔ دارای قرارداد فعال" : c.supplier_id == null ? "اول supplier_id را ثبت کنید" : undefined}
                    onClick={() => void sync(c)}>{syncing === c.id ? "در حال ساخت…" : "ساخت مکان فروشنده برای شعبه‌های فعال"}</button>
                </div></td>
              </tr>,
              syncResult?.chain_id === c.id && (
                <tr key={`${c.id}-sync`} className="bg-green-50/50">
                  <td colSpan={9} className="p-3 text-sm">
                    <p className="font-bold">{syncResult.note}</p>
                    <p className="mt-1">مکان تازه: {toPersianNum(syncResult.created.length)} · کل شعبه‌های متصل به مکان فروشنده: {toPersianNum(syncResult.linked_total)} · وضعیت مکان‌های تازه: <span dir="ltr">{syncResult.new_location_status}</span></p>
                    {syncResult.created.length > 0 && (
                      <ul className="mt-1 list-inside list-disc text-xs" dir="ltr">
                        {syncResult.created.map((x) => <li key={x.branch_id}>{x.branch_code} → location #{x.supplier_location_id}</li>)}
                      </ul>
                    )}
                    <button type="button" className="mt-2 text-xs underline" onClick={() => setSyncResult(null)}>بستن</button>
                  </td>
                </tr>
              ),
              editing === c.id && (
                <tr key={`${c.id}-edit`} className="bg-neutral-50">
                  <td colSpan={9} className="p-3">
                    <form onSubmit={save} className="grid gap-3 md:grid-cols-2" aria-label={`ویرایش ${c.name}`}>
                      <ChainFields d={d} setD={setD} sectors={sectors} />
                      <div className="flex gap-2 md:col-span-2">
                        <button className={btn} disabled={busy}>{busy ? "در حال ذخیره…" : "ذخیره"}</button>
                        <button type="button" className={ghost} onClick={() => setEditing(null)}>انصراف</button>
                      </div>
                    </form>
                  </td>
                </tr>
              ),
            ];
          })}
        </tbody>
      </table>
      {chains.length === 0 && <p className="p-6 text-center text-sm text-neutral-500">هنوز زنجیره‌ای ثبت نشده است.</p>}
    </div>
  );
}

/* ---------------------------------------------------------------- branches */

function BranchesTable({ token, chains, setMsg }: { token: string; chains: AdminChain[]; setMsg: (m: Msg) => void }) {
  const [chain, setChain] = useState("");
  const [province, setProvince] = useState("");
  const [status, setStatus] = useState("");
  const [items, setItems] = useState<AdminBranch[] | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [form, setForm] = useState<{ branch?: AdminBranch } | null>(null);

  const load = async () => {
    setItems(null);
    const p = new URLSearchParams();
    if (chain) p.set("chain", chain);
    if (province.trim()) p.set("province", province.trim());
    if (status) p.set("status", status);
    try { setItems((await apiRequest<{ items: AdminBranch[] }>(`/admin/network/branches${p.size ? `?${p}` : ""}`, { token })).items); }
    catch (e) { setItems([]); setMsg({ ok: false, text: (e as Error).message }); }
  };
  useEffect(() => { const t = setTimeout(() => void load(), 300); return () => clearTimeout(t); }, [chain, province, status]); // eslint-disable-line react-hooks/exhaustive-deps

  const setBranchStatus = async (b: AdminBranch, s: ContractStatus) => {
    setBusyId(b.id); setMsg(null);
    try {
      const out = await apiRequest<AdminBranch>(`/admin/network/branches/${b.id}`, { token, method: "PUT", body: JSON.stringify({ contract_status: s }) });
      setItems((xs) => xs?.map((x) => (x.id === b.id ? out : x)) ?? null);
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusyId(null); }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 rounded-xl bg-white p-3 ring-1 ring-neutral-200">
        <label className="text-sm">زنجیره
          <select className={field} value={chain} onChange={(e) => setChain(e.target.value)}>
            <option value="">همه</option>{chains.map((c) => <option key={c.id} value={c.slug}>{c.name}</option>)}
          </select></label>
        <label className="text-sm">استان (نام یا شناسه)<input className={field} value={province} onChange={(e) => setProvince(e.target.value)} placeholder="مثلاً تهران" /></label>
        <label className="text-sm">وضعیت شعبه
          <select className={field} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">همه</option>{CONTRACT_STATUSES.map((s) => <option key={s} value={s}>{STATUS_FA[s]}</option>)}
          </select></label>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className={btn} disabled={chains.length === 0} onClick={() => setForm({})}>ثبت یک شعبه</button>
        <p className="text-xs text-neutral-500">برای ثبت گروهی از «ورود CSV شعبه‌ها» استفاده کنید. هر شعبه باید منبع داده و مرجع آن را داشته باشد.</p>
      </div>
      {form && <BranchForm token={token} chains={chains} branch={form.branch} setMsg={setMsg}
        onClose={() => setForm(null)}
        onSaved={(out, created) => {
          setForm(null);
          setMsg({ ok: true, text: created ? "شعبه ثبت شد." : "تغییرات شعبه ذخیره شد." });
          setItems((xs) => (created ? (xs ? [out, ...xs] : [out]) : xs?.map((x) => (x.id === out.id ? out : x)) ?? null));
        }} />}
      <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-neutral-200">
        {items === null && <p className="p-6 text-center text-sm text-neutral-400">در حال بارگذاری…</p>}
        {items && items.length > 0 && (
          <table className="w-full text-right text-sm">
            <thead className="text-xs text-neutral-500"><tr>{["کد / عنوان", "زنجیره", "استان / شهر", "نشانی", "مختصات", "منبع داده", "مکان فروشنده", "وضعیت شعبه", "نمایش عمومی", ""].map((h) => <th key={h} className="p-3 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {items.map((b) => (
                <tr key={b.id} className="border-t border-neutral-100 align-top">
                  <td className="p-3"><span className="font-bold">{b.title}</span><div className="text-xs text-neutral-500" dir="ltr">{b.branch_code}</div></td>
                  <td className="p-3">{b.chain.name}<div className="mt-1"><Badge s={b.chain_contract_status} /></div></td>
                  <td className="p-3">{b.province.name}{b.city ? ` / ${b.city}` : ""}{b.district ? <div className="text-xs text-neutral-500">{b.district}</div> : null}</td>
                  <td className="p-3 text-xs">{b.address ?? "—"}{b.phone && <div dir="ltr">{b.phone}</div>}</td>
                  <td className="p-3 text-xs" dir="ltr">{b.latitude != null ? `${b.latitude}, ${b.longitude}` : "—"}</td>
                  <td className="p-3 text-xs">{DATA_SOURCE_FA[b.data_source] ?? b.data_source}<div className="text-neutral-500">{b.source_reference}</div></td>
                  <td className="p-3 text-xs" dir="ltr">{b.supplier_location_id != null ? `#${b.supplier_location_id}` : "—"}</td>
                  <td className="p-3">
                    <select aria-label={`وضعیت ${b.title}`} className="rounded-lg border border-neutral-300 px-2 py-1 text-xs" disabled={busyId === b.id}
                      value={b.contract_status} onChange={(e) => void setBranchStatus(b, e.target.value as ContractStatus)}>
                      {CONTRACT_STATUSES.map((s) => <option key={s} value={s}>{STATUS_FA[s]}</option>)}
                    </select>
                  </td>
                  <td className="p-3 text-xs">{b.public ? <span className="font-bold text-green-700">بله</span> : "خیر"}</td>
                  <td className="p-3"><button className={ghost} onClick={() => setForm({ branch: b })}>ویرایش</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {items?.length === 0 && <p className="p-6 text-center text-sm text-neutral-500">شعبه‌ای با این فیلترها ثبت نشده است.</p>}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- CSV import */

const ACTION_FA = { create: "ایجاد", update: "به‌روزرسانی", error: "خطا" } as const;

function CsvImport({ token, setMsg, onCommitted }: { token: string; setMsg: (m: Msg) => void; onCommitted: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [csv, setCsv] = useState<string | null>(null);
  const [dry, setDry] = useState<ImportResult | null>(null);
  const [done, setDone] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);

  const pick = async (f: File | null) => {
    setFile(f); setDry(null); setDone(null); setCsv(null); setMsg(null);
    if (!f) return;
    if (f.size > MAX_CSV) { setMsg({ ok: false, text: "حداکثر حجم فایل ۲ مگابایت است." }); setFile(null); return; }
    setCsv(await f.text());
  };

  const run = async (commit: boolean) => {
    if (csv == null) return;
    setBusy(true); setMsg(null);
    try {
      const out = await apiRequest<ImportResult>(`/admin/network/branches/import${commit ? "?commit=1" : ""}`,
        { token, method: "POST", body: JSON.stringify({ csv }) });
      if (commit) {
        setDone(out); setDry(null);
        setMsg({ ok: true, text: `ثبت شد: ${toPersianNum(out.created)} ایجاد، ${toPersianNum(out.updated)} به‌روزرسانی${out.errors ? `، ${toPersianNum(out.errors)} ردیف خطادار ثبت نشد` : ""}.` });
        await onCommitted();
      } else setDry(out);
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  };

  const downloadTemplate = async () => {
    setMsg(null);
    try {
      const res = await fetch(apiUrl("/admin/network/branches/template.csv"), { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error(`دریافت قالب ناموفق بود (${res.status})`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url; a.download = "network-branches-template.csv"; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };

  const shown = done ?? dry;
  const good = dry ? dry.created + dry.updated : 0;
  return (
    <div className="space-y-4 rounded-xl bg-white p-4 ring-1 ring-neutral-200">
      <div className="space-y-1 text-sm text-neutral-700">
        <p>فایل CSV با کدگذاری UTF-8. ستون‌های لازم: chain_slug، branch_code، province، city، data_source، source_reference. شعبه با (chain_slug، branch_code) شناخته می‌شود؛ اگر باشد به‌روز می‌شود.</p>
        <p>منبع داده یکی از: {Object.entries(DATA_SOURCE_FA).map(([k, v]) => `${k} (${v})`).join("، ")}.</p>
        <button type="button" className="font-bold text-[#1748C9] underline" onClick={() => void downloadTemplate()}>دریافت فایل قالب (template.csv)</button>
      </div>
      <label className="block text-sm font-bold">فایل CSV
        <input className="mt-1 block text-sm" type="file" accept=".csv,text/csv" onChange={(e) => void pick(e.target.files?.[0] ?? null)} />
      </label>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={btn} disabled={busy || csv == null} onClick={() => void run(false)}>
          {busy && !dry ? "در حال بررسی…" : "۱. بررسی آزمایشی (بدون ثبت)"}</button>
        <button type="button" className={btn} disabled={busy || !dry || good === 0} onClick={() => void run(true)}
          title={!dry ? "اول بررسی آزمایشی را اجرا کنید" : undefined}>
          {busy && dry ? "در حال ثبت…" : "۲. ثبت نهایی"}</button>
      </div>
      {dry && (
        <p className="text-sm">
          نتیجهٔ بررسی آزمایشی «{file?.name}»: {toPersianNum(dry.rows)} ردیف — {toPersianNum(dry.created)} ایجاد، {toPersianNum(dry.updated)} به‌روزرسانی، <span className={dry.errors ? "font-bold text-red-700" : ""}>{toPersianNum(dry.errors)} خطا</span>.
          {dry.errors > 0 && good > 0 && " با «ثبت نهایی» فقط ردیف‌های بدون خطا ثبت می‌شوند."}
          {good === 0 && " هیچ ردیف قابل ثبتی نیست."}
        </p>
      )}
      {shown && shown.results.length > 0 && (
        <div className="max-h-[28rem] overflow-auto rounded-lg ring-1 ring-neutral-200">
          <table className="w-full text-right text-sm">
            <thead className="sticky top-0 bg-white text-xs text-neutral-500"><tr>{["خط", "کد شعبه", "نتیجه", "توضیح"].map((h) => <th key={h} className="p-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {shown.results.map((r) => (
                <tr key={r.line} className={`border-t border-neutral-100 ${r.action === "error" ? "bg-red-50" : ""}`}>
                  <td className="p-2 tabular-nums">{toPersianNum(r.line)}</td>
                  <td className="p-2" dir="ltr">{r.branch_code ?? "—"}</td>
                  <td className="p-2">{ACTION_FA[r.action]}</td>
                  <td className="p-2 text-xs">{r.error ?? ""}{r.code ? <span className="text-neutral-400" dir="ltr"> ({r.code})</span> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.rows > shown.results.length && <p className="p-2 text-xs text-neutral-500">فقط {toPersianNum(shown.results.length)} ردیف اول نمایش داده شد.</p>}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- sectors */

function SectorsPanel({ token, sectors, reload, setMsg }: { token: string; sectors: Sector[] | null; reload: () => Promise<void>; setMsg: (m: Msg) => void }) {
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      await apiRequest("/admin/network/sectors", { token, method: "POST", body: JSON.stringify({ slug: slug.trim(), name }) });
      setSlug(""); setName(""); setMsg({ ok: true, text: "حوزه افزوده شد." }); await reload();
    } catch (err) { setMsg({ ok: false, text: (err as Error).message }); }
    finally { setBusy(false); }
  };
  const toggle = async (s: Sector) => {
    setMsg(null);
    try { await apiRequest(`/admin/network/sectors/${s.id}`, { token, method: "PUT", body: JSON.stringify({ active: !s.active }) }); await reload(); }
    catch (err) { setMsg({ ok: false, text: (err as Error).message }); }
  };
  return (
    <div className="space-y-4">
      <ul className="divide-y divide-neutral-100 rounded-xl bg-white ring-1 ring-neutral-200">
        {sectors === null && <li className="p-4 text-sm text-neutral-400">در حال بارگذاری…</li>}
        {sectors?.length === 0 && <li className="p-4 text-sm text-neutral-500">حوزه‌ای تعریف نشده است.</li>}
        {sectors?.map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-2 p-3 text-sm">
            <span><span className="font-bold">{s.name}</span> <span className="text-xs text-neutral-500" dir="ltr">{s.slug}</span>
              {!s.active && <span className="mr-2 rounded-full bg-neutral-100 px-2 py-0.5 text-xs">غیرفعال</span>}</span>
            <button className={ghost} onClick={() => void toggle(s)}>{s.active ? "غیرفعال کن" : "فعال کن"}</button>
          </li>
        ))}
      </ul>
      <form onSubmit={create} className="grid gap-3 rounded-xl bg-white p-4 ring-1 ring-neutral-200 md:grid-cols-3">
        <label className="text-sm">نام حوزه<input className={field} required value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label className="text-sm">شناسهٔ لاتین<input className={field} required dir="ltr" pattern="[a-z0-9]+(-[a-z0-9]+)*" placeholder="dried-fruit" value={slug} onChange={(e) => setSlug(e.target.value)} /></label>
        <div className="flex items-end"><button className={btn} disabled={busy}>{busy ? "در حال ثبت…" : "افزودن حوزه"}</button></div>
      </form>
    </div>
  );
}

/* ---------------------------------------------------------------- single branch create / edit */

type BranchDraft = { chain_slug: string; branch_code: string; title: string; province: string; city: string; district: string;
  address: string; latitude: string; longitude: string; phone: string; contract_status: ContractStatus;
  data_source: (typeof DATA_SOURCES)[number] | ""; source_reference: string };

const toBranchDraft = (b?: AdminBranch): BranchDraft => ({
  chain_slug: b?.chain.slug ?? "", branch_code: b?.branch_code ?? "", title: b?.title ?? "", province: b?.province.slug ?? "",
  city: b?.city ?? "", district: b?.district ?? "", address: b?.address ?? "",
  latitude: b?.latitude != null ? String(b.latitude) : "", longitude: b?.longitude != null ? String(b.longitude) : "",
  phone: b?.phone ?? "", contract_status: b?.contract_status ?? "prospect", data_source: b?.data_source ?? "",
  source_reference: b?.source_reference ?? "",
});

function BranchForm({ token, chains, branch, setMsg, onClose, onSaved }: {
  token: string; chains: AdminChain[]; branch?: AdminBranch; setMsg: (m: Msg) => void;
  onClose: () => void; onSaved: (b: AdminBranch, created: boolean) => void;
}) {
  const [d, setD] = useState<BranchDraft>(() => toBranchDraft(branch));
  const [provinces, setProvinces] = useState<NamedRef[] | null>(null);
  const [errors, setErrors] = useState<{ field: string | null; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    // The 31 provinces are reference data served by the public coverage endpoint.
    network.coverage().then((r) => setProvinces(r.provinces.map((p) => ({ slug: p.slug, name: p.name }))))
      .catch((e) => setErrors({ field: null, text: (e as Error).message }));
  }, []);

  const set = (k: keyof BranchDraft) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setD({ ...d, [k]: e.target.value });
  const err = (k: string) => errors?.field === k
    ? <span role="alert" className="mt-1 block text-xs font-bold text-red-700">{errors.text}</span> : null;
  const cls = (k: string) => `${field} ${errors?.field === k ? "border-red-500" : ""}`;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErrors(null); setMsg(null);
    const body: Record<string, unknown> = {
      branch_code: d.branch_code, title: d.title || null, province: d.province, city: d.city,
      district: d.district || null, address: d.address || null, latitude: d.latitude.trim() || null,
      longitude: d.longitude.trim() || null, phone: d.phone.trim() || null, contract_status: d.contract_status,
      data_source: d.data_source, source_reference: d.source_reference,
    };
    if (!branch) body.chain_slug = d.chain_slug; // PUT rejects chain_slug; city is always sent with province
    try {
      const out = await apiRequest<AdminBranch>(branch ? `/admin/network/branches/${branch.id}` : "/admin/network/branches",
        { token, method: branch ? "PUT" : "POST", body: JSON.stringify(body) });
      onSaved(out, !branch);
    } catch (ex) {
      const f = ex instanceof ApiError ? ex.details?.field ?? null : null;
      setErrors({ field: typeof f === "string" ? f : null, text: (ex as Error).message });
    } finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} aria-label={branch ? `ویرایش شعبهٔ ${branch.title}` : "ثبت شعبهٔ تازه"}
      className="grid gap-3 rounded-xl border border-[#102B7A] bg-white p-4 md:grid-cols-3">
      <h2 className="font-black md:col-span-3">{branch ? `ویرایش شعبه: ${branch.title}` : "ثبت شعبهٔ تازه"}</h2>
      {errors && !errors.field && <p role="alert" className="rounded-lg bg-red-50 p-2 text-sm text-red-700 md:col-span-3">{errors.text}</p>}
      <label className="text-sm">زنجیره
        {branch ? <input className={field} value={branch.chain.name} disabled /> : (
          <select className={cls("chain_slug")} required value={d.chain_slug} onChange={set("chain_slug")}>
            <option value="">انتخاب کنید</option>{chains.map((c) => <option key={c.id} value={c.slug}>{c.name}</option>)}
          </select>)}
        {err("chain_slug")}</label>
      <label className="text-sm">کد شعبه<input className={cls("branch_code")} required dir="ltr" value={d.branch_code} onChange={set("branch_code")} />{err("branch_code")}</label>
      <label className="text-sm">عنوان شعبه<input className={cls("title")} value={d.title} onChange={set("title")} />{err("title")}</label>
      <label className="text-sm">استان
        <select className={cls("province")} required value={d.province} onChange={set("province")} disabled={!provinces}>
          <option value="">{provinces ? "انتخاب کنید" : "در حال بارگذاری…"}</option>
          {provinces?.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
        </select>{err("province")}</label>
      <label className="text-sm">شهر<input className={cls("city")} required value={d.city} onChange={set("city")} />{err("city")}</label>
      <label className="text-sm">محله / منطقه<input className={cls("district")} value={d.district} onChange={set("district")} />{err("district")}</label>
      <label className="text-sm md:col-span-2">نشانی<input className={cls("address")} value={d.address} onChange={set("address")} />{err("address")}</label>
      <label className="text-sm">تلفن<input className={cls("phone")} dir="ltr" inputMode="tel" value={d.phone} onChange={set("phone")} />{err("phone")}</label>
      <label className="text-sm">عرض جغرافیایی (latitude)<input className={cls("latitude")} dir="ltr" inputMode="decimal" placeholder="35.7" value={d.latitude} onChange={set("latitude")} />{err("latitude")}</label>
      <label className="text-sm">طول جغرافیایی (longitude)<input className={cls("longitude")} dir="ltr" inputMode="decimal" placeholder="51.4" value={d.longitude} onChange={set("longitude")} />{err("longitude")}</label>
      <label className="text-sm">وضعیت شعبه
        <select className={cls("contract_status")} value={d.contract_status} onChange={set("contract_status")}>
          {CONTRACT_STATUSES.map((s) => <option key={s} value={s}>{STATUS_FA[s]}</option>)}
        </select>{err("contract_status")}</label>
      <label className="text-sm">منبع داده
        <select className={cls("data_source")} required value={d.data_source} onChange={set("data_source")}>
          <option value="">انتخاب کنید</option>
          {DATA_SOURCES.map((s) => <option key={s} value={s}>{DATA_SOURCE_FA[s]}</option>)}
        </select>{err("data_source")}</label>
      <label className="text-sm md:col-span-2">مرجع منبع (شمارهٔ نامه، نام فایل، نشانی صفحه یا گزارش بازدید)
        <input className={cls("source_reference")} required value={d.source_reference} onChange={set("source_reference")} />{err("source_reference")}</label>
      <p className="text-xs text-neutral-500 md:col-span-3">مختصات اختیاری است ولی باید هر دو با هم و داخل محدودهٔ ایران باشند. چیزی را حدس نزنید؛ فقط از منبع ثبت‌شده وارد کنید.</p>
      <div className="flex gap-2 md:col-span-3">
        <button className={btn} disabled={busy}>{busy ? "در حال ذخیره…" : branch ? "ذخیرهٔ تغییرات" : "ثبت شعبه"}</button>
        <button type="button" className={ghost} onClick={onClose}>انصراف</button>
      </div>
    </form>
  );
}
