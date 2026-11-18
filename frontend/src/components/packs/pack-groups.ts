// Occasion groups for /pack-builder filters and the catalog archive (Stitch 55/57/62/63 labels).
import type { PackDetail } from "@/lib/storefront";

const text = (p: PackDetail) => `${p.title_fa} ${p.purpose_fa} ${p.occasion ?? ""} ${p.kind_fa}`;
const has = (re: RegExp) => (p: PackDetail) => re.test(text(p));
// Occasion filters (Stitch 55/62/63 labels). Matching is on real pack fields only; an empty group shows an honest empty state.
export const GROUPS: [string, string, (p: PackDetail) => boolean][] = [
  ["", "همه پک‌ها", () => true],
  ["livelihood", "معیشتی و ارزاق", (p) => p.kind === "livelihood" || (p.audience === "household" && p.kind !== "occasion")],
  ["occasion", "مناسبت‌ها و نذورات", (p) => p.kind === "occasion" || !!p.occasion || has(/نذر|محرم|افطار/)(p)],
  ["cultural", "فرهنگی و مدارس", has(/فرهنگ|کتاب|مدرس|تحصیل|نوشت.?افزار|تحریر/)],
  ["premium", "هدایای فاخر و صنایع‌دستی", (p) => ["premium", "executive"].includes(p.tier ?? "")],
  ["hotel", "تجهیز هتل و مراکز", has(/هتل|پذیرایی|مهمانسرا|آبدارخانه/)],
  ["work", "سازمانی و کارکنان", (p) => ["organization", "office", "employee_gift"].includes(p.audience)],
  ["charity", "خیریه", has(/خیریه|نیازمند|مستمند|مهربانی/)],
];
