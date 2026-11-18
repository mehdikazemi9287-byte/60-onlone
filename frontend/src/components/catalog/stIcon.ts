// Material Symbols name for a real taxonomy node (Stitch screens 27/05 use Material icons, not lucide).
// Only names present in the self-hosted subset (tools/stitch/icons-included.txt) are used; the closest
// available glyph stands in where the ideal one (laptop_mac, smartphone, router, tv, kitchen…) is not in the subset.
const RULES: [RegExp, string][] = [
  [/laptop|computer|رایانه|لپ/i, "inventory_2"], [/mobile|tablet|موبایل|تبلت|گوشی/i, "phone"],
  [/network|router|شبکه|مودم/i, "hub"], [/appliance|برقی|electronic|الکترونیک|digital|دیجیتال/i, "bolt"],
  [/office|اداری|stationery|تحریر/i, "edit_note"], [/print|چاپ/i, "print"], [/book|کتاب/i, "menu_book"],
  [/business|سازمان/i, "business_center"], [/nut|آجیل|خشکبار/i, "nutrition"], [/grain|rice|غلات|برنج|حبوبات/i, "rice_bowl"],
  [/tea|coffee|چای|قهوه|نوشیدنی/i, "coffee"], [/supermarket|grocery|food|سوپرمارکت|خوراکی|مواد غذایی/i, "shopping_basket"],
  [/clean|detergent|شوینده/i, "cleaning_services"], [/hygien|بهداشت/i, "sanitizer"], [/beauty|cosmetic|آرایشی|زیبایی/i, "spa"],
  [/health|medical|سلامت|پزشکی/i, "health_and_safety"], [/home|خانه/i, "home"], [/gift|هدیه|کادو|پک/i, "card_giftcard"],
  [/car|auto|خودرو/i, "directions_car"], [/cool|سرمایش/i, "ac_unit"], [/shop|فروشگاه/i, "storefront"],
];

export function stIcon(slug: string, name = ""): string {
  const key = `${slug} ${name}`;
  for (const [re, icon] of RULES) if (re.test(key)) return icon;
  return "category";
}
