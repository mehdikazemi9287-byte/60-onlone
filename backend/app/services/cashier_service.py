"""Phase 2 — cashier («تصمیم پشت صندوق»): deterministic pricing of a cart for a buyer.

Per line, in this fixed shape (step order and caps come from `cashier_rules`):
  1. base offer price
  2. price_selection — quantity tier vs organization/contract tier; they never stack
     (mode 'lowest' takes the lower, 'contract_first' prefers the contract price)
  3. line discounts in step_order — partner_discount (best single partner offer), recurring_*
     each computed on the running amount, capped by cap_bps of the selected price
  4. seller_net_floor guard — discounts are clipped so a line never drops below the seller's net
     (cost_price_minor × qty when the offer discloses it, else selected price − commission)
Then per order: coins (capped by cap_bps of the discounted order, the loyalty 50% ceiling, the
balance and the floor headroom) and credit (organization credit for the remainder).

Output is a quote only: checkout_service stays the authority for orders and money movement.
`compute()` is pure (no DB, no clock); `quote()` loads a snapshot and calls it.
Integer arithmetic only; every rate is basis points (10_000 = 100%).
"""
from __future__ import annotations

import datetime as _dt

from app.core.errors import NotFoundError, PermissionError_, ValidationError
from app.services import loyalty_service
from app.services import product_channel_policy as policy
from app.services import sale_eligibility as se
from app.services.seller_shop_service import resolve_commission_bps

BPS = 10_000
FRESH_HOURS = se.MAX_CONFIRMATION_AGE_HOURS
MAX_LINES = 200
MAX_QTY = 100_000

# Used when a rule row is missing (e.g. deleted by hand); mirrors the 0055 seed.
DEFAULT_RULES: dict[str, dict] = {
    "price_selection": {"step_order": 10, "enabled": 1, "mode": "lowest", "percent_bps": None, "cap_bps": None,
                        "cap_scope": "line", "min_items": None, "funded_by": "seller"},
    "partner_discount": {"step_order": 20, "enabled": 1, "mode": "stack", "percent_bps": None, "cap_bps": 1500,
                         "cap_scope": "line", "min_items": None, "funded_by": None},
    "recurring_discount": {"step_order": 30, "enabled": 1, "mode": "stack", "percent_bps": 500, "cap_bps": 1000,
                           "cap_scope": "line", "min_items": 1, "funded_by": "platform"},
    "recurring_discount_bulk": {"step_order": 31, "enabled": 1, "mode": "stack", "percent_bps": 1000, "cap_bps": 1000,
                                "cap_scope": "line", "min_items": 5, "funded_by": "platform"},
    "coins": {"step_order": 50, "enabled": 1, "mode": "payment", "percent_bps": None, "cap_bps": 2000,
              "cap_scope": "order", "min_items": None, "funded_by": "platform"},
    "credit": {"step_order": 60, "enabled": 1, "mode": "payment", "percent_bps": None, "cap_bps": None,
               "cap_scope": "order", "min_items": None, "funded_by": None},
    "seller_net_floor": {"step_order": 90, "enabled": 1, "mode": "guard", "percent_bps": None, "cap_bps": None,
                         "cap_scope": "line", "min_items": None, "funded_by": None},
}
LINE_STEPS = ("partner_discount", "recurring")
RECURRING_KEYS = ("recurring_discount", "recurring_discount_bulk")
RULE_MODES = {"price_selection": ("lowest", "contract_first"), "seller_net_floor": ("guard",),
              "coins": ("payment",), "credit": ("payment",)}
SELLER_KIND_RANK = {"brand": 0, "partner": 1, "shop": 2, "supplier": 2}
HEALTH_RANK = {"good": 0, "at_risk": 1}


# ── time helpers ─────────────────────────────────────────────────────────────

def _now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _parse_ts(value) -> _dt.datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        t = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


def _fresh(value, now: _dt.datetime) -> bool:
    t = _parse_ts(value)
    return t is not None and t >= now - _dt.timedelta(hours=FRESH_HOURS)


# ── rules ────────────────────────────────────────────────────────────────────

def load_rules(conn) -> dict[str, dict]:
    rules = {k: dict(v, rule_key=k) for k, v in DEFAULT_RULES.items()}
    for r in conn.execute("SELECT * FROM cashier_rules"):
        rules[r["rule_key"]] = dict(r)
    return rules


def list_rules(conn) -> list[dict]:
    return sorted(load_rules(conn).values(), key=lambda r: (int(r["step_order"]), r["rule_key"]))


