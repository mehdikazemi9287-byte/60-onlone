"""Smart Fulfillment Engine — deterministic, rule-based supplier routing.

This module is a PURE DOMAIN SERVICE. It has no Flask imports and no HTTP
concerns. It receives structured data, applies scoring rules, and returns an
ordered list of candidates with explanations. The engine is fully testable
in isolation.

Scoring components (all configurable via SCORE_WEIGHTS at module level):

    geo_score       — 0‥GEO_MAX   based on geographic proximity
    price_score     — 0‥PRICE_MAX based on offer selling price vs. cheapest
    stock_score     — 0‥STOCK_MAX stock > 0 (required) + buffer bonus
    rating_score    — 0‥RATING_MAX supplier rating_x10 / 50 * RATING_MAX
    prep_score      — 0‥PREP_MAX  inverse of preparation time

Total score out of 100. Higher is better.

Routing rules (by policy_type):

    LOCAL_ONLY:
        Only same-city candidates are eligible.
        If no same-city stock → return empty list (fulfillment unavailable).

    LOCAL_PREFERRED:
        Same-city candidates preferred. If none, same-province. If none,
        intercity/national if supplier can_intercity_shipping.

    NATIONAL_SHIPPING:
        Any active supplier with stock that allows the required delivery mode.

    PICKUP_ONLY:
        Only suppliers in the same city with can_pickup = 1.

After filtering by policy and geo, the engine scores remaining candidates
and returns them sorted descending. The caller takes candidates[0] as the
selected supplier (deterministic tie-breaker: supplier.id ASC).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Scoring weights (must sum to 100)
# ---------------------------------------------------------------------------
SCORE_WEIGHTS = {
    "geo":    30,  # geographic proximity
    "price":  25,  # competitive price
    "stock":  15,  # availability confidence
    "rating": 20,  # supplier rating
    "prep":   10,  # preparation speed
}
assert sum(SCORE_WEIGHTS.values()) == 100, "Weights must sum to 100"

GEO_SAME_CITY       = 100   # same city
GEO_SAME_PROVINCE   = 60    # same province, different city
GEO_INTERCITY       = 20    # different province (national)

# Valid state transitions for FulfillmentOrder
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending_assignment": {"assigned", "cancelled", "failed"},
    "assigned":           {"accepted", "rejected", "cancelled"},
    "accepted":           {"preparing", "cancelled"},
    "preparing":          {"ready", "cancelled"},
    "ready":              {"dispatched", "delivered"},   # delivered = direct pickup
    "dispatched":         {"delivered", "failed"},
    "delivered":          set(),
    "rejected":           {"assigned"},                  # after reroute → re-assigned
    "cancelled":          set(),
    "failed":             set(),
}


# ---------------------------------------------------------------------------
# Data classes (plain Python, no ORM, no Flask)
# ---------------------------------------------------------------------------

@dataclass
class OfferCandidate:
    """One supplier location + offer combination considered for routing."""
    offer_id:               int
    supplier_id:            int
    supplier_name:          str
    supplier_type:          str
    supplier_status:        str
    supplier_rating_x10:    int
    location_id:            int
    location_province:      str
    location_city:          str
    can_local_delivery:     bool
    can_intercity_shipping: bool
    can_pickup:             bool
    prep_time_minutes:      int
    selling_price_minor:    int
    cost_price_minor:       int | None
    stock_available:        int   # quantity - reserved (computed)
    fulfillment_type:       str

    # Computed by engine
    geo_tier:    str  = ""     # "same_city" | "same_province" | "intercity"
    scores:      dict = field(default_factory=dict)
    total_score: int  = 0
    eligible:    bool = False
    ineligible_reason: str = ""


@dataclass
class RoutingResult:
    """Output of the routing engine for a single (product, customer_location) pair."""
    selected:    OfferCandidate | None
    candidates:  list[OfferCandidate]   # all considered, sorted by score desc
    policy_type: str
    customer_province: str
    customer_city:     str
    product_id:        int
    quantity_needed:   int
    unavailable_reason: str = ""

    def to_audit_json(self) -> str:
        """Compact JSON for routing_audit.candidates_json."""
        items = []
        for c in self.candidates:
            items.append({
                "offer_id":      c.offer_id,
                "supplier_id":   c.supplier_id,
                "supplier_name": c.supplier_name,
                "location_id":   c.location_id,
                "city":          c.location_city,
                "province":      c.location_province,
                "geo_tier":      c.geo_tier,
                "price":         c.selling_price_minor,
                "stock":         c.stock_available,
                "score":         c.total_score,
                "eligible":      c.eligible,
                "reason":        c.ineligible_reason if not c.eligible else "ok",
            })
        return json.dumps(items, ensure_ascii=False)

    def to_reason_json(self) -> str:
        """Compact JSON for fulfillment_orders.routing_reason_json."""
        if not self.selected:
            return json.dumps({"unavailable": self.unavailable_reason}, ensure_ascii=False)
        s = self.selected
        return json.dumps({
            "supplier_id":   s.supplier_id,
            "location_id":   s.location_id,
            "geo_tier":      s.geo_tier,
            "scores":        s.scores,
            "total_score":   s.total_score,
            "policy":        self.policy_type,
        }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# City / province normalisation
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Lowercase + strip common Persian/Arabic diacritics for matching."""
    text = (text or "").strip().lower()
    for a, b in [("‌", ""), ("‌", ""), ("ی", "ي"), ("ک", "ك")]:
        text = text.replace(a, b)
    return text


