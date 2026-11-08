import { scopedDraftKey, pendingDraftKey } from "@/lib/client-draft-storage";
// Shared organizational order draft — the single model behind the Order
// Composer, the 60AI procurement copilot and the Pack Builder hand-off.
// Prices are never invented: a line is "needs_quote" unless the catalog
// returned a verified offer price for it.

export type RequestKind = "general" | "gift_pack" | "it_equipment" | "office" | "event";
export type Priority = "low" | "normal" | "high" | "urgent";
export type DraftSource = "manual" | "assistant" | "pack_builder";

export interface LineItem {
  id: string;
  name: string;
  masterProductId: number | null;
  sku: string | null;
  imageUrl: string | null;
  quantity: number;
  unit: string;
  targetSpec: string;
  alternative: string;
  targetUnitPriceToman: number | null;
  verifiedPriceMinor: number | null; // only from a verified catalog offer
  catalog: "idle" | "searching" | "matched" | "none";
}

export interface Destination {
  id: string;
  label: string;
  province: string;
  city: string;
  address: string;
  recipient: string;
  phone: string;
  window: string;
  notes: string;
  alloc: Record<string, number>; // item id -> quantity
}

export interface Draft {
  title: string;
  kind: RequestKind;
  recipients: number | null;
  budgetTotalToman: number | null;
  budgetPerCapitaToman: number | null;
  neededBy: string; // YYYY-MM-DD
  priority: Priority;
  constraints: string[];
  notes: string;
  items: LineItem[];
  destinations: Destination[];
  source: DraftSource;
}

export const KIND_LABEL: Record<RequestKind, string> = {
  general: "خرید عمومی", gift_pack: "پک هدیه/مناسبتی", it_equipment: "تجهیزات فناوری", office: "لوازم اداری", event: "رویداد",
};
export const PRIORITY_LABEL: Record<Priority, string> = { low: "کم", normal: "عادی", high: "بالا", urgent: "فوری" };
export const UNITS = ["عدد", "دستگاه", "بسته", "کارتن", "پک", "جفت", "کیلوگرم", "لیتر", "متر", "سرویس"];

let seq = 0;
export const uid = (p: string) => `${p}${Date.now().toString(36)}${(seq++).toString(36)}`;

export function newItem(name = "", quantity = 1, extra: Partial<LineItem> = {}): LineItem {
  return {
    id: uid("i"), name, masterProductId: null, sku: null, imageUrl: null, quantity, unit: "",
    targetSpec: "", alternative: "", targetUnitPriceToman: null, verifiedPriceMinor: null, catalog: "idle", ...extra,
  };
}

export function newDestination(extra: Partial<Destination> = {}): Destination {
  return { id: uid("d"), label: "", province: "", city: "", address: "", recipient: "", phone: "", window: "", notes: "", alloc: {}, ...extra };
}

export function emptyDraft(source: DraftSource = "manual"): Draft {
  return {
    title: "", kind: "general", recipients: null, budgetTotalToman: null, budgetPerCapitaToman: null, neededBy: "",
    priority: "normal", constraints: [], notes: "", items: [], destinations: [newDestination()], source,
  };
}

export type DraftOp =
  | { type: "set"; patch: Partial<Omit<Draft, "items" | "destinations">> }
  | { type: "addItem"; item: LineItem }
  | { type: "updateItem"; id: string; patch: Partial<LineItem> }
  | { type: "removeItem"; id: string }
  | { type: "addDestination"; destination: Destination }
  | { type: "updateDestination"; id: string; patch: Partial<Omit<Destination, "alloc">> }
  | { type: "removeDestination"; id: string }
  | { type: "setAlloc"; destinationId: string; itemId: string; quantity: number }
  | { type: "splitEqual" }
  | { type: "splitByCounts"; counts: Record<string, number> } // destination id -> share
  | { type: "replace"; draft: Draft };

/** Largest-remainder split so every item's allocations add up exactly. */
function split(total: number, weights: number[]): number[] {
  const sum = weights.reduce((a, b) => a + b, 0) || 1;
  const raw = weights.map((w) => (total * w) / sum);
  const base = raw.map(Math.floor);
  let rest = total - base.reduce((a, b) => a + b, 0);
  const order = raw.map((r, i) => [r - Math.floor(r), i]).sort((a, b) => b[0] - a[0]);
  for (const [, i] of order) { if (rest-- <= 0) break; base[i] += 1; }
  return base;
}

function reallocate(d: Draft, weights: number[]): Draft {
  const dests = d.destinations.map((x) => ({ ...x, alloc: { ...x.alloc } }));
  for (const item of d.items) {
    const parts = split(item.quantity, weights);
    dests.forEach((x, i) => { x.alloc[item.id] = parts[i]; });
  }
  return { ...d, destinations: dests };
}