def update_rule(conn, *, rule_key: str, data: dict, actor: int) -> dict:
    row = conn.execute("SELECT * FROM cashier_rules WHERE rule_key=?", (rule_key,)).fetchone()
    if row is None:
        raise NotFoundError("قاعدهٔ صندوق یافت نشد")
    allowed = {"step_order", "enabled", "mode", "percent_bps", "cap_bps", "min_items", "funded_by", "note"}
    extra = set(data) - allowed
    if extra:
        raise ValidationError("فیلد ناشناخته", details={"fields": sorted(extra)})
    new = dict(row)

    def _int(key, lo, hi, nullable):
        v = data[key]
        if v is None and nullable:
            return None
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValidationError(f"«{key}» نامعتبر است", details={"field": key})
        return v

    if "step_order" in data:
        new["step_order"] = _int("step_order", 1, 999, False)
    if "enabled" in data:
        if not isinstance(data["enabled"], bool):
            raise ValidationError("«enabled» باید true یا false باشد")
        new["enabled"] = int(data["enabled"])
    if "mode" in data:
        if data["mode"] not in RULE_MODES.get(rule_key, ("stack",)):
            raise ValidationError("حالت قاعده برای این مرحله مجاز نیست")
        new["mode"] = data["mode"]
    for key in ("percent_bps", "cap_bps"):
        if key in data:
            new[key] = _int(key, 0, BPS, True)
    if "min_items" in data:
        new["min_items"] = _int("min_items", 1, 10_000, True)
    if "funded_by" in data:
        if data["funded_by"] not in (None, "platform", "seller", "partner"):
            raise ValidationError("تأمین‌کنندهٔ هزینهٔ تخفیف نامعتبر است")
        new["funded_by"] = data["funded_by"]
    if "note" in data:
        if data["note"] is not None and (not isinstance(data["note"], str) or len(data["note"]) > 500):
            raise ValidationError("یادداشت نامعتبر است")
        new["note"] = data["note"]
    # Line discounts must stay before the order-level payment steps.
    if rule_key in ("partner_discount",) + RECURRING_KEYS and new["step_order"] >= 50:
        raise ValidationError("تخفیف‌های سطری باید پیش از سکه و اعتبار اجرا شوند (ترتیب کمتر از ۵۰)")
    if rule_key in ("coins", "credit") and new["step_order"] < 50:
        raise ValidationError("سکه و اعتبار پس از تخفیف‌های سطری اجرا می‌شوند (ترتیب ۵۰ یا بیشتر)")
    if rule_key == "price_selection" and new["step_order"] != row["step_order"]:
        raise ValidationError("انتخاب قیمت همیشه اولین مرحله است")
    conn.execute(
        """UPDATE cashier_rules SET step_order=?, enabled=?, mode=?, percent_bps=?, cap_bps=?, min_items=?,
               funded_by=?, note=?, updated_by_user_id=?, updated_at=? WHERE rule_key=?""",
        (new["step_order"], new["enabled"], new["mode"], new["percent_bps"], new["cap_bps"], new["min_items"],
         new["funded_by"], new["note"], actor, _now_utc().strftime("%Y-%m-%dT%H:%M:%S.000Z"), rule_key))
    return dict(conn.execute("SELECT * FROM cashier_rules WHERE rule_key=?", (rule_key,)).fetchone())


# ── buyer context ────────────────────────────────────────────────────────────

def buyer_context(conn, *, user_id: int | None = None, organization_id: int | None = None,
                  redeem_coins: int = 0, coupon_codes=(), use_credit: bool = True,
                  recurring: bool = False, platform_admin: bool = False) -> dict:
    """Validated buyer context. An organization price needs an active membership of an active org."""
    if isinstance(redeem_coins, bool) or not isinstance(redeem_coins, int) or redeem_coins < 0:
        raise ValidationError("تعداد سکه باید عدد صحیح نامنفی باشد")
    if redeem_coins and user_id is None:
        raise ValidationError("برای استفاده از سکه وارد حساب شوید")
    codes = tuple(sorted({str(c).strip().upper() for c in (coupon_codes or ()) if isinstance(c, str) and c.strip()}))[:5]
    credit = 0
    if organization_id is not None:
        if isinstance(organization_id, bool) or not isinstance(organization_id, int) or organization_id < 1:
            raise ValidationError("شناسهٔ سازمان نامعتبر است")
        org = conn.execute("SELECT status FROM organizations WHERE id=?", (organization_id,)).fetchone()
        if org is None:
            raise NotFoundError("سازمان یافت نشد", code="organization_not_found")
        member = None
        if user_id is not None:
            member = conn.execute("SELECT id FROM organization_memberships WHERE organization_id=? AND user_id=? "
                                  "AND status='active'", (organization_id, user_id)).fetchone()
        if member is None and not platform_admin:
            raise NotFoundError("سازمان یافت نشد", code="organization_not_found")
        if org["status"] != "active":
            raise PermissionError_("سازمان فعال نیست", code="organization_inactive")
        if use_credit and member is not None:
            credit = _credit_available(conn, user_id=user_id, organization_id=organization_id)
    balance = loyalty_service.balance(conn, user_id) if user_id is not None else 0
    return {"user_id": user_id, "organization_id": organization_id,
            "channel": "organization" if organization_id else "retail",
            "redeem_coins": redeem_coins, "coin_balance": balance, "coupon_codes": codes,
            "credit_available_minor": credit, "recurring": bool(recurring)}


