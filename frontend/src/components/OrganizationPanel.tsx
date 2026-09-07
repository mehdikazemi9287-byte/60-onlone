"use client";
import Link from "next/link";
import PurchaseDocument from "./PurchaseDocument";
import { FormEvent, useEffect, useState } from "react";
import { apiRequest, newIdempotencyKey } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
type Org = {
  id: number;
  display_name: string;
  membership: { role: string; status: string };
};
type PR = {
  id: number;
  title: string;
  request_number: string;
  status: string;
  requester_user_id: number;
};
type Document = {
  id: number;
  title?: string;
  rfq_number?: string;
  po_number?: string;
  status: string;
};
const states: Record<string, string> = {
  draft: "پیش‌نویس",
  submitted: "ارسال‌شده",
  under_review: "در حال بررسی",
  approved: "تأیید‌شده",
  rejected: "ردشده",
  cancelled: "لغوشده",
  open: "باز",
  closed: "بسته",
  awarded: "انتخاب پیشنهاد",
};
export default function OrganizationPanel() {
  const { user, token, loading } = useAuth();
  const [orgs, setOrgs] = useState<Org[]>([]),
    [selected, setSelected] = useState("");
  const [prs, setPrs] = useState<PR[]>([]),
    [rfqs, setRfqs] = useState<Document[]>([]),
    [pos, setPos] = useState<Document[]>([]),
    [error, setError] = useState("");
  const [title, setTitle] = useState(""),
    [description, setDescription] = useState(""),
    [quantity, setQuantity] = useState(1),
    [city, setCity] = useState(""),
    [province, setProvince] = useState("");
  const [busy, setBusy] = useState(false),
    [key, setKey] = useState(""),
    [reload, setReload] = useState(0),
    [notice, setNotice] = useState("");
  useEffect(() => setKey(newIdempotencyKey()), []);
  useEffect(() => {
    if (!token) return;
    apiRequest<{ items: Org[] }>("/organizations", { token })
      .then((r) => {
        const active = r.items.filter((o) => o.membership.status === "active");
        setOrgs(active);
        setSelected(active.length ? String(active[0].id) : "");
      })
      .catch((e) => setError(e.message));
  }, [token]);
  useEffect(() => {
    if (!token || !selected) return;
    let live = true;
    setError("");
    setBusy(true);
    const base = "/orgs/" + selected + "/procurement/";
    Promise.all([
      apiRequest<{ items: PR[] }>(base + "requests", { token }),
      apiRequest<{ items: Document[] }>(base + "rfqs", { token }),
      apiRequest<{ items: Document[] }>(base + "purchase-orders", { token }),
    ])
      .then(([a, b, c]) => {
        if (live) {
          setPrs(a.items);
          setRfqs(b.items);
          setPos(c.items);
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      })
      .finally(() => {
        if (live) setBusy(false);
      });
    return () => {
      live = false;
    };
  }, [token, selected, reload]);
  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await apiRequest("/orgs/" + selected + "/procurement/requests", {
        token: token!,
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({
          title,
          delivery_province: province || null,
          delivery_city: city || null,
          items: [{ free_text_description: description, quantity }],
        }),
      });
      setNotice(
        "پیش‌نویس درخواست خرید ثبت شد؛ برای ارسال، ردیف آن را بررسی کنید.",
      );
      setTitle("");
      setDescription("");
      setKey(newIdempotencyKey());
      setReload((v) => v + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function action(id: number, op: string) {
    setBusy(true);
    setError("");
    try {
      await apiRequest(
        "/orgs/" +
          selected +
          "/procurement/requests/" +
          id +
          "/" +
          (op === "approve" || op === "reject" ? "approve" : op),
        { token: token!, method: "POST", body: JSON.stringify({ action: op }) },
      );
      setReload((v) => v + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (loading) return <p className="p-8">در حال بررسی ورود…</p>;
  if (!user)
    return (
      <main className="container-page py-12">
        <h1 className="text-2xl">تأمین سازمانی</h1>
        <p className="my-4">
          برای مشاهده درخواست‌ها و اعتبار سازمان خود وارد شوید.
        </p>
        <Link className="btn-primary" href="/login">
          ورود
        </Link>
      </main>
    );
  const admin =
    orgs.find((o) => String(o.id) === selected)?.membership.role ===
    "organization_admin";
  return (
    <main className="container-page py-8 space-y-6">
      <h1 className="text-2xl font-bold">تدارکات سازمانی</h1>
      <nav className="flex flex-wrap gap-5">
        <Link href="/wallet">اعتبار کارکنان</Link>
        <Link href="/requests/new">استعلام تأمین کالا</Link>
        <Link href="/account">حساب من</Link>
      </nav>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {!orgs.length ? (
        <p>عضویت فعال سازمانی برای این حساب یافت نشد.</p>
      ) : (
        <>
          <label className="block">
            سازمان
            <select
              className="block border rounded-xl p-3"
              value={selected}
              onChange={(e) => {
                setSelected(e.target.value);
                setKey(newIdempotencyKey());
                setPrs([]);
                setRfqs([]);
                setPos([]);
              }}
            >
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.display_name}
                </option>
              ))}
            </select>
          </label>
          <section className="border rounded-2xl p-5">
            <h2 className="text-xl font-bold mb-4">درخواست خرید جدید</h2>
            <form
              onSubmit={create}
              onChange={() => setKey(newIdempotencyKey())}
            >
              <fieldset disabled={busy} className="space-y-4">
                <label className="block">
                  عنوان
                  <input
                    className="block border rounded-xl p-3 w-full"
                    required
                    maxLength={200}
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                </label>
                <label className="block">
                  شرح دقیق کالا و گونه مورد نیاز
                  <textarea
                    className="block border rounded-xl p-3 w-full"
                    required
                    maxLength={2000}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </label>
                <label className="block">
                  تعداد
                  <input
                    className="block border rounded-xl p-3"
                    required
                    type="number"
                    min={1}
                    max={100000}
                    value={quantity}
                    onChange={(e) => setQuantity(Number(e.target.value))}
                  />
                </label>
                <div className="grid sm:grid-cols-2 gap-4">
                  <label>
                    استان تحویل
                    <input
                      className="block border rounded-xl p-3 w-full"
                      maxLength={100}
                      value={province}
                      onChange={(e) => setProvince(e.target.value)}
                    />
                  </label>
                  <label>
                    شهر تحویل
                    <input
                      className="block border rounded-xl p-3 w-full"
                      maxLength={100}
                      value={city}
                      onChange={(e) => setCity(e.target.value)}
                    />
                  </label>
                </div>
                <p>این پیش‌نویس تعهد خرید یا پیش‌فاکتور دارای قیمت نیست.</p>
                <button className="btn-primary" disabled={!key}>
                  ثبت پیش‌نویس
                </button>
              </fieldset>
            </form>
          </section>
          <section>
            <h2 className="text-xl font-bold">درخواست‌های خرید</h2>
            {busy && <p>در حال دریافت…</p>}
            {!busy && !prs.length && <p>درخواستی ثبت نشده است.</p>}
            {prs.map((p) => (
              <article
                className="border rounded-xl p-4 my-3 space-y-3"
                key={p.id}
              >
                <h3 className="font-bold">{p.title}</h3>
                <p>
                  {p.request_number} · {states[p.status] ?? p.status}
                </p>
                <div className="flex gap-3 flex-wrap">
                  {p.status === "draft" &&
                    (admin || p.requester_user_id === user.id) && (
                      <button
                        disabled={busy}
                        className="btn-primary"
                        onClick={() => action(p.id, "submit")}
                      >
                        ارسال برای بررسی
                      </button>
                    )}
                  {admin &&
                    ["submitted", "under_review"].includes(p.status) && (
                      <>
                        <button
                          disabled={busy}
                          onClick={() => action(p.id, "approve")}
                        >
                          تأیید درخواست
                        </button>
                        <button
                          disabled={busy}
                          onClick={() => action(p.id, "reject")}
                        >
                          رد درخواست
                        </button>
                      </>
                    )}
                </div>
              </article>
            ))}
          </section>
          {[
            { title: "استعلام‌های تأمین‌کنندگان", items: rfqs },
            { title: "سفارش‌های خرید سازمانی", items: pos },
          ].map((group) => (
            <section key={group.title}>
              <h2 className="text-xl font-bold">{group.title}</h2>
              {!busy && !group.items.length && <p>سندی ثبت نشده است.</p>}
              {group.items.map((d) => (
                <article className="border rounded-xl p-4 my-3" key={d.id}>
                  <p>{d.title ?? d.rfq_number ?? d.po_number}</p>
                  <p>{states[d.status] ?? d.status}</p>
                  {d.po_number && (
                    <PurchaseDocument
                      organizationId={selected}
                      id={d.id}
                      token={token!}
                    />
                  )}
                </article>
              ))}
            </section>
          ))}
        </>
      )}
    </main>
  );
}
