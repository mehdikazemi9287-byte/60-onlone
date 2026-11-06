/** Phases 2–5 — buy box, recurring lists, brands, org orders/credit/welfare, seller logistics & exports. */
import { ApiError, apiRequest } from "@/lib/api";

// ── Brands ──────────────────────────────────────────────────────────────────
export type Brand = { id: number; title: string; shop_slug: string | null; shop_logo_url: string | null; rating_x10: number;
  brand_name: string; trademark_number: string; official: true };
export type BrandRegistration = { id: number; brand_name: string; trademark_number: string; document_url: string;
  status: "pending" | "verified" | "rejected"; review_note: string | null; reviewed_at: string | null; created_at: string };

// ── Buy Box ─────────────────────────────────────────────────────────────────
export type BuyBoxOffer = { offer_id: number; supplier_id: number; seller_name: string; shop_slug: string | null; seller_kind: string;
  official: boolean; unit_price_minor: number | null; landed_unit_minor?: number; landed_unit_incl_vat_minor?: number | null; price_incl_vat_minor?: number | null;
  in_stock: boolean; lead_time_days: number | null; eligible: boolean; is_winner: boolean };
export type BuyBox = { offers: BuyBoxOffer[]; winner: BuyBoxOffer | null; offer_count: number; eligible_count: number };

// ── Recurring lists ─────────────────────────────────────────────────────────
export type RecurringStatus = "active" | "paused" | "cancelled";
export type RecurringList = { id: number; title: string; frequency: "weekly" | "biweekly" | "monthly"; status: RecurringStatus;
  next_run_on: string; last_run_on: string | null; organization_id: number | null;
  items: { product_id: number; offer_id: number | null; quantity: number; slug: string; title_fa: string }[] };
export type QuoteLine = { product_id: number; title_fa: string | null; quantity: number; unit_price_minor: number; line_after_discounts_minor: number };
export type DraftQuote = { lines: QuoteLine[]; totals: { payable_minor: number; discount_total_minor: number; base_line_minor: number } };

export const FREQ_FA: Record<string, string> = { weekly: "هفتگی", biweekly: "دو هفته یک‌بار", monthly: "ماهانه" };
export const RECUR_FA: Record<string, string> = { active: "فعال", paused: "متوقف", cancelled: "لغوشده" };

// ── Organization ────────────────────────────────────────────────────────────
export type OrgOrderRow = { id: number; order_number: string; status: string; placed_at: string; total_minor: number;
  credit_minor: number; cash_minor: number; po_reference: string | null; payment_method: string | null; cash_status: string | null };
export type OrgInvoice = { invoice_number: string; order_number: string; issued_at: string; status: string; po_reference: string | null;
  purchase_request_number: string | null; buyer: { legal_name: string | null; display_name: string; national_id: string | null };
  lines: { id: number; title_fa: string; quantity: number; unit_price_minor: number; line_total_minor: number }[];
  subtotal_minor: number; shipping_fee_minor: number; tax_minor: number; total_minor: number; credit_minor: number; cash_minor: number };
export type CreditContract = { id: number; reference: string; funder_type: string; funder_name: string | null; contract_number: string | null;
  limit_minor: number; outstanding_minor: number; headroom_minor: number; status: "active" | "frozen" | "closed"; freeze_reason: string | null;
  statement_weekday: number; due_days: number; starts_at: string; closed_at: string | null };
export type CreditStatement = { id: number; reference: string; period_start: string; period_end: string; opening_minor: number;
  usage_minor: number; payments_minor: number; closing_minor: number; due_at: string; paid_at: string | null; status: "open" | "paid" | "overdue" };
export type WelfarePlan = { id: number; reference: string; title: string; plan_type: "free" | "category" | "product"; per_employee_cap_minor: number;
  all_members: number; status: "active" | "closed"; starts_at: string; expires_at: string; category_slugs: string[]; product_ids: number[] };
export type ApprovalRule = { id: number; name: string; min_total_minor: number; max_total_minor: number | null;
  decision: "auto_approve" | "require_approvals"; required_approvals: number; approver_role: string | null; is_active: boolean };
export type PreferredSeller = { id: number; supplier_id: number | null; category_id: number | null; note: string | null; created_at: string };

export const ORDER_STATUS_FA: Record<string, string> = { pending: "در انتظار پرداخت", paid: "پرداخت‌شده", processing: "در حال آماده‌سازی",
  shipped: "ارسال‌شده", delivered: "تحویل‌شده", cancelled: "لغوشده", refunded: "بازپرداخت‌شده" };
export const FINANCE_ROLES = ["organization_admin", "organization_finance"];

// ── Seller logistics ────────────────────────────────────────────────────────
export type Shipment = { id: number; fulfillment_order_id: number; order_id: number; tracking_number: string; provider_code: string;
  service_level: string; status: string; pickup_requested_at: string | null; deliver_by_at: string | null; label: Record<string, unknown> };
export type ExportJob = { id: number; reference: string; connector: string; period_start: string; period_end: string; status: string;
  document_count: number; file_name: string; created_at: string };

export const SHIP_STATUS_FA: Record<string, string> = { created: "برچسب صادر شد", picked_up: "تحویل به پیک", in_transit: "در مسیر",
  out_for_delivery: "در حال تحویل", delivered: "تحویل شد", failed: "تحویل ناموفق", returned: "مرجوع شد" };

/** Error text for a failed call; feature-disabled/permission errors get a plain explanation. */
export function errText(e: unknown, fallback = "خطا در ارتباط با سرور"): string {
  if (e instanceof ApiError) {
    if (e.code === "feature_disabled") return "این امکان فعلاً فعال نیست.";
    if (e.status === 403) return e.message || "دسترسی این بخش را ندارید.";
    return e.message || fallback;
  }
  return fallback;
}

/** Same rounding as backend consumer_rights_service.gross. */
export function grossMinor(net: number | null | undefined, vatBps: number | undefined): number | null {
  if (net == null) return null;
  return net + Math.floor((net * (vatBps ?? 0)) / 10000);
}

/** Authenticated file download: the token goes in a header, never in the URL. */
export async function downloadAuthed(path: string, token: string, fallbackName: string): Promise<void> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  try { const sid = window.localStorage.getItem("60online_supplier"); if (sid) headers["X-Supplier-Id"] = sid; } catch {}
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1${path}`, { headers });
  if (!res.ok) throw new ApiError(res.status, "DOWNLOAD_FAILED", "دریافت فایل ناموفق بود");
  const blob = await res.blob();
  const m = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "");
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = m?.[1] ?? fallbackName; a.rel = "noopener";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export { apiRequest };
