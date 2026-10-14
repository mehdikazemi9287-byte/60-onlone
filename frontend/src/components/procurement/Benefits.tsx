"use client";

// Employee benefits. HR: create a program (fixed pack / choice of packs / credit), open → close, then turn
// all selections into ONE organization purchase request. Employees: choose a pack or see their credit.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Gift, Lock, Plus } from "lucide-react";
import { apiRequest, newIdempotencyKey } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useOrganization } from "@/components/organization/Dashboard";
import { storefront, type PackSummary } from "@/lib/storefront";
import { formatPrice, toPersianNum } from "@/lib/utils";
import { Chip, Drawer, Empty, Notice, cx, n } from "./ui";
import s from "./proc.module.css";

type Program = { id: number; title: string; mode: "fixed_pack" | "pack_choice" | "credit"; status: "draft" | "open" | "closed"; note: string | null;
  closes_at: string | null; packs: PackSummary[]; selections: { total: number; by_pack: { pack_id: number; count: number }[] };
  my_selection?: { pack_id: number; status: string } | null; purchase_request_id: number | null;
  credit?: { id: number; allocated_minor: number; expires_at: string | null; category_slugs_json: string | null }[] };
const MODE: Record<string, string> = { fixed_pack: "پک ثابت", pack_choice: "انتخاب بین پک‌ها", credit: "اعتبار کارمند" };
const STATUS: Record<string, [string, "muted" | "ok" | "info"]> = { draft: ["پیش‌نویس", "muted"], open: ["باز برای انتخاب", "ok"], closed: ["بسته", "info"] };

export function OrgBenefits() {
  const o = useOrganization(true);
  const [items, setItems] = useState<Program[] | null>(null), [error, setError] = useState(""), [flash, setFlash] = useState("");
  const [create, setCreate] = useState(false), [toPr, setToPr] = useState<Program | null>(null);
  const load = useCallback(() => {
    if (o.token && o.selected) apiRequest<{ items: Program[] }>(`/orgs/${o.selected}/benefits`, { token: o.token }).then((r) => { setItems(r.items); setError(""); }).catch((e) => setError(e.message));
  }, [o.token, o.selected]);
  useEffect(load, [load]);
  const hr = o.org?.membership.role === "organization_admin";
  const status = async (p: Program, st: string) => {
    try { await apiRequest(`/orgs/${o.selected}/benefits/${p.id}/status`, { token: o.token!, method: "POST", body: JSON.stringify({ status: st }) }); setFlash(st === "open" ? "برنامه باز شد و به کارکنان اطلاع داده شد." : "مهلت انتخاب بسته شد."); load(); }
    catch (e) { setFlash(e instanceof Error ? e.message : "ناموفق"); }
  };
  if (error) return <div className={s.root}><Empty icon={<Lock />} title="عضویت سازمانی لازم است">{error}</Empty></div>;
  if (!items) return <div className={s.root}><div className={s.skeleton} style={{ height: 240 }} /></div>;
  return (
    <div className={s.root}>
      <header className={s.head}><div className={s.headRow}><div><div className={s.eyebrow}>میز کار سازمانی</div><h1 className={s.title}>مزایای کارکنان</h1>
        <div className={s.meta}><span>{o.org?.display_name}</span><span>پک ثابت، انتخاب بین پک‌ها یا اعتبار کارمند</span></div></div>
        {hr && <button className={cx(s.btn, s.primary)} onClick={() => setCreate(true)}><Plus /> برنامه جدید</button>}</div></header>
      {flash && <Notice tone="info" icon={<CheckCircle2 />}>{flash}</Notice>}
      {!items.length ? <Empty icon={<Gift />} title="برنامه مزایایی تعریف نشده است">{hr ? "یک برنامه بسازید و برای کارکنان باز کنید." : "برنامه‌ای برای شما باز نیست."}</Empty> : (
        <div className={s.stack}>{items.map((p) => (
          <section key={p.id} className={s.card}>
            <div className={s.sectionHead}><div><h2>{p.title} <Chip tone={STATUS[p.status][1]} dot>{STATUS[p.status][0]}</Chip></h2><p>{MODE[p.mode]}{p.note ? ` · ${p.note}` : ""}</p></div>
              {hr && <div className={s.headActions}>
                {p.status === "draft" && <button className={cx(s.btn, s.sm, s.primary)} onClick={() => status(p, "open")}>باز کردن برای کارکنان</button>}
                {p.status === "open" && <button className={cx(s.btn, s.sm)} onClick={() => status(p, "closed")}>بستن مهلت</button>}
                {p.status === "closed" && p.mode !== "credit" && !p.purchase_request_id && <button className={cx(s.btn, s.sm, s.primary)} onClick={() => setToPr(p)}>ساخت درخواست خرید تجمیعی</button>}
                {p.purchase_request_id && <Link className={cx(s.btn, s.sm)} href={`/organization/requests/${p.purchase_request_id}?org=${o.selected}`}>درخواست خرید</Link>}
              </div>}</div>
            {p.mode !== "credit" && <div className={s.grid3}>{p.packs.map((pk) => {
              const c = p.selections.by_pack.find((x) => x.pack_id === pk.id)?.count ?? 0;
              return <div key={pk.id} className={s.stat}><small>{pk.title_fa}</small><b>{n(c)} انتخاب</b><span className={s.small}>{n(pk.item_count)} قلم · {pk.price_minor != null ? formatPrice(pk.price_minor) : "قیمت با استعلام"}</span></div>; })}</div>}
            <p className={s.small} style={{ marginTop: 8 }}>مجموع انتخاب‌ها: {n(p.selections.total)}</p>
          </section>))}</div>
      )}
      {create && o.token && <CreateProgram token={o.token} org={o.selected} onClose={() => setCreate(false)} onDone={() => { setCreate(false); setFlash("برنامه ساخته شد (پیش‌نویس)."); load(); }} />}
      {toPr && o.token && <ToRequest token={o.token} org={o.selected} p={toPr} onClose={() => setToPr(null)} onDone={(m) => { setToPr(null); setFlash(m); load(); }} />}
    </div>
  );
}