def same_city(a: str, b: str) -> bool:
    return _norm(a) == _norm(b)


def same_province(a: str, b: str) -> bool:
    return _norm(a) == _norm(b)


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

def load_candidates(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    quantity_needed: int,
    offer_id: int | None = None,
) -> list[OfferCandidate]:
    """Active offers for a product with allowed provenance (REAL; TEST only in test mode) on the
    retail channel. When the cart line is bound to an offer, only that offer is a candidate."""
    from app.services.sale_eligibility import allowed_provenance
    prov = ",".join(f"'{p}'" for p in allowed_provenance())
    rows = conn.execute(
        """
        SELECT
            so.id                           AS offer_id,
            so.supplier_id,
            s.display_name                  AS supplier_name,
            s.supplier_type,
            s.status                        AS supplier_status,
            s.rating_x10,
            sl.id                           AS location_id,
            sl.province                     AS location_province,
            sl.city                         AS location_city,
            sl.can_local_delivery,
            sl.can_intercity_shipping,
            sl.can_pickup,
            COALESCE(so.prep_time_minutes, sl.prep_time_minutes, 60) AS prep_time_minutes,
            so.selling_price_minor,
            so.cost_price_minor,
            (so.stock_quantity - so.stock_reserved) AS stock_available,
            so.fulfillment_type
        FROM seller_offers so
        JOIN suppliers       s  ON s.id  = so.supplier_id
        JOIN supplier_locations sl ON sl.id = so.supplier_location_id
        WHERE so.product_id = ?
          AND so.status     = 'active'
          AND s.status      = 'active'
          AND sl.status     = 'active'
          AND so.provenance IN ({prov}) AND s.provenance IN ({prov})
          AND so.channel IN ('retail', 'both') AND so.pricing_mode IN ('fixed', 'bulk')
          AND (? IS NULL OR so.id = ?)
        ORDER BY s.rating_x10 DESC, so.selling_price_minor ASC, s.id ASC
        """.replace("{prov}", prov).replace("so.channel IN ('retail', 'both')", __import__("app.services.product_channel_policy",fromlist=["offer_sql"]).offer_sql("so.product_id","so.channel","retail")),
        (product_id, offer_id, offer_id),
    ).fetchall()

    return [
        OfferCandidate(
            offer_id               = int(r["offer_id"]),
            supplier_id            = int(r["supplier_id"]),
            supplier_name          = r["supplier_name"],
            supplier_type          = r["supplier_type"],
            supplier_status        = r["supplier_status"],
            supplier_rating_x10    = int(r["rating_x10"]),
            location_id            = int(r["location_id"]),
            location_province      = r["location_province"],
            location_city          = r["location_city"],
            can_local_delivery     = bool(r["can_local_delivery"]),
            can_intercity_shipping = bool(r["can_intercity_shipping"]),
            can_pickup             = bool(r["can_pickup"]),
            prep_time_minutes      = int(r["prep_time_minutes"]),
            selling_price_minor    = int(r["selling_price_minor"]),
            cost_price_minor       = int(r["cost_price_minor"]) if r["cost_price_minor"] is not None else None,
            stock_available        = int(r["stock_available"]),
            fulfillment_type       = r["fulfillment_type"],
        )
        for r in rows
    ]


