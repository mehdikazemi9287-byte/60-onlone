// Typed client for the enterprise procurement endpoints + shared labels.
import { apiRequest, newIdempotencyKey } from "@/lib/api";
import { toPersianNum } from "@/lib/utils";

export type Dest = {
  label: string | null; province: string; city: string; address: string; needed_by_date: string | null;
  recipient_name?: string | null; recipient_phone?: string | null; delivery_window?: string | null; notes?: string | null;
  allocations: { item_index: number; quantity: number }[];
};
export type WsItem = {
  id: number; master_product_id: number | null; name: string; brand: string | null; image_url: string | null; sku: string | null;
  quantity: number; unit: string; target_unit_price_minor: number | null; target_specification: string | null;
  acceptable_alternative: string | null; notes: string | null;
};
export type Step = { key: string; label: string; state: "approved" | "pending" | "upcoming" | "rejected"; actor: string | null; at: string | null; comment: string | null };
export type RfqSupplier = {
  supplier_id: number; name: string; invited_at: string; viewed_at: string | null; decline_reason: string | null;
  state: "draft" | "sent" | "viewed" | "quoted" | "partially_quoted" | "declined" | "expired";
  quote: { id: number; quote_number: string; status: string; revision: number; grand_total_minor: number; items_quoted: number; short: boolean } | null;
};
export type Rfq = { id: number; rfq_number: string; title: string; status: string; deadline_at: string | null; notes: string | null; items: number; suppliers: RfqSupplier[]; quotes_received: number };
export type Delivery = {
  allocations?:{item_index:number;quantity:number}[];
  destination_index: number; label: string | null; city: string | null; status: string | null; tracking_reference: string | null; updated_at: string | null;
  receipts: { id: number; kind: string; receiver_name: string; notes: string | null; created_at: string; quantities: { item_index: number; quantity: number }[] }[];
};
export type Order = {
  id: number; po_number: string; status: string; supplier: string | null; rfq_id: number; grand_total_minor: number | null;
  documents?: import("@/components/procurement/OrderDocuments").OrderDoc[];
  items_total_minor: number | null; shipping_minor: number | null; vat_minor: number | null; discount_minor: number | null;
  items: { id: number; master_product_id: number | null; free_text_description: string | null; quantity: number; unit: string; unit_price_minor_snapshot: number; total_minor_snapshot: number }[];
  deliveries: Delivery[];
  corrections: { id: number; receipt_id: number | null; kind: string; reason: string; status: string; resolution: string | null; created_at: string; resolved_at: string | null }[];
  finance: PoFinance;
};
export type PayMethod = "cash" | "cheque" | "credit" | "bill";
export type FinPolicy = { id: number; version: string; contract_reference: string; environment: "test" | "production"; methods: PayMethod[]; credit_limit_minor: number | null;
  max_parts?: number; max_term_days?: number | null; dual_approval_threshold_minor?: number | null; effective_from?: string | null };
