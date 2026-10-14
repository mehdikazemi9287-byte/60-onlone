"""RFQ (Request for Quotation) Service.

Manages the RFQ lifecycle from creation to award.

State machine:
  draft → open → closed → awarded
  Any state → cancelled (with restrictions)

Column names match migration 0005 exactly:
  rfq_items.quantity_requested   (not .quantity)
  supplier_quotes.total_items_minor / grand_total_minor  (not total_amount_minor)
  supplier_quotes.rfq_supplier_id  (required)
  supplier_quote_items.quantity_available  (not .quantity)
  supplier_quote_items.total_minor  (not .total_price_minor)
"""
from __future__ import annotations

import datetime
from typing import Any

from app.core.errors import ConflictError, PermissionError_, NotFoundError, ValidationError
from app.services.procurement_service import _assert_org_member, _can_procure, _audit, _now


# ── Number generation ──────────────────────────────────────────────────────────

def _next_rfq_number(conn, organization_id: int) -> str:
    # rfq_number is globally unique, not organization-scoped. The caller owns
    # the serialized write transaction; preserve every previously issued value.
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    prefix = f"RFQ-{today}-"
    highest = conn.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(rfq_number, ?) AS INTEGER)),0) FROM rfqs WHERE rfq_number LIKE ?",
        (len(prefix)+1, prefix+"%"),
    ).fetchone()[0]
    return f"{prefix}{highest+1:04d}"


def _next_quote_number(conn, organization_id: int) -> str:
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    count = conn.execute(
        """SELECT COUNT(*) FROM supplier_quotes sq
           JOIN rfqs r ON r.id = sq.rfq_id
           WHERE r.organization_id=?""",
        (organization_id,),
    ).fetchone()[0]
    return f"Q-{today}-{count + 1:04d}"


# ── Serialisation ──────────────────────────────────────────────────────────────

