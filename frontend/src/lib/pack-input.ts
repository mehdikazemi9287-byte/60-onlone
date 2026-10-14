/** Persian inputs and integer Rial totals; no estimates for missing prices. */
export function normalizedDigits(value: string): string {
  return value.replace(/[۰-۹]/g, d => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
    .replace(/[٠-٩]/g, d => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)))
    .replace(/[,،٬\s]/g, "");
}
export function positiveInteger(value: string, maximum = 100000): number | null {
  const input = normalizedDigits(value);
  if (!/^\d+$/.test(input)) return null;
  const result = Number(input);
  return Number.isSafeInteger(result) && result > 0 && result <= maximum ? result : null;
}
export function tomanBudgetMinor(value: string): number | null {
  const amount = positiveInteger(value, Math.floor(Number.MAX_SAFE_INTEGER / 10));
  return amount === null ? null : amount * 10;
}
export function exactPackTotals(lines: { quantity: number; priceMinor: number | null }[], count: number) {
  if (!Number.isSafeInteger(count) || count < 1 || count > 100000 || !lines.length || lines.length > 50)
    return { status: "invalid" as const, perPackMinor: null, totalMinor: null };
  let subtotal = 0, missing = false;
  for (const line of lines) {
    if (!Number.isSafeInteger(line.quantity) || line.quantity < 1 || line.quantity * count > 100000)
      return { status: "invalid" as const, perPackMinor: null, totalMinor: null };
    if (line.priceMinor === null) { missing = true; continue; }
    if (!Number.isSafeInteger(line.priceMinor) || line.priceMinor < 0 || !Number.isSafeInteger(line.priceMinor * line.quantity))
      return { status: "invalid" as const, perPackMinor: null, totalMinor: null };
    subtotal += line.priceMinor * line.quantity;
    if (!Number.isSafeInteger(subtotal) || !Number.isSafeInteger(subtotal * count))
      return { status: "invalid" as const, perPackMinor: null, totalMinor: null };
  }
  return missing ? { status: "quote" as const, perPackMinor: null, totalMinor: null }
    : { status: "exact" as const, perPackMinor: subtotal, totalMinor: subtotal * count };
}