export type PoFinance = {
  policy: FinPolicy | null;
  plan: null | { id: number; status: string; environment: string; total_minor: number; decision_note: string | null; created_at: string; submitted_at: string | null; decided_at: string | null;
    parts: { id: number; method: PayMethod; amount_minor: number; due_date: string | null; reference: string | null; status: string }[] };
  collected_minor: number; refunded_minor: number; fully_paid: boolean;
  approvals?: { round: number; created_at: string; actor: string }[];
  settlement: null | { amount_minor: number; reference: string; environment: string; created_at: string };
  ledger: { kind: string; amount_minor: number; environment: string; note: string | null; created_at: string; actor: string | null }[];
};
export type CaseRow = {
  id: number; organization_id?: number; organization?: string; suppliers?: string[]; request_number: string; title: string; status: string; requester: string | null; owner: string | null; needed_by_date: string | null;
  urgency: string; updated_at: string; created_at?: string; next_action: { key: string; label: string; owner: string | null }; blocked_reason: string | null; rfqs: number; quotes: number;
  order: null | { po_number: string; status: string; delivered: number; destinations: number; payment: string | null; settled: boolean };
};
export type FinanceSummary = {
  policy: FinPolicy | null; role: string;
  credit: { limit_minor: number | null; used_minor: number; remaining_minor: number | null };
  receivable_minor: number;
  plans: { id: number; po_number: string; purchase_request_id: number; status: string; environment: string; total_minor: number; collected_minor: number; refunded_minor: number; settled: boolean }[];
  instruments: { id: number; po_number: string; method: PayMethod; amount_minor: number; due_date: string | null; reference: string | null; status: string; environment: string }[];
  ledger: { kind: string; amount_minor: number; environment: string; note: string | null; created_at: string; po_number: string; actor: string | null }[];
  today: string; bank_integration: false;
  pending_approvals: FinanceSummary["plans"];
  expected: FinPart[]; received: FinPart[]; overdue: FinPart[];
  refunds: { amount_minor: number; environment: string; note: string | null; created_at: string; po_number: string; purchase_request_id: number; actor: string | null }[];
  payables: { po_number: string; purchase_order_id: number; purchase_request_id: number; environment: string; supplier: string | null; supplier_is_demo: boolean;
    amount_minor: number; state: "settled" | "ready" | "blocked_correction" | "awaiting_delivery" | "awaiting_collection"; settlement: { reference: string; created_at: string } | null }[];
  reconciliation: { po_number: string; purchase_request_id: number; environment: string; total_minor: number; collected_minor: number; refunded_minor: number;
    settled_minor: number; state: "reconciled" | "mismatch" | "collected" | "partial" | "open" }[];
};
export type FinPart = { id: number; po_number: string; purchase_request_id: number; method: PayMethod; amount_minor: number; due_date: string | null;
  reference: string | null; status: string; environment: string; plan_status: string; overdue: boolean };
export type PolicyRules = { methods: PayMethod[]; credit_limit_minor: number | null; max_parts: number; max_term_days: number | null;
  dual_approval_threshold_minor: number | null; separation_of_duties?: boolean };
export type PolicyDraft = { id: number; organization_id: number; version: string; environment: "test" | "production"; contract_reference: string | null;
  rules: PolicyRules; effective_from: string; status: string; lifecycle: string; lifecycle_fa: string; proposer: string | null; reviewer: string | null;
  review_note: string | null; row_version: number; proposed_by: number; organization?: string; org_provenance?: string;
  events?: { action: string; note: string | null; created_at: string; actor: string }[] };
export type PolicyList = { organization: { id: number; display_name: string; provenance: string }; active_policy_id: number | null;
  allowed_environment: "test" | "production"; can_propose: boolean; can_review: boolean; items: PolicyDraft[] };
export type TimelineEvent = { type: string; at: string; actor: string | null; details: Record<string, unknown>; source: string; internal?: boolean };
export type Workspace = {
  unallocated?: { item_index: number; quantity: number }[];
  allocation?: { item_index: number; total: number; allocated: number; unallocated: number }[];
  destinations_hash?: string;
  request: {
    id: number; request_number: string; title: string; description: string | null; status: string; needed_by_date: string | null;
    budget_minor: number | null; urgency: string; notes: string | null; destinations: Dest[]; submitted_at: string | null; created_at: string;
  };
  organization: { id: number; name: string; currency: string };
  requester: string | null; owner: string | null; items: WsItem[];
  approval: { steps: Step[]; configured: boolean };
  rfqs: Rfq[]; orders: Order[];
  coverage?:{purchase_request_item_id:number;requested:number;awarded:number;ordered:number;unawarded:number;unordered:number}[];
  case: { id: number; status: string; assignee: string | null; next_action: string | null; due_at: string | null; blocked_reason: string | null } | null;
  finance: { policy_status: string; environment: string | null; methods: { key: string; label: string; enabled: boolean; reason: string }[]; order_total_minor: number | null; posting: string; note: string };
  next_action: { key: string; label: string; owner: string | null };
  sla: { needed_by_date: string | null; rfq_deadline: string | null; case_due_at: string | null };
  documents: { uploads_enabled: boolean; reason: string };
  timeline: TimelineEvent[];
  permissions: { role: string; procurement_role: string | null; can_submit: boolean; can_approve: boolean; can_procure: boolean; can_read_internal: boolean; can_receive: boolean; can_cancel: boolean };
};
export type Comparison = {
  rfq_id: number; rfq_number: string; rfq_status: string; total_quotes: number; lowest_quote_id: number | null;
  rfq_items: { id: number; master_product_id: number | null; free_text_description: string | null; product_name_fa?: string | null; quantity: number; unit: string }[];
  quotes: {
    quote_id: number; quote_number: string; supplier_id: number; supplier_name: string; status: string; rank: number; revision: number;
    computed_items_total_minor: number; shipping_cost_minor: number; computed_grand_total_minor: number; vat_amount_minor: number; discount_minor: number;
    payment_terms: string | null; delivery_lead_days: number | null; validity_days: number | null; warranty_terms: string | null; submitted_at: string;
    items: { rfq_item_id: number; unit_price_minor: number; quantity: number; total_price_minor: number; discount_minor: number; alternative_description: string | null; delivery_date: string | null; notes: string | null }[];
  }[];
};
export type Dashboard = {
  counts: { open_requests: number; awaiting_quotes: number; quotes_received: number; needs_approval: number; active_orders: number; awaiting_delivery: number };
  finance: { policy_status: string; due_items: null };
  actions: { request_id: number; request_number: string; title: string; action: string; needed_by_date: string | null }[];
  scope: string;
};
export type Policy = {
  organization_id: number; employee_submit_allowed: boolean; version: number; updated_at: string | null;
  approval_chain: { key: string; label: string; role: string | null; procurement_role: string | null }[];
};