def _rfq_dict(row) -> dict:
    return {
        "id": row["id"],
        "organization_id": row["organization_id"],
        "purchase_request_id": row["purchase_request_id"],
        "rfq_number": row["rfq_number"],
        "title": row["title"],
        "status": row["status"],
        "deadline_at": row["deadline_at"],
        "notes": row["notes"],
        "created_by_user_id": row["created_by_user_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _rfq_item_dict(row) -> dict:
    return {
        "id": row["id"],
        "rfq_id": row["rfq_id"],
        "purchase_request_item_id": row["purchase_request_item_id"],
        "master_product_id": row["master_product_id"],
        "free_text_description": row["free_text_description"],
        "product_name_fa": row["product_name_fa"] if "product_name_fa" in row.keys() else row["free_text_description"],
        "quantity": row["quantity_requested"],  # expose as 'quantity' for API compatibility
        "unit": row["unit"],
        "notes": row["notes"],
    }


def _rfq_supplier_dict(row) -> dict:
    return {
        "id": row["id"],
        "rfq_id": row["rfq_id"],
        "supplier_id": row["supplier_id"],
        "status": row["status"],
        "invited_at": row["invited_at"],
    }


def _quote_dict(row) -> dict:
    # vat_amount_minor, shipping_vat_minor, shipping_vat_rate_bps added by migration 0020
    # Use dict() access with fallback so this function still works on pre-migration rows.
    keys = row.keys() if hasattr(row, "keys") else []
    vat_amount_minor     = row["vat_amount_minor"]     if "vat_amount_minor"     in keys else 0
    shipping_vat_minor   = row["shipping_vat_minor"]   if "shipping_vat_minor"   in keys else 0
    shipping_vat_rate_bps = row["shipping_vat_rate_bps"] if "shipping_vat_rate_bps" in keys else 0
    return {
        "id": row["id"],
        "rfq_id": row["rfq_id"],
        "supplier_id": row["supplier_id"],
        "quote_number": row["quote_number"],
        "status": row["status"],
        "total_amount_minor": row["total_items_minor"],  # alias for API compat
        "total_items_minor": row["total_items_minor"],
        "shipping_cost_minor": row["shipping_cost_minor"],
        "vat_amount_minor": vat_amount_minor,
        "shipping_vat_minor": shipping_vat_minor,
        "shipping_vat_rate_bps": shipping_vat_rate_bps,
        # vat_bps: DEPRECATED alias — vat_amount_minor is the correct field (amount, not rate)
        "vat_bps": None,
        "grand_total_minor": row["grand_total_minor"],
        "payment_terms": row["payment_terms"],
        "delivery_lead_days": row["delivery_lead_days"],
        "validity_days": row["validity_days"],
        "notes": row["notes"],
        "submitted_at": row["submitted_at"],
        "created_at": row["created_at"],
    }


def _quote_item_dict(row) -> dict:
    return {
        "id": row["id"],
        "supplier_quote_id": row["supplier_quote_id"],
        "rfq_item_id": row["rfq_item_id"],
        "unit_price_minor": row["unit_price_minor"],
        "quantity": row["quantity_available"],  # alias
        "total_price_minor": row["total_minor"],  # alias
        "notes": row["notes"],
    }


# ── RFQ CRUD ───────────────────────────────────────────────────────────────────

def create_rfq(
    conn,
    *,
    organization_id: int,
    purchase_request_id: int,
    actor_user_id: int,
    title: str,
    deadline_at: str | None = None,
    notes: str | None = None,
    items: list[dict] | None = None,
) -> dict:
    """Create a draft RFQ from an approved Purchase Request."""
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    if not _can_procure(membership):
        raise PermissionError_("دسترسی ایجاد درخواست استعلام ندارید")

    pr_row = conn.execute(
        "SELECT * FROM purchase_requests WHERE id=? AND organization_id=?",
        (purchase_request_id, organization_id),
    ).fetchone()
    if not pr_row:
        raise NotFoundError("درخواست خرید یافت نشد")
    if pr_row["status"] not in ("approved", "sourcing"):
        raise ConflictError(
            f"درخواست خرید باید در وضعیت 'approved' باشد (وضعیت فعلی: '{pr_row['status']}')"
        )

    title = (title or "").strip()
    if not title:
        raise ValidationError("عنوان استعلام الزامی است")

    rfq_number = _next_rfq_number(conn, organization_id)
    cur = conn.execute(
        """INSERT INTO rfqs
           (organization_id, purchase_request_id, rfq_number, title,
            deadline_at, notes, created_by_user_id)
           VALUES (?,?,?,?,?,?,?)""",
        (organization_id, purchase_request_id, rfq_number, title,
         deadline_at, notes, actor_user_id),
    )
    rfq_id = cur.lastrowid

    pr_items = items or []
    if not pr_items:
        # Copy all PR items
        pr_items_rows = conn.execute(
            "SELECT * FROM purchase_request_items WHERE purchase_request_id=? ORDER BY id",
            (purchase_request_id,),
        ).fetchall()
        for pri in pr_items_rows:
            conn.execute(
                """INSERT INTO rfq_items
                   (rfq_id, purchase_request_item_id, master_product_id,
                    free_text_description, quantity_requested, unit, notes)
                   VALUES (?,?,?,?,?,?,?)""",
                (rfq_id, pri["id"], pri["master_product_id"],
                 pri["free_text_description"], pri["quantity"], pri["unit"], pri["notes"]),
            )
    else:
        for item in pr_items:
            qty = item.get("quantity", 0)
            if not isinstance(qty, int) or qty < 1:
                raise ValidationError("تعداد باید عدد صحیح مثبت باشد")
            conn.execute(
                """INSERT INTO rfq_items
                   (rfq_id, purchase_request_item_id, master_product_id,
                    free_text_description, quantity_requested, unit, notes)
                   VALUES (?,?,?,?,?,?,?)""",
                (rfq_id, item.get("purchase_request_item_id"),
                 item.get("master_product_id"), item.get("free_text_description"),
                 qty, item.get("unit"), item.get("notes")),
            )

    # Move PR to sourcing
    conn.execute(
        "UPDATE purchase_requests SET status='sourcing', updated_at=? WHERE id=?",
        (_now(), purchase_request_id),
    )

    _audit(conn, organization_id=organization_id, actor_user_id=actor_user_id,
           event_type="rfq_created", entity_type="rfq", entity_id=rfq_id,
           details={"rfq_number": rfq_number, "purchase_request_id": purchase_request_id})

    return get_rfq(conn, rfq_id, actor_user_id=actor_user_id, organization_id=organization_id)


def get_rfq(conn, rfq_id: int, *, actor_user_id: int, organization_id: int) -> dict:
    _assert_org_member(conn, actor_user_id, organization_id)
    row = conn.execute(
        "SELECT * FROM rfqs WHERE id=? AND organization_id=?",
        (rfq_id, organization_id),
    ).fetchone()
    if not row:
        raise NotFoundError("استعلام یافت نشد")
    rfq = _rfq_dict(row)
    items = conn.execute(
        "SELECT ri.*,mp.canonical_name_fa AS product_name_fa FROM rfq_items ri LEFT JOIN master_products mp ON mp.id=ri.master_product_id WHERE ri.rfq_id=? ORDER BY ri.id", (rfq_id,)
    ).fetchall()
    rfq["items"] = [_rfq_item_dict(i) for i in items]
    suppliers = conn.execute(
        "SELECT * FROM rfq_suppliers WHERE rfq_id=? ORDER BY id", (rfq_id,)
    ).fetchall()
    rfq["suppliers"] = [_rfq_supplier_dict(s) for s in suppliers]
    return rfq


def list_rfqs(
    conn,
    *,
    organization_id: int,
    actor_user_id: int,
    status: str | None = None,
    purchase_request_id: int | None = None,
) -> list[dict]:
    _assert_org_member(conn, actor_user_id, organization_id)
    where = ["organization_id=?"]
    params: list = [organization_id]
    if status:
        where.append("status=?")
        params.append(status)
    if purchase_request_id:
        where.append("purchase_request_id=?")
        params.append(purchase_request_id)
    rows = conn.execute(
        f"SELECT * FROM rfqs WHERE {' AND '.join(where)} ORDER BY id DESC",
        params,
    ).fetchall()
    result = []
    for r in rows:
        rfq = _rfq_dict(r)
        items = conn.execute("SELECT ri.*,mp.canonical_name_fa AS product_name_fa FROM rfq_items ri LEFT JOIN master_products mp ON mp.id=ri.master_product_id WHERE ri.rfq_id=? ORDER BY ri.id", (r["id"],)).fetchall()
        rfq["items"] = [_rfq_item_dict(i) for i in items]
        suppliers = conn.execute("SELECT * FROM rfq_suppliers WHERE rfq_id=? ORDER BY id", (r["id"],)).fetchall()
        rfq["suppliers"] = [_rfq_supplier_dict(s) for s in suppliers]
        result.append(rfq)
    return result


def invite_supplier_to_rfq(
    conn, rfq_id: int, supplier_id: int, *, actor_user_id: int, organization_id: int
) -> dict:
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    if not _can_procure(membership):
        raise PermissionError_("دسترسی دعوت تأمین‌کننده ندارید")

    row = conn.execute(
        "SELECT * FROM rfqs WHERE id=? AND organization_id=?", (rfq_id, organization_id)
    ).fetchone()
    if not row:
        raise NotFoundError("استعلام یافت نشد")
    if row["status"] not in ("draft", "open"):
        raise ConflictError(f"استعلام در وضعیت '{row['status']}' قابل دعوت نیست")

    sup = conn.execute("SELECT id FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
    if not sup:
        raise NotFoundError("تأمین‌کننده یافت نشد")

    existing = conn.execute(
        "SELECT id FROM rfq_suppliers WHERE rfq_id=? AND supplier_id=?",
        (rfq_id, supplier_id),
    ).fetchone()
    if existing:
        raise ConflictError("این تأمین‌کننده قبلاً دعوت شده است")

    now = _now()
    cur = conn.execute(
        "INSERT INTO rfq_suppliers (rfq_id, supplier_id, status, invited_at) VALUES (?,?,'invited',?)",
        (rfq_id, supplier_id, now),
    )
    _audit(conn, organization_id=organization_id, actor_user_id=actor_user_id,
           event_type="supplier_invited", entity_type="rfq", entity_id=rfq_id,
           details={"supplier_id": supplier_id})
    row2 = conn.execute("SELECT * FROM rfq_suppliers WHERE id=?", (cur.lastrowid,)).fetchone()
    return _rfq_supplier_dict(row2)


def open_rfq(conn, rfq_id: int, *, actor_user_id: int, organization_id: int) -> dict:
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    if not _can_procure(membership):
        raise PermissionError_("دسترسی باز کردن استعلام ندارید")

    row = conn.execute("SELECT * FROM rfqs WHERE id=? AND organization_id=?", (rfq_id, organization_id)).fetchone()
    if not row:
        raise NotFoundError("استعلام یافت نشد")
    if row["status"] != "draft":
        raise ConflictError(f"استعلام در وضعیت '{row['status']}' است و قابل باز کردن نیست")

    count = conn.execute("SELECT COUNT(*) FROM rfq_suppliers WHERE rfq_id=?", (rfq_id,)).fetchone()[0]
    if count == 0:
        raise ValidationError("حداقل یک تأمین‌کننده باید دعوت شده باشد")

    now = _now()
    conn.execute("UPDATE rfqs SET status='open', updated_at=? WHERE id=?", (now, rfq_id))
    _audit(conn, organization_id=organization_id, actor_user_id=actor_user_id,
           event_type="rfq_opened", entity_type="rfq", entity_id=rfq_id)
    return get_rfq(conn, rfq_id, actor_user_id=actor_user_id, organization_id=organization_id)


def close_rfq(conn, rfq_id: int, *, actor_user_id: int, organization_id: int) -> dict:
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    if not _can_procure(membership):
        raise PermissionError_("دسترسی بستن استعلام ندارید")

    row = conn.execute("SELECT * FROM rfqs WHERE id=? AND organization_id=?", (rfq_id, organization_id)).fetchone()
    if not row:
        raise NotFoundError("استعلام یافت نشد")
    if row["status"] != "open":
        raise ConflictError(f"فقط استعلام باز قابل بستن است (وضعیت: '{row['status']}')")

    now = _now()
    conn.execute("UPDATE rfqs SET status='closed', updated_at=? WHERE id=?", (now, rfq_id))
    _audit(conn, organization_id=organization_id, actor_user_id=actor_user_id,
           event_type="rfq_closed", entity_type="rfq", entity_id=rfq_id)
    return get_rfq(conn, rfq_id, actor_user_id=actor_user_id, organization_id=organization_id)


# ── Supplier Quote Submission ──────────────────────────────────────────────────

def _lookup_standard_vat_rate(conn, today: str) -> int:
    """Resolve the STANDARD VAT rate for a given date from tax_rates table.

    Uses the raw conn so this works inside write_transaction() without Flask app context.
    Always pass the document date (today at submission time), never a hardcoded default.
    Raises ValidationError if no rate found — that would indicate a migration problem.
    """
    row = conn.execute(
        """SELECT rate_bps FROM tax_rates
           WHERE tax_category_id = (SELECT id FROM tax_categories WHERE code = 'STANDARD')
             AND effective_from <= ?
             AND (effective_until IS NULL OR effective_until >= ?)
             AND (jurisdiction IS NULL OR jurisdiction = 'IR')
           ORDER BY effective_from DESC
           LIMIT 1""",
        (today, today),
    ).fetchone()
    if row is None:
        from app.core.errors import ValidationError
        raise ValidationError(f"نرخ مالیات استاندارد برای تاریخ {today} در جدول tax_rates یافت نشد")
    return row["rate_bps"]


def submit_supplier_quote(
    conn,
    rfq_id: int,
    *,
    supplier_id: int,
    items: list[dict],  # [{rfq_item_id, unit_price_minor, quantity, notes}]
    shipping_cost_minor: int = 0,
    payment_terms: str | None = None,
    delivery_lead_days: int | None = None,
    validity_days: int | None = None,
    notes: str | None = None,
    vat_rate_bps: int | None = None,
    # When None (default), the STANDARD rate is looked up from tax_rates for today.
    # Pass an explicit int only when the caller has already resolved the rate
    # (e.g. org is exempt, or a non-standard category applies).
) -> dict:
    rfq_row = conn.execute("SELECT * FROM rfqs WHERE id=?", (rfq_id,)).fetchone()
    if not rfq_row:
        raise NotFoundError("استعلام یافت نشد")
    if rfq_row["status"] != "open":
        raise ConflictError(f"استعلام در وضعیت '{rfq_row['status']}' است — ارائه قیمت ممکن نیست")

    inv_row = conn.execute(
        "SELECT * FROM rfq_suppliers WHERE rfq_id=? AND supplier_id=?",
        (rfq_id, supplier_id),
    ).fetchone()
    if not inv_row:
        raise PermissionError_("این تأمین‌کننده برای این استعلام دعوت نشده است")

    rfq_supplier_id = inv_row["id"]

    if not isinstance(items,list) or not 1 <= len(items) <= 50 or any(not isinstance(i,dict) for i in items):
        raise ValidationError("یک تا ۵۰ ردیف قیمت معتبر لازم است")
    if isinstance(shipping_cost_minor,bool) or not isinstance(shipping_cost_minor,int) or shipping_cost_minor < 0:
        raise ValidationError("هزینه ارسال نمی‌تواند منفی باشد")

    organization_id = rfq_row["organization_id"]
    quote_number = _next_quote_number(conn, organization_id)
    now = _now()

    # Resolve VAT rate: never hardcode; always look up from tax_rates for today.
    if vat_rate_bps is None:
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        vat_rate_bps = _lookup_standard_vat_rate(conn, today)

    # Build items with computed totals
    prepared_items = []
    items_total = 0
    seen_items=set()
    for item in items:
        rfq_item_id = item.get("rfq_item_id")
        unit_price = item.get("unit_price_minor")
        qty = item.get("quantity")
        if isinstance(rfq_item_id,bool) or not isinstance(rfq_item_id,int) or rfq_item_id < 1:
            raise ValidationError("شناسه ردیف استعلام الزامی است")
        if rfq_item_id in seen_items:
            raise ValidationError("ردیف استعلام تکراری است")
        seen_items.add(rfq_item_id)
        if isinstance(unit_price,bool) or not isinstance(unit_price,int) or unit_price < 0:
            raise ValidationError("قیمت واحد نمی‌تواند منفی باشد")
        rfq_item_row = conn.execute(
            "SELECT * FROM rfq_items WHERE id=? AND rfq_id=?", (rfq_item_id, rfq_id)
        ).fetchone()
        if not rfq_item_row:
            raise NotFoundError(f"ردیف استعلام {rfq_item_id} یافت نشد")
        actual_qty = qty if qty is not None else rfq_item_row["quantity_requested"]
        if isinstance(actual_qty,bool) or not isinstance(actual_qty, int) or actual_qty < 1:
            raise ValidationError("تعداد باید عدد صحیح مثبت باشد")
        item_total = unit_price * actual_qty
        # BLOCKER 5: integer floor division — no float arithmetic on money
        vat_amount = (item_total * vat_rate_bps) // 10_000
        prepared_items.append({
            "rfq_item_id": rfq_item_id,
            "unit_price_minor": unit_price,
            "quantity_available": actual_qty,
            "vat_rate_bps": vat_rate_bps,
            "vat_amount_minor": vat_amount,
            "discount_minor": 0,
            "total_minor": item_total,
            "notes": item.get("notes"),
        })
        items_total += item_total

    # Aggregate VAT — integer floor division only, never float arithmetic
    items_vat = sum(pi["vat_amount_minor"] for pi in prepared_items)
    # Shipping VAT uses the same rate as items (one quote = one VAT rate)
    shipping_vat = (shipping_cost_minor * vat_rate_bps) // 10_000
    total_vat = items_vat + shipping_vat
    grand_total = items_total + shipping_cost_minor + total_vat
    if grand_total > 9007199254740991:
        raise ValidationError("مبلغ پیشنهاد بیش از دامنه عدد صحیح قابل نمایش است")

    cur = conn.execute(
        """INSERT INTO supplier_quotes
           (rfq_id, supplier_id, rfq_supplier_id, quote_number, status,
            total_items_minor, shipping_cost_minor, grand_total_minor,
            vat_amount_minor, shipping_vat_minor, shipping_vat_rate_bps,
            payment_terms, delivery_lead_days, validity_days, notes, submitted_at)
           VALUES (?,?,?,?,'submitted',?,?,?,?,?,?,?,?,?,?,?)""",
        (rfq_id, supplier_id, rfq_supplier_id, quote_number,
         items_total, shipping_cost_minor, grand_total,
         items_vat, shipping_vat, vat_rate_bps,
         payment_terms, delivery_lead_days, validity_days, notes, now),
    )
    quote_id = cur.lastrowid

    for item in prepared_items:
        conn.execute(
            """INSERT INTO supplier_quote_items
               (supplier_quote_id, rfq_item_id, unit_price_minor, quantity_available,
                vat_rate_bps, vat_amount_minor, discount_minor, total_minor, notes)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (quote_id, item["rfq_item_id"], item["unit_price_minor"],
             item["quantity_available"], item["vat_rate_bps"], item["vat_amount_minor"],
             item["discount_minor"], item["total_minor"], item["notes"]),
        )

    # Update rfq_suppliers status to responded
    conn.execute(
        "UPDATE rfq_suppliers SET status='responded' WHERE rfq_id=? AND supplier_id=?",
        (rfq_id, supplier_id),
    )

    return get_supplier_quote(conn, quote_id)


def get_supplier_quote(conn, quote_id: int) -> dict:
    row = conn.execute("SELECT * FROM supplier_quotes WHERE id=?", (quote_id,)).fetchone()
    if not row:
        raise NotFoundError("قیمت‌نامه یافت نشد")
    q = _quote_dict(row)
    items = conn.execute(
        "SELECT * FROM supplier_quote_items WHERE supplier_quote_id=? ORDER BY id",
        (quote_id,),
    ).fetchall()
    q["items"] = [_quote_item_dict(i) for i in items]
    return q


def list_supplier_quotes(conn, rfq_id: int, *, actor_user_id: int, organization_id: int) -> list[dict]:
    _assert_org_member(conn, actor_user_id, organization_id)
    row = conn.execute("SELECT * FROM rfqs WHERE id=? AND organization_id=?", (rfq_id, organization_id)).fetchone()
    if not row:
        raise NotFoundError("استعلام یافت نشد")
    quotes = conn.execute(
        "SELECT * FROM supplier_quotes WHERE rfq_id=? ORDER BY grand_total_minor ASC", (rfq_id,)
    ).fetchall()
    result = []
    for q in quotes:
        quote = _quote_dict(q)
        items = conn.execute(
            "SELECT * FROM supplier_quote_items WHERE supplier_quote_id=? ORDER BY id", (q["id"],)
        ).fetchall()
        quote["items"] = [_quote_item_dict(i) for i in items]
        result.append(quote)
    return result


# ── Quote Comparison ───────────────────────────────────────────────────────────

def get_rfq_comparison(conn, rfq_id: int, *, actor_user_id: int, organization_id: int) -> dict:
    _assert_org_member(conn, actor_user_id, organization_id)
    rfq_row = conn.execute(
        "SELECT * FROM rfqs WHERE id=? AND organization_id=?", (rfq_id, organization_id)
    ).fetchone()
    if not rfq_row:
        raise NotFoundError("استعلام یافت نشد")
    if rfq_row["status"] not in ("closed", "open", "awarded"):
        raise ConflictError("مقایسه فقط برای استعلام‌های باز، بسته یا جایزه‌یافته امکان‌پذیر است")

    rfq_items = conn.execute("SELECT ri.*,mp.canonical_name_fa AS product_name_fa FROM rfq_items ri LEFT JOIN master_products mp ON mp.id=ri.master_product_id WHERE ri.rfq_id=? ORDER BY ri.id", (rfq_id,)).fetchall()
    quotes = conn.execute("SELECT * FROM supplier_quotes WHERE rfq_id=? ORDER BY id", (rfq_id,)).fetchall()

    comparison_quotes = []
    for q in quotes:
        q_items = conn.execute(
            "SELECT * FROM supplier_quote_items WHERE supplier_quote_id=? ORDER BY id", (q["id"],)
        ).fetchall()

        # Use server-authoritative stored totals.
        # computed_items_total is re-derived from line items (tamper-proof for items subtotal).
        # computed_grand_total uses the stored grand_total_minor which includes all VAT correctly
        # (VAT was resolved at submission time via tax_rates effective-date lookup).
        computed_items_total = sum(qi["total_minor"] for qi in q_items)
        # grand_total_minor is the AUTHORITATIVE value — includes items VAT + shipping VAT.
        # Fall back to items+shipping (pre-migration 0020 rows) if grand_total_minor not present.
        stored_grand_total = q["grand_total_minor"] or 0
        computed_grand_total = stored_grand_total if stored_grand_total else (
            computed_items_total + (q["shipping_cost_minor"] or 0)
        )

        sup = conn.execute("SELECT display_name FROM suppliers WHERE id=?", (q["supplier_id"],)).fetchone()
        supplier_name = sup["display_name"] if sup else f"تأمین‌کننده {q['supplier_id']}"

        comparison_quotes.append({
            "quote_id": q["id"],
            "quote_number": q["quote_number"],
            "supplier_id": q["supplier_id"],
            "supplier_name": supplier_name,
            "status": q["status"],
            "computed_items_total_minor": computed_items_total,
            "shipping_cost_minor": q["shipping_cost_minor"] or 0,
            "computed_grand_total_minor": computed_grand_total,
            "payment_terms": q["payment_terms"],
            "delivery_lead_days": q["delivery_lead_days"],
            "validity_days": q["validity_days"],
            "submitted_at": q["submitted_at"],
            "items": [_quote_item_dict(qi) for qi in q_items],
        })

    comparison_quotes.sort(key=lambda x: x["computed_grand_total_minor"])
    for rank, cq in enumerate(comparison_quotes, 1):
        cq["rank"] = rank

    return {
        "rfq_id": rfq_id,
        "rfq_number": rfq_row["rfq_number"],
        "rfq_status": rfq_row["status"],
        "rfq_items": [_rfq_item_dict(ri) for ri in rfq_items],
        "quotes": comparison_quotes,
        "total_quotes": len(comparison_quotes),
        "lowest_quote_id": comparison_quotes[0]["quote_id"] if comparison_quotes else None,
    }


# ── Award ──────────────────────────────────────────────────────────────────────

def award_rfq(
    conn,
    rfq_id: int,
    *,
    actor_user_id: int,
    organization_id: int,
    winning_quote_id: int,
    reason: str | None = None,
) -> dict:
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    if not _can_procure(membership):
        raise PermissionError_("دسترسی جایزه دادن استعلام ندارید")

    rfq_row = conn.execute(
        "SELECT * FROM rfqs WHERE id=? AND organization_id=?", (rfq_id, organization_id)
    ).fetchone()
    if not rfq_row:
        raise NotFoundError("استعلام یافت نشد")
    if rfq_row["status"] != "closed":
        raise ConflictError(f"فقط استعلام بسته قابل جایزه دادن است (وضعیت: '{rfq_row['status']}')")

    win_quote = conn.execute(
        "SELECT * FROM supplier_quotes WHERE id=? AND rfq_id=?", (winning_quote_id, rfq_id)
    ).fetchone()
    if not win_quote:
        raise NotFoundError("قیمت‌نامه برنده یافت نشد")
    if win_quote["status"] != "submitted":
        raise ConflictError("قیمت‌نامه برنده باید در وضعیت 'submitted' باشد")

    now = _now()

    conn.execute(
        "UPDATE supplier_quotes SET status='awarded', updated_at=? WHERE id=?",
        (now, winning_quote_id),
    )
    # Mark others as rejected
    conn.execute(
        """UPDATE supplier_quotes SET status='rejected', updated_at=?
           WHERE rfq_id=? AND id!=? AND status='submitted'""",
        (now, rfq_id, winning_quote_id),
    )
    conn.execute("UPDATE rfqs SET status='awarded', updated_at=? WHERE id=?", (now, rfq_id))

    if rfq_row["purchase_request_id"]:
        conn.execute(
            "UPDATE purchase_requests SET status='awarded', updated_at=? WHERE id=?",
            (now, rfq_row["purchase_request_id"]),
        )

    _audit(conn, organization_id=organization_id, actor_user_id=actor_user_id,
           event_type="quote_awarded", entity_type="rfq", entity_id=rfq_id,
           details={"winning_quote_id": winning_quote_id, "reason": reason})

    return {
        "rfq": get_rfq(conn, rfq_id, actor_user_id=actor_user_id, organization_id=organization_id),
        "winning_quote": get_supplier_quote(conn, winning_quote_id),
    }


# ── Supplier-facing ────────────────────────────────────────────────────────────

def list_supplier_invited_rfqs(conn, supplier_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT r.*, rs.status AS supplier_status, rs.invited_at
           FROM rfqs r
           JOIN rfq_suppliers rs ON rs.rfq_id = r.id
           WHERE rs.supplier_id=?
           ORDER BY r.id DESC""",
        (supplier_id,),
    ).fetchall()
    result = []
    for r in rows:
        rfq = _rfq_dict(r)
        rfq["supplier_status"] = r["supplier_status"]
        rfq["invited_at"] = r["invited_at"]
        items = conn.execute("SELECT ri.*,mp.canonical_name_fa AS product_name_fa FROM rfq_items ri LEFT JOIN master_products mp ON mp.id=ri.master_product_id WHERE ri.rfq_id=? ORDER BY ri.id", (r["id"],)).fetchall()
        rfq["items"] = [_rfq_item_dict(i) for i in items]
        result.append(rfq)
    return result
