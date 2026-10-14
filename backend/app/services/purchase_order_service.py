"""Purchase Order Service.

Creates and manages Purchase Orders after RFQ award.

Column names match migration 0005:
  purchase_orders.awarded_supplier_quote_id  (not supplier_quote_id)
  purchase_orders.total_items_minor_snapshot / grand_total_minor_snapshot  (with _snapshot suffix)
  purchase_orders status: 'draft'|'confirmed'|'sent'|'partially_received'|'received'|'cancelled'
  purchase_order_items.unit_price_minor_snapshot / total_minor_snapshot  (with _snapshot suffix)
  purchase_order_items.supplier_quote_item_id  (required)

Key invariant: PO financial values are IMMUTABLE historical snapshots.
"""
from __future__ import annotations

import json

import datetime
from typing import Any

from app.core.errors import ConflictError, PermissionError_, NotFoundError, ValidationError
from app.services.procurement_service import _assert_org_member, _can_procure, _audit, _now


# ── Number generation ──────────────────────────────────────────────────────────

def _next_po_number(conn, organization_id: int) -> str:
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    count = conn.execute(
        "SELECT COUNT(*) FROM purchase_orders WHERE organization_id=?",
        (organization_id,),
    ).fetchone()[0]
    return f"PO-{today}-{count + 1:04d}"


# ── Serialisation ──────────────────────────────────────────────────────────────