def _credit_available(conn, *, user_id: int, organization_id: int) -> int:
    """Largest single active allocation (checkout funds an order from exactly one allocation)."""
    from app.services.credit_service import allocation_state
    best = 0
    now = _now_utc()
    for a in conn.execute(
            """SELECT a.id, a.valid_from, a.expires_at FROM credit_allocations a
               JOIN organization_memberships m ON m.id=a.membership_id AND m.status='active'
               WHERE a.user_id=? AND a.organization_id=? AND a.status='active'""", (user_id, organization_id)):
        start, end = _parse_ts(a["valid_from"]), _parse_ts(a["expires_at"])
        if (start and start > now) or (end and end <= now):
            continue
        best = max(best, int(allocation_state(conn, int(a["id"]))["available_minor"]))
    return best


def _retail_ctx() -> dict:
    return {"user_id": None, "organization_id": None, "channel": "retail", "redeem_coins": 0, "coin_balance": 0,
            "coupon_codes": (), "credit_available_minor": 0, "recurring": False}


# ── snapshot loading ─────────────────────────────────────────────────────────

_OFFER_SQL = """
SELECT so.id, so.product_id, so.supplier_id, so.selling_price_minor, so.cost_price_minor, so.stock_quantity,
       so.stock_reserved, so.status, so.min_order_quantity, so.max_order_quantity, so.lead_time_days,
       so.pricing_mode, so.channel, so.valid_until, so.provenance, so.last_price_confirmed_at,
       so.last_inventory_confirmed_at,
       s.status AS supplier_status, s.health_status, s.seller_kind, s.provenance AS supplier_provenance,
       s.display_name, s.shop_title, s.shop_slug, p.category_id, p.title_fa, p.slug AS product_slug
FROM seller_offers so
JOIN suppliers s ON s.id = so.supplier_id
JOIN products p ON p.id = so.product_id
"""


def _ineligible_reasons(conn, o, ctx: dict, quantity: int, now: _dt.datetime) -> list[str]:
    reasons = []
    allowed_prov = se.allowed_provenance()
    if o["supplier_status"] != "active":
        reasons.append("supplier_inactive")
    if o["health_status"] == "suspended":
        reasons.append("seller_suspended")
    if o["status"] != "active":
        reasons.append("offer_inactive")
    if o["provenance"] not in allowed_prov or o["supplier_provenance"] not in allowed_prov:
        reasons.append("provenance")
    modes = ("fixed", "bulk", "contract") if ctx["channel"] == "organization" else ("fixed", "bulk")
    if o["pricing_mode"] not in modes:
        reasons.append("pricing_mode")
    if ctx["channel"] not in policy.channels(policy.effective(conn, o["product_id"], o["channel"])):
        reasons.append("channel_unavailable")
    if o["valid_until"] and str(o["valid_until"])[:10] < now.date().isoformat():
        reasons.append("offer_expired")
    if int(o["selling_price_minor"]) <= 0:
        reasons.append("no_price")
    if not (_fresh(o["last_price_confirmed_at"], now) and _fresh(o["last_inventory_confirmed_at"], now)):
        reasons.append("price_unconfirmed")
    available = int(o["stock_quantity"]) - int(o["stock_reserved"])
    if available <= 0:
        reasons.append("out_of_stock")
    elif available < quantity:
        reasons.append("insufficient_stock")
    if quantity < int(o["min_order_quantity"] or 1):
        reasons.append("below_min_order")
    if o["max_order_quantity"] is not None and quantity > int(o["max_order_quantity"]):
        reasons.append("above_max_order")
    return reasons


def _tier_prices(conn, offer_id: int, ctx: dict, quantity: int, now: _dt.datetime) -> tuple[int | None, int | None]:
    """(quantity tier unit price, organization contract unit price) for this buyer; fresh tiers only."""
    tier = contract = None
    for t in conn.execute(
            "SELECT organization_id, unit_price_minor, confirmed_at FROM offer_price_tiers "
            "WHERE offer_id=? AND channel=? AND min_qty<=? AND (max_qty IS NULL OR max_qty>=?)",
            (offer_id, ctx["channel"], quantity, quantity)):
        if not _fresh(t["confirmed_at"], now):
            continue
        price = int(t["unit_price_minor"])
        if t["organization_id"] is None:
            tier = price if tier is None else min(tier, price)
        elif ctx["organization_id"] is not None and int(t["organization_id"]) == int(ctx["organization_id"]):
            contract = price if contract is None else min(contract, price)
    return tier, contract


def _category_chain(conn, category_id, cache: dict) -> tuple[int, ...]:
    if category_id in cache:
        return cache[category_id]
    chain, cur, seen = [], category_id, set()
    while cur is not None and cur not in seen and len(chain) < 12:
        seen.add(cur)
        chain.append(int(cur))
        row = conn.execute("SELECT parent_id FROM categories WHERE id=?", (cur,)).fetchone()
        cur = row["parent_id"] if row else None
    cache[category_id] = tuple(chain)
    return cache[category_id]


