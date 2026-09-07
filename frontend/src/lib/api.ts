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
  const { token, ...rest } = options;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(rest.headers as Record<string, string>),
  };

  const res = await fetch(`${BASE}/api/v1${path}`, { ...rest, headers });

  if (!res.ok) {
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
};

// ── Catalog ─────────────────────────────────────────────────────────────────
//
// The Flask backend returns flat rows (title_fa, category_slug, category_name_fa,
// price_minor, in_stock, quantity_available, image_url, ...), not the nested
// `Product`/`Category` shape this app's components expect. `normalizeProduct`
// adapts one real row into that shape — it never invents a field the backend
// didn't send; every value flows straight through.

type BackendProductRow = {
  id: number;
  slug: string;
  title_fa: string;
  description_fa?: string;
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
  }) => {
    const qs = new URLSearchParams(
      Object.fromEntries(
        Object.entries(params ?? {})
          .filter(([, v]) => v != null)
          .map(([k, v]) => [k, String(v)]),
      ),
    ).toString();
    const res = await request<BackendProductList>(
      `/products${qs ? `?${qs}` : ""}`,
    );
    return {
      items: res.items.map(normalizeProduct),
      total: res.total,
      page: res.page,
      pages: res.total_pages,
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
  list: async () => {
    const res = await request<{
      items: {
        id: number;
        slug: string;
        name_fa: string;
        parent_id: number | null;
        product_count: number;
        sort_order: number;
      }[];
    }>("/categories");
    return res.items.map((c) => ({
      id: c.id,
      slug: c.slug,
      name: c.name_fa,
      icon: null,
      parent_id: c.parent_id,
      product_count: c.product_count,
    })) as import("./types").Category[];
  },
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

export const checkout = {
  quote: (token: string) =>
    request<import("./types").CheckoutQuote>("/checkout/quote", { token }),

  place: (
    token: string,
    idempotencyKey: string,
    shipping_address: import("./types").Address,
    payment_method: import("./types").PaymentMethod = "card",
  ) =>
    request<{ order: import("./types").Order }>("/checkout", {
      method: "POST",
      token,
      body: JSON.stringify({ shipping_address, payment_method }),
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
