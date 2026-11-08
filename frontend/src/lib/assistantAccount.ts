// 60AI account context: answers "where is my order / request / case?" from the caller's OWN records.
// Server-side only. Uses the caller's bearer token, so the backend's authorization decides visibility
// (a requester sees their own cases, an organization admin sees the organization's). Strictly read-only:
// it never creates, approves, pays or cancels anything; every next step is a link to the real page.
import { PR_STATUS } from "@/lib/procurement/api";

export type AccountIntent = "orders" | "requests" | "org" | "any";

export type AccountItem = {
  kind: "order" | "personal_request" | "org_case";
  ref: string; title: string; status: string; statusFa: string;
  nextAction: string | null; owner: string | null; detail: string | null; href: string;
};
export type AccountContext = {
  signedIn: boolean;
  user: { name: string | null; role: string } | null;
  orgs: { id: number; name: string; role: string }[];
  items: AccountItem[];
  notes: string[];
};

const ORDER_STATUS_FA: Record<string, string> = {
  pending: "ثبت‌شده، در انتظار پرداخت/تأیید", paid: "پرداخت‌شده", processing: "در حال پردازش", shipped: "ارسال شده",
  delivered: "تحویل داده شده", cancelled: "لغو شده",
};
const REQUEST_STATUS_FA: Record<string, string> = {
  open: "ثبت‌شده، در انتظار بررسی", reviewing: "در حال بررسی کارشناس", answered: "پاسخ داده شد", closed: "بسته‌شده",
};
const ROLE_FA: Record<string, string> = {
  organization_admin: "مدیر سازمان", employee: "کارمند", requester: "درخواست‌دهنده", approver: "تأییدکننده",
  buyer: "کارشناس خرید", finance: "مالی", finance_manager: "مدیر مالی",
};

const norm = (s: string) => s.replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/‌/g, " ").replace(/\s+/g, " ").trim();

/** Status/tracking questions only. Shopping questions ("سفارش برنج", "پک سازمانی") stay with the catalog assistant. */
export function detectAccountIntent(raw: string): AccountIntent | null {
  const q = norm(raw);
  const tracking = /(وضعیت|پیگیری|کجاست|کجا است|چی شد|چه شد|رسید|ارسال شد|اقدام بعدی|قدم بعدی|مرحله بعد|پیش ?فاکتور من|پیشنهاد(های)? قیمت من|تخصیص|مقصد(های)? من)/.test(q);
  const mine = /(سفارش(های|ها)? من|سفارشم|درخواست(های|ها)? من|درخواستم|استعلام(های|ها)? من|استعلامم|پرونده(های|ها)?( من)?|پرونده ام|پرونده‌ام)/.test(q);
  if (!tracking && !mine) return null;
  if (/(سازمان|سازمانی|پرونده|تخصیص|مقصد|خرید سازمانی)/.test(q)) return "org";
  if (/(استعلام|درخواست)/.test(q)) return "requests";
  if (/سفارش/.test(q)) return "orders";
  return "any";
}

async function get<T>(origin: string, path: string, token: string): Promise<{ ok: boolean; status: number; data: T | null }> {
  const res = await fetch(origin + "/api/v1" + path, {
    headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: AbortSignal.timeout(10000),
  });
  if (!res.ok) return { ok: false, status: res.status, data: null };
  return { ok: true, status: res.status, data: (await res.json()) as T };
}

type CaseRow = { id: number; request_number: string; title: string; status: string; next_action: { label: string; owner: string | null } | null;
  blocked_reason: string | null; rfqs: number; quotes: number; order: null | { po_number: string; status: string; delivered: number; destinations: number } };