const base = (org: number | string) => `/orgs/${org}/procurement`;

export const proc = {
  workspace: (token: string, org: number | string, id: number | string, signal?: AbortSignal) =>
    apiRequest<Workspace>(`${base(org)}/requests/${id}/workspace`, { token, signal }),
  dashboard: (token: string, org: number | string, signal?: AbortSignal) =>
    apiRequest<Dashboard>(`${base(org)}/dashboard`, { token, signal }),
  policy: (token: string, org: number | string) => apiRequest<{ policy: Policy }>(`${base(org)}/policy`, { token }),
  savePolicy: (token: string, org: number | string, body: Partial<Policy>) =>
    apiRequest<{ policy: Policy }>(`${base(org)}/policy`, { token, method: "PUT", body: JSON.stringify(body) }),
  suppliers: (token: string, org: number | string) =>
    apiRequest<{ items: { id: number; display_name: string; supplier_type: string | null; rating_x10: number | null }[] }>(`${base(org)}/suppliers`, { token }),
  cases: (token: string, org: number | string, qs: string, signal?: AbortSignal) =>
    apiRequest<{ items: CaseRow[]; scope: string }>(`${base(org)}/cases${qs ? `?${qs}` : ""}`, { token, signal }),
  finance: (token: string, org: number | string) => apiRequest<FinanceSummary>(`${base(org)}/finance`, { token }),
  comparison: (token: string, org: number | string, rfq: number | string) =>
    apiRequest<Comparison>(`${base(org)}/rfqs/${rfq}/comparison`, { token }),
  post: <T = unknown>(token: string, path: string, body?: unknown, idempotent = false) =>
    apiRequest<T>(path, {
      token, method: "POST", body: body === undefined ? undefined : JSON.stringify(body),
      headers: idempotent ? { "Idempotency-Key": newIdempotencyKey() } : undefined,
    }),
  base,
};

// ── Labels ──────────────────────────────────────────────────────────────────

