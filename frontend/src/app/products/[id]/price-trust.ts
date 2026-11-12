// Footer trust line of the product page. It must match what the price box above it shows (audit SO-04):
// only a sale-eligible seller price may be called "verified"; a supplier list price or an inquiry-only item
// never claims a verified price or verified stock.
export type PriceTrustInput = { price_minor?: number | null; list_price_minor?: number | null };

export function priceTrustText(d: PriceTrustInput): string {
  if (d.price_minor != null) return "قیمتی که می‌بینید قیمت تأییدشدهٔ فروشنده است، نه قیمت تخمینی.";
  if (d.list_price_minor) return "قیمت نمایش‌داده‌شده قیمت فهرست تأمین‌کننده است، نه قیمت نهایی فروش؛ قیمت و موجودی هنگام استعلام تأیید می‌شود.";
  return "قیمت و موجودی این کالا پس از ثبت استعلام اعلام می‌شود.";
}
