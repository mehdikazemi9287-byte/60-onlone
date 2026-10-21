/** Read-only dashboard contract from backend/app/api/v1/admin_dashboard.py. */
export type AttentionKind = "customer_request" | "catalog_image" | "supplier";
export type QueueFilter = "all" | AttentionKind;
export type AttentionItem = {
  id: number;
  title: string;
  kind: AttentionKind;
  status: string;
  href: string;
};
export type Operations = {
  scope_count: number;
  items: { id: number; title: string; organization_id: number }[];
  has_more: boolean;
};
export type Dashboard = {
  environment: string;
  as_of: string;
  timezone: string;
  metrics: Record<string, unknown>;
  attention: AttentionItem[];
  attention_is_sample: boolean;
  operations: Operations;
  integrations: { sepidar: string };
};

export const queueFilters: ReadonlyArray<{ value: QueueFilter; label: string }> = [
  { value: "all", label: "همه" },
  { value: "customer_request", label: "استعلام شخصی" },
  { value: "catalog_image", label: "تصویر کاتالوگ" },
  { value: "supplier", label: "تأمین‌کننده" },
];
export const attentionLabels: Record<AttentionKind, string> = {
  customer_request: "استعلام شخصی",
  catalog_image: "تصویر کاتالوگ",
  supplier: "وضعیت تأمین‌کننده",
};

/** Missing, malformed, or negative values are unknown, never zero. */
export function metricValue(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : null;
}

export function filterAttention(items: readonly AttentionItem[], kind: QueueFilter) {
  return kind === "all" ? [...items] : items.filter((item) => item.kind === kind);
}

export function operationsState(operations: Operations | null, loading: boolean) {
  if (loading) return "pending";
  if (!operations) return "unavailable";
  if (operations.scope_count === 0) return "forbidden";
  return operations.items.length ? "ready" : "empty";
}

export function formatSnapshotTime(value: string, timezone: string): string | null {
  if (!value || !Number.isFinite(Date.parse(value))) return null;
  try {
    return new Intl.DateTimeFormat("fa-IR", {
      hour: "2-digit", minute: "2-digit", timeZone: timezone,
    }).format(new Date(value));
  } catch {
    return null;
  }
}

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const positiveId = (value: unknown) => metricValue(value) !== null && Number(value) > 0;
const attentionDestinations: Record<AttentionKind, string> = {
  customer_request: "/admin/inquiries",
  catalog_image: "/admin/catalog-review",
  supplier: "/admin/suppliers",
};

/** Validate the existing server response before rendering; do not synthesize rows. */
export function parseDashboard(value: unknown): Dashboard {
  const fail = () => { throw new Error("پاسخ پیشخوان معتبر نیست؛ دوباره دریافت کنید."); };
  if (!record(value)) return fail();
  const ops = value.operations;
  if (
    typeof value.environment !== "string" || typeof value.as_of !== "string" ||
    typeof value.timezone !== "string" ||
    formatSnapshotTime(value.as_of, value.timezone) === null ||
    !record(value.metrics) || !Array.isArray(value.attention) ||
    typeof value.attention_is_sample !== "boolean" || !record(ops) ||
    metricValue(ops.scope_count) === null || !Array.isArray(ops.items) ||
    typeof ops.has_more !== "boolean" || !record(value.integrations) ||
    typeof value.integrations.sepidar !== "string"
  ) return fail();
  for (const item of value.attention) {
    if (!record(item) || !positiveId(item.id) || typeof item.title !== "string" ||
      typeof item.status !== "string" || typeof item.kind !== "string" ||
      !Object.prototype.hasOwnProperty.call(attentionDestinations, item.kind) ||
      item.href !== attentionDestinations[item.kind as AttentionKind]) return fail();
  }
  for (const item of ops.items) {
    if (!record(item) || !positiveId(item.id) || !positiveId(item.organization_id) ||
      typeof item.title !== "string") return fail();
  }
  if (ops.scope_count === 0 && (ops.items.length > 0 || ops.has_more)) return fail();
  return value as Dashboard;
}
