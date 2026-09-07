"use client";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { apiRequest } from "@/lib/api";
type Supplier = {
  id: number;
  display_name: string;
  legal_name: string;
  status: string;
  supplier_type: string;
  onboarding_status?: string;
};
export default function AdminSuppliers() {
  const { user, token, loading } = useAuth();
  const [rows, setRows] = useState<Supplier[]>([]),
    [page, setPage] = useState(1),
    [reload, setReload] = useState(0),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [legal, setLegal] = useState(""),
    [name, setName] = useState(""),
    [national, setNational] = useState(""),
    [type, setType] = useState(""),
    [source, setSource] = useState("");
  useEffect(() => {
    if (!token || user?.role !== "admin") return;
    let active = true;
    setBusy(true);
    setError("");
    apiRequest<{ suppliers: Supplier[] }>(
      "/admin/suppliers?limit=25&offset=" + (page - 1) * 25,
      { token },
    )
      .then((r) => {
        if (active) setRows(r.suppliers);
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [token, user?.role, page, reload]);
  async function create(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await apiRequest("/admin/suppliers", {
        token: token!,
        method: "POST",
        body: JSON.stringify({
          legal_name: legal,
          display_name: name,
          national_id: national,
          supplier_type: type,
          status: "pending",
          notes: source,
        }),
      });
      setNotice(
        "ثبت اولیه انجام شد؛ قرارداد، پیشنهاد معتبر و آمادگی تحویل باید جداگانه احراز شوند.",
      );
      setLegal("");
      setName("");
      setNational("");
      setSource("");
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
        <Link href="/login?next=%2Fadmin%2Fsuppliers">ورود به حساب مدیر</Link>
      </main>
    );
  if (user.role !== "admin")
    return <p className="p-8">دسترسی مدیریت لازم است.</p>;
  return (
    <main className="container-page py-8 space-y-6">
      <h1 className="text-2xl font-bold">مدیریت تأمین‌کنندگان</h1>
      <nav className="flex flex-wrap gap-5">
        <Link href="/admin">مخزن کالا</Link>
        <Link href="/crm">پیگیری مشتریان</Link>
      </nav>
      <p>
        وجود نام یا وضعیت در سامانه به‌تنهایی مدرک قرارداد، قیمت معتبر یا آمادگی
        تحویل نیست.
      </p>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <form onSubmit={create}>
        <fieldset disabled={busy} className="border rounded-2xl p-5 space-y-4">
          <legend className="font-bold">ثبت اولیه با مدرک موجود</legend>
          <label className="block">
            نام حقوقی
            <input
              className="block border rounded-xl p-3 w-full"
              required
              maxLength={200}
              value={legal}
              onChange={(e) => setLegal(e.target.value)}
            />
          </label>
          <label className="block">
            نام نمایشی
            <input
              className="block border rounded-xl p-3 w-full"
              required
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="block">
            شناسه ملی واقعی
            <input
              className="block border rounded-xl p-3 w-full"
              required
              maxLength={50}
              value={national}
              onChange={(e) => setNational(e.target.value)}
            />
          </label>
          <label className="block">
            نوع فعالیت
            <select
              className="block border rounded-xl p-3 w-full"
              required
              value={type}
              onChange={(e) => setType(e.target.value)}
            >
              <option value="">انتخاب کنید</option>
              <option value="producer">تولیدکننده</option>
              <option value="distributor">توزیع‌کننده</option>
              <option value="wholesaler">عمده‌فروش</option>
              <option value="retailer">خرده‌فروش</option>
              <option value="local_shop">فروشگاه محلی</option>
            </select>
          </label>
          <label className="block">
            منشأ اطلاعات و وضعیت بررسی
            <textarea
              className="block border rounded-xl p-3 w-full"
              required
              minLength={20}
              maxLength={2000}
              value={source}
              onChange={(e) => setSource(e.target.value)}
            />
          </label>
          <button className="btn-primary">ثبت در انتظار بررسی</button>
        </fieldset>
      </form>
      <section className="space-y-3">
        <h2 className="text-xl font-bold">رکوردهای موجود</h2>
        {busy && <p>در حال دریافت…</p>}
        {!busy && !rows.length && !error && <p>رکوردی در این صفحه نیست.</p>}
        {rows.map((s) => (
          <article key={s.id} className="border rounded-xl p-4 space-y-2">
            <h3 className="font-bold">{s.display_name}</h3>
            <p>{s.legal_name}</p>
            <p>
              شناسه سامانه: {s.id} · وضعیت ثبت‌شده: {s.status}
            </p>
            <p>مرحله پذیرش ثبت‌شده: {s.onboarding_status || "ثبت نشده"}</p>
          </article>
        ))}
      </section>
      <nav className="flex justify-between">
        <button
          disabled={busy || page <= 1}
          onClick={() => setPage((p) => p - 1)}
        >
          صفحه قبل
        </button>
        <span>{page}</span>
        <button
          disabled={busy || rows.length < 25}
          onClick={() => setPage((p) => p + 1)}
        >
          صفحه بعد
        </button>
      </nav>
    </main>
  );
}
