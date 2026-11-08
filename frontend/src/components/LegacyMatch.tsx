"use client";
import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
type Master = { id: number; canonical_name_fa: string };
export default function LegacyMatch({
  token,
  masters,
}: {
  token: string;
  masters: Master[];
}) {
  const [rows, setRows] = useState<
      { id: number; sku: string; title_fa: string }[]
    >([]),
    [selected, setSelected] = useState<Record<number, string>>({}),
    [notes, setNotes] = useState<Record<number, string>>({});
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [reload, setReload] = useState(0);
  useEffect(() => {
    apiRequest<{ items: { id: number; sku: string; title_fa: string }[] }>(
      "/admin/catalog/legacy-products",
      { token },
    )
      .then((r) => setRows(r.items))
      .catch((e) => setError(e.message));
  }, [token, reload]);
  async function link(id: number) {
    setBusy(true);
    setError("");
    try {
      await apiRequest("/admin/catalog/legacy-products/" + id + "/link", {
        token,
        method: "POST",
        body: JSON.stringify({
          master_product_id: Number(selected[id]),
          evidence: notes[id],
        }),
      });
      setReload((v) => v + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="border rounded-2xl p-5 space-y-4">
      <h2 className="text-xl font-bold">محصولات نیازمند تطبیق با مخزن</h2>
      <p>
        مرجع را ابتدا در جست‌وجوی بالا پیدا کنید. تطبیق باید بر اساس مدل، گونه
        یا شناسه قابل اتکا باشد.
      </p>
      {error && <p role="alert">{error}</p>}
      {!rows.length && !error && <p>محصول بدون مرجع یافت نشد.</p>}
      {rows.map((p) => (
        <article key={p.id} className="border rounded-xl p-4 space-y-3">
          <h3 className="font-bold">{p.title_fa}</h3>
          <p>
            شناسه محصول: {p.id} · SKU: {p.sku}
          </p>
          <label className="block">
            کالای مرجع
            <select
              className="block border rounded-xl p-3 w-full"
              value={selected[p.id] ?? ""}
              disabled={busy}
              onChange={(e) =>
                setSelected((v) => ({ ...v, [p.id]: e.target.value }))
              }
            >
              <option value="">انتخاب از نتایج جست‌وجو</option>
              {masters.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.canonical_name_fa} — {m.id}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            مدرک و دلیل تطبیق
            <textarea
              className="block border rounded-xl p-3 w-full"
              value={notes[p.id] ?? ""}
              minLength={20}
              maxLength={1000}
              disabled={busy}
              onChange={(e) =>
                setNotes((v) => ({ ...v, [p.id]: e.target.value }))
              }
            />
          </label>
          <button
            className="btn-primary"
            disabled={
              busy || !selected[p.id] || (notes[p.id]?.trim().length ?? 0) < 20
            }
            onClick={() => link(p.id)}
          >
            ثبت تطبیق مستند
          </button>
        </article>
      ))}
    </section>
  );
}