def get_policy_type(conn: sqlite3.Connection, product_id: int) -> str:
    """Return the policy_type for a product. Falls back to DEFAULT policy."""
    row = conn.execute(
        """
        SELECT fp.policy_type
        FROM   products p
        JOIN   fulfillment_policies fp ON fp.id = p.fulfillment_policy_id
        WHERE  p.id = ?
        """,
        (product_id,),
    ).fetchone()
    if row:
        return row["policy_type"]
    # Fall back to the default policy
    default_row = conn.execute(
        "SELECT policy_type FROM fulfillment_policies WHERE is_default = 1 LIMIT 1"
    ).fetchone()
    return default_row["policy_type"] if default_row else "NATIONAL_SHIPPING"


def _classify_geo(
    candidate: OfferCandidate,
    customer_province: str,
    customer_city: str,
) -> str:
    if same_city(candidate.location_city, customer_city):
        return "same_city"
    if same_province(candidate.location_province, customer_province):
        return "same_province"
    return "intercity"


def _score_candidates(
    candidates: list[OfferCandidate],
    *,
    customer_province: str,
    customer_city: str,
    policy_type: str,
    quantity_needed: int,
) -> None:
    """Score and tag each candidate in-place."""
    # Collect price range for relative price scoring
    eligible_prices = [
        c.selling_price_minor for c in candidates
        if c.stock_available >= quantity_needed
    ]
    min_price = min(eligible_prices) if eligible_prices else 1
    max_price = max(eligible_prices) if eligible_prices else 1

    for c in candidates:
        c.geo_tier = _classify_geo(c, customer_province, customer_city)

        # --- stock gate (hard requirement) ---
        if c.stock_available < quantity_needed:
            c.eligible = False
            c.ineligible_reason = "موجودی ناکافی"
            c.total_score = 0
            continue

        # --- policy gate ---
        eligible, reason = _policy_gate(c, policy_type)
        if not eligible:
            c.eligible = False
            c.ineligible_reason = reason
            c.total_score = 0
            continue

        c.eligible = True

        # --- geo score ---
        raw_geo = {
            "same_city":     GEO_SAME_CITY,
            "same_province": GEO_SAME_PROVINCE,
            "intercity":     GEO_INTERCITY,
        }[c.geo_tier]
        geo_score = round(raw_geo / 100 * SCORE_WEIGHTS["geo"])

        # --- price score (lower price → higher score) ---
        if max_price == min_price:
            price_score = SCORE_WEIGHTS["price"]
        else:
            price_score = round(
                (1 - (c.selling_price_minor - min_price) / (max_price - min_price))
                * SCORE_WEIGHTS["price"]
            )

        # --- stock confidence score (having more buffer is good) ---
        stock_buffer = min(c.stock_available / max(quantity_needed, 1), 5)  # cap at 5x
        stock_score = round((stock_buffer / 5) * SCORE_WEIGHTS["stock"])

        # --- rating score ---
        rating_score = round(c.supplier_rating_x10 / 50 * SCORE_WEIGHTS["rating"])

        # --- preparation speed score (lower prep time → higher score) ---
        MAX_PREP = 480  # 8 hours is the worst we consider
        clamped_prep = min(c.prep_time_minutes, MAX_PREP)
        prep_score = round((1 - clamped_prep / MAX_PREP) * SCORE_WEIGHTS["prep"])

        c.scores = {
            "geo":    geo_score,
            "price":  price_score,
            "stock":  stock_score,
            "rating": rating_score,
            "prep":   prep_score,
        }
        c.total_score = sum(c.scores.values())


def _policy_gate(c: OfferCandidate, policy_type: str) -> tuple[bool, str]:
    """Return (eligible, reason). Checks policy constraints against geo + capabilities."""
    if policy_type == "LOCAL_ONLY":
        if c.geo_tier != "same_city":
            return False, "LOCAL_ONLY: تأمین‌کننده همشهر نیست"
        if not c.can_local_delivery and not c.can_pickup:
            return False, "LOCAL_ONLY: قابلیت تحویل محلی ندارد"
        return True, ""

    if policy_type == "PICKUP_ONLY":
        if c.geo_tier != "same_city":
            return False, "PICKUP_ONLY: تأمین‌کننده همشهر نیست"
        if not c.can_pickup:
            return False, "PICKUP_ONLY: تحویل حضوری پشتیبانی نمی‌شود"
        return True, ""

    if policy_type == "LOCAL_PREFERRED":
        # All geos are potentially eligible, but geo_tier is used in scoring.
        if c.geo_tier == "intercity" and not c.can_intercity_shipping:
            return False, "LOCAL_PREFERRED/intercity: ارسال بین‌شهری پشتیبانی نمی‌شود"
        return True, ""

    if policy_type == "NATIONAL_SHIPPING":
        if c.geo_tier == "same_city" or c.geo_tier == "same_province":
            return True, ""
        if not c.can_intercity_shipping:
            return False, "NATIONAL: ارسال بین‌شهری پشتیبانی نمی‌شود"
        return True, ""

    return True, ""


