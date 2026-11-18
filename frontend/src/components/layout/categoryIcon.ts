import {
  Apple, Armchair, Baby, Beef, BookOpen, BriefcaseBusiness, Car, Coffee, CookingPot, Cpu, Dumbbell, Gem, Gift,
  Hammer, HeartPulse, Home, LayoutGrid, Laptop, Leaf, type LucideIcon, Milk, Nut, PawPrint, Pencil, Router, Shirt,
  ShoppingBasket, Smartphone, Sparkles, SprayCan, Tv, Wheat,
} from "lucide-react";

// Icon is chosen from the real slug/name of a taxonomy node; unknown nodes get a neutral grid icon.
const RULES: [RegExp, LucideIcon][] = [
  [/laptop|computer|رایانه|لپ/i, Laptop], [/mobile|tablet|موبایل|تبلت|گوشی/i, Smartphone],
  [/network|router|شبکه|مودم/i, Router], [/digital|electronic|دیجیتال|الکترونیک/i, Cpu],
  [/tv|audio|video|صوتی|تصویری|تلویزیون/i, Tv], [/appliance|برقی|خانگی/i, CookingPot],
  [/kitchen|آشپزخانه/i, CookingPot], [/office|اداری|stationery|تحریر/i, Pencil], [/book|کتاب/i, BookOpen],
  [/business|سازمان/i, BriefcaseBusiness], [/nut|آجیل|خشکبار/i, Nut], [/dairy|لبنی|لبنیات/i, Milk],
  [/protein|meat|گوشت|پروتئین/i, Beef], [/fruit|میوه|سبزی/i, Apple], [/grain|rice|غلات|برنج|حبوبات/i, Wheat],
  [/tea|coffee|چای|قهوه|نوشیدنی/i, Coffee], [/supermarket|grocery|food|سوپرمارکت|خوراکی|مواد غذایی/i, ShoppingBasket],
  [/clean|detergent|شوینده|بهداشتی/i, SprayCan], [/beauty|cosmetic|آرایشی|زیبایی/i, Sparkles],
  [/health|medical|سلامت|پزشکی/i, HeartPulse], [/fashion|cloth|پوشاک|مد/i, Shirt], [/baby|kid|کودک|نوزاد/i, Baby],
  [/furniture|مبلمان|دکور/i, Armchair], [/home|خانه/i, Home], [/tool|ابزار/i, Hammer], [/sport|ورزش/i, Dumbbell],
  [/car|auto|خودرو/i, Car], [/pet|حیوان/i, PawPrint], [/gift|هدیه|کادو/i, Gift], [/jewel|طلا|زیورآلات/i, Gem],
  [/carpet|rug|فرش|موکت|گلیم/i, Leaf],
];

export function categoryIcon(slug: string, name = ""): LucideIcon {
  const key = `${slug} ${name}`;
  for (const [re, icon] of RULES) if (re.test(key)) return icon;
  return LayoutGrid;
}