export async function fetchAccountContext(origin: string, token: string | null, intent: AccountIntent): Promise<AccountContext> {
  const empty: AccountContext = { signedIn: false, user: null, orgs: [], items: [], notes: [] };
  if (!token) return { ...empty, notes: ["برای دیدن وضعیت سفارش، درخواست یا پرونده باید وارد حساب خود شوید."] };
  const me = await get<{ user: { full_name: string | null; role: string } }>(origin, "/auth/me", token);
  if (!me.ok || !me.data) return { ...empty, notes: ["نشست شما معتبر نیست؛ دوباره وارد شوید."] };
  const ctx: AccountContext = { signedIn: true, user: { name: me.data.user.full_name, role: me.data.user.role }, orgs: [], items: [], notes: [] };

  const orgs = await get<{ items: { id: number; display_name: string; membership?: { role: string; status: string } }[] }>(origin, "/organizations", token);
  ctx.orgs = (orgs.data?.items ?? []).filter((o) => !o.membership || o.membership.status === "active")
    .map((o) => ({ id: o.id, name: o.display_name, role: ROLE_FA[o.membership?.role ?? ""] ?? (o.membership?.role || "عضو") }));

  if (intent === "orders" || intent === "any") {
    const r = await get<{ items: { order_number: string; status: string; item_count: number; organization_id: number | null }[] }>(origin, "/orders?page_size=5", token);
    for (const o of r.data?.items ?? []) ctx.items.push({
      kind: "order", ref: o.order_number, title: `سفارش ${o.order_number}`, status: o.status, statusFa: ORDER_STATUS_FA[o.status] ?? o.status,
      nextAction: o.status === "delivered" || o.status === "cancelled" ? null : "مشاهده جزئیات و مراحل ارسال", owner: null,
      detail: `${o.item_count.toLocaleString("fa-IR")} قلم`, href: `/orders/${encodeURIComponent(o.order_number)}`,
    });
    if (!r.ok && r.status === 403) ctx.notes.push("فهرست سفارش‌های شخصی برای نقش فعلی شما در دسترس نیست.");
  }
  if (intent === "requests" || intent === "any") {
    const r = await get<{ items: { id: number; subject: string; status: string; response: string | null }[] }>(origin, "/requests", token);
    for (const q of (r.data?.items ?? []).slice(0, 5)) ctx.items.push({
      kind: "personal_request", ref: `#${q.id}`, title: q.subject, status: q.status, statusFa: REQUEST_STATUS_FA[q.status] ?? q.status,
      nextAction: q.status === "answered" ? "مشاهده پاسخ و پیشنهاد قیمت" : q.status === "closed" ? null : "منتظر پاسخ کارشناس فروش",
      owner: null, detail: q.response, href: `/requests/${q.id}`,
    });
  }
  if (intent === "org" || intent === "any") {
    if (!ctx.orgs.length && intent === "org") ctx.notes.push("شما عضو هیچ سازمانی نیستید؛ برای خرید سازمانی ابتدا سازمان باید شما را دعوت کند.");
    for (const org of ctx.orgs.slice(0, 3)) {
      const r = await get<{ items: CaseRow[]; scope: string }>(origin, `/orgs/${org.id}/procurement/cases`, token);
      if (!r.ok) { if (r.status === 403) ctx.notes.push(`نقش شما در «${org.name}» اجازه دیدن پرونده‌ها را نمی‌دهد.`); continue; }
      for (const c of (r.data?.items ?? []).slice(0, 5)) {
        const parts = [`${org.name}`];
        if (c.rfqs) parts.push(`${c.rfqs.toLocaleString("fa-IR")} استعلام`);
        if (c.quotes) parts.push(`${c.quotes.toLocaleString("fa-IR")} پیشنهاد`);
        if (c.order) parts.push(`سفارش ${c.order.po_number}: تحویل ${c.order.delivered.toLocaleString("fa-IR")} از ${c.order.destinations.toLocaleString("fa-IR")} مقصد`);
        if (c.blocked_reason) parts.push(`مانع: ${c.blocked_reason}`);
        ctx.items.push({
          kind: "org_case", ref: c.request_number, title: c.title, status: c.status, statusFa: PR_STATUS[c.status] ?? c.status,
          nextAction: c.next_action?.label ?? null, owner: c.next_action?.owner ?? null, detail: parts.join(" · "),
          href: `/organization/requests/${c.id}?org=${org.id}`,
        });
      }
    }
  }
  if (!ctx.items.length && !ctx.notes.length) ctx.notes.push("موردی برای نمایش پیدا نشد.");
  return ctx;
}
