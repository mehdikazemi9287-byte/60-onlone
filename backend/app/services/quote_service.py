"""Server-authoritative checkout quote — the split-payment calculation.

Nothing monetary is ever accepted from the client. The frontend calls
`POST /api/v1/checkout/quote`, renders what it is told, and posts back only an
address and an idempotency key. `checkout_service` recomputes this same quote
inside the checkout transaction, so a quote that went stale between display and
submission cannot be exploited.

Money equation (v6):
    taxable_base_minor = subtotal_minor   (shipping is VAT-exempt)
    tax_minor          = taxable_base_minor * rate_bps // 10000  (integer floor)
    total_minor        = subtotal_minor + shipping_fee_minor + tax_minor
    credit_to_use      = min(eligible_credit, total_minor)
    cash_due           = total_minor - credit_to_use
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.core.db import Database
from app.core.errors import ConflictError, ValidationError
from app.core.money import format_minor
from app.services import cart_service, credit_rules, loyalty_service
from app.services.credit_rules import CartLine, CreditContext
from app.services.tax_service import calculate_line_tax_with_conn


def _cart_lines(conn: sqlite3.Connection, cart_items: list[dict]) -> list[CartLine]:
    lines: list[CartLine] = []
    for item in cart_items:
        row = conn.execute(
            """
            SELECT c.slug AS category_slug FROM products p
            JOIN categories c ON c.id = p.category_id WHERE p.id = ?
            """,
            (item["product_id"],),
        ).fetchone()
        lines.append(CartLine(
            product_id=item["product_id"],
            title_fa=item["title_fa"],
            sku=item["sku"],
            category_slug=row["category_slug"] if row else "",
            unit_price_minor=int(item["unit_price_minor"]),
            quantity=int(item["quantity"]),
            line_total_minor=int(item["line_total_minor"]),
        ))
    return lines


def _period_consumed(conn: sqlite3.Connection, allocation_id: int) -> int:
    """Credit already captured against this allocation.

    Phase 2 treats "the period" as the whole life of the allocation, because an
    allocation already carries its own validity window. Calendar-month periods
    are NOT implemented.
    """
    row = conn.execute(
        """
        SELECT COALESCE(SUM(amount_minor), 0) AS n FROM credit_ledger_entries
        WHERE allocation_id = ? AND entry_type = 'capture'
        """,
        (allocation_id,),
    ).fetchone()
    return int(row["n"])


def _user_organization_id(conn: sqlite3.Connection, user_id: int) -> int | None:
    """Return the organization_id for the user's active org membership, or None."""
    row = conn.execute(
        """
        SELECT organization_id FROM organization_memberships
        WHERE user_id = ? AND status = 'active'
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    return int(row["organization_id"]) if row else None


def build_quote(
    conn: sqlite3.Connection, *, user_id: int, exponent: int = 0, now: datetime | None = None,
    redeem_coins: int = 0,
) -> dict:
    """Compute the funding breakdown for the caller's current cart.

    Runs inside whatever transaction the caller owns, so checkout and the
    preview endpoint see exactly the same numbers.

    Money equation (v6 + 60Coin redemption):
        redeem_discount_minor = min(redeem_coins * 10_000, subtotal_minor,
                                     subtotal_minor * 50%)   (see loyalty_service caps)
        discounted_subtotal   = subtotal_minor - redeem_discount_minor
        taxable_base_minor    = discounted_subtotal   (shipping excluded from VAT)
        tax_minor             = taxable_base_minor * rate_bps // 10000
        total_minor           = discounted_subtotal + shipping_fee_minor + tax_minor
        credit_to_use         = min(eligible_credit, total_minor)
        cash_due              = total_minor - credit_to_use

    The coin discount is applied to the merchandise subtotal BEFORE VAT is
    computed — the same treatment a cart-level discount/coupon would get —
    which is why total_minor = subtotal_minor + shipping_fee_minor + tax_minor
    (the existing, unmodified CHECK constraint on orders_v2/payment_intents_v2)
    still holds exactly: subtotal_minor here already IS the discounted value.
    Credit (org funding) is a separate, payment-method-level offset applied
    afterward, unchanged from before.
    """
    from app.services.credit_service import allocation_state

    now = now or datetime.now(timezone.utc)
    cart = cart_service.read_cart(conn, user_id, exponent)
    lines = _cart_lines(conn, cart["items"])

    gross_subtotal_minor = int(cart["subtotal_minor"])
    shipping_minor = int(cart["shipping_fee_minor"])

    # ── 60Coin redemption (validated here, inside the caller's transaction —
    # a client-claimed balance is never trusted) ───────────────────────────
    if redeem_coins:
        if not isinstance(redeem_coins, int) or isinstance(redeem_coins, bool) or redeem_coins < 0:
            raise ValidationError("redeem_coins باید عدد صحیح نامنفی باشد")
        available_balance = loyalty_service.balance(conn, user_id)
        if redeem_coins > available_balance:
            raise ConflictError(
                "موجودی ۶۰کوین کافی نیست",
                details={"balance_coins": available_balance, "requested_coins": redeem_coins},
            )
        max_allowed = loyalty_service.max_redeemable_coins(gross_subtotal_minor, available_balance)
        if redeem_coins > max_allowed:
            raise ValidationError(
                "تعداد کوین درخواستی بیش از سقف مجاز این سفارش است",
                details={"max_redeemable_coins": max_allowed},
            )
    redeem_discount_minor = redeem_coins * loyalty_service.REDEEM_MINOR_PER_COIN
    subtotal_minor = gross_subtotal_minor - redeem_discount_minor

    # ── VAT calculation ────────────────────────────────────────────────────────
    # Taxable base is the (discount-adjusted) merchandise subtotal; shipping
    # is VAT-exempt. We need the organization for exemption checking — use
    # the user's active membership (if any) so employees buying on behalf of
    # their org get the correct exemption applied at quote time.
    org_id = _user_organization_id(conn, user_id)
    today_str = now.strftime("%Y-%m-%d")

    tax_result = calculate_line_tax_with_conn(
        conn,
        subtotal_minor=subtotal_minor,
        tax_category_code="STANDARD",
        effective_date=today_str,
        organization_id=org_id,
    )
    tax_minor          = tax_result["tax_minor"]
    tax_rate_bps       = tax_result["rate_bps"]
    taxable_base_minor = subtotal_minor   # shipping excluded

    total_minor = subtotal_minor + shipping_minor + tax_minor

    quote = {
        "cart": {
            "item_count": cart["item_count"],
            "subtotal": format_minor(subtotal_minor, exponent),
            "subtotal_minor": subtotal_minor,
            "gross_subtotal_minor": gross_subtotal_minor,
            "shipping_fee": cart["shipping_fee"],
            "shipping_fee_minor": shipping_minor,
            "total": format_minor(total_minor, exponent),
            "total_minor": total_minor,
        },
        "currency": cart["currency"],
        # VAT snapshot
        "taxable_base_minor": taxable_base_minor,
        "tax_rate_bps": tax_rate_bps,
        "tax_minor": tax_minor,
        "tax": format_minor(tax_minor, exponent),
        # 60Coin redemption snapshot
        "redeem_coins": redeem_coins,
        "redeem_discount_minor": redeem_discount_minor,
        "redeem_discount": format_minor(redeem_discount_minor, exponent),
        # credit / cash split
        "has_organization_credit": False,
        "organization": None,
        "allocation": None,
        "eligible_credit": format_minor(0, exponent),
        "eligible_credit_minor": 0,
        "credit_to_use": format_minor(0, exponent),
        "credit_to_use_minor": 0,
        "cash_due": format_minor(total_minor, exponent),
        "cash_due_minor": total_minor,
        "final_payable": format_minor(total_minor, exponent),
        "final_payable_minor": total_minor,
        "restrictions": [],
        "payment_method": "card",
    }

    if total_minor <= 0:
        return quote

    # Candidate allocations: active membership, ordered so the one expiring
    # soonest is consumed first (use-it-or-lose-it is the fairer default).
    #
    # LIMITATION (Phase 2, documented in AUDIT_EVIDENCE.md): exactly ONE
    # allocation funds an order. If an employee holds several grants, the one
    # yielding the largest usable amount is chosen and the others are left
    # untouched -- they are not combined. Combining them needs multiple
    # reservations per payment intent, which the schema deliberately forbids
    # today (credit_reservations.payment_intent_id is UNIQUE). Lifting this is
    # a Phase 3 change to the reservation model, not a tweak here.
    candidates = conn.execute(
        """
        SELECT a.*, o.status AS organization_status, o.display_name AS organization_name,
               m.status AS membership_status, m.role AS membership_role
        FROM credit_allocations a
        JOIN organizations o ON o.id = a.organization_id
        JOIN organization_memberships m ON m.id = a.membership_id
        WHERE a.user_id = ?
        ORDER BY (a.expires_at IS NULL), a.expires_at ASC, a.id ASC
        """,
        (user_id,),
    ).fetchall()

    if not candidates:
        return quote

    quote["has_organization_credit"] = True
    best: tuple[int, sqlite3.Row, credit_rules.Evaluation] | None = None
    all_restrictions: list[dict] = []

    for allocation in candidates:
        state = allocation_state(conn, int(allocation["id"]))
        ctx = CreditContext(
            now=now,
            organization_status=allocation["organization_status"],
            membership_status=allocation["membership_status"],
            membership_role=allocation["membership_role"],
            allocation_status=allocation["status"],
            allocated_minor=state["allocated_minor"],
            available_minor=state["available_minor"],
            valid_from=allocation["valid_from"],
            expires_at=allocation["expires_at"],
            category_slugs=credit_rules.parse_category_slugs(allocation["category_slugs_json"]),
            per_transaction_limit_minor=allocation["per_transaction_limit_minor"],
            period_limit_minor=allocation["period_limit_minor"],
            period_consumed_minor=_period_consumed(conn, int(allocation["id"])),
            lines=lines,
            shipping_fee_minor=int(cart["shipping_fee_minor"]),
            subtotal_minor=subtotal_minor,  # discounted (post-60Coin-redemption) value
            tax_minor=tax_minor,
        )
        evaluation = credit_rules.evaluate(ctx)
        if evaluation.usable_minor > 0 and (best is None or evaluation.usable_minor > best[0]):
            best = (evaluation.usable_minor, allocation, evaluation)
        else:
            all_restrictions.extend(
                r.to_dict() for r in evaluation.blocking
            )

    if best is None:
        # Nothing usable: surface why, de-duplicated, so the UI can explain it.
        seen, unique = set(), []
        for restriction in all_restrictions:
            if restriction["code"] not in seen:
                seen.add(restriction["code"])
                unique.append(restriction)
        quote["restrictions"] = unique
        return quote

    usable, allocation, evaluation = best
    # Credit covers up to total_minor (which now includes VAT)
    credit_to_use = min(usable, total_minor)
    cash_due = total_minor - credit_to_use

    quote.update({
        "organization": {
            "id": allocation["organization_id"],
            "display_name": allocation["organization_name"],
            "status": allocation["organization_status"],
        },
        "allocation": {
            "id": allocation["id"],
            "reference": allocation["reference"],
            "expires_at": allocation["expires_at"],
            "category_slugs": credit_rules.parse_category_slugs(allocation["category_slugs_json"]),
        },
        "eligible_credit": format_minor(usable, exponent),
        "eligible_credit_minor": usable,
        "credit_to_use": format_minor(credit_to_use, exponent),
        "credit_to_use_minor": credit_to_use,
        "cash_due": format_minor(cash_due, exponent),
        "cash_due_minor": cash_due,
        "final_payable": format_minor(total_minor, exponent),
        "final_payable_minor": total_minor,
        # Informational caps are useful to the employee even when they did not bind.
        "restrictions": [
            r.to_dict() for r in evaluation.restrictions
            if r.kind == credit_rules.BLOCK
            or (r.cap_minor is not None and r.cap_minor < total_minor)
        ],
        "payment_method": "split" if credit_to_use and cash_due else ("credit" if credit_to_use else "card"),
    })
    return quote


def get_quote(db: Database, *, user_id: int, exponent: int = 0, redeem_coins: int = 0) -> dict:
    with db.read_transaction() as conn:
        return build_quote(conn, user_id=user_id, exponent=exponent, redeem_coins=redeem_coins)