def route(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    quantity_needed: int,
    customer_province: str,
    customer_city: str,
    offer_id: int | None = None,
) -> RoutingResult:
    """Main entry point. Returns a RoutingResult with selected candidate + all candidates.

    LOCAL_PREFERRED enforces STRICT GEO TIER PRIORITY:
      1. If any eligible same_city candidate exists → compete ONLY within same_city.
      2. Else if any eligible same_province candidate exists → compete ONLY within same_province.
      3. Else use eligible intercity/national candidates.

    This means a national supplier with a dramatically better price or rating CANNOT
    beat a local supplier for LOCAL_PREFERRED — geography is a hard tier gate,
    not merely a scoring component.
    """
    policy_type = get_policy_type(conn, product_id)
    candidates  = load_candidates(conn, product_id=product_id, quantity_needed=quantity_needed, offer_id=offer_id)

    _score_candidates(
        candidates,
        customer_province = customer_province,
        customer_city     = customer_city,
        policy_type       = policy_type,
        quantity_needed   = quantity_needed,
    )

    eligible = [c for c in candidates if c.eligible]

    # LOCAL_PREFERRED: enforce strict tier priority so the best geo tier wins
    # regardless of how well a lower-tier supplier scores on price/rating/etc.
    if policy_type == "LOCAL_PREFERRED" and eligible:
        same_city_eligible = [c for c in eligible if c.geo_tier == "same_city"]
        if same_city_eligible:
            # Restrict competition to same-city tier only
            eligible = same_city_eligible
        else:
            same_province_eligible = [c for c in eligible if c.geo_tier == "same_province"]
            if same_province_eligible:
                # Restrict competition to same-province tier only
                eligible = same_province_eligible
            # else: no local candidates at all → fall through to intercity (eligible unchanged)

    # Sort: score DESC, then supplier_id ASC (deterministic tie-breaker)
    eligible.sort(key=lambda c: (-c.total_score, c.supplier_id))
    # Also sort full candidate list for audit (eligible first, then ineligible)
    candidates.sort(key=lambda c: (0 if c.eligible else 1, -c.total_score, c.supplier_id))

    selected = eligible[0] if eligible else None
    unavailable_reason = ""
    if not selected:
        if not candidates:
            unavailable_reason = "هیچ تأمین‌کننده‌ای برای این محصول تعریف نشده است"
        elif policy_type == "LOCAL_ONLY":
            unavailable_reason = "تأمین‌کننده محلی موجود (یا دارای موجودی) در شهر شما وجود ندارد"
        elif policy_type == "PICKUP_ONLY":
            unavailable_reason = "هیچ نقطه تحویل حضوری در شهر شما موجود نیست"
        else:
            unavailable_reason = "هیچ تأمین‌کننده‌ای با موجودی و قابلیت ارسال موجود نیست"

    return RoutingResult(
        selected           = selected,
        candidates         = candidates,
        policy_type        = policy_type,
        customer_province  = customer_province,
        customer_city      = customer_city,
        product_id         = product_id,
        quantity_needed    = quantity_needed,
        unavailable_reason = unavailable_reason,
    )


def route_cart(
    conn: sqlite3.Connection,
    *,
    cart_items: list[dict],   # [{product_id, quantity, ...}]
    customer_province: str,
    customer_city: str,
) -> dict[int, RoutingResult]:
    """Route each item in the cart. Returns {product_id: RoutingResult}."""
    return {
        item["product_id"]: route(
            conn,
            product_id       = item["product_id"],
            quantity_needed  = item["quantity"],
            customer_province = customer_province,
            customer_city     = customer_city,
        )
        for item in cart_items
    }
