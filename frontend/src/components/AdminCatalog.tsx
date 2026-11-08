"use client";
import Link from "next/link";
import LegacyMatch from "./LegacyMatch";
import { FormEvent, useEffect, useRef, useState } from "react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useAdminEditorState } from "./admin/AdminShell";
import { CATALOG_CSV_TEMPLATE, readCatalogCsv } from "./admin/catalog-file";
type Master = {
  id: number;
  canonical_name_fa: string;
  brand?: string;
  category?: string;
  status: string;
  provenance: string;
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
    [total, setTotal] = useState<number | null>(null),
    [rows, setRows] = useState<Master[]>([]);
  const [csv, setCsv] = useState(""),
    [source, setSource] = useState(""),
    [preview, setPreview] = useState<Preview | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [refresh, setRefresh] = useState(0);
  const setDirty = useAdminEditorState();
  const fileSequence = useRef(0);
  const importInFlight = useRef(false);
  const [reading, setReading] = useState(false);
  const [listBusy, setListBusy] = useState(true);
  const [listError, setListError] = useState("");
  const hasUnsavedImport = reading || busy || Boolean((csv || source.trim()) && !preview?.confirmed);
  useEffect(() => {
    setDirty(hasUnsavedImport);
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (hasUnsavedImport) { event.preventDefault(); event.returnValue = ""; }
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => { window.removeEventListener("beforeunload", beforeUnload); setDirty(false); };
  }, [hasUnsavedImport, setDirty]);
  useEffect(() => () => { fileSequence.current += 1; }, []);
  async function selectFile(file: File | undefined) {
    const selection = ++fileSequence.current;
    setPreview(null); setCsv(""); setError(""); setReading(Boolean(file));
    if (!file) return;
    try {
      const text = await readCatalogCsv(file);
      // A slow, previously selected file must not replace the current selection.
      if (selection === fileSequence.current) setCsv(text);
    } catch (cause: unknown) {
      if (selection === fileSequence.current) setError(cause instanceof Error ? cause.message : "خواندن فایل انجام نشد.");
    } finally {
      if (selection === fileSequence.current) setReading(false);
    }
  }
  useEffect(() => {
    if (!token || user?.role !== "admin") return;
    let live = true;
    setListBusy(true); setListError(""); setRows([]); setTotal(null);
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
        if (live) setListError(e instanceof Error ? e.message : "فهرست کالاها دریافت نشد.");
      })
      .finally(() => { if (live) setListBusy(false); });
    return () => {
      live = false;
    };
  }, [token, user?.role, page, query, refresh]);
  async function upload(confirm: boolean) {
    if (importInFlight.current || reading || !token || !csv || !source.trim()) return;
    if (confirm && (!preview?.preview_token || preview.confirmed || preview.invalid > 0 || preview.valid < 1)) return;
    importInFlight.current = true;
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
      importInFlight.current = false;
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
      <nav className="flex flex-wrap gap-x-5 gap-y-2">
        <Link href="/admin/suppliers">تأمین‌کنندگان</Link>
        <Link href="/admin/cases">پرونده‌های خرید سازمان‌ها</Link>
        <Link href="/admin/access">دسترسی‌ها و سیاست پرداخت</Link>
        <Link href="/admin/catalog/new">ایجاد مستقیم کالا</Link>
        <Link href="/admin/catalog-review">بازبینی و انتشار کاتالوگ</Link>
        <Link href="/admin/packs">مدیریت پک‌ها</Link>
        <Link href="/admin/returns">مرجوعی‌ها</Link>
        <Link href="/admin/settlements">تسویه تأمین‌کنندگان</Link>
        <Link href="/admin/inquiries">استعلام‌های مشتریان</Link>
        <Link href="/crm">درخواست‌های مشتریان</Link>
        <Link href="/account">حساب من</Link>
        <Link href="/search">کاتالوگ عمومی</Link>
      </nav>
      {listError && <div role="alert"><p>{listError}</p><button type="button" className="underline" onClick={() => setRefresh(v => v + 1)}>دریافت دوباره فهرست</button></div>}
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
      <p role="status">{listBusy ? "در حال دریافت کالاها…" : total === null ? "تعداد کالاها در دسترس نیست." : `${total} کالای مرجع مطابق جست‌وجو`}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {rows.map((p) => (
          <article key={p.id} className="border rounded-xl p-4">
            <h2 className="font-bold">{p.canonical_name_fa}</h2>
            <p>شناسه مرجع: {p.id} · منشأ: {({real:"واقعی",demo:"نمایشی",test:"آزمایشی"} as Record<string,string>)[p.provenance]??p.provenance}</p>
            <p>
              {p.brand} · {p.category} · {p.status}
            </p>
            {p.provenance==="real"&&p.status!=="merged"&&<Link className="inline-flex mt-3 text-sm underline" href={`/admin/catalog/${p.id}/edit`}>ویرایش توضیحات و مشخصات</Link>}
          </article>
        ))}
      </div>
      <nav className="flex justify-between">
        <button disabled={listBusy || page <= 1} onClick={() => setPage((v) => v - 1)}>
          قبلی
        </button>
        <span>{page}</span>
        <button
          disabled={listBusy || total === null || page * 25 >= total}
          onClick={() => setPage((v) => v + 1)}
        >
          بعدی
        </button>
      </nav>
      <LegacyMatch token={token!} masters={rows} />
      <section id="catalog-import" aria-labelledby="catalog-import-title" aria-busy={reading || busy} className="border rounded-2xl p-5 space-y-4 scroll-mt-24">
        <h2 id="catalog-import-title" className="text-xl font-bold">ورود گروهی با پیش‌نمایش</h2>
        <div className="flex flex-wrap gap-4">
          <a className="underline" href={"data:text/csv;charset=utf-8," + encodeURIComponent(CATALOG_CSV_TEMPLATE)} download="60online-products-template.csv">دریافت قالب خالی CSV</a>
          <Link className="underline" href="/admin/taxonomy">بررسی دسته‌بندی‌ها</Link>
        </div>
        <p className="text-sm">قالب فقط سرستون دارد؛ نام کالا و شناسهٔ دسته را از اطلاعات واقعی تکمیل کنید. ابتدا پیش‌نمایش بگیرید؛ ثبت فقط با تأیید همین فایل انجام می‌شود.</p>
        {error && <p role="alert">{error}</p>}
        {reading && <p role="status">در حال خواندن و بررسی فایل…</p>}
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
            onChange={(e) => { void selectFile(e.target.files?.[0]); }}
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
          disabled={busy || reading || !csv || !source.trim()}
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
                disabled={busy || reading || !preview.preview_token || preview.invalid > 0 || preview.valid < 1}
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
