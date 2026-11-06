// Marketplace storefront API (REAL products/offers only; prices only from verified offers).
import { apiRequest } from "./api";

export type TaxNode = { id: number; slug: string; name_fa: string; level: string; product_count: number; children: TaxNode[] };
export type Facets = { brands: { value: string; count: number }[]; categories: { slug: string; name_fa: string; count: number }[]; availability: { value: string; count: number }[];
  sizes?: { value: string; count: number }[]; price_range?: { min: number; max: number } | null };
export type Tier = { min_qty: number; max_qty: number | null; unit_price_minor: number; contract?: boolean };
export type Offer = {
  declared_channel?:string;allowed_channels?:string[];
  offer_id: number; seller: string; seller_city: string | null; pricing_mode: string; channel: string; price_minor: number | null;
  price_confirmed: boolean; stock_state: "in_stock" | "out_of_stock" | "unknown"; available: number | null; min_order_quantity: number;
  max_order_quantity: number | null; lead_time_days: number | null; valid_until: string | null; tiers: { retail: Tier[]; organization: Tier[] };
  provenance: string; eligible: boolean; list_price_minor?: number | null; list_price_at?: string | null; price_incl_vat_minor?: number | null; vat_bps?: number;
};
export type Variant = { allowed_channels?:string[]; supply_channel?:string; sku_id: number; slug: string; sku: string; label: string | null; title_fa: string; attributes: Record<string, unknown>;
  image_url: string | null; availability: string; price_minor: number | null; selected: boolean };
export type Card = { allowed_channels?:string[]; supply_channel?:string; id: number; slug: string; title_fa: string; brand_fa: string; image_url: string | null; price_minor: number | null;
  purchasable: boolean; variant_count: number; variant_labels: string[]; category_name_fa: string | null; availability: string;
  list_price_minor?: number | null; list_price_at?: string | null; org_only?: boolean };
export type ProductPage = {
  allowed_channels?:string[];supply_channel?:string;
  product: { allowed_channels?:string[];supply_channel?:string;sku_id: number; slug: string; sku: string; title_fa: string; family_title_fa: string; family_slug: string | null; brand_fa: string;
    description_fa: string; images: string[]; variant_label: string | null; attributes: Record<string, unknown>; specs: { label: string; value: unknown }[];
    provenance: string; master_product_id: number; unit?: string | null; package_quantity?: number | null };
  breadcrumbs: { slug: string; name_fa: string; level: string }[];
  variants: Variant[]; offers: Offer[]; availability: string; price_minor: number | null; price_incl_vat_minor?: number | null; vat_bps?: number; cta: "add_to_cart" | "request_quote";
  sale_blocker: string | null; sales_enabled: boolean; list_price_minor?: number | null; list_price_at?: string | null; org_only?: boolean; related: Card[]; alternatives: Card[];
};
export type PackItem = { allowed_channels?:string[]; master_product_id: number; sku_id: number | null; slug: string | null; title_fa: string; brand_fa: string | null;
  variant_label: string | null; image_url: string | null; quantity: number; required: boolean; weight_g: number | null;
  unit_price_minor: number | null; line_total_minor: number | null; available: boolean;
  alternatives?: { master_product_id: number; title_fa: string; brand_fa: string | null; variant_label: string | null; slug: string | null }[] };
export type PackSummary = { allowed_channels?:string[]; id: number; slug: string; title_fa: string; kind: string; kind_fa: string; tier: string | null; tier_fa: string | null;
  occasion: string | null; audience: string; audience_fa: string; purpose_fa: string; household_size: number | null; item_count: number;
  unit_count: number; food_weight_g: number | null; brands: string[]; customizable: boolean; substitution_policy: string; min_order_qty: number;
  lead_time_days: number | null; packaging_fa: string | null; availability: "purchasable" | "quote_only"; price_minor: number | null;
  price_per_person_minor: number | null; image_url: string | null };
export type PackDetail = PackSummary & { items: PackItem[]; description_fa: string | null };

export const storefront = {
  product: (slug: string, token?: string | null) => apiRequest<ProductPage>(`/storefront/products/${encodeURIComponent(slug)}`, { token: token ?? undefined }),
  brands: () => apiRequest<{ items: { name: string; product_count: number; image_url: string | null }[] }>("/storefront/brands"),
  packs: (qs = "") => apiRequest<{ items: PackSummary[] }>(`/storefront/packs${qs ? `?${qs}` : ""}`),
  pack: (slug: string) => apiRequest<{ pack: PackDetail }>(`/storefront/packs/${encodeURIComponent(slug)}`),
  compare: (slugs: string[]) => apiRequest<{ items: PackDetail[] }>(`/storefront/pack-compare?slugs=${slugs.map(encodeURIComponent).join(",")}`),
};

export const SALE_BLOCKER_FA: Record<string, string> = {
  no_verified_offer: "قیمت روز این کالا را برایتان استعلام می‌کنیم؛ درخواست را ثبت کنید تا قیمت و زمان تحویل اعلام شود.",
  offer_needs_quote: "قیمت این کالا بر اساس تعداد و شرایط شما اعلام می‌شود؛ درخواست استعلام را ثبت کنید.",
};
export const PRICING_MODE_FA: Record<string, string> = { fixed: "قیمت ثابت", bulk: "قیمت پلکانی عمده", contract: "قیمت قراردادی",
  rfq_only: "فقط استعلام", out_of_stock: "ناموجود", unavailable: "غیرفعال" };
