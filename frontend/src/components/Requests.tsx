"use client";
import Link from "next/link";
import { useEffect, useState, FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiRequest, catalog, newIdempotencyKey } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
type Item = { slug: string; name: string; quantity: number };
type Inquiry = {
  id: number;
  subject: string;
  message: string;
  kind: string;
  status: string;
  response: string | null;
  items: Item[];
  created_at: string;
};
const labels: Record<string, string> = {
  open: "ثبت‌شده",
  reviewing: "در حال بررسی",
  answered: "پاسخ داده‌شده",
  closed: "بسته‌شده",
};
const field = "w-full rounded-xl border p-3";
export default function Requests({
  create = false,
  admin = false,
}: {
  create?: boolean;
  admin?: boolean;
}) {
  const { user, token, loading } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [items, setItems] = useState<Item[]>([]),
    [query, setQuery] = useState(""),
    [results, setResults] = useState<Item[]>([]);
  const [subject, setSubject] = useState(""),
    [message, setMessage] = useState(""),
    [kind, setKind] = useState("price");
  const [orgs, setOrgs] = useState<
      { id: number; name?: string; name_fa?: string; display_name?: string }[]
    >([]),
    [org, setOrg] = useState("");
  const [rows, setRows] = useState<Inquiry[]>([]),
    [page, setPage] = useState(1),
    [pages, setPages] = useState(1);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [key, setKey] = useState(""),
    [reload, setReload] = useState(0);
  const [responses, setResponses] = useState<Record<number, string>>({});
  useEffect(() => {
    setKey(newIdempotencyKey());
  }, []);
  useEffect(() => {
    const slug = params.get("slug");
    if (create && slug)
      catalog
        .get(slug)
        .then(({ product: p }) => {
          const requestedQuantity = Number(params.get("quantity") ?? 1);
          setItems([{ slug: p.slug, name: p.name, quantity: Number.isInteger(requestedQuantity) && requestedQuantity > 0 && requestedQuantity <= 100000 ? requestedQuantity : 1 }]);
          setSubject("استعلام " + p.name);
        })
        .catch((e) => setError(e.message));
  }, [create, params]);
  useEffect(() => {
    if (!token || !create) return;
    apiRequest<{
      items: {
        id: number;
        name?: string;
        name_fa?: string;
        display_name?: string;
      }[];
    }>("/organizations", { token })
      .then((r) => setOrgs(r.items))
      .catch((e) => setError(e.message));
  }, [token, create]);
  useEffect(() => {
    if (!token || create || (admin && user?.role !== "admin")) return;
    let live = true;
    setBusy(true);
    apiRequest<{ items: Inquiry[]; pages: number }>(
      (admin ? "/admin/requests" : "/requests") + "?page=" + page,
      { token },
    )
      .then((r) => {
        if (live) {
          setRows(r.items);
          setPages(r.pages);
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
  }, [token, create, admin, user?.role, page, reload]);
  if (loading) return <p className="p-8">در حال بررسی ورود…</p>;
  if (!user || !token)
    return (
      <main className="container py-12">
        <h1 className="text-2xl">درخواست و پیگیری</h1>
        {create && (
          <p className="my-4">
            این یک استعلام است، نه خرید قطعی: پس از ورود، کالا و تعداد انتخابی
            حفظ می‌شود؛ پس از ثبت، شمارهٔ پیگیری می‌گیرید و قیمت، موجودی و
            زمان تحویل پس از بررسی در «درخواست‌های من» اعلام می‌شود.
          </p>
        )}
        <p className="my-4">برای حفظ و پیگیری درخواست، وارد حساب خود شوید.</p>
        <Link
          className="btn-primary"
          href={
            "/login?next=" +
            encodeURIComponent(
              create
                ? "/requests/new" +
                    (params.get("slug")
                      ? "?slug=" + encodeURIComponent(params.get("slug")!) + "&quantity=" + encodeURIComponent(params.get("quantity") ?? "1")
                      : "")
                : "/requests",
            )
          }
        >
          ورود به حساب
        </Link>
      </main>
    );
  if (admin && user.role !== "admin")
    return <p className="p-8">دسترسی مدیریت لازم است.</p>;
  async function search(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const r = await catalog.list({ q: query, page_size: 20 });
      setResults(
        r.items.map((p) => ({ slug: p.slug, name: p.name, quantity: 1 })),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await apiRequest("/requests", {
        token: token!,
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({
          kind,
          subject,
          message,
          organization_id: org ? Number(org) : null,
          items: items.map(({ slug, quantity }) => ({ slug, quantity })),
        }),
      });
      router.push("/requests");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function answer(id: number, status: string) {
    setBusy(true);
    setError("");
    try {
      await apiRequest("/admin/requests/" + id, {
        token: token!,
        method: "PATCH",
        body: JSON.stringify({ status, response: responses[id] ?? "" }),
      });
      setReload((v) => v + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="container max-w-4xl py-8">
      <nav className="flex flex-wrap gap-5 mb-6">
        <Link href="/search">کاتالوگ</Link>
        <Link href="/requests">درخواست‌های من</Link>
        <Link href="/requests/new">درخواست جدید</Link>
        {user.role === "admin" && <Link href="/crm">پیگیری مشتریان</Link>}
      </nav>
      <h1 className="text-2xl font-bold mb-5">
        {create
          ? "ثبت استعلام یا درخواست"
          : admin
            ? "پیگیری درخواست‌های مشتریان"
            : "درخواست‌های من"}
      </h1>
      {error && (
        <p role="alert" className="border rounded-xl p-4 my-4">
          {error}
        </p>
      )}
      {create ? (
        <>
          <p className="mb-5">
            این درخواست سفارش خرید یا تأیید قیمت نیست. شرایط تأمین پس از بررسی
            پاسخ داده می‌شود.
          </p>
          <form onSubmit={search} className="flex gap-2 mb-4">
            <input
              aria-label="جست‌وجوی کالا"
              className={field}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="نام کالای مورد درخواست"
              required
            />
            <button className="btn-primary">جست‌وجو</button>
          </form>
          <ul className="mb-5">
            {results.map((p) => (
              <li
                key={p.slug}
                className="flex justify-between gap-3 p-2 border-b"
              >
                <span>{p.name}</span>
                <button
                  type="button"
                  disabled={
                    items.some((i) => i.slug === p.slug) ||
                    items.length >= 50 ||
                    busy
                  }
                  onClick={() => {
                    setItems((v) => [...v, p]);
                    setKey(newIdempotencyKey());
                  }}
                >
                  افزودن
                </button>
              </li>
            ))}
          </ul>
          <form
            onSubmit={submit}
            onChange={() => setKey(newIdempotencyKey())}
            className="space-y-4"
          >
            <fieldset disabled={busy} className="space-y-4">
              <label className="block">
                نوع درخواست
                <select
                  className={field}
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                >
                  <option value="price">استعلام قیمت و موجودی</option>
                  <option value="procurement">تأمین سازمانی</option>
                  <option value="support">پشتیبانی</option>
                </select>
              </label>
              {orgs.length > 0 && (
                <label className="block">
                  سازمان
                  <select
                    className={field}
                    value={org}
                    onChange={(e) => setOrg(e.target.value)}
                  >
                    <option value="">درخواست شخصی</option>
                    {orgs.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.display_name ?? o.name_fa ?? o.name ?? o.id}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="block">
                موضوع
                <input
                  className={field}
                  value={subject}
                  maxLength={200}
                  required
                  onChange={(e) => setSubject(e.target.value)}
                />
              </label>
              {items.map((p) => (
                <div
                  key={p.slug}
                  className="flex flex-wrap items-center gap-3 border rounded-xl p-3"
                >
                  <span className="flex-1">{p.name}</span>
                  <label>
                    تعداد
                    <input
                      className="w-24 border p-2 mx-2"
                      type="number"
                      min={1}
                      max={100000}
                      required
                      value={p.quantity}
                      onChange={(e) =>
                        setItems((v) =>
                          v.map((i) =>
                            i.slug === p.slug
                              ? { ...i, quantity: Number(e.target.value) }
                              : i,
                          ),
                        )
                      }
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => {
                      setItems((v) => v.filter((i) => i.slug !== p.slug));
                      setKey(newIdempotencyKey());
                    }}
                  >
                    حذف
                  </button>
                </div>
              ))}
              <label className="block">
                توضیحات و شرایط مورد نیاز
                <textarea
                  className={field}
                  rows={4}
                  maxLength={4000}
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                />
              </label>
              <button
                className="btn-primary"
                disabled={!key || (kind !== "support" && !items.length)}
              >
                {busy ? "در حال ثبت…" : "ثبت درخواست"}
              </button>
            </fieldset>
          </form>
        </>
      ) : (
        <>
          {busy && <p role="status">در حال دریافت…</p>}
          {!busy && !rows.length && !error && <p>درخواستی ثبت نشده است.</p>}
          {rows.map((r) => (
            <article
              key={r.id}
              className="border rounded-2xl p-5 my-4 space-y-3"
            >
              <div className="flex justify-between gap-3">
                <h2 className="font-bold">{r.subject}</h2>
                <span>{labels[r.status] ?? r.status}</span>
              </div>
              <p>
                شماره پیگیری: {r.id} ·{" "}
                {new Date(r.created_at).toLocaleDateString("fa-IR")}
              </p>
              <p className="whitespace-pre-wrap">{r.message}</p>
              <ul>
                {r.items.map((i) => (
                  <li key={i.slug}>
                    <Link href={"/products/" + encodeURIComponent(i.slug)}>
                      {i.name}
                    </Link>{" "}
                    — تعداد {i.quantity}
                  </li>
                ))}
              </ul>
              {r.response && (
                <p className="bg-brand-gray rounded-xl p-3 whitespace-pre-wrap">
                  پاسخ: {r.response}
                </p>
              )}
              {admin && (
                <div className="space-y-3">
                  <label className="block">
                    پاسخ و توضیح وضعیت
                    <textarea
                      className={field}
                      maxLength={4000}
                      value={responses[r.id] ?? ""}
                      onChange={(e) =>
                        setResponses((v) => ({ ...v, [r.id]: e.target.value }))
                      }
                    />
                  </label>
                  <div className="flex flex-wrap gap-3">
                    {["reviewing", "answered", "closed"].map((s) => (
                      <button
                        className="btn-primary"
                        disabled={busy || !responses[r.id]?.trim()}
                        key={s}
                        onClick={() => answer(r.id, s)}
                      >
                        {labels[s]}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </article>
          ))}
          <nav className="flex justify-between">
            <button
              disabled={page <= 1 || busy}
              onClick={() => setPage((v) => v - 1)}
            >
              صفحه قبل
            </button>
            <span>
              {page} / {pages}
            </span>
            <button
              disabled={page >= pages || busy}
              onClick={() => setPage((v) => v + 1)}
            >
              صفحه بعد
            </button>
          </nav>
        </>
      )}
    </main>
  );
}