export const PR_STATUS: Record<string, string> = {
  draft: "پیش‌نویس", submitted: "ارسال‌شده برای بررسی", under_review: "در حال تأیید", approved: "تأییدشده",
  rejected: "ردشده", sourcing: "در حال استعلام", quoted: "پیشنهاد رسیده", awarded: "پیشنهاد انتخاب شد",
  cancelled: "لغوشده", completed: "بسته‌شده",
};
export const RFQ_STATUS: Record<string, string> = { draft: "پیش‌نویس", open: "باز برای پیشنهاد", closed: "بسته‌شده", awarded: "برنده انتخاب شد", cancelled: "لغوشده" };
export const SUPPLIER_STATE: Record<string, string> = {
  draft: "پیش‌نویس", sent: "ارسال‌شده", viewed: "مشاهده‌شده", quoted: "پیشنهاد کامل", partially_quoted: "پیشنهاد ناقص",
  declined: "انصراف", expired: "منقضی",
};
export const PO_STATUS: Record<string, string> = {
  draft: "پیش‌نویس سفارش", confirmed: "تأییدشده", sent: "ارسال به تأمین‌کننده", partially_received: "دریافت جزئی",
  received: "دریافت کامل", cancelled: "لغوشده",
};
export const DELIVERY_STATUS: Record<string, string> = {
  confirmed: "تأییدشده", preparing: "در حال آماده‌سازی", ready: "آماده ارسال", shipped: "ارسال‌شده",
  partially_delivered: "تحویل جزئی", delivered: "تحویل کامل",
};
export const DELIVERY_FLOW = ["confirmed", "preparing", "ready", "shipped", "partially_delivered", "delivered"];
export const RECEIPT_KIND: Record<string, string> = { full: "تحویل کامل", partial: "تحویل جزئی", shortage: "کسری", damaged: "آسیب", mismatch: "مغایرت" };
export const PAY_METHOD: Record<string, string> = { cash: "نقدی", cheque: "چکی", credit: "اعتباری", bill: "برات/تعهد" };
export const PLAN_STATUS: Record<string, string> = { draft: "پیش‌نویس", submitted: "در انتظار تأیید مالی", approved: "تأیید مالی شد", rejected: "رد مالی" };
export const PART_STATUS: Record<string, string> = { pending: "در انتظار", received: "دریافت شد", cleared: "وصول شد", bounced: "برگشت خورد", cancelled: "لغو" };
export const FIN_EVENT: Record<string, string> = {
  plan_created: "ثبت برنامه پرداخت", plan_submitted: "ارسال برای تأیید مالی", plan_approved: "تأیید مالی", plan_rejected: "رد مالی",
  part_received: "دریافت", part_cleared: "وصول", part_bounced: "برگشت", refund_recorded: "بازپرداخت", settlement_recorded: "تسویه با تأمین‌کننده",
};
export const URGENCY: Record<string, string> = { low: "کم", normal: "عادی", high: "بالا", urgent: "فوری" };
export const ROLE_LABEL: Record<string, string> = {
  employee: "کارمند", organization_admin: "مدیر سازمان", procurement_agent: "کارشناس تدارکات", organization_finance: "مالی سازمان",
  requester: "درخواست‌دهنده", approver: "مدیر واحد/تأییدکننده", procurement_officer: "مسئول تدارکات",
};
export const EVENT_LABEL: Record<string, string> = {
  pr_created: "درخواست ایجاد شد", pr_submitted: "درخواست ارسال شد", pr_approved: "درخواست تأیید شد", pr_rejected: "درخواست رد شد",
  pr_cancelled: "درخواست لغو شد", approval_step: "مرحله تأیید", rfq_created: "استعلام ایجاد شد", rfq_opened: "استعلام برای تأمین‌کنندگان باز شد",
  rfq_closed: "استعلام بسته شد", rfq_cancelled: "استعلام لغو شد", supplier_invited: "تأمین‌کننده دعوت شد",
  supplier_responded: "پاسخ تأمین‌کننده", supplier_declined: "انصراف تأمین‌کننده", quote_submitted: "پیشنهاد دریافت شد",
  quote_awarded: "پیشنهاد انتخاب شد", quote_rejected: "پیشنهاد رد شد", po_created: "سفارش ایجاد شد", po_confirmed: "سفارش تأیید شد",
  po_sent: "سفارش برای تأمین‌کننده ارسال شد", po_acknowledged: "تأمین‌کننده سفارش را پذیرفت", po_completed: "سفارش تکمیل شد",
  po_cancelled: "سفارش لغو شد", delivery_status: "وضعیت ارسال", receipt: "رسید تحویل", correction_opened: "مرجوعی/اصلاحیه ثبت شد",
  correction_resolved: "مرجوعی/اصلاحیه رسیدگی شد", closed: "پرونده بسته شد", note: "یادداشت داخلی", policy_updated: "سیاست خرید به‌روزرسانی شد",
};

export function money(minor: number | null | undefined, currency = "IRR"): string {
  if (minor == null) return "—";
  if (currency === "IRR") return `${toPersianNum(Math.round(minor / 10).toLocaleString("en-US"))} تومان`;
  return `${toPersianNum(minor.toLocaleString("en-US"))} ${currency}`;
}
export const fa = (n: number | string | null | undefined) => (n == null ? "—" : toPersianNum(typeof n === "number" ? n.toLocaleString("en-US") : n));
