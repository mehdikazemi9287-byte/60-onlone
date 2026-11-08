/**
 * API client — thin wrapper around fetch, connects to the Flask backend.
 * Browser requests are same-origin by default and proxied by Next.js to Flask.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: Record<string, string>,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  options: RequestInit & { token?: string } = {},
): Promise<T> {
  const { token: explicit, ...rest } = options;
  // Catalog prices may be members-only: send the stored session on catalog reads too.
  let token = explicit;
  if (!token && typeof window !== "undefined" && /^\/(storefront|products|shops|stores|brands|categories|offers|vambi)\b/.test(path)) {
    try { token = window.localStorage.getItem("60online_token") ?? undefined; } catch {}
  }
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(rest.headers as Record<string, string>),
  };
  // Users with several supplier accounts pick one; the API verifies membership.
  if (path.startsWith("/supplier") && typeof window !== "undefined") {
    try { const sid = window.localStorage.getItem("60online_supplier"); if (sid) headers["X-Supplier-Id"] = sid; } catch {}
  }

  const res = await fetch(`${BASE}/api/v1${path}`, { ...rest, headers });

  if (!res.ok) {
    if (res.status===401 && token && typeof window!=="undefined") window.dispatchEvent(new CustomEvent("60online:session-invalid",{detail:token}));
    // Real backend error shape: {"error": {"code": "...", "message": "...", "details": {...}}}
    let code = "UNKNOWN";
    let message = res.statusText;
    let details: Record<string, string> | undefined;
    try {
      const body = await res.json();
      const err = body.error;
      if (err && typeof err === "object") {
        code = err.code ?? code;
        message = err.message ?? message;
        details = err.details;
      } else if (typeof err === "string") {
        code = err;
        message = body.message ?? message;
      }
    } catch {}
    throw new ApiError(res.status, code, message, details);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** Random idempotency key for a checkout attempt. */