/** Allocate one item across destinations, keeping each destination's current share. */
function spreadItem(d: Draft, itemId: string, quantity: number): Draft {
  if (d.destinations.length === 1) {
    const only = d.destinations[0];
    return { ...d, destinations: [{ ...only, alloc: { ...only.alloc, [itemId]: quantity } }] };
  }
  const own = d.destinations.map((x) => x.alloc[itemId] || 0);
  const others = d.destinations.map((x) => d.items.reduce((s, i) => s + (i.id === itemId ? 0 : x.alloc[i.id] || 0), 0));
  const weights = own.some((w) => w > 0) ? own : others.some((w) => w > 0) ? others : d.destinations.map(() => 1);
  const parts = split(quantity, weights);
  return { ...d, destinations: d.destinations.map((x, n) => ({ ...x, alloc: { ...x.alloc, [itemId]: parts[n] } })) };
}

export function applyOp(d: Draft, op: DraftOp): Draft {
  switch (op.type) {
    case "set": {
      const next = { ...d, ...op.patch };
      // Keep total and per-capita budget consistent when recipients are known.
      if (next.recipients && op.patch.budgetPerCapitaToman !== undefined && op.patch.budgetTotalToman === undefined)
        next.budgetTotalToman = next.budgetPerCapitaToman != null ? next.budgetPerCapitaToman * next.recipients : null;
      else if (next.recipients && op.patch.budgetTotalToman !== undefined && op.patch.budgetPerCapitaToman === undefined)
        next.budgetPerCapitaToman = next.budgetTotalToman != null ? Math.round(next.budgetTotalToman / next.recipients) : null;
      else if (op.patch.recipients !== undefined && next.recipients && next.budgetPerCapitaToman != null)
        next.budgetTotalToman = next.budgetPerCapitaToman * next.recipients;
      return next;
    }
    case "addItem":
      return spreadItem({ ...d, items: [...d.items, op.item] }, op.item.id, op.item.quantity);
    case "updateItem": {
      const items = d.items.map((i) => (i.id === op.id ? { ...i, ...op.patch } : i));
      return op.patch.quantity !== undefined ? spreadItem({ ...d, items }, op.id, op.patch.quantity) : { ...d, items };
    }
    case "removeItem":
      return {
        ...d, items: d.items.filter((i) => i.id !== op.id),
        destinations: d.destinations.map((x) => { const alloc = { ...x.alloc }; delete alloc[op.id]; return { ...x, alloc }; }),
      };
    case "addDestination": {
      const next = { ...d, destinations: [...d.destinations, op.destination] };
      return next;
    }
    case "updateDestination":
      return { ...d, destinations: d.destinations.map((x) => (x.id === op.id ? { ...x, ...op.patch } : x)) };
    case "removeDestination": {
      if (d.destinations.length <= 1) return d;
      const next = { ...d, destinations: d.destinations.filter((x) => x.id !== op.id) };
      return next.destinations.length === 1 ? reallocate(next, [1]) : next;
    }
    case "setAlloc":
      return {
        ...d, destinations: d.destinations.map((x) => (x.id === op.destinationId
          ? { ...x, alloc: { ...x.alloc, [op.itemId]: Math.max(0, Math.floor(op.quantity) || 0) } } : x)),
      };
    case "splitEqual":
      return reallocate(d, d.destinations.map(() => 1));
    case "splitByCounts":
      return reallocate(d, d.destinations.map((x) => op.counts[x.id] ?? 0));
    case "replace":
      return op.draft;
  }
}

// ── Reconciliation & validation ─────────────────────────────────────────────

export function allocated(d: Draft, itemId: string): number {
  if (d.destinations.length === 1) return d.items.find((i) => i.id === itemId)?.quantity ?? 0;
  return d.destinations.reduce((s, x) => s + (x.alloc[itemId] || 0), 0);
}

export interface Issue { level: "error" | "warn"; text: string; target?: string }

export function validate(d: Draft): Issue[] {
  const out: Issue[] = [];
  if (!d.title.trim()) out.push({ level: "error", text: "عنوان درخواست را وارد کنید", target: "title" });
  if (!d.items.length) out.push({ level: "error", text: "حداقل یک قلم اضافه کنید", target: "items" });
  if (d.items.length > 50) out.push({ level: "error", text: "حداکثر ۵۰ قلم در هر درخواست", target: "items" });
  d.items.forEach((i, n) => {
    if (!i.name.trim()) out.push({ level: "error", text: `شرح قلم ${n + 1} خالی است`, target: i.id });
    if (!Number.isSafeInteger(i.quantity) || i.quantity < 1 || i.quantity > 100000) out.push({ level: "error", text: `تعداد «${i.name || n + 1}» نامعتبر است`, target: i.id });
  });
  d.destinations.forEach((x, n) => {
    const name = x.label || x.city || `مقصد ${n + 1}`;
    if (!x.province.trim() || !x.city.trim() || !x.address.trim())
      out.push({ level: "error", text: `استان، شهر و نشانی «${name}» را کامل کنید`, target: x.id });
  });
  if (d.destinations.length > 1) {
    for (const i of d.items) {
      const a = allocated(d, i.id);
      if (a !== i.quantity) out.push({ level: "error", text: `تخصیص «${i.name}»: ${a} از ${i.quantity}`, target: i.id });
    }
    d.destinations.forEach((x, n) => {
      if (!d.items.some((i) => (x.alloc[i.id] || 0) > 0))
        out.push({ level: "error", text: `مقصد «${x.label || x.city || n + 1}» هیچ سهمی ندارد`, target: x.id });
    });
  }
  if (!d.neededBy) out.push({ level: "warn", text: "تاریخ موردنیاز مشخص نشده است", target: "neededBy" });
  return out;
}

