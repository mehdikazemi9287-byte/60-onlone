// Smart 60 Pack Builder — pure logic (no DOM). PORTED VERBATIM from the
// original vanilla-JS storefront: /home/ubuntu/70online/repo/frontend/src/pack-builder.js
// (recovered 2026-09-10). Algorithm, thresholds, labels and honesty rules are
// unchanged. Only TypeScript types were added. Unit-tested in pack-builder.test.mjs.
//
// integer minor units only; server (cart/checkout) remains authoritative; this
// only drives the optimistic in-page budget UI. A "pack" is a plain array of
// { product, quantity }. `product` must carry an integer `price_minor` — a
// product with no resolvable price is never invented a price and must be
// filtered out by the caller before it reaches these functions (see filterPriced).

export interface PBProduct {
  id: number;
  price_minor: number | null;
  in_stock?: boolean;
  title_fa?: string;
  slug?: string;
  [k: string]: unknown;
}
export interface PBItem { product: PBProduct; quantity: number; }
export interface PBBudgetState { total_minor: number; remaining_minor: number; over_budget: boolean; }
export interface PBTier { id: string; label: string; items: PBItem[]; total_minor: number; remaining_minor: number; over_budget: boolean; }

export const BUDGET_PRESETS_MINOR = [
  { id: "starter", label: "۵ میلیون تومان", amount_minor: 50_000_000 },
  { id: "standard", label: "۱۵ میلیون تومان", amount_minor: 150_000_000 },
  { id: "premium", label: "۳۰ میلیون تومان", amount_minor: 300_000_000 },
] as const;

export const OCCASIONS = [
  { id: "household", label: "لوازم خانگی روزمره", category_slugs: ["appliances", "appliance", "home-kitchen"] },
  { id: "supermarket", label: "سوپرمارکت و مایحتاج", category_slugs: ["supermarket", "nuts-local", "fresh-dairy-frozen"] },
  { id: "office", label: "اداری و سازمانی", category_slugs: ["office", "office-org"] },
  { id: "digital", label: "دیجیتال", category_slugs: ["digital", "laptop", "mobile"] },
  { id: "school", label: "مدرسه و نوشت‌افزار", category_slugs: ["books-stationery"] },
  { id: "gift", label: "هدیه و مناسبتی", category_slugs: ["gift-seasonal"] },
] as const;

function assertMinor(value: unknown, label: string): asserts value is number {
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new TypeError(`${label} must be a non-negative integer, received ${JSON.stringify(value)}`);
  }
}

/** Keep only products with a real, positive integer price. Never invents one. */
export function filterPriced(products: PBProduct[]): PBProduct[] {
  if (!Array.isArray(products)) throw new TypeError("products must be an array");
  return products.filter((p) => Number.isInteger(p.price_minor) && (p.price_minor as number) > 0);
}

export function packTotalMinor(items: PBItem[]): number {
  if (!Array.isArray(items)) throw new TypeError("items must be an array");
  return items.reduce((sum, it) => {
    assertMinor(it.product.price_minor, "price_minor");
    assertMinor(it.quantity, "quantity");
    return sum + (it.product.price_minor as number) * it.quantity;
  }, 0);
}

export function budgetState(items: PBItem[], budgetMinor: number): PBBudgetState {
  assertMinor(budgetMinor, "budgetMinor");
  const total = packTotalMinor(items);
  return { total_minor: total, remaining_minor: budgetMinor - total, over_budget: total > budgetMinor };
}

export function addItem(items: PBItem[], product: PBProduct, quantity = 1): PBItem[] {
  assertMinor(quantity, "quantity");
  if (quantity <= 0) return items;
  const idx = items.findIndex((it) => it.product.id === product.id);
  if (idx === -1) return [...items, { product, quantity }];
  const next = [...items];
  next[idx] = { product, quantity: next[idx].quantity + quantity };
  return next;
}

export function removeItem(items: PBItem[], productId: number): PBItem[] {
  return items.filter((it) => it.product.id !== productId);
}

export function setQuantity(items: PBItem[], productId: number, quantity: number): PBItem[] {
  assertMinor(quantity, "quantity");
  if (quantity <= 0) return removeItem(items, productId);
  return items.map((it) => (it.product.id === productId ? { ...it, quantity } : it));
}

export function replaceItem(items: PBItem[], productId: number, newProduct: PBProduct): PBItem[] {
  const idx = items.findIndex((it) => it.product.id === productId);
  if (idx === -1) return items;
  const next = [...items];
  next[idx] = { product: newProduct, quantity: next[idx].quantity };
  return next;
}

/** Fill greedily from `sortedProducts` up to `targetMinor` without exceeding it. */
function fillToTarget(sortedProducts: PBProduct[], targetMinor: number): { items: PBItem[]; total_minor: number } {
  assertMinor(targetMinor, "targetMinor");
  const items: PBItem[] = [];
  let total = 0;
  for (const product of sortedProducts) {
    if (total + (product.price_minor as number) <= targetMinor) {
      items.push({ product, quantity: 1 });
      total += product.price_minor as number;
    }
  }
  return { items, total_minor: total };
}

/**
 * Three dynamic recommendation tiers built from real catalog data only.
 * Economy fills toward the low end of the budget from the cheapest priced,
 * in-stock products; Premium fills toward the full budget from the priciest;
 * Balanced targets the middle. A product with no price never appears here
 * (see filterPriced) — there is no invented price anywhere in this module.
 */
export function buildRecommendations(products: PBProduct[], budgetMinor: number): {
  economy: PBTier; balanced: PBTier; premium: PBTier;
} {
  assertMinor(budgetMinor, "budgetMinor");
  const available = filterPriced(products).filter((p) => p.in_stock !== false);

  const cheapFirst = [...available].sort((a, b) => (a.price_minor as number) - (b.price_minor as number));
  const pricyFirst = [...available].sort((a, b) => (b.price_minor as number) - (a.price_minor as number));

  const economyTarget = Math.floor(budgetMinor * 0.6);
  const balancedTarget = Math.floor(budgetMinor * 0.9);
  const premiumTarget = budgetMinor;

  const economy = fillToTarget(cheapFirst, economyTarget);
  const balanced = fillToTarget(cheapFirst, balancedTarget);
  const premium = fillToTarget(pricyFirst, premiumTarget);

  const withRemaining = (tier: { items: PBItem[]; total_minor: number }, target: number) => ({
    ...tier,
    remaining_minor: target - tier.total_minor,
    over_budget: tier.total_minor > budgetMinor,
  });

  return {
    economy: { id: "economy", label: "اقتصادی", ...withRemaining(economy, economyTarget) },
    balanced: { id: "balanced", label: "متعادل", ...withRemaining(balanced, balancedTarget) },
    premium: { id: "premium", label: "ویژه", ...withRemaining(premium, premiumTarget) },
  };
}