export function newIdempotencyKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `idem-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// ── Auth ────────────────────────────────────────────────────────────────────
// Real user shape as returned by the backend's auth_service — kept local to
// this module rather than added to types.ts's already-declared (unused)
// `User` interface, to avoid changing a type other, not-yet-wired code paths
// might depend on.

export interface AuthUser {
  id: number;
  email: string;
  full_name: string;
  phone?: string | null;
  role: string;
}

export const auth = {
  register: (
    email: string,
    password: string,
    full_name: string,
    phone?: string,
  ) =>
    request<{ access_token: string; token_type: string; user: AuthUser }>(
      "/auth/register",
      {
        method: "POST",
        body: JSON.stringify({ email, password, full_name, phone }),
      },
    ),

  login: (email: string, password: string) =>
    request<{
      access_token: string;
      token_type: string;
      expires_in: number;
      user: AuthUser;
    }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  logout: (token: string) =>
    request<{ message: string }>("/auth/logout", { method: "POST", token }),

  me: (token: string) => request<{ user: AuthUser }>("/auth/me", { token }),

  otpRequest: (phone: string) =>
    request<{ sent: boolean; expires_in_seconds: number; resend_in_seconds: number }>("/auth/otp/request", {
      method: "POST",
      body: JSON.stringify({ phone }),
    }),

  otpVerify: (phone: string, code: string, fullName?: string, acceptTerms?: boolean) =>
    request<{ access_token: string; token_type: string; expires_in: number; user: AuthUser; created: boolean }>(
      "/auth/otp/verify",
      { method: "POST", body: JSON.stringify({ phone, code, full_name: fullName || undefined, accept_terms: acceptTerms || undefined }) },
    ),
};

// ── Catalog ─────────────────────────────────────────────────────────────────
//
// The Flask backend returns flat rows (title_fa, category_slug, category_name_fa,
// price_minor, in_stock, quantity_available, image_url, ...), not the nested
// `Product`/`Category` shape this app's components expect. `normalizeProduct`
// adapts one real row into that shape — it never invents a field the backend
// didn't send; every value flows straight through.

type BackendProductRow = {
  variant_count?: number;
  variant_labels?: string[];
  availability?: "purchasable" | "quote" | "no_offer";
  family_slug?: string | null;
  price_from?: boolean;
  master_product_id?: number | null;
  list_price_minor?: number | null;
  list_price_at?: string | null;
  org_only?: boolean;
  allowed_channels?:string[];supply_channel?:string;
  id: number;
  slug: string;
  title_fa: string;
  description_fa?: string;
  specifications?: import("./types").ProductSpecs | null;
  price_minor: number | null;
  purchasable?: boolean;
  price_status?: "verified" | "pending";
  currency?: string;
  image_url?: string | null;
  category_slug?: string;
  category_name_fa?: string;
  brand_fa?: string | null;
  rating?: number;
  in_stock?: boolean;
  quantity_available?: number;
  sku?: string;
};

type BackendProductList = {
  packs?: import("./storefront").PackSummary[];
  facets?: import("./storefront").Facets;
  attribute_facets?: import("./storefront").AttributeFacet[];
  items: BackendProductRow[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
};

export function normalizeProduct(
  row: BackendProductRow,
): import("./types").Product {
  return {
    id: row.id,
    slug: row.slug,
    name: row.title_fa,
    description: row.description_fa ?? "",
    price_minor: row.price_minor,
    purchasable: row.purchasable === true,
    price_status: row.price_status,
    list_price_minor: row.list_price_minor ?? null,
    list_price_at: row.list_price_at ?? null,
    org_only: row.org_only === true,
    allowed_channels:row.allowed_channels,supply_channel:row.supply_channel,
    image_url: row.image_url ?? undefined,
    category: row.category_slug
      ? {
          id: 0,
          slug: row.category_slug,
          name: row.category_name_fa ?? row.category_slug,
          icon: null,
          parent_id: null,
          product_count: 0,
        }
      : undefined,
    brand: row.brand_fa ?? undefined,
    rating: row.rating,
    // The real product-detail page's review UI is a separate, not-yet-wired
    // module (out of scope this pass) — no review_count exists in the source
    // data, so it is left undefined rather than invented.
    stock: row.in_stock === false ? 0 : row.quantity_available,
    sku: row.sku,
    master_product_id: row.master_product_id ?? null,
    specifications: row.specifications ?? undefined,
    variant_count: row.variant_count,
    variant_labels: row.variant_labels,
    availability: row.availability,
    family_slug: row.family_slug,
    price_from: row.price_from,
  };
}

export const catalog = {
  list: async (params?: {
    category?: string;
    q?: string;
    page?: number;
    page_size?: number;
    sort?: string;
    available_only?: string;
    price_max?: number;
    group?: "sku" | "family";
    brand?: string;
    availability?: string;
    size?: string;
    min_price?: number;
    max_price?: number;
    in_stock?: string;
    official?: string;
    /** Phase 6 attribute filters, e.g. {"attr.oil_type": "sunflower,canola", "attr.volume_ml": "1..2"}. */
    attrs?: Record<string, string>;
  }) => {
    // Precise SKUs by default (requests, composer, pack builder); browsing passes group: "family".
    const qs = new URLSearchParams(
      Object.fromEntries(
        Object.entries({ group: "sku", ...(params ?? {}), attrs: undefined, ...(params?.attrs ?? {}) })
          .filter(([, v]) => v != null && v !== "")
          .map(([k, v]) => [k, String(v)]),
      ),
    ).toString();
    // Marketplace storefront: REAL products only, grouped by product family, typed results.
    const res = await request<BackendProductList>(
      `/storefront/products${qs ? `?${qs}` : ""}`,
    );
    return {
      items: res.items.map(normalizeProduct),
      total: res.total,
      page: res.page,
      pages: res.total_pages,
      packs: res.packs ?? [],
      facets: res.facets,
      attribute_facets: res.attribute_facets ?? [],
    };
  },

  get: async (slug: string) => {
    const res = await request<{ product: BackendProductRow }>(
      `/products/${slug}`,
    );
    return { product: normalizeProduct(res.product) };
  },
};

// ── Categories ────────────────────────────────────────────────────────────────

export const categories = {
  /** Category-level nodes of the real taxonomy that contain REAL products (empty nodes are never listed). */
  list: async () => {
    const res = await request<{ items: import("./storefront").TaxNode[] }>("/storefront/taxonomy");
    const out: import("./types").Category[] = [];
    for (const dept of res.items)
      for (const c of dept.children)
        out.push({ id: c.id, slug: c.slug, name: c.name_fa, icon: null, parent_id: dept.id, product_count: c.product_count });
    return out;
  },
  tree: () => request<{ items: import("./storefront").TaxNode[] }>("/storefront/taxonomy").then((r) => r.items),
};

// ── Cart ─────────────────────────────────────────────────────────────────────
// The real endpoint returns the cart object directly (no {cart:...} wrapper)
// — every mutation (add/update/remove/clear) also returns the resulting cart
// straight from cart_service, so the caller can always just re-render from
// the mutation's own response.

function _notifyCartChanged() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("60online:cart-changed"));
  }
}

export const cart = {
  get: (token: string) => request<import("./types").Cart>("/cart", { token }),

  add: async (token: string, product_id: number, quantity: number) => {
    const res = await request<import("./types").Cart>("/cart/items", {
      method: "POST",
      token,
      body: JSON.stringify({ product_id, quantity }),
    });
    _notifyCartChanged();
    return res;
  },

  update: async (token: string, product_id: number, quantity: number) => {
    const res = await request<import("./types").Cart>(
      `/cart/items/${product_id}`,
      {
        method: "PATCH",
        token,
        body: JSON.stringify({ quantity }),
      },
    );
    _notifyCartChanged();
    return res;
  },

  remove: async (token: string, product_id: number) => {
    const res = await request<import("./types").Cart>(
      `/cart/items/${product_id}`,
      { method: "DELETE", token },
    );
    _notifyCartChanged();
    return res;
  },

  clear: async (token: string) => {
    const res = await request<import("./types").Cart>("/cart", {
      method: "DELETE",
      token,
    });
    _notifyCartChanged();
    return res;
  },
};

// ── Checkout ─────────────────────────────────────────────────────────────────
// Server-authoritative: the client never computes or sends a price. `quote`
// is display-only; `place` recomputes the same numbers itself inside its own
// transaction, so a stale/tampered quote can never be exploited (see the
// backend's own /checkout/quote docstring).

/** Where the browser must go to pay at the bank (redirect gateways such as Sepehr). */
export interface PaymentRedirect {
  url: string;
  method: "POST" | "GET";
  fields: Record<string, string>;
  provider: string;
}

/** 201 → `order` is the paid order. 202 → pay at the bank first via `payment_redirect`. */
export type CheckoutPlaced =
  | { order: import("./types").Order; payment_redirect?: undefined }
  | {
      order?: undefined;
      status: "payment_redirect";
      payment_intent_id: number;
      reference: string;
      cash_due_minor: number;
      payment_redirect: PaymentRedirect;
    };

/** Leave for the bank's payment page. The bank returns the browser to our callback. */
export function goToPaymentGateway(redirect: PaymentRedirect): void {
  if (redirect.method === "GET") {
    const url = new URL(redirect.url);
    Object.entries(redirect.fields).forEach(([k, v]) => url.searchParams.set(k, v));
    window.location.assign(url.toString());
    return;
  }
  const form = document.createElement("form");
  form.method = "POST";
  form.action = redirect.url;
  Object.entries(redirect.fields).forEach(([name, value]) => {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    form.appendChild(input);
  });
  document.body.appendChild(form);
  form.submit();
}

export const checkout = {
  quote: (token: string) =>
    request<import("./types").CheckoutQuote>("/checkout/quote", { token }),

  welfare: (token: string) =>
    request<{ available: boolean; allowed_minor: number; remaining_minor: number }>("/checkout/welfare", { token }),

  place: (
    token: string,
    idempotencyKey: string,
    shipping_address: import("./types").Address,
    payment_method: import("./types").PaymentMethod = "card",
    accepted_terms_version?: string,
    payment_provider?: string,
    use_welfare?: boolean,
    proforma_number?: string,
  ) =>
    request<CheckoutPlaced>("/checkout", {
      method: "POST",
      token,
      body: JSON.stringify({ shipping_address, payment_method, ...(accepted_terms_version ? { accepted_terms_version } : {}),
        ...(payment_provider ? { payment_provider } : {}), ...(use_welfare ? { use_welfare: true } : {}),
        ...(proforma_number ? { proforma_number } : {}) }),
      headers: { "Idempotency-Key": idempotencyKey },
    }),
};

// ── Orders ───────────────────────────────────────────────────────────────────

export const orders = {
  list: (token: string, page = 1, pageSize = 10) =>
    request<{ items: import("./types").Order[]; total: number; page: number }>(
      `/orders?page=${page}&page_size=${pageSize}`,
      { token },
    ),

  get: (token: string, orderNumber: string) =>
    request<{
      order: import("./types").Order;
      fulfillment_orders: import("./types").FulfillmentOrder[];
    }>(`/orders/${orderNumber}`, { token }),
};

// ── Organization ─────────────────────────────────────────────────────────────

export const org = {
  get: (token: string, id: number) =>
    request<{ organization: import("./types").Organization }>(
      `/organizations/${id}`,
      { token },
    ),

  creditAllocations: (token: string, orgId: number) =>
    request<{ items: import("./types").CreditAllocation[] }>(
      `/organizations/${orgId}/credit-allocations`,
      { token },
    ),
};

export { ApiError, request as apiRequest };

// ── Smart Pack Builder ───────────────────────────────────────────────────────
export interface PackLine {
  product_id: number;
  slug: string | null;
  title: string;
  brand: string | null;
  category_slug: string | null;
  category_name: string | null;
  quantity: number;
  image_url: string | null;
  price_status: "verified" | "unpriced" | "unavailable";
  purchase_status: "purchasable" | "inquiry-only" | "unavailable";
  in_stock: boolean;
  unit_price: number | null;
  line_total: number | null;
}
export interface PackSummary {
  verified_subtotal: number | null;
  unpriced_item_count: number;
  has_unpriced: boolean;
  all_purchasable: boolean;
  currency: string;
  note: string;
}
export interface Pack {
  id: number;
  name: string;
  kind: string;
  created_at: string;
  updated_at: string;
  items: PackLine[];
  item_count: number;
  summary: PackSummary;
}
export interface PackRow {
  id: number;
  name: string;
  kind: string;
  item_count: number;
  updated_at: string;
}
export interface PackCartResult {
  pack_id: number;
  added: { product_id: number; title: string; quantity: number }[];
  skipped: { product_id: number; title: string; reason: string }[];
  cart_updated: boolean;
}

export const packs = {
  list: (token: string) => request<{ packs: PackRow[] }>("/packs", { token }),
  get: (token: string, id: number) => request<{ pack: Pack }>(`/packs/${id}`, { token }),
  create: (token: string, name: string, kind = "custom") =>
    request<{ pack: Pack }>("/packs", { method: "POST", token, body: JSON.stringify({ name, kind }) }),
  rename: (token: string, id: number, name: string) =>
    request<{ pack: Pack }>(`/packs/${id}`, { method: "PATCH", token, body: JSON.stringify({ name }) }),
  remove: (token: string, id: number) =>
    request<{ deleted: number }>(`/packs/${id}`, { method: "DELETE", token }),
  setItem: (token: string, id: number, product_id: number, quantity: number) =>
    request<{ pack: Pack }>(`/packs/${id}/items`, {
      method: "PUT", token, body: JSON.stringify({ product_id, quantity }),
    }),
  removeItem: (token: string, id: number, product_id: number) =>
    request<{ pack: Pack }>(`/packs/${id}/items/${product_id}`, { method: "DELETE", token }),
  addToCart: (token: string, id: number) =>
    request<PackCartResult>(`/packs/${id}/add-to-cart`, { method: "POST", token, body: "{}" }),
  proforma: (token: string, id: number, message: string, organization_id?: number) =>
    request<{ request_id: number; status: string; subject: string }>(
      `/packs/${id}/proforma`,
      { method: "POST", token, body: JSON.stringify({ message, organization_id }) },
    ),
};