def _partner_candidates(conn, *, product_id: int, supplier_id: int, category_chain: tuple[int, ...],
                        ctx: dict, now: _dt.datetime) -> list[dict]:
    today = now.date().isoformat()
    out = []
    for d in conn.execute(
            """SELECT id, title_fa, partner_supplier_id, partner_name, scope, category_id, product_id,
                      seller_supplier_id, channel, percent_bps, max_discount_minor, funded_by, coupon_code
               FROM partner_discounts
               WHERE status='active' AND (valid_from IS NULL OR valid_from <= ?)
                 AND (valid_until IS NULL OR valid_until >= ?) AND channel IN ('any', ?)
               ORDER BY id""", (today, today, ctx["channel"])):
        if d["coupon_code"] is not None and d["coupon_code"] not in ctx["coupon_codes"]:
            continue
        scope = d["scope"]
        if scope == "product" and int(d["product_id"]) != product_id:
            continue
        if scope == "seller" and int(d["seller_supplier_id"]) != supplier_id:
            continue
        if scope == "category" and int(d["category_id"]) not in category_chain:
            continue
        out.append(dict(d))
    return out


def _snapshot_line(conn, o, ctx: dict, quantity: int, now: _dt.datetime, cat_cache: dict) -> dict:
    tier, contract = _tier_prices(conn, int(o["id"]), ctx, quantity, now)
    chain = _category_chain(conn, o["category_id"], cat_cache)
    return {
        "product_id": int(o["product_id"]), "product_slug": o["product_slug"], "title_fa": o["title_fa"],
        "offer_id": int(o["id"]), "supplier_id": int(o["supplier_id"]),
        "seller_name": o["shop_title"] or o["display_name"], "seller_kind": o["seller_kind"],
        "category_id": o["category_id"], "quantity": quantity,
        "base_unit_minor": int(o["selling_price_minor"]), "tier_unit_minor": tier, "contract_unit_minor": contract,
        "cost_unit_minor": int(o["cost_price_minor"]) if o["cost_price_minor"] is not None else None,
        "commission_bps": resolve_commission_bps(conn, supplier_id=int(o["supplier_id"]),
                                                 category_id=o["category_id"], channel=ctx["channel"]),
        "partner_discounts": _partner_candidates(conn, product_id=int(o["product_id"]), supplier_id=int(o["supplier_id"]),
                                                 category_chain=chain, ctx=ctx, now=now),
    }


def _offer_public(o, reasons: list[str], quantity: int) -> dict:
    return {"offer_id": int(o["id"]), "supplier_id": int(o["supplier_id"]),
            "seller_name": o["shop_title"] or o["display_name"], "shop_slug": o["shop_slug"],
            "seller_kind": o["seller_kind"], "official": o["seller_kind"] == "brand",
            "health_status": o["health_status"] if o["health_status"] != "suspended" else None,
            "unit_price_minor": int(o["selling_price_minor"]), "quantity": quantity,
            "in_stock": int(o["stock_quantity"]) - int(o["stock_reserved"]) > 0,
            "lead_time_days": o["lead_time_days"], "eligible": not reasons, "reasons": reasons}


# ── buy box ──────────────────────────────────────────────────────────────────

def buy_box(conn, product_id: int, buyer_ctx: dict | None = None, *, quantity: int = 1,
            now: _dt.datetime | None = None) -> dict:
    """Winner among sellers: suspended never wins; 'good' health beats 'at_risk'; then lowest landed
    line price (after tier/contract and partner discount); then official brand; then lead time; then id."""
    ctx = buyer_ctx or _retail_ctx()
    now = now or _now_utc()
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= MAX_QTY:
        raise ValidationError("تعداد نامعتبر است")
    from app.services import consumer_rights_service as _crs
    vat_bps = _crs.standard_vat_bps(conn)
    rules = load_rules(conn)
    cat_cache: dict = {}
    offers, ranked = [], []
    for o in conn.execute(_OFFER_SQL + " WHERE so.product_id=? ORDER BY so.id", (product_id,)):
        reasons = _ineligible_reasons(conn, o, ctx, quantity, now)
        pub = _offer_public(o, reasons, quantity)
        if not reasons:
            snap = _snapshot_line(conn, o, ctx, quantity, now, cat_cache)
            priced = compute([snap], {**ctx, "redeem_coins": 0, "credit_available_minor": 0, "recurring": False},
                             rules)["lines"][0]
            pub["unit_price_minor"] = priced["unit_price_minor"]
            pub["price_source"] = priced["price_source"]
            pub["landed_line_minor"] = priced["line_after_discounts_minor"]
            pub["landed_unit_minor"] = priced["line_after_discounts_minor"] // quantity
            pub["partner_discount_minor"] = priced["partner_discount_minor"]
            pub["landed_unit_incl_vat_minor"] = _crs.gross(pub["landed_unit_minor"], vat_bps)  # display (consumer law)
            ranked.append(((HEALTH_RANK.get(o["health_status"], 1), priced["line_after_discounts_minor"],
                            SELLER_KIND_RANK.get(o["seller_kind"], 2),
                            o["lead_time_days"] if o["lead_time_days"] is not None else 10_000, int(o["id"])), pub))
        offers.append(pub)
    ranked.sort(key=lambda x: x[0])
    winner = ranked[0][1] if ranked else None
    for pub in offers:
        pub["is_winner"] = winner is not None and pub["offer_id"] == winner["offer_id"]
    return {"product_id": product_id, "quantity": quantity, "channel": ctx["channel"], "vat_bps": vat_bps,
            "offers": offers, "winner": winner, "offer_count": len(offers), "eligible_count": len(ranked)}


