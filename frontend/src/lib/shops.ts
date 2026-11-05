/** Phase 1 — seller shops (غرفه‌ها). */
import { apiRequest } from "@/lib/api";

export interface Shop {
  id: number;
  slug: string | null;
  title: string;
  bio: string | null;
  logo_url: string | null;
  kind: "shop" | "brand" | "partner" | "supplier";
  province: string | null;
  city: string | null;
  rating_x10: number;
  official: boolean;
  url: string | null;
  // private (owner/admin) fields
  status?: string;
  onboarding_stage?: string;
  health_status?: "good" | "at_risk" | "suspended";
  commission_rate_bps?: number;
  sheba_on_file?: boolean;
}

export interface ShopItem {
  slug: string;
  title: string;
  price_minor: number | null;
  in_stock: boolean;
  min_order_quantity: number;
}

export interface ShopBalance {
  ready_minor: number;
  held_minor: number;
  settled_minor: number;
  hold_days: number;
}

export interface ShopApplication {
  seller_kind: "shop" | "brand" | "partner";
  legal_name: string;
  shop_title: string;
  shop_slug: string;
  national_id: string;
  mobile: string;
  province: string;
  city: string;
  sheba?: string;
  shop_bio?: string;
  accept_terms: boolean;
}

export const shops = {
  list: (kind?: string) =>
    apiRequest<{ items: Shop[] }>(`/shops${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`),
  page: (slug: string, page = 1) =>
    apiRequest<{ shop: Shop; items: ShopItem[]; total: number; page: number; page_size: number }>(
      `/shops/${encodeURIComponent(slug)}?page=${page}`,
    ),
  terms: () => apiRequest<{ version: string; hold_days: number }>("/shops/terms"),
  apply: (token: string, body: ShopApplication) =>
    apiRequest<{ shop: Shop }>("/sellers/apply", { method: "POST", token, body: JSON.stringify(body) }),
  mine: (token: string) => apiRequest<{ shop: Shop; balance: ShopBalance }>("/supplier/shop", { token }),
  update: (token: string, body: Partial<Pick<Shop, "title" | "bio" | "logo_url">> & Record<string, unknown>) =>
    apiRequest<{ shop: Shop }>("/supplier/shop", { method: "PUT", token, body: JSON.stringify(body) }),
};

export const KIND_LABEL: Record<string, string> = {
  shop: "غرفه‌دار",
  brand: "برند رسمی",
  partner: "شریک",
  supplier: "تأمین‌کننده",
};

export const HEALTH_LABEL: Record<string, string> = {
  good: "خوب",
  at_risk: "در خطر",
  suspended: "متوقف",
};