def _po_dict(row) -> dict:
    return {
        "id": row["id"],
        "organization_id": row["organization_id"],
        "purchase_request_id": row["purchase_request_id"],
        "rfq_id": row["rfq_id"],
        "supplier_quote_id": row["awarded_supplier_quote_id"],  # alias for API compat
        "supplier_id": row["awarded_supplier_quote_id"],  # placeholder
        "po_number": row["po_number"],
        "status": row["status"],
        "total_amount_minor": row["total_items_minor_snapshot"],
        "shipping_cost_minor": row["shipping_cost_minor_snapshot"],
        "vat_bps": row["vat_amount_minor_snapshot"],  # stored as amount not bps; expose raw
        "vat_amount_minor": row["vat_amount_minor_snapshot"],
        "grand_total_minor": row["grand_total_minor_snapshot"],
        "payment_terms": row["payment_terms_snapshot"],
        "delivery_lead_days": row["delivery_lead_days_snapshot"],
        "delivery_address": row["delivery_address"],
        "notes": None,
        "confirmed_at": row["confirmed_at"],
        "created_by_user_id": row["created_by_user_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _po_dict_full(conn, row) -> dict:
    """Richer po_dict that also infers supplier_id from the quote."""
    po = _po_dict(row)
    # Get supplier_id from the awarded quote
    q = conn.execute(
        "SELECT supplier_id FROM supplier_quotes WHERE id=?",
        (row["awarded_supplier_quote_id"],)
    ).fetchone()
    po["supplier_id"] = q["supplier_id"] if q else None
    return po


def _poi_dict(row) -> dict:
    return {
        "id": row["id"],
        "purchase_order_id": row["purchase_order_id"],
        "rfq_item_id": row["rfq_item_id"],
        "master_product_id": row["master_product_id"],
        "free_text_description": row["free_text_description"],
        "quantity": row["quantity"],
        "unit": row["unit"],
        # IMMUTABLE snapshots
        "unit_price_minor": row["unit_price_minor_snapshot"],
        "total_price_minor": row["total_minor_snapshot"],
        "vat_rate_bps": row["vat_rate_bps_snapshot"],
        "vat_amount_minor": row["vat_amount_minor_snapshot"],
        "discount_minor": row["discount_minor_snapshot"],
    }


# ── Create PO from awarded quote ───────────────────────────────────────────────

def allocation_preview(conn, *, organization_id, actor_user_id, supplier_quote_id):
    membership=_assert_org_member(conn,actor_user_id,organization_id)
    if not _can_procure(membership):raise PermissionError_('دسترسی ایجاد سفارش خرید ندارید')
    quote=conn.execute('SELECT q.*,r.purchase_request_id FROM supplier_quotes q JOIN rfqs r ON r.id=q.rfq_id WHERE q.id=? AND r.organization_id=?',(supplier_quote_id,organization_id)).fetchone()
    if not quote:raise NotFoundError('قیمت‌نامه یافت نشد')
    if quote['status']!='awarded':raise ConflictError('فقط پیشنهاد منتخب قابل سفارش است')
    if not quote['purchase_request_id']:return {'requirements':[],'suggested':[]}
    from app.services.procurement_coverage import allocation_requirements,quote_destinations,proposal
    proposal(conn,quote['purchase_request_id'],supplier_quote_id,orders=True)
    _,requirements=allocation_requirements(conn,quote['purchase_request_id'],supplier_quote_id)
    try:
        destinations=quote_destinations(conn,quote['purchase_request_id'],supplier_quote_id)
        suggested=[{'purchase_request_item_id':r['purchase_request_item_id'],'destination_index':i,'quantity':a['quantity']} for i,d in enumerate(destinations) for a in d['allocations'] for r in requirements if r['item_index']==a['item_index']]
    except ConflictError as e:
        if e.code!='partial_destination_allocation_required':raise
        suggested=None
    return {'requirements':requirements,'suggested':suggested}

def create_purchase_order(
    conn,
    *,
    organization_id: int,
    actor_user_id: int,
    supplier_quote_id: int,
    delivery_address: str | None = None,
    notes: str | None = None,
    vat_bps: int | None = None,  # DEPRECATED: ignored; VAT is copied from the quote snapshot
    destination_allocations: list | None = None,
) -> dict:
    """
    Create a PO from an awarded supplier quote.
    All financial values are IMMUTABLE snapshots copied from the quote at this moment.
    Future price changes must NOT affect this PO.
    """
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    if not _can_procure(membership):
        raise PermissionError_("دسترسی ایجاد سفارش خرید ندارید")

    quote_row = conn.execute(
        "SELECT * FROM supplier_quotes WHERE id=?", (supplier_quote_id,)
    ).fetchone()
    if not quote_row:
        raise NotFoundError("قیمت‌نامه یافت نشد")
    if quote_row["status"] != "awarded":
        raise ConflictError("فقط قیمت‌نامه‌های برنده می‌توانند به سفارش خرید تبدیل شوند")

    rfq_id = quote_row["rfq_id"]
    rfq_row = conn.execute(
        "SELECT * FROM rfqs WHERE id=? AND organization_id=?", (rfq_id, organization_id)
    ).fetchone()
    if not rfq_row:
        raise PermissionError_("استعلام در این سازمان یافت نشد")

    existing_po = conn.execute(
        "SELECT id FROM purchase_orders WHERE awarded_supplier_quote_id=?", (supplier_quote_id,)
    ).fetchone()
    if existing_po:
        raise ConflictError("سفارش خرید برای این قیمت‌نامه قبلاً ایجاد شده است")

    pr_row = conn.execute("SELECT destinations_json FROM purchase_requests WHERE id=?", (rfq_row["purchase_request_id"],)).fetchone() \
        if rfq_row["purchase_request_id"] else None
    if pr_row and pr_row["destinations_json"]:
        from app.services.procurement_service import unallocated
        items = [dict(r) for r in conn.execute("SELECT quantity FROM purchase_request_items WHERE purchase_request_id=? ORDER BY id",
                                               (rfq_row["purchase_request_id"],))]
        missing = unallocated(json.loads(pr_row["destinations_json"]), items)
        if missing:
            raise ConflictError("تخصیص مقصد برخی اقلام ناقص است؛ پیش از صدور سفارش مقصد همه مقادیر را مشخص کنید",
                                code="destinations_incomplete", details={"unallocated": missing})

    # Load quote items — SNAPSHOT
    quote_items = conn.execute(
        """SELECT qi.*, ri.master_product_id, ri.free_text_description, ri.unit,
                  ri.quantity_requested as rfq_quantity
           FROM supplier_quote_items qi
           JOIN rfq_items ri ON ri.id = qi.rfq_item_id
           WHERE qi.supplier_quote_id=? ORDER BY qi.id""",
        (supplier_quote_id,),
    ).fetchall()

    if not quote_items:
        raise ValidationError("قیمت‌نامه هیچ ردیفی ندارد")

    from app.services.product_channel_policy import require_master
    for qi in quote_items:require_master(conn,qi["master_product_id"],"organization")
    destination_snapshot=None
    if rfq_row['purchase_request_id']:
        from app.services.procurement_coverage import proposal,quote_destinations
        proposal(conn,rfq_row['purchase_request_id'],supplier_quote_id,orders=True)
        destination_snapshot=json.dumps(quote_destinations(conn,rfq_row['purchase_request_id'],supplier_quote_id,destination_allocations),ensure_ascii=False)

    # Financial snapshot: copy from the AUTHORITATIVE quote values, never recompute.
    # quote.grand_total_minor was set at submission time with correct VAT (items + shipping VAT).
    # Recomputing here would re-introduce the bug and break the Quote == PO invariant.
    items_total    = sum(qi["total_minor"] for qi in quote_items)
    shipping_cost  = quote_row["shipping_cost_minor"] or 0
    discount_total = sum(qi["discount_minor"] for qi in quote_items)

    # vat_amount_minor column added by migration 0020; default to items-VAT sum for pre-migration rows.
    quote_keys = quote_row.keys() if hasattr(quote_row, "keys") else []
    if "vat_amount_minor" in quote_keys and quote_row["vat_amount_minor"] is not None:
        vat_amount = quote_row["vat_amount_minor"]
    else:
        # Pre-migration 0020 fallback: sum per-item VAT (shipping VAT was zero before the patch)
        vat_amount = sum(qi["vat_amount_minor"] for qi in quote_items)

    # AUTHORITATIVE grand_total: always copy from quote, never recompute.
    # This is the Quote == PO invariant: PO.grand_total_minor_snapshot == Quote.grand_total_minor.
    grand_total = quote_row["grand_total_minor"]

    po_number = _next_po_number(conn, organization_id)

    cur = conn.execute(
        """INSERT INTO purchase_orders
           (organization_id, purchase_request_id, rfq_id, awarded_supplier_quote_id,
            created_by_user_id, po_number, status,
            total_items_minor_snapshot, shipping_cost_minor_snapshot,
            discount_minor_snapshot, vat_amount_minor_snapshot, grand_total_minor_snapshot,
            payment_terms_snapshot, delivery_lead_days_snapshot,
            delivery_address)
           VALUES (?,?,?,?,?,?,'draft',?,?,?,?,?,?,?,?)""",
        (
            organization_id,
            rfq_row["purchase_request_id"],
            rfq_id,
            supplier_quote_id,
            actor_user_id,
            po_number,
            items_total,
            shipping_cost,
            discount_total,
            vat_amount,
            grand_total,
            quote_row["payment_terms"],
            quote_row["delivery_lead_days"],
            delivery_address,
        ),
    )
    po_id = cur.lastrowid
    conn.execute('UPDATE purchase_orders SET destinations_json_snapshot=? WHERE id=?',(destination_snapshot,po_id))

    # Insert IMMUTABLE line items
    for qi in quote_items:
        conn.execute(
            """INSERT INTO purchase_order_items
               (purchase_order_id, rfq_item_id, supplier_id, supplier_quote_item_id,
                master_product_id, free_text_description, quantity, unit,
                unit_price_minor_snapshot, vat_rate_bps_snapshot,
                vat_amount_minor_snapshot, discount_minor_snapshot, total_minor_snapshot)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                po_id,
                qi["rfq_item_id"],
                quote_row["supplier_id"],
                qi["id"],
                qi["master_product_id"],
                qi["free_text_description"],
                qi["quantity_available"],
                qi["unit"],
                qi["unit_price_minor"],       # SNAPSHOT — immutable
                qi["vat_rate_bps"],
                qi["vat_amount_minor"],
                qi["discount_minor"],
                qi["total_minor"],            # SNAPSHOT — immutable
            ),
        )

    _audit(conn, organization_id=organization_id, actor_user_id=actor_user_id,
           event_type="pr_created", entity_type="purchase_order", entity_id=po_id,
           details={"po_number": po_number, "grand_total_minor": grand_total,
                    "supplier_quote_id": supplier_quote_id,"destinations":json.loads(destination_snapshot) if destination_snapshot is not None else None})

    return get_purchase_order(conn, po_id, actor_user_id=actor_user_id, organization_id=organization_id)


def get_purchase_order(conn, po_id: int, *, actor_user_id: int, organization_id: int) -> dict:
    _assert_org_member(conn, actor_user_id, organization_id)
    row = conn.execute(
        "SELECT * FROM purchase_orders WHERE id=? AND organization_id=?",
        (po_id, organization_id),
    ).fetchone()
    if not row:
        raise NotFoundError("سفارش خرید یافت نشد")
    po = _po_dict_full(conn, row)
    items = conn.execute(
        "SELECT * FROM purchase_order_items WHERE purchase_order_id=? ORDER BY id",
        (po_id,),
    ).fetchall()
    po["items"] = [_poi_dict(i) for i in items]
    return po


def list_purchase_orders(
    conn,
    *,
    organization_id: int,
    actor_user_id: int,
    status: str | None = None,
    supplier_id: int | None = None,
) -> list[dict]:
    _assert_org_member(conn, actor_user_id, organization_id)
    where = ["po.organization_id=?"]
    params: list = [organization_id]
    if status:
        where.append("po.status=?")
        params.append(status)
    if supplier_id:
        where.append("sq.supplier_id=?")
        params.append(supplier_id)
    rows = conn.execute(
        f"""SELECT po.* FROM purchase_orders po
            JOIN supplier_quotes sq ON sq.id = po.awarded_supplier_quote_id
            WHERE {' AND '.join(where)} ORDER BY po.id DESC""",
        params,
    ).fetchall()
    result = []
    for r in rows:
        po = _po_dict_full(conn, r)
        items = conn.execute(
            "SELECT * FROM purchase_order_items WHERE purchase_order_id=? ORDER BY id",
            (r["id"],),
        ).fetchall()
        po["items"] = [_poi_dict(i) for i in items]
        result.append(po)
    return result


# ── State transitions ──────────────────────────────────────────────────────────
# Actual status machine per migration: draft → confirmed → sent → received / cancelled

def confirm_purchase_order(conn, po_id: int, *, actor_user_id: int, organization_id: int) -> dict:
    """draft → confirmed"""
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    if not _can_procure(membership):
        raise PermissionError_("دسترسی تأیید سفارش خرید ندارید")
    row = conn.execute(
        "SELECT * FROM purchase_orders WHERE id=? AND organization_id=?", (po_id, organization_id)
    ).fetchone()
    if not row:
        raise NotFoundError("سفارش خرید یافت نشد")
    if row["status"] != "draft":
        raise ConflictError(f"وضعیت فعلی '{row['status']}' — انتظار 'draft'")
    from app.services.product_channel_policy import require_references
    require_references(conn,"purchase_order_items","purchase_order_id",po_id)
    now = _now()
    conn.execute(
        "UPDATE purchase_orders SET status='confirmed', confirmed_at=?, updated_at=? WHERE id=?",
        (now, now, po_id),
    )
    _audit(conn, organization_id=organization_id, actor_user_id=actor_user_id,
           event_type="pr_approved", entity_type="purchase_order", entity_id=po_id)
    return get_purchase_order(conn, po_id, actor_user_id=actor_user_id, organization_id=organization_id)


def send_purchase_order(conn, po_id: int, *, actor_user_id: int, organization_id: int) -> dict:
    """confirmed → sent"""
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    if not _can_procure(membership):
        raise PermissionError_("دسترسی ارسال سفارش خرید ندارید")
    row = conn.execute(
        "SELECT * FROM purchase_orders WHERE id=? AND organization_id=?", (po_id, organization_id)
    ).fetchone()
    if not row:
        raise NotFoundError("سفارش خرید یافت نشد")
    if row["status"] != "confirmed":
        raise ConflictError(f"وضعیت فعلی '{row['status']}' — انتظار 'confirmed'")
    now = _now()
    conn.execute("UPDATE purchase_orders SET status='sent', updated_at=? WHERE id=?", (now, po_id))
    _audit(conn, organization_id=organization_id, actor_user_id=actor_user_id,
           event_type="pr_submitted", entity_type="purchase_order", entity_id=po_id)
    return get_purchase_order(conn, po_id, actor_user_id=actor_user_id, organization_id=organization_id)


def acknowledge_purchase_order(conn, po_id: int, *, actor_user_id: int, organization_id: int) -> dict:
    """sent → partially_received (as 'acknowledged')"""
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    if not _can_procure(membership):
        raise PermissionError_("دسترسی دریافت سفارش خرید ندارید")
    row = conn.execute(
        "SELECT * FROM purchase_orders WHERE id=? AND organization_id=?", (po_id, organization_id)
    ).fetchone()
    if not row:
        raise NotFoundError("سفارش خرید یافت نشد")
    if row["status"] != "sent":
        raise ConflictError(f"وضعیت فعلی '{row['status']}' — انتظار 'sent'")
    now = _now()
    conn.execute(
        "UPDATE purchase_orders SET status='partially_received', updated_at=? WHERE id=?",
        (now, po_id),
    )
    return get_purchase_order(conn, po_id, actor_user_id=actor_user_id, organization_id=organization_id)


def complete_purchase_order(conn, po_id: int, *, actor_user_id: int, organization_id: int) -> dict:
    """partially_received → received (complete). Updates PR to completed."""
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    if not _can_procure(membership):
        raise PermissionError_("دسترسی تکمیل سفارش خرید ندارید")
    row = conn.execute(
        "SELECT * FROM purchase_orders WHERE id=? AND organization_id=?", (po_id, organization_id)
    ).fetchone()
    if not row:
        raise NotFoundError("سفارش خرید یافت نشد")
    if row["status"] != "partially_received":
        raise ConflictError(f"وضعیت فعلی '{row['status']}' — انتظار 'partially_received'")
    now = _now()
    conn.execute(
        "UPDATE purchase_orders SET status='received', updated_at=? WHERE id=?", (now, po_id)
    )
    # Update PR to completed
    if row["purchase_request_id"]:
        conn.execute(
            "UPDATE purchase_requests SET status='completed', updated_at=? WHERE id=?",
            (now, row["purchase_request_id"]),
        )
    _audit(conn, organization_id=organization_id, actor_user_id=actor_user_id,
           event_type="pr_cancelled", entity_type="purchase_order", entity_id=po_id)
    return get_purchase_order(conn, po_id, actor_user_id=actor_user_id, organization_id=organization_id)


def cancel_purchase_order(
    conn, po_id: int, *, actor_user_id: int, organization_id: int, reason: str | None = None
) -> dict:
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    if not _can_procure(membership):
        raise PermissionError_("دسترسی لغو سفارش خرید ندارید")
    row = conn.execute(
        "SELECT * FROM purchase_orders WHERE id=? AND organization_id=?", (po_id, organization_id)
    ).fetchone()
    if not row:
        raise NotFoundError("سفارش خرید یافت نشد")
    if row["status"] in ("received", "cancelled"):
        raise ConflictError(f"سفارش در وضعیت '{row['status']}' قابل لغو نیست")
    now = _now()
    conn.execute(
        "UPDATE purchase_orders SET status='cancelled', updated_at=? WHERE id=?", (now, po_id)
    )
    _audit(conn, organization_id=organization_id, actor_user_id=actor_user_id,
           event_type="pr_cancelled", entity_type="purchase_order", entity_id=po_id,
           details={"reason": reason})
    return get_purchase_order(conn, po_id, actor_user_id=actor_user_id, organization_id=organization_id)
