"use client";
import Link from "next/link";
import LegacyMatch from "./LegacyMatch";
import { FormEvent, useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
type Master = {
  id: number;
  canonical_name_fa: string;
  brand?: string;
  category?: string;
  status: string;
};
type Preview = {
  total: number;
  valid: number;
  invalid: number;
  created: number;
  updated: number;
  published: number;
  confirmed: boolean;
  preview_token: string | null;
  rows: {
    row_number: number;
    status: string;
    errors: string[];
    data: { canonical_name_fa: string; category_slug: string };
  }[];
};
export default function AdminCatalog() {
  const { user, token, loading } = useAuth();
  const [q, setQ] = useState(""),
    [query, setQuery] = useState(""),
    [page, setPage] = useState(1),
    [total, setTotal] = useState(0),
    [rows, setRows] = useState<Master[]>([]);
  const [csv, setCsv] = useState(""),
    [source, setSource] = useState(""),
    [preview, setPreview] = useState<Preview | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!token || user?.role !== "admin") return;
    let live = true;
    apiRequest<{ items: Master[]; total: number }>(
      "/admin/catalog/products?status=&page_size=25&page=" +
        page +
        "&q=" +
        encodeURIComponent(query),
      { token },
    )
      .then((r) => {
        if (live) {
          setRows(r.items);
          setTotal(r.total);
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [token, user?.role, page, query, refresh]);
  async function upload(confirm: boolean) {
    setBusy(true);
    setError("");
    try {
      const result = await apiRequest<Preview>("/admin/catalog/import", {
        token: token!,
        method: "POST",
        body: JSON.stringify({
          csv_text: csv,
          source,
          confirm,
          preview_token: preview?.preview_token,
        }),
      });
      setPreview(result);
      if (result.confirmed) setRefresh((v) => v + 1);
    } catch (e) {
      setError((e as Error).message);
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }
  if (loading) return <p className="p-8">در حال بررسی ورود…</p>;
  if (!user)
    return (
      <main className="container-page py-12">
        <Link href="/login">ورود به حساب مدیر</Link>
      </main>
    );
  if (user.role !== "admin")
    return <p className="p-8">دسترسی مدیریت لازم است.</p>;
  return (
    <main className="container-page py-8 space-y-6">
      <h1 className="text-2xl font-bold">مدیریت مخزن کالا</h1>
      <nav className="flex gap-5">
        <Link href="/admin/suppliers">تأمین‌کنندگان</Link>
        <Link href="/crm">درخواست‌های مشتریان</Link>
        <Link href="/account">حساب من</Link>
        <Link href="/search">کاتالوگ عمومی</Link>
      </nav>
      {error && <p role="alert">{error}</p>}
      <form
        className="flex gap-3"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          setPage(1);
          setQuery(q);
        }}
      >
        <input
          className="border rounded-xl p-3 flex-1 min-w-0"
          aria-label="جست‌وجو در مخزن"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="btn-primary">جست‌وجو</button>
      </form>
      <p>{total} کالای مرجع مطابق جست‌وجو</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {rows.map((p) => (
          <article key={p.id} className="border rounded-xl p-4">
            <h2 className="font-bold">{p.canonical_name_fa}</h2>
            <p>شناسه مرجع: {p.id}</p>
            <p>
              {p.brand} · {p.category} · {p.status}
            </p>
          </article>
        ))}
      </div>
      <nav className="flex justify-between">
        <button disabled={page <= 1} onClick={() => setPage((v) => v - 1)}>
          قبلی
        </button>
        <span>{page}</span>
        <button
          disabled={page * 25 >= total}
          onClick={() => setPage((v) => v + 1)}
        >
          بعدی
        </button>
      </nav>
      <LegacyMatch token={token!} masters={rows} />
      <section className="border rounded-2xl p-5 space-y-4">
        <h2 className="text-xl font-bold">ورود گروهی با پیش‌نمایش</h2>
        <p>
          فایل UTF-8 با ستون‌های canonical_name_fa و category_slug لازم است.
          مقدار active در publish_status درخواست انتشار کاتالوگ است؛ قیمت و
          موجودی فروش باید جداگانه تأیید شوند.
        </p>
        <label className="block">
          فایل CSV
          <input
            className="block my-2 max-w-full"
            type="file"
            accept=".csv,text/csv"
            disabled={busy}
            onChange={async (e) => {
              const f = e.target.files?.[0];
              setPreview(null);
              setCsv("");
              if (f) {
                if (f.size > 2000000) {
                  setError("حداکثر حجم فایل دو مگابایت است");
                  return;
                }
                setCsv(await f.text());
              }
            }}
          />
        </label>
        <label className="block">
          منشأ و شرح نسخه فایل
          <input
            className="block w-full border rounded-xl p-3"
            maxLength={500}
            value={source}
            disabled={busy}
            onChange={(e) => {
              setSource(e.target.value);
              setPreview(null);
            }}
          />
        </label>
        <button
          className="btn-primary"
          disabled={busy || !csv || !source.trim()}
          onClick={() => upload(false)}
        >
          بررسی و پیش‌نمایش
        </button>
        {preview && (
          <div className="space-y-3">
            <p>
              معتبر: {preview.valid} · نامعتبر: {preview.invalid}
            </p>
            {preview.rows.map((row) => (
              <div className="border-b py-2" key={row.row_number}>
                <p>
                  ردیف {row.row_number}: {row.data.canonical_name_fa} ·{" "}
                  {row.data.category_slug}
                </p>
                {row.errors.map((e, i) => (
                  <p key={i}>{e}</p>
                ))}
              </div>
            ))}
            {preview.confirmed ? (
              <p role="status">
                ثبت انجام شد: {preview.created} جدید، {preview.updated} اصلاح،{" "}
                {preview.published} انتشار
              </p>
            ) : (
              <button
                className="btn-primary"
                disabled={busy || !preview.preview_token || preview.invalid > 0}
                onClick={() => upload(true)}
              >
                تأیید ورود همین فایل
              </button>
            )}
          </div>
        )}
      </section>
    </main>
  );
}
