// Tiered price alerts — client for /api/v1/me/price-watches and /api/v1/supplier/price-alerts.
// The level is decided by the server from the account; the client never sends one.
import { apiRequest } from "@/lib/api";

export type WatchLevel = "consumer" | "employee" | "org_buyer" | "shop";
export type AlertType = "price_target" | "back_in_stock" | "welfare_added" | "price_drop" | "new_seller" | "contract_expiring" | "new_tier";

export type PriceWatch = {
  id: number;
  product: { id: number; slug: string; title_fa: string };
  level: WatchLevel; level_fa: string; organization_id: number | null; quantity: number;
  target_price_minor: number | null; alert_types: AlertType[]; sms_enabled: boolean; active: boolean;
  /** Alert types this watch's level may use, with their Persian labels — the server is the only source. */
  allowed_alert_types: AlertType[]; alert_fa: Partial<Record<AlertType, string>>;
  created_at: string; last_notified_at: string | null;
  current: { price_minor: number | null; in_stock: boolean | null; checked_at: string | null; level_changed: boolean };
  price_hidden?: boolean;
};

export type LevelInfo = {
  level: WatchLevel; level_fa: string; organization_id: number | null; alert_types: AlertType[]; price_visible: boolean;
  alert_fa: Partial<Record<AlertType, string>>;
  is_seller: boolean; options: { organization_id: number; organization_name: string | null; level: WatchLevel; level_fa: string }[];
};

export type WatchHistory = { watch_id: number; level: WatchLevel; level_fa: string; quantity: number; days: number;
  points: { day: string; min_price_minor: number | null; price_minor: number | null; in_stock: boolean }[] };

export type SellerAlerts = {
  checked: boolean; sms_enabled: boolean;
  items: { product: { id: number; slug: string; title_fa: string }; level: "retail" | "organization"; level_fa: string;
    is_best: boolean; own_price_minor: number | null; updated_at: string }[];
  recent: { product: { id: number; slug: string; title_fa: string }; text: string; created_at: string }[];
};

export const priceWatch = {
  list: (token: string) => apiRequest<{ items: PriceWatch[]; level: LevelInfo; price_hidden?: boolean }>("/me/price-watches", { token }),
  forProduct: (token: string, slug: string) =>
    apiRequest<{ items: PriceWatch[] }>(`/me/price-watches?product=${encodeURIComponent(slug)}`, { token }),
  level: (token: string) => apiRequest<LevelInfo>("/me/price-watches/level", { token }),
  create: (token: string, body: { slug: string; target_price_minor?: number; quantity?: number; organization_id?: number }) =>
    apiRequest<{ watch: PriceWatch }>("/me/price-watches", { token, method: "POST", body: JSON.stringify(body) }),
  update: (token: string, id: number, body: Partial<{ target_price_minor: number | null; quantity: number; alert_types: AlertType[]; active: boolean; sms_enabled: boolean }>) =>
    apiRequest<{ watch: PriceWatch }>(`/me/price-watches/${id}`, { token, method: "PATCH", body: JSON.stringify(body) }),
  remove: (token: string, id: number) => apiRequest<{ deleted: boolean }>(`/me/price-watches/${id}`, { token, method: "DELETE" }),
  history: (token: string, id: number) => apiRequest<WatchHistory>(`/me/price-watches/${id}/history?days=90`, { token }),
  seller: (token: string) => apiRequest<SellerAlerts>("/supplier/price-alerts", { token }),
  sellerSms: (token: string, enabled: boolean) =>
    apiRequest<{ sms_enabled: boolean }>("/supplier/price-alerts/settings", { token, method: "PATCH", body: JSON.stringify({ sms_enabled: enabled }) }),
};