# ── pure engine ──────────────────────────────────────────────────────────────

def _cap(amount: int, base: int, bps) -> int:
    return amount if bps is None else min(amount, base * int(bps) // BPS)


def _price_selection(line: dict, rule: dict) -> tuple[int, str]:
    base, tier, contract = line["base_unit_minor"], line["tier_unit_minor"], line["contract_unit_minor"]
    if not rule["enabled"]:
        return base, "base"
    if rule["mode"] == "contract_first" and contract is not None:
        return contract, "contract"
    options = [(base, 2, "base")]  # rank: contract wins an exact tie, then tier, then base
    if tier is not None:
        options.append((tier, 1, "tier"))
    if contract is not None:
        options.append((contract, 0, "contract"))
    price, _, source = min(options)
    return price, source


def _recurring_rule(rules: dict, item_count: int) -> dict | None:
    best = None
    for key in RECURRING_KEYS:
        r = rules.get(key)
        if r and r["enabled"] and r["percent_bps"] and item_count >= int(r["min_items"] or 1):
            if best is None or int(r["min_items"] or 1) > int(best["min_items"] or 1):
                best = r
    return best


def _allocate(total: int, weights: list[int]) -> list[int]:
    """Split `total` by weights (largest remainder, ties to the earlier line); never exceeds a weight
    when total <= sum(weights)."""
    s = sum(weights)
    if total <= 0 or s <= 0:
        return [0] * len(weights)
    parts = [total * w // s for w in weights]
    rema = sorted(range(len(weights)), key=lambda i: (-(total * weights[i] % s), i))
    left = total - sum(parts)
    for i in rema:
        if left <= 0:
            break
        if parts[i] < weights[i]:
            parts[i] += 1
            left -= 1
    return parts


def compute(lines: list[dict], ctx: dict, rules: dict) -> dict:
    """Pure: snapshot lines + buyer context + rules → priced quote. No DB access, no clock."""
    price_rule = rules["price_selection"]
    floor_on = bool(rules["seller_net_floor"]["enabled"])
    recurring_rule = _recurring_rule(rules, len(lines)) if ctx.get("recurring") else None
    line_steps = []
    if rules["partner_discount"]["enabled"]:
        line_steps.append(rules["partner_discount"])
    if recurring_rule is not None:
        line_steps.append(recurring_rule)
    line_steps.sort(key=lambda r: (int(r["step_order"]), r["rule_key"]))

    out_lines = []
    discount_used: dict = {}  # partner discount id → amount used so far in this order (cap is per order)
    for idx, src in enumerate(lines):
        q = int(src["quantity"])
        base_line = src["base_unit_minor"] * q
        unit, source = _price_selection(src, price_rule)
        priced = unit * q
        commission = priced * int(src["commission_bps"]) // BPS
        floor = (src["cost_unit_minor"] * q) if src["cost_unit_minor"] is not None else priced - commission
        floor = max(0, min(floor, priced)) if floor_on else 0
        adjustments = []
        if priced != base_line:
            adjustments.append({"step": "price_selection", "source": source, "amount_minor": base_line - priced,
                                "funded_by": "seller"})
        current = priced
        funded = {"platform": 0, "partner": 0, "seller": 0}
        partner_total = 0
        partner_liab = []
        for rule in line_steps:
            key = rule["rule_key"]
            if key == "partner_discount":
                best = None
                for d in src["partner_discounts"]:
                    amt = current * int(d["percent_bps"]) // BPS
                    if d["max_discount_minor"] is not None:
                        amt = min(amt, max(0, int(d["max_discount_minor"]) - discount_used.get(d["id"], 0)))
                    if best is None or amt > best[0]:
                        best = (amt, d)
                if best is None:
                    continue
                raw, d = best
                funder = d["funded_by"]
                if funder == "partner" and d["partner_supplier_id"] is not None \
                        and int(d["partner_supplier_id"]) == src["supplier_id"]:
                    funder = "seller"  # a seller's own partner promo comes out of the seller share
                meta = {"partner_discount_id": d["id"], "title_fa": d["title_fa"],
                        "partner_name": d["partner_name"], "partner_supplier_id": d["partner_supplier_id"],
                        "coupon_code": d["coupon_code"]}
            else:
                raw = current * int(rule["percent_bps"]) // BPS
                funder = rule["funded_by"] or "platform"
                meta = {"rule_key": key, "percent_bps": int(rule["percent_bps"])}
            capped = _cap(raw, priced, rule["cap_bps"])
            amount = max(0, min(capped, current - floor))
            if funder == "seller":
                # The seller keeps price − commission − own promos; never below cost (or zero).
                own_floor = (src["cost_unit_minor"] * q) if src["cost_unit_minor"] is not None else 0
                amount = max(0, min(amount, priced - commission - funded["seller"] - own_floor))
            if amount <= 0 and raw <= 0:
                continue
            adj = {"step": "partner_discount" if key == "partner_discount" else "recurring_discount",
                   "amount_minor": amount, "requested_minor": raw, "funded_by": funder, **meta}
            if capped < raw:
                adj["capped_by"] = "cap_bps"
            if amount < capped:
                adj["capped_by"] = "seller_net_floor"
            adjustments.append(adj)
            current -= amount
            funded[funder] += amount
            if key == "partner_discount":
                partner_total += amount
                discount_used[d["id"]] = discount_used.get(d["id"], 0) + amount
                if funder == "partner" and amount:
                    partner_liab.append({"partner_discount_id": d["id"], "partner_name": d["partner_name"],
                                         "partner_supplier_id": d["partner_supplier_id"], "amount_minor": amount})
        out_lines.append({
            "line_no": idx + 1, "product_id": src["product_id"], "product_slug": src.get("product_slug"),
            "title_fa": src.get("title_fa"), "offer_id": src["offer_id"], "supplier_id": src["supplier_id"],
            "seller_name": src.get("seller_name"), "seller_kind": src.get("seller_kind"), "quantity": q,
            "base_unit_minor": src["base_unit_minor"], "base_line_minor": base_line,
            "unit_price_minor": unit, "price_source": source, "line_price_minor": priced,
            "partner_discount_minor": partner_total, "line_after_discounts_minor": current,
            "seller_net_floor_minor": floor, "commission_bps": int(src["commission_bps"]),
            "commission_minor": commission, "adjustments": adjustments,
            "_funded": funded, "_partner_liab": partner_liab,
        })

    # Order level — coins.
    subtotal = sum(l["line_after_discounts_minor"] for l in out_lines)
    coins_rule = rules["coins"]
    coins_used = 0
    coin_value = loyalty_service.REDEEM_MINOR_PER_COIN
    requested = int(ctx.get("redeem_coins") or 0)
    coins_note = "استفاده از سکه فعلاً غیرفعال است" if requested and not coins_rule["enabled"] else None
    if requested and coins_rule["enabled"]:
        headroom = [l["line_after_discounts_minor"] - l["seller_net_floor_minor"] for l in out_lines]
        cap_minor = subtotal * loyalty_service.MAX_REDEEM_BPS_OF_SUBTOTAL // BPS
        cap_minor = _cap(cap_minor, subtotal, coins_rule["cap_bps"])
        cap_minor = min(cap_minor, sum(headroom))
        coins_used = min(requested, int(ctx.get("coin_balance") or 0), cap_minor // coin_value)
        if coins_used < requested:
            coins_note = "سکهٔ قابل استفاده به سقف مجاز یا موجودی محدود شد"
        parts = _allocate(coins_used * coin_value, headroom)
        for l, part in zip(out_lines, parts):
            if part:
                l["adjustments"].append({"step": "coins", "amount_minor": part, "funded_by": "platform"})
                l["_funded"]["platform"] += part
            l["coins_minor"] = part
    for l in out_lines:
        l.setdefault("coins_minor", 0)
        l["payable_minor"] = l["line_after_discounts_minor"] - l["coins_minor"]
        f = l.pop("_funded")
        l["platform_funded_minor"] = f["platform"]
        l["partner_funded_minor"] = f["partner"]
        l["seller_funded_minor"] = f["seller"]
        l["seller_share_minor"] = l["line_price_minor"] - l["commission_minor"] - f["seller"]
        l["platform_net_minor"] = l["commission_minor"] - f["platform"]
        if l["payable_minor"] + f["platform"] + f["partner"] + f["seller"] != l["line_price_minor"]:
            raise RuntimeError("cashier invariant broken: funding does not add up to the line price")

    payable = sum(l["payable_minor"] for l in out_lines)
    credit_rule = rules["credit"]
    credit = 0
    if credit_rule["enabled"] and ctx.get("organization_id"):
        credit = _cap(min(int(ctx.get("credit_available_minor") or 0), payable), payable, credit_rule["cap_bps"])

    sum_keys = ("base_line_minor", "line_price_minor", "partner_discount_minor", "line_after_discounts_minor",
                "coins_minor", "payable_minor", "commission_minor", "seller_share_minor", "platform_funded_minor",
                "partner_funded_minor", "seller_funded_minor", "platform_net_minor")
    sellers: dict[int, dict] = {}
    partners: dict[tuple, dict] = {}
    for l in out_lines:
        s = sellers.setdefault(l["supplier_id"], {"supplier_id": l["supplier_id"], "seller_name": l["seller_name"],
                                                  "seller_kind": l["seller_kind"], "line_count": 0,
                                                  **{k: 0 for k in sum_keys}})
        s["line_count"] += 1
        for k in sum_keys:
            s[k] += l[k]
        for p in l.pop("_partner_liab"):
            key = (p["partner_supplier_id"], p["partner_name"])
            agg = partners.setdefault(key, {"partner_supplier_id": p["partner_supplier_id"],
                                            "partner_name": p["partner_name"], "amount_minor": 0})
            agg["amount_minor"] += p["amount_minor"]
    totals = {k: sum(l[k] for l in out_lines) for k in sum_keys}
    totals.update({"coins_used": coins_used, "credit_minor": credit, "cash_minor": payable - credit,
                   "discount_total_minor": totals["base_line_minor"] - payable})
    return {
        "channel": ctx.get("channel", "retail"), "organization_id": ctx.get("organization_id"),
        "recurring": bool(ctx.get("recurring")),
        "recurring_rule": recurring_rule["rule_key"] if recurring_rule else None,
        "lines": out_lines, "sellers": [sellers[k] for k in sorted(sellers)],
        "partner_receivables": [partners[k] for k in sorted(partners, key=lambda k: (k[0] or 0, k[1] or ""))],
        "totals": totals, "coins_requested": requested, "coins_note": coins_note,
        "rules_applied": [r["rule_key"] for r in [price_rule] + line_steps + [coins_rule, credit_rule,
                                                                              rules["seller_net_floor"]]
                          if r["enabled"]],
    }


# ── quote ────────────────────────────────────────────────────────────────────

def _clean_items(items) -> list[dict]:
    if not isinstance(items, list) or not items:
        raise ValidationError("سبد خالی است")
    if len(items) > MAX_LINES:
        raise ValidationError("تعداد اقلام سبد بیش از حد مجاز است")
    out = []
    for it in items:
        if not isinstance(it, dict):
            raise ValidationError("قلم سبد نامعتبر است")
        q = it.get("quantity", 1)
        if isinstance(q, bool) or not isinstance(q, int) or not 1 <= q <= MAX_QTY:
            raise ValidationError("تعداد کالا نامعتبر است")
        pid, oid = it.get("product_id"), it.get("offer_id")
        for v in (pid, oid):
            if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 1):
                raise ValidationError("شناسهٔ کالا یا پیشنهاد نامعتبر است")
        if pid is None and oid is None:
            raise ValidationError("برای هر قلم شناسهٔ کالا یا پیشنهاد فروشنده لازم است")
        out.append({"product_id": pid, "offer_id": oid, "quantity": q})
    return out


def quote(conn, items, buyer_ctx: dict | None = None, *, now: _dt.datetime | None = None) -> dict:
    """Price a cart. Items name an offer (pinned seller) or a product (buy-box winner).
    Items that cannot be sold are returned under `unavailable` with reasons, never priced."""
    ctx = buyer_ctx or _retail_ctx()
    now = now or _now_utc()
    clean = _clean_items(items)
    rules = load_rules(conn)
    cat_cache: dict = {}
    snaps, unavailable = [], []
    for it in clean:
        q = it["quantity"]
        if it["offer_id"] is not None:
            o = conn.execute(_OFFER_SQL + " WHERE so.id=?", (it["offer_id"],)).fetchone()
            if o is None or (it["product_id"] is not None and int(o["product_id"]) != it["product_id"]):
                unavailable.append({**it, "reasons": ["offer_not_found"]})
                continue
            reasons = _ineligible_reasons(conn, o, ctx, q, now)
            if reasons:
                unavailable.append({**it, "product_id": int(o["product_id"]), "reasons": reasons})
                continue
        else:
            box = buy_box(conn, it["product_id"], ctx, quantity=q, now=now)
            if box["winner"] is None:
                unavailable.append({**it, "reasons": ["no_eligible_offer"] if box["offers"] else ["no_offer"]})
                continue
            o = conn.execute(_OFFER_SQL + " WHERE so.id=?", (box["winner"]["offer_id"],)).fetchone()
        snaps.append(_snapshot_line(conn, o, ctx, q, now, cat_cache))
    result = compute(snaps, ctx, rules)
    result["unavailable"] = unavailable
    result["priced_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return result


# ── partner discounts admin ──────────────────────────────────────────────────

def _date(v, field):
    if v is None:
        return None
    try:
        return _dt.date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise ValidationError(f"تاریخ «{field}» نامعتبر است")


def _clean_discount(conn, data: dict, current: dict | None = None) -> dict:
    allowed = {"title_fa", "partner_supplier_id", "partner_name", "scope", "category_id", "product_id",
               "seller_supplier_id", "channel", "percent_bps", "max_discount_minor", "valid_from", "valid_until",
               "funded_by", "coupon_code", "status"}
    extra = set(data) - allowed
    if extra:
        raise ValidationError("فیلد ناشناخته", details={"fields": sorted(extra)})
    d = {**(current or {"scope": "all", "channel": "any", "funded_by": "partner", "status": "active"}), **data}
    title = d.get("title_fa")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValidationError("عنوان تخفیف الزامی است")
    d["title_fa"] = title.strip()
    name = d.get("partner_name")
    if name is not None and (not isinstance(name, str) or not name.strip() or len(name) > 120):
        raise ValidationError("نام شریک نامعتبر است")
    d["partner_name"] = name.strip() if isinstance(name, str) else None
    for key, table in (("partner_supplier_id", "suppliers"), ("seller_supplier_id", "suppliers"),
                       ("category_id", "categories"), ("product_id", "products")):
        v = d.get(key)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, int) or v < 1 \
                or not conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (v,)).fetchone():
            raise ValidationError(f"«{key}» یافت نشد", details={"field": key})
    if d.get("partner_supplier_id") is None and d.get("partner_name") is None:
        raise ValidationError("شریک (فروشندهٔ شریک یا نام شریک بیرونی) الزامی است")
    if d["scope"] not in ("all", "category", "product", "seller"):
        raise ValidationError("دامنهٔ تخفیف نامعتبر است")
    need = {"category": "category_id", "product": "product_id", "seller": "seller_supplier_id"}.get(d["scope"])
    if need and d.get(need) is None:
        raise ValidationError(f"برای این دامنه «{need}» لازم است")
    if d["channel"] not in ("any", "retail", "organization"):
        raise ValidationError("کانال تخفیف نامعتبر است")
    p = d.get("percent_bps")
    if isinstance(p, bool) or not isinstance(p, int) or not 1 <= p <= BPS:
        raise ValidationError("درصد تخفیف (bps) باید بین ۱ و ۱۰۰۰۰ باشد")
    m = d.get("max_discount_minor")
    if m is not None and (isinstance(m, bool) or not isinstance(m, int) or m <= 0):
        raise ValidationError("سقف ریالی تخفیف نامعتبر است")
    if d["funded_by"] not in ("partner", "platform"):
        raise ValidationError("تأمین هزینهٔ تخفیف باید partner یا platform باشد")
    if d["status"] not in ("active", "paused", "archived"):
        raise ValidationError("وضعیت تخفیف نامعتبر است")
    d["valid_from"], d["valid_until"] = _date(d.get("valid_from"), "valid_from"), _date(d.get("valid_until"), "valid_until")
    if d["valid_from"] and d["valid_until"] and d["valid_until"] < d["valid_from"]:
        raise ValidationError("بازهٔ اعتبار تخفیف نامعتبر است")
    code = d.get("coupon_code")
    if code is not None:
        if not isinstance(code, str) or not code.strip().isascii() or not 3 <= len(code.strip()) <= 40:
            raise ValidationError("کد تخفیف باید ۳ تا ۴۰ نویسهٔ لاتین باشد")
        code = code.strip().upper()
        clash = conn.execute("SELECT id FROM partner_discounts WHERE coupon_code=?", (code,)).fetchone()
        if clash and (current is None or int(clash["id"]) != int(current["id"])):
            raise ValidationError("این کد تخفیف قبلاً ثبت شده است")
    d["coupon_code"] = code
    return d


_DISCOUNT_COLS = ("title_fa", "partner_supplier_id", "partner_name", "scope", "category_id", "product_id",
                  "seller_supplier_id", "channel", "percent_bps", "max_discount_minor", "valid_from", "valid_until",
                  "funded_by", "coupon_code", "status")


def create_partner_discount(conn, *, data: dict, actor: int) -> dict:
    d = _clean_discount(conn, data)
    cur = conn.execute(
        f"INSERT INTO partner_discounts ({', '.join(_DISCOUNT_COLS)}, created_by_user_id) "
        f"VALUES ({', '.join('?' * (len(_DISCOUNT_COLS) + 1))})",
        tuple(d.get(c) for c in _DISCOUNT_COLS) + (actor,))
    return get_partner_discount(conn, int(cur.lastrowid))


def update_partner_discount(conn, *, discount_id: int, data: dict) -> dict:
    current = get_partner_discount(conn, discount_id)
    d = _clean_discount(conn, data, current)
    conn.execute(f"UPDATE partner_discounts SET {', '.join(c + '=?' for c in _DISCOUNT_COLS)}, updated_at=? WHERE id=?",
                 tuple(d.get(c) for c in _DISCOUNT_COLS) + (_now_utc().strftime("%Y-%m-%dT%H:%M:%S.000Z"), discount_id))
    return get_partner_discount(conn, discount_id)


def get_partner_discount(conn, discount_id: int) -> dict:
    row = conn.execute("SELECT * FROM partner_discounts WHERE id=?", (discount_id,)).fetchone()
    if row is None:
        raise NotFoundError("تخفیف شریک یافت نشد")
    return dict(row)


def list_partner_discounts(conn, *, status: str | None = None) -> list[dict]:
    if status is not None and status not in ("active", "paused", "archived"):
        raise ValidationError("وضعیت نامعتبر است")
    sql, args = "SELECT * FROM partner_discounts", ()
    if status:
        sql, args = sql + " WHERE status=?", (status,)
    return [dict(r) for r in conn.execute(sql + " ORDER BY id DESC", args)]


# Fields only staff may see: seller cost floors, commissions and the platform/seller split.
_INTERNAL_KEYS = {"seller_net_floor_minor", "commission_bps", "commission_minor", "seller_share_minor",
                  "platform_net_minor", "platform_funded_minor", "partner_funded_minor", "seller_funded_minor",
                  "partner_liabilities", "cost_unit_minor"}


def public_view(value):
    """Strip internal economics from a quote before it leaves for a buyer."""
    if isinstance(value, dict):
        return {k: public_view(v) for k, v in value.items() if k not in _INTERNAL_KEYS and not k.startswith("_")}
    if isinstance(value, list):
        return [public_view(v) for v in value]
    return value
