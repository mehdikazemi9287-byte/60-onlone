"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Bell } from "lucide-react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

type N = { id: number; kind: string; title: string; body: string | null; link: string | null; created_at: string; read_at: string | null };
export default function NotificationsPage() {
  const { token, user, loading } = useAuth();
  const [d, setD] = useState<{ items: N[]; unread: number } | null>(null);
  useEffect(() => { if (token) apiRequest<typeof d>("/me/notifications", { token }).then(setD).catch(() => setD({ items: [], unread: 0 })); }, [token]);
  const readAll = async () => { if (token) setD(await apiRequest("/me/notifications/read", { token, method: "POST", body: "{}" })); };
  if (loading) return <div className="container-page py-8"><div className="h-40 animate-pulse rounded-xl bg-neutral-100" /></div>;
  if (!user) return <div className="container-page py-8 text-center"><Link href="/login?next=/notifications" className="font-bold text-brand-blue">برای مشاهده اعلان‌ها وارد شوید</Link></div>;
  return (
    <div className="container-page max-w-2xl py-8" dir="rtl">
      <div className="mb-4 flex items-center justify-between"><h1 className="flex items-center gap-2 text-xl font-black text-brand-navy"><Bell className="h-5 w-5" /> اعلان‌ها</h1>
        {!!d?.unread && <button type="button" onClick={readAll} className="text-sm font-bold text-brand-blue">همه خوانده شد</button>}</div>
      {!d ? <div className="h-40 animate-pulse rounded-xl bg-neutral-100" /> : !d.items.length ? <p className="card p-6 text-center text-sm text-neutral-600">اعلانی ندارید.</p> : (
        <ul className="space-y-2">{d.items.map((n) => (
          <li key={n.id} className={`card p-4 ${n.read_at ? "" : "border-brand-blue"}`}>
            <p className="font-bold">{n.title}</p>{n.body && <p className="mt-1 text-sm text-neutral-600">{n.body}</p>}
            <div className="mt-2 flex justify-between text-xs text-neutral-500"><span>{new Date(n.created_at).toLocaleString("fa-IR")}</span>{n.link && <Link href={n.link} className="font-bold text-brand-blue">مشاهده</Link>}</div>
          </li>))}</ul>)}
    </div>
  );
}