// ── API payload ──────────────────────────────────────────────────────────────

export function toRequestPayload(d: Draft, currency: string | undefined) {
  const total = d.budgetTotalToman ?? (d.budgetPerCapitaToman && d.recipients ? d.budgetPerCapitaToman * d.recipients : null);
  const facts = [
    `نوع: ${KIND_LABEL[d.kind]}`,
    d.recipients ? `تعداد گیرندگان: ${d.recipients}` : "",
    d.budgetPerCapitaToman ? `بودجه سرانه: ${d.budgetPerCapitaToman.toLocaleString("en-US")} تومان` : "",
    d.constraints.length ? `محدودیت‌ها: ${d.constraints.join("؛ ")}` : "",
    `منبع: ${d.source === "assistant" ? "دستیار خرید 60AI" : d.source === "pack_builder" ? "پک‌ساز" : "ساخت دستی"}`,
  ].filter(Boolean).join("\n");
  const single = d.destinations.length === 1;
  return {
    title: d.title.trim(),
    description: facts,
    notes: d.notes.trim() || null,
    urgency: d.priority,
    needed_by_date: d.neededBy || null,
    budget_minor: currency === "IRR" && total ? Math.round(total) * 10 : null,
    substitution_policy: "require_approval",
    items: d.items.map((i) => ({
      ...(i.masterProductId ? { master_product_id: i.masterProductId } : { free_text_description: i.name.trim() }),
      quantity: i.quantity,
      unit: i.unit || null,
      target_specification: i.targetSpec.trim() || null,
      acceptable_alternative: i.alternative.trim() || null,
      estimated_unit_price_minor: currency === "IRR" && i.targetUnitPriceToman ? Math.round(i.targetUnitPriceToman) * 10 : null,
    })),
    destinations: d.destinations.map((x) => ({
      label: x.label.trim() || null, province: x.province.trim(), city: x.city.trim(), address: x.address.trim(),
      recipient_name: x.recipient.trim() || null, recipient_phone: x.phone.trim() || null,
      delivery_window: x.window.trim() || null, notes: x.notes.trim() || null,
      allocations: d.items
        .map((i, item_index) => ({ item_index, quantity: single ? i.quantity : x.alloc[i.id] || 0 }))
        .filter((a) => a.quantity > 0),
    })),
  };
}

// ── Persistence (per-viewer convenience only) ────────────────────────────────

export const DRAFT_STORAGE_KEY = "60o_org_order_draft_v1";

export function loadDraft(): Draft | null {
  try {
    const raw = localStorage.getItem(scopedDraftKey(DRAFT_STORAGE_KEY));
    if (!raw) return null;
    const d = JSON.parse(raw) as Draft;
    return Array.isArray(d.items) && Array.isArray(d.destinations) && d.destinations.length ? d : null;
  } catch { return null; }
}

export function saveDraft(d: Draft | null) {
  try { if (d) localStorage.setItem(scopedDraftKey(DRAFT_STORAGE_KEY), JSON.stringify(d)); else localStorage.removeItem(scopedDraftKey(DRAFT_STORAGE_KEY)); return true; } catch { return false; }
}

/** Add a catalog product to the local organizational draft; returns the new item count. */
export function addProductToOrgDraft(p: { name: string; master_product_id?: number | null; image_url?: string | null; sku?: string | null }, quantity = 1): number {
  const d = loadDraft() ?? emptyDraft("manual");
  const existing = p.master_product_id ? d.items.find((i) => i.masterProductId === p.master_product_id) : undefined;
  if (existing) {
    // Same catalog item again: raise its quantity instead of duplicating the line.
    if (quantity > 1) saveDraft(applyOp(d, { type: "updateItem", id: existing.id, patch: { quantity: existing.quantity + quantity } }));
    return d.items.length;
  }
  const next = applyOp(d, {
    type: "addItem",
    item: newItem(p.name, Math.max(1, Math.floor(quantity)), { masterProductId: p.master_product_id ?? null, imageUrl: p.image_url ?? null, sku: p.sku ?? null, catalog: p.master_product_id ? "matched" : "none" }),
  });
  saveDraft(next);
  return next.items.length;
}

/** Pack Builder / other entry points hand a draft over through this key. */
export function handOffDraft(d: Draft) { return saveDraft(d); }

export function loadPendingDraft(): Draft | null {
  try { const d=JSON.parse(localStorage.getItem(pendingDraftKey(DRAFT_STORAGE_KEY))||"null");return d&&Array.isArray(d.items)&&Array.isArray(d.destinations)&&d.destinations.length?d:null;}catch{return null;}
}
export function clearPendingDraft(){try{localStorage.removeItem(pendingDraftKey(DRAFT_STORAGE_KEY));}catch{}}
