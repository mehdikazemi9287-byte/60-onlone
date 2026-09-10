export const BUDGET_PRESETS_MINOR = [
  { id: "starter", label: "۵ میلیون تومان", amount_minor: 50_000_000 },
  { id: "standard", label: "۱۵ میلیون تومان", amount_minor: 150_000_000 },
  { id: "premium", label: "۳۰ میلیون تومان", amount_minor: 300_000_000 },
];
export const OCCASIONS = [
  { id: "household", label: "لوازم خانگی روزمره", category_slugs: ["appliances", "appliance", "home-kitchen"] },
  { id: "supermarket", label: "سوپرمارکت و مایحتاج", category_slugs: ["supermarket", "nuts-local", "fresh-dairy-frozen"] },
  { id: "office", label: "اداری و سازمانی", category_slugs: ["office", "office-org"] },
  { id: "digital", label: "دیجیتال", category_slugs: ["digital", "laptop", "mobile"] },
  { id: "school", label: "مدرسه و نوشت‌افزار", category_slugs: ["books-stationery"] },
  { id: "gift", label: "هدیه و مناسبتی", category_slugs: ["gift-seasonal"] },
];
function assertMinor(value, label) {
  if (!Number.isInteger(value) || value < 0) throw new TypeError(`${label} must be a non-negative integer, received ${JSON.stringify(value)}`);
}
export function filterPriced(products) {
  if (!Array.isArray(products)) throw new TypeError("products must be an array");
  return products.filter((p) => Number.isInteger(p.price_minor) && p.price_minor > 0);
}
export function packTotalMinor(items) {
  if (!Array.isArray(items)) throw new TypeError("items must be an array");
  return items.reduce((sum, it) => { assertMinor(it.product.price_minor, "price_minor"); assertMinor(it.quantity, "quantity"); return sum + it.product.price_minor * it.quantity; }, 0);
}
export function budgetState(items, budgetMinor) {
  assertMinor(budgetMinor, "budgetMinor");
  const total = packTotalMinor(items);
  return { total_minor: total, remaining_minor: budgetMinor - total, over_budget: total > budgetMinor };
}
export function addItem(items, product, quantity = 1) {
  assertMinor(quantity, "quantity");
  if (quantity <= 0) return items;
  const idx = items.findIndex((it) => it.product.id === product.id);
  if (idx === -1) return [...items, { product, quantity }];
  const next = [...items]; next[idx] = { product, quantity: next[idx].quantity + quantity }; return next;
}
export function removeItem(items, productId) { return items.filter((it) => it.product.id !== productId); }
export function setQuantity(items, productId, quantity) {
  assertMinor(quantity, "quantity");
  if (quantity <= 0) return removeItem(items, productId);
  return items.map((it) => (it.product.id === productId ? { ...it, quantity } : it));
}
export function replaceItem(items, productId, newProduct) {
  const idx = items.findIndex((it) => it.product.id === productId);
  if (idx === -1) return items;
  const next = [...items]; next[idx] = { product: newProduct, quantity: next[idx].quantity }; return next;
}
function fillToTarget(sortedProducts, targetMinor) {
  assertMinor(targetMinor, "targetMinor");
  const items = []; let total = 0;
  for (const product of sortedProducts) if (total + product.price_minor <= targetMinor) { items.push({ product, quantity: 1 }); total += product.price_minor; }
  return { items, total_minor: total };
}
export function buildRecommendations(products, budgetMinor) {
  assertMinor(budgetMinor, "budgetMinor");
  const available = filterPriced(products).filter((p) => p.in_stock !== false);
  const cheapFirst = [...available].sort((a, b) => a.price_minor - b.price_minor);
  const pricyFirst = [...available].sort((a, b) => b.price_minor - a.price_minor);
  const economyTarget = Math.floor(budgetMinor * 0.6), balancedTarget = Math.floor(budgetMinor * 0.9), premiumTarget = budgetMinor;
  const economy = fillToTarget(cheapFirst, economyTarget), balanced = fillToTarget(cheapFirst, balancedTarget), premium = fillToTarget(pricyFirst, premiumTarget);
  const withRemaining = (tier, target) => ({ ...tier, remaining_minor: target - tier.total_minor, over_budget: tier.total_minor > budgetMinor });
  return {
    economy: { id: "economy", label: "اقتصادی", ...withRemaining(economy, economyTarget) },
    balanced: { id: "balanced", label: "متعادل", ...withRemaining(balanced, balancedTarget) },
    premium: { id: "premium", label: "ویژه", ...withRemaining(premium, premiumTarget) },
  };
}
