// ── Core domain types matching the backend API ──────────────────────────────

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: "customer" | "supplier" | "admin";
  is_active: boolean;
}

export interface Organization {
  id: number;
  display_name: string;
  legal_name: string;
  status: "active" | "suspended";
  credit_limit_minor: number;
}

export interface CreditAllocation {
  id: number;
  amount_minor: number;
  available_minor: number;
  allocated_minor: number;
  expires_at: string | null;
  status: "active" | "exhausted" | "expired";
}

export interface Category {
  id: number;
  slug: string;
  name: string;
  icon: string | null;
  parent_id: number | null;
  product_count: number;
}

export interface Product {
  id: number;
  slug: string;
  name: string;
  description: string;
  price_minor: number | null;
  purchasable: boolean;
  price_status?: "verified" | "pending";
  original_price_minor?: number;  // if set and > price_minor, shows discount badge
  image_url?: string;
  category?: Category;
  brand?: string;
  rating?: number;
  review_count?: number;
  stock?: number;
  sku?: string;
  specifications?: ProductSpecs;
  master_product_id?: number | null; // catalog identity (organization RFQ)
  variant_count?: number;
  variant_labels?: string[];
  availability?: "purchasable" | "quote" | "no_offer";
  family_slug?: string | null;
  price_from?: boolean;
  /** Latest known supplier/list price (IRR) with its date — informational, never a sale price. */
  list_price_minor?: number | null;
  list_price_at?: string | null;
  /** Bulk/B2B item: organizational purchasing only. */
  org_only?: boolean;
  allowed_channels?:string[];supply_channel?:string;
}

export interface ProductSpecs {
  groups: { title: string; items: { label: string; value: string }[] }[];
  source: { url: string; type: string; retrieved_at?: string; note?: string };
}

export interface CartItem {
  product_id: number;
  slug?: string;
  title_fa: string;
  sku: string;
  unit_price_minor: number;
  quantity: number;
  quantity_available?: number;
  line_total_minor: number;
  image_emoji: string;
  image_url?: string | null;
}

export interface Cart {
  cart_id?: number;
  item_count: number;
  subtotal_minor: number;
  subtotal: string;
  shipping_fee_minor: number;
  shipping_fee: string;
  total_minor?: number;
  total?: string;
  currency: string;
  items: CartItem[];
}

export interface CheckoutQuote {
  recurring_discount_minor?: number;
  cart: {
    item_count: number;
    subtotal: string;
    subtotal_minor: number;
    shipping_fee: string;
    shipping_fee_minor: number;
    total: string;
    total_minor: number;
  };
  currency: string;
  taxable_base_minor: number;
  tax_rate_bps: number;
  tax_minor: number;
  tax: string;
  has_organization_credit: boolean;
  organization: { id: number; display_name: string } | null;
  allocation: { id: number; expires_at: string | null } | null;
  eligible_credit: string;
  eligible_credit_minor: number;
  credit_to_use: string;
  credit_to_use_minor: number;
  cash_due: string;
  cash_due_minor: number;
  final_payable: string;
  final_payable_minor: number;
  payment_method: "card" | "credit" | "split";
  restrictions: { code: string; message: string }[];
}

export interface Order {
  id: number;
  order_number: string;
  status: "pending" | "paid" | "processing" | "shipped" | "delivered" | "cancelled";
  subtotal_minor: number;
  shipping_fee_minor: number;
  tax_minor: number;
  tax?: string;
  total: string;
  total_minor: number;
  credit_minor: number;
  cash_minor: number;
  currency: string;
  placed_at: string;
  shipping_address?: Address;
  items: OrderItem[];
}

export interface OrderItem {
  product_id: number;
  slug?: string;
  image_emoji?: string;
  title_fa: string;
  sku: string;
  unit_price_minor: number;
  quantity: number;
  line_total_minor: number;
}

export interface Address {
  recipient_name: string;
  recipient_phone: string;
  province: string;
  city: string;
  line1: string;
  postal_code: string;
}

export interface Supplier {
  id: number;
  display_name: string;
  legal_name: string;
  status: "active" | "inactive" | "suspended";
  rating_x10: number;
}

export interface FulfillmentOrder {
  id: number;
  order_id: number;
  status: "assigned" | "accepted" | "preparing" | "ready" | "dispatched" | "delivered";
  supplier_name: string;
  created_at: string;
}

export type PaymentMethod = "card" | "credit" | "split";