function CreateProgram({ token, org, onClose, onDone }: { token: string; org: string; onClose: () => void; onDone: () => void }) {
  const [packs, setPacks] = useState<PackSummary[]>([]), [title, setTitle] = useState(""), [mode, setMode] = useState("pack_choice"), [picked, setPicked] = useState<string[]>([]);
  const [note, setNote] = useState(""), [err, setErr] = useState(""), [key] = useState(newIdempotencyKey);
  useEffect(() => { storefront.packs().then((r) => setPacks(r.items)).catch(() => {}); }, []);
  const toggle = (slug: string) => setPicked((x) => mode === "fixed_pack" ? [slug] : x.includes(slug) ? x.filter((y) => y !== slug) : [...x, slug]);
  const save = async () => {
    try { await apiRequest(`/orgs/${org}/benefits`, { token, method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify({ title, mode, note, pack_slugs: mode === "credit" ? [] : picked }) }); onDone(); }
    catch (e) { setErr(e instanceof Error ? e.message : "ناموفق"); }
  };
  return (
    <Drawer open title="برنامه مزایای جدید" onClose={onClose} footer={<button className={cx(s.btn, s.primary)} disabled={title.trim().length < 3} onClick={save}>ذخیره پیش‌نویس</button>}>
      <div className={s.stack}>
        <label className={s.field}>عنوان<input className={s.input} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="مثلاً هدیه نوروز کارکنان" /></label>
        <label className={s.field}>نوع برنامه<select className={s.select} value={mode} onChange={(e) => { setMode(e.target.value); setPicked([]); }}>{Object.entries(MODE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        {mode === "credit" ? <Notice tone="info" icon={<AlertTriangle />}>در این حالت کارکنان با اعتبار تخصیص‌یافته از بخش «اعتبار سازمان» و محدودیت دسته‌های تعیین‌شده خرید می‌کنند؛ پرداخت ترکیبی اعتبار و نقد طبق سیاست سازمان است.</Notice> : (
          <div><b className={s.small}>{mode === "fixed_pack" ? "یک پک انتخاب کنید" : "۲ تا ۶ پک انتخاب کنید"}</b>
            {packs.map((p) => <label key={p.slug} className={s.row} style={{ marginTop: 6 }}><input type={mode === "fixed_pack" ? "radio" : "checkbox"} name="packs" checked={picked.includes(p.slug)} onChange={() => toggle(p.slug)} />
              {p.title_fa} <span className={s.small} style={{ color: "var(--muted)" }}>({toPersianNum(p.item_count)} قلم)</span></label>)}</div>)}
        <label className={s.field}>توضیح برای کارکنان<textarea className={s.textarea} rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></label>
        {err && <Notice tone="bad" icon={<AlertTriangle />}>{err}</Notice>}
      </div>
    </Drawer>
  );
}

function ToRequest({ token, org, p, onClose, onDone }: { token: string; org: string; p: Program; onClose: () => void; onDone: (m: string) => void }) {
  const [d, setD] = useState({ label: "", province: "", city: "", address: "", recipient_name: "", recipient_phone: "" }), [err, setErr] = useState(""), [key] = useState(newIdempotencyKey);
  const send = async () => {
    try { const r = await apiRequest<{ purchase_request_id: number; items: number; units: number }>(`/orgs/${org}/benefits/${p.id}/purchase-request`, { token, method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify({ destination: d }) });
      onDone(`درخواست خرید تجمیعی ساخته شد: ${toPersianNum(r.items)} قلم، ${toPersianNum(r.units)} عدد.`); }
    catch (e) { setErr(e instanceof Error ? e.message : "ناموفق"); }
  };
  const f = (k: keyof typeof d, l: string) => <label className={s.field}>{l}<input className={s.input} value={d[k]} onChange={(e) => setD({ ...d, [k]: e.target.value })} /></label>;
  return (
    <Drawer open title={`درخواست خرید: ${p.title}`} onClose={onClose} footer={<button className={cx(s.btn, s.primary)} onClick={send}>ساخت درخواست</button>}>
      <div className={s.stack}>
        <p className={s.small}>اقلام همه انتخاب‌ها تجمیع و یک درخواست خرید سازمانی (پیش‌نویس) ساخته می‌شود؛ مسیر استعلام و تأیید مثل سایر خریدهاست.</p>
        <div className={s.grid2}>{f("label", "نام مقصد")}{f("province", "استان")}{f("city", "شهر")}{f("recipient_name", "گیرنده")}{f("recipient_phone", "تلفن گیرنده")}</div>
        {f("address", "نشانی")}
        {err && <Notice tone="bad" icon={<AlertTriangle />}>{err}</Notice>}
      </div>
    </Drawer>
  );
}

export function MyBenefits() {
  const { token, user, loading } = useAuth();
  const [items, setItems] = useState<Program[] | null>(null), [msg, setMsg] = useState("");
  const load = useCallback(() => { if (token) apiRequest<{ items: Program[] }>("/me/benefits", { token }).then((r) => setItems(r.items)).catch(() => setItems([])); }, [token]);
  useEffect(load, [load]);
  const choose = async (p: Program, slug: string) => {
    try { await apiRequest(`/me/benefits/${p.id}/select`, { token: token!, method: "POST", body: JSON.stringify({ pack_slug: slug }) }); setMsg("انتخاب شما ثبت شد."); load(); }
    catch (e) { setMsg(e instanceof Error ? e.message : "ناموفق"); }
  };
  if (loading) return <div className={s.root}><div className={s.skeleton} style={{ height: 200 }} /></div>;
  if (!user) return <div className={s.root}><Empty icon={<Lock />} title="ورود لازم است" action={<Link className={cx(s.btn, s.primary)} href="/login?next=/benefits">ورود</Link>} /></div>;
  return (
    <div className={s.root}>
      <header className={s.head}><div className={s.eyebrow}>حساب من</div><h1 className={s.title}><Gift /> مزایای کارکنان</h1></header>
      {msg && <Notice tone="info" icon={<CheckCircle2 />}>{msg}</Notice>}
      {!items ? <div className={s.skeleton} style={{ height: 200 }} /> : !items.length ? <Empty icon={<Gift />} title="برنامه مزایای فعالی برای شما نیست">برنامه‌ها را سازمان شما تعریف می‌کند.</Empty> : (
        <div className={s.stack}>{items.map((p) => (
          <section key={p.id} className={s.card}>
            <div className={s.sectionHead}><div><h2>{p.title} <Chip tone={STATUS[p.status][1]} dot>{STATUS[p.status][0]}</Chip></h2><p>{MODE[p.mode]}{p.note ? ` · ${p.note}` : ""}</p></div></div>
            {p.mode === "credit" ? (
              !p.credit?.length ? <p className={s.small}>اعتبار فعالی برای شما تخصیص داده نشده است.</p>
                : <div>{p.credit.map((c) => <p key={c.id} className={s.small}>اعتبار: <b>{formatPrice(c.allocated_minor)}</b>{c.expires_at ? ` · تا ${new Date(c.expires_at).toLocaleDateString("fa-IR")}` : ""}{c.category_slugs_json ? " · محدود به دسته‌های مشخص" : ""}</p>)}
                  <Link className={cx(s.btn, s.sm, s.primary)} href="/search">خرید با اعتبار</Link></div>
            ) : <div className={s.grid3}>{p.packs.map((pk) => {
              const mine = p.my_selection?.pack_id === pk.id && p.my_selection.status === "selected";
              return <div key={pk.slug} className={s.stat} style={mine ? { outline: "2px solid var(--blue)" } : undefined}>
                <small><Link href={`/packs/${pk.slug}`}>{pk.title_fa}</Link></small><b>{n(pk.item_count)} قلم</b>
                {p.status === "open" ? <button className={cx(s.btn, s.sm, mine ? undefined : s.primary)} disabled={mine} onClick={() => choose(p, pk.slug)}>{mine ? "انتخاب شما" : "انتخاب این پک"}</button>
                  : mine ? <Chip tone="ok">انتخاب شما</Chip> : null}</div>; })}</div>}
          </section>))}</div>
      )}
    </div>
  );
}
