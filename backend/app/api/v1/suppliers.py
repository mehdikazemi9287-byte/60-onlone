"""Supplier Portal API + Admin Supplier Management.

URL structure:
  /api/v1/supplier/...                  — Supplier self-service (role=supplier)
  /api/v1/admin/suppliers/...           — Admin CRUD (role=admin)

Supplier isolation: every supplier endpoint resolves the logged-in user's
supplier record and uses only THAT supplier_id. A supplier can never touch
another supplier's data — this is enforced by `get_supplier_for_user()` +
FK-checked queries in the service layer.
"""

from __future__ import annotations

import json

from flask import Blueprint, g, jsonify, request

from app.core.deps import get_db, require_auth
from app.core.errors import NotFoundError, ValidationError
from app.services import fulfillment_service, supplier_catalog_import_service, supplier_service

bp = Blueprint("suppliers", __name__)


# =========================================================================
# Helpers
# =========================================================================


def _get_supplier_or_404(user_id: int, db) -> dict:
    """Resolve the supplier for the authenticated user. 404 if none."""
    with db.read_transaction() as conn:
        sup = fulfillment_service.get_supplier_for_user(conn, user_id)
    if sup is None:
        raise NotFoundError(
            "حساب تأمین‌کننده یافت نشد. با پشتیبان تماس بگیرید.",
            code="supplier_not_linked",
        )
    return sup


def _int(val, name: str) -> int:
    import re
    if type(val) is int:
        result = val
    elif isinstance(val, str) and re.fullmatch(r"[+-]?\d+", val.strip()):
        try:
            result = int(val.strip())
        except ValueError:
            raise ValidationError(f"مقدار «{name}» باید عدد صحیح معتبر باشد")
    else:
        raise ValidationError(f"مقدار «{name}» باید عدد صحیح باشد")
    if not -9223372036854775808 <= result <= 9223372036854775807:
        raise ValidationError(f"مقدار «{name}» خارج از محدودهٔ عدد صحیح است")
    return result


def _bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return bool(val)
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return False


# =========================================================================
# SUPPLIER PORTAL — /api/v1/supplier/*
# =========================================================================


@bp.get("/api/v1/supplier/me")
@require_auth("supplier")
def supplier_me():
    """Supplier profile."""
    db = get_db()
    sup = _get_supplier_or_404(g.current_user["id"], db)
    with db.read_transaction() as conn:
        locs = supplier_service.list_locations(conn, supplier_id=sup["id"])
    return jsonify({"supplier": sup, "locations": locs})


@bp.get("/api/v1/supplier/orders")
@require_auth("supplier")
def supplier_orders():
    db = get_db()
    sup = _get_supplier_or_404(g.current_user["id"], db)
    status = request.args.get("status")
    limit = min(int(request.args.get("limit", "50")), 100)
    offset = int(request.args.get("offset", "0"))
    with db.read_transaction() as conn:
        orders = fulfillment_service.list_fulfillment_orders_for_supplier(
            conn, supplier_id=sup["id"], status=status, limit=limit, offset=offset
        )
    return jsonify({"fulfillment_orders": orders})


@bp.get("/api/v1/supplier/orders/<int:fo_id>")
@require_auth("supplier")
def supplier_order_detail(fo_id: int):
    db = get_db()
    sup = _get_supplier_or_404(g.current_user["id"], db)
    with db.read_transaction() as conn:
        # Security: ensure supplier owns this FO
        row = conn.execute(
            "SELECT supplier_id FROM fulfillment_orders WHERE id = ?", (fo_id,)
        ).fetchone()
        if row is None or int(row["supplier_id"]) != sup["id"]:
            raise NotFoundError("سفارش تأمین یافت نشد")
        fo = fulfillment_service.read_fulfillment_order(conn, fo_id=fo_id)
    return jsonify({"fulfillment_order": fo})


@bp.post("/api/v1/supplier/orders/<int:fo_id>/accept")
@require_auth("supplier")
def supplier_accept_order(fo_id: int):
    db = get_db()
    sup = _get_supplier_or_404(g.current_user["id"], db)
    with db.write_transaction() as conn:
        fulfillment_service.supplier_accept(
            conn,
            fulfillment_order_id=fo_id,
            supplier_id=sup["id"],
            actor_user_id=g.current_user["id"],
        )
        fo = fulfillment_service.read_fulfillment_order(conn, fo_id=fo_id)
    return jsonify({"fulfillment_order": fo})


@bp.post("/api/v1/supplier/orders/<int:fo_id>/reject")
@require_auth("supplier")
def supplier_reject_order(fo_id: int):
    db = get_db()
    sup = _get_supplier_or_404(g.current_user["id"], db)
    body = request.get_json(silent=True) or {}
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise ValidationError("دلیل رد الزامی است")
    with db.write_transaction() as conn:
        fulfillment_service.supplier_reject(
            conn,
            fulfillment_order_id=fo_id,
            supplier_id=sup["id"],
            reason=reason,
            actor_user_id=g.current_user["id"],
        )
        fo = fulfillment_service.read_fulfillment_order(conn, fo_id=fo_id)
    return jsonify({"fulfillment_order": fo})


@bp.post("/api/v1/supplier/orders/<int:fo_id>/prepare")
@require_auth("supplier")
def supplier_prepare_order(fo_id: int):
    db = get_db()
    sup = _get_supplier_or_404(g.current_user["id"], db)
    with db.write_transaction() as conn:
        fulfillment_service.supplier_start_preparing(
            conn,
            fulfillment_order_id=fo_id,
            supplier_id=sup["id"],
            actor_user_id=g.current_user["id"],
        )
        fo = fulfillment_service.read_fulfillment_order(conn, fo_id=fo_id)
    return jsonify({"fulfillment_order": fo})


@bp.post("/api/v1/supplier/orders/<int:fo_id>/ready")
@require_auth("supplier")
def supplier_ready_order(fo_id: int):
    db = get_db()
    sup = _get_supplier_or_404(g.current_user["id"], db)
    with db.write_transaction() as conn:
        fulfillment_service.supplier_mark_ready(
            conn,
            fulfillment_order_id=fo_id,
            supplier_id=sup["id"],
            actor_user_id=g.current_user["id"],
        )
        fo = fulfillment_service.read_fulfillment_order(conn, fo_id=fo_id)
    return jsonify({"fulfillment_order": fo})


@bp.post("/api/v1/supplier/orders/<int:fo_id>/dispatch")
@require_auth("supplier")
def supplier_dispatch_order(fo_id: int):
    db = get_db()
    sup = _get_supplier_or_404(g.current_user["id"], db)
    with db.write_transaction() as conn:
        fulfillment_service.supplier_mark_dispatched(
            conn,
            fulfillment_order_id=fo_id,
            supplier_id=sup["id"],
            actor_user_id=g.current_user["id"],
        )
        fo = fulfillment_service.read_fulfillment_order(conn, fo_id=fo_id)
    return jsonify({"fulfillment_order": fo})


@bp.post("/api/v1/supplier/orders/<int:fo_id>/deliver")
@require_auth("supplier")
def supplier_deliver_order(fo_id: int):
    db = get_db()
    sup = _get_supplier_or_404(g.current_user["id"], db)
    with db.write_transaction() as conn:
        fulfillment_service.supplier_mark_delivered(
            conn,
            fulfillment_order_id=fo_id,
            supplier_id=sup["id"],
            actor_user_id=g.current_user["id"],
        )
        fo = fulfillment_service.read_fulfillment_order(conn, fo_id=fo_id)
    return jsonify({"fulfillment_order": fo})


# ---- Offer management -------------------------------------------------------


@bp.get("/api/v1/supplier/offers")
@require_auth("supplier")
def supplier_offers():
    db = get_db()
    sup = _get_supplier_or_404(g.current_user["id"], db)
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    if limit is None or offset is None or not 1 <= limit <= 100 or offset < 0:
        raise ValidationError("صفحه‌بندی نامعتبر است")
    with db.read_transaction() as conn:
        offers = supplier_service.list_offers(
            conn, supplier_id=sup["id"], limit=limit, offset=offset
        )
    return jsonify({"offers": offers})


@bp.patch("/api/v1/supplier/offers/<int:offer_id>/stock")
@require_auth("supplier")
def supplier_update_stock(offer_id: int):
    db = get_db()
    sup = _get_supplier_or_404(g.current_user["id"], db)
    body = request.get_json(silent=True) or {}
    qty = _int(body.get("stock_quantity"), "stock_quantity")
    with db.write_transaction() as conn:
        offer = supplier_service.update_offer_stock(
            conn, offer_id=offer_id, supplier_id=sup["id"], stock_quantity=qty
        )
    return jsonify({"offer": offer})


@bp.patch("/api/v1/supplier/offers/<int:offer_id>/price")
@require_auth("supplier")
def supplier_update_price(offer_id: int):
    db = get_db()
    sup = _get_supplier_or_404(g.current_user["id"], db)
    body = request.get_json(silent=True) or {}
    price = _int(body.get("selling_price_minor"), "selling_price_minor")
    with db.write_transaction() as conn:
        offer = supplier_service.update_offer_price(
            conn, offer_id=offer_id, supplier_id=sup["id"], selling_price_minor=price
        )
    return jsonify({"offer": offer})


# ---- Catalog bulk import ----------------------------------------------------


@bp.post("/api/v1/supplier/catalog/import")
@require_auth("supplier")
def supplier_catalog_import():
    """Supplier submits a batch of catalog rows (manual entry or parsed from
    an uploaded CSV/Excel file client-side — this endpoint takes the parsed
    JSON rows either way, so it's the same entry point a future direct
    file-upload or ERP/API connector could reuse).

    Every row is matched against the REAL existing catalog by barcode or
    supplier SKU. A row that cannot be matched is queued for human review —
    it never creates a new product."""
    db = get_db()
    sup = _get_supplier_or_404(g.current_user["id"], db)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("بدنه درخواست باید یک شیء باشد")
    location_id = _int(body.get("supplier_location_id"), "supplier_location_id")
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise ValidationError("rows باید آرایه‌ای از ردیف‌ها باشد")
    with db.write_transaction() as conn:
        summary = supplier_catalog_import_service.import_catalog_batch(
            conn,
            supplier_id=sup["id"],
            supplier_location_id=location_id,
            submitted_by_user_id=g.current_user["id"],
            rows=rows,
        )
        from app.services import catalog_structure_service
        summary["structure"] = catalog_structure_service.apply(conn, create_skus=False)  # new variants → families + hidden SKUs
    return jsonify(summary), 201


# =========================================================================
# ADMIN — /api/v1/admin/suppliers/*
# =========================================================================


@bp.post("/api/v1/admin/suppliers")
@require_auth("admin")
def admin_create_supplier():
    db = get_db()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("بدنه درخواست باید شیء باشد")
    with db.write_transaction() as conn:
        from app.api.v1.admin_content import assert_admin
        from app.api.v1.admin_supplier_profile import audit
        assert_admin(conn)
        for field in ("legal_name", "display_name", "national_id", "supplier_type", "status"):
            if field in body and not isinstance(body[field], str):
                raise ValidationError("متن مشخصات تأمین‌کننده نامعتبر است")
        for field in ("phone", "email", "bank_name", "bank_account", "sheba", "notes"):
            if body.get(field) is not None and not isinstance(body[field], str):
                raise ValidationError("اطلاعات تماس یا منبع نامعتبر است")
        rating = body.get("rating_x10", 0)
        if type(rating) is not int:
            raise ValidationError("امتیاز باید عدد صحیح باشد")
        sup = supplier_service.create_supplier(
            conn,
            legal_name=body.get("legal_name", ""),
            display_name=body.get("display_name", ""),
            national_id=body.get("national_id", ""),
            supplier_type=body.get("supplier_type", "retailer"),
            status=body.get("status", "pending"),
            phone=body.get("phone"),
            email=body.get("email"),
            bank_name=body.get("bank_name"),
            bank_account=body.get("bank_account"),
            sheba=body.get("sheba"),
            rating_x10=int(body.get("rating_x10", 0)),
            user_id=body.get("user_id"),
            notes=body.get("notes"),
        )
        audit(conn, sup["id"], "supplier.created", None, sup, body.get("notes") or "منبع در فراخوان قبلی ثبت نشده است")
    return jsonify({"supplier": sup}), 201


@bp.get("/api/v1/admin/suppliers")
@require_auth("admin")
def admin_list_suppliers():
    db = get_db()
    status = request.args.get("status")
    stype = request.args.get("supplier_type")
    limit = min(int(request.args.get("limit", "50")), 200)
    offset = int(request.args.get("offset", "0"))
    with db.read_transaction() as conn:
        suppliers = supplier_service.list_suppliers(
            conn, status=status, supplier_type=stype, limit=limit, offset=offset
        )
    return jsonify({"suppliers": suppliers})


@bp.get("/api/v1/admin/suppliers/<int:supplier_id>")
@require_auth("admin")
def admin_get_supplier(supplier_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        sup = supplier_service.get_supplier(conn, supplier_id=supplier_id)
        locs = supplier_service.list_locations(conn, supplier_id=supplier_id)
        offers = supplier_service.list_offers(conn, supplier_id=supplier_id)
    return jsonify({"supplier": sup, "locations": locs, "offers": offers})


@bp.patch("/api/v1/admin/suppliers/<int:supplier_id>/status")
@require_auth("admin")
def admin_update_supplier_status(supplier_id: int):
    db = get_db()
    body = request.get_json(silent=True) or {}
    with db.write_transaction() as conn:
        from app.api.v1.admin_content import assert_admin
        from app.api.v1.admin_supplier_profile import audit
        assert_admin(conn)
        before = supplier_service.get_supplier(conn, supplier_id=supplier_id)
        sup = supplier_service.update_supplier_status(
            conn, supplier_id=supplier_id, status=body.get("status", "")
        )
        if before != sup:
            audit(conn, supplier_id, "supplier.status_updated", before, sup, body.get("reason"))
    return jsonify({"supplier": sup})


@bp.post("/api/v1/admin/suppliers/<int:supplier_id>/onboarding/advance")
@require_auth("admin")
def admin_advance_onboarding(supplier_id: int):
    """Advance a supplier's onboarding lifecycle (draft -> submitted ->
    under_review -> approved | rejected). Every transition is recorded in
    supplier_onboarding_events. Reaching 'approved' also sets the supplier's
    operational status to 'active' — everything else about the pre-existing
    active/suspended/inactive status field is untouched by this endpoint."""
    db = get_db()
    body = request.get_json(silent=True) or {}
    with db.write_transaction() as conn:
        sup = supplier_service.advance_onboarding_stage(
            conn,
            supplier_id=supplier_id,
            to_stage=body.get("to_stage", ""),
            actor_user_id=g.current_user["id"],
            note=body.get("note"),
        )
    return jsonify({"supplier": sup})


@bp.get("/api/v1/admin/suppliers/<int:supplier_id>/onboarding/events")
@require_auth("admin")
def admin_onboarding_events(supplier_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        events = supplier_service.list_onboarding_events(conn, supplier_id=supplier_id)
    return jsonify({"events": events})


@bp.patch("/api/v1/admin/suppliers/<int:supplier_id>/user")
@require_auth("admin")
def admin_link_supplier_user(supplier_id: int):
    """Link a users.id to a supplier so they can use the portal."""
    db = get_db()
    body = request.get_json(silent=True) or {}
    if "user_id" not in body:
        raise ValidationError("فیلد «user_id» الزامی است (برای قطع اتصال، مقدار null را صریحاً ارسال کنید)")
    user_id = body.get("user_id")
    with db.write_transaction() as conn:
        if not conn.execute("SELECT 1 FROM suppliers WHERE id = ?", (supplier_id,)).fetchone():
            raise NotFoundError("تأمین‌کننده یافت نشد")
        # Verify user exists
        if user_id is not None:
            row = conn.execute("SELECT id, role FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise NotFoundError("کاربر یافت نشد")
            # Ensure user has supplier role
            if row["role"] not in ("supplier", "admin"):
                conn.execute("UPDATE users SET role = 'supplier' WHERE id = ?", (user_id,))
        conn.execute(
            "UPDATE suppliers SET user_id = ?, updated_at = datetime('now') WHERE id = ?",
            (user_id, supplier_id),
        )
        if user_id is not None:
            conn.execute("""INSERT INTO supplier_users (supplier_id, user_id, role, status) VALUES (?,?,'owner','active')
                            ON CONFLICT(supplier_id, user_id) DO UPDATE SET role='owner', status='active'""",
                         (supplier_id, user_id))
        sup = supplier_service.get_supplier(conn, supplier_id=supplier_id)
    return jsonify({"supplier": sup})


# ---- Admin Locations -------------------------------------------------------


@bp.post("/api/v1/admin/suppliers/<int:supplier_id>/locations")
@require_auth("admin")
def admin_create_location(supplier_id: int):
    db = get_db()
    body = request.get_json(silent=True) or {}
    with db.write_transaction() as conn:
        loc = supplier_service.create_location(
            conn,
            supplier_id=supplier_id,
            province=body.get("province", ""),
            city=body.get("city", ""),
            district=body.get("district"),
            address=body.get("address"),
            latitude=body.get("latitude"),
            longitude=body.get("longitude"),
            status=body.get("status", "active"),
            can_pickup=_bool(body.get("can_pickup", False)),
            can_local_delivery=_bool(body.get("can_local_delivery", True)),
            can_intercity_shipping=_bool(body.get("can_intercity_shipping", False)),
            service_radius_km=body.get("service_radius_km"),
            operating_hours_json=(
                json.dumps(body["operating_hours"]) if "operating_hours" in body else None
            ),
            prep_time_minutes=int(body.get("prep_time_minutes", 60)),
        )
    return jsonify({"location": loc}), 201


@bp.get("/api/v1/admin/suppliers/<int:supplier_id>/locations")
@require_auth("admin")
def admin_list_locations(supplier_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        locs = supplier_service.list_locations(conn, supplier_id=supplier_id)
    return jsonify({"locations": locs})


@bp.patch("/api/v1/admin/locations/<int:location_id>/status")
@require_auth("admin")
def admin_update_location_status(location_id: int):
    db = get_db()
    body = request.get_json(silent=True) or {}
    with db.write_transaction() as conn:
        loc = supplier_service.update_location_status(
            conn, location_id=location_id, status=body.get("status", "")
        )
    return jsonify({"location": loc})


# ---- Admin Offers ----------------------------------------------------------


@bp.post("/api/v1/admin/offers")
@require_auth("admin")
def admin_create_offer():
    db = get_db()
    body = request.get_json(silent=True) or {}
    with db.write_transaction() as conn:
        offer = supplier_service.create_offer(
            conn,
            product_id=_int(body.get("product_id"), "product_id"),
            supplier_id=_int(body.get("supplier_id"), "supplier_id"),
            supplier_location_id=_int(body.get("supplier_location_id"), "supplier_location_id"),
            selling_price_minor=_int(body.get("selling_price_minor"), "selling_price_minor"),
            stock_quantity=_int(body.get("stock_quantity", 0), "stock_quantity"),
            supplier_sku=body.get("supplier_sku"),
            cost_price_minor=(
                int(body["cost_price_minor"])
                if "cost_price_minor" in body and body["cost_price_minor"] is not None
                else None
            ),
            status=body.get("status", "active"),
            min_order_quantity=int(body.get("min_order_quantity", 1)),
            fulfillment_type=body.get("fulfillment_type", "delivery"),
            prep_time_minutes=(
                int(body["prep_time_minutes"])
                if "prep_time_minutes" in body and body["prep_time_minutes"] is not None
                else None
            ),
            shipping_days=(
                int(body["shipping_days"])
                if "shipping_days" in body and body["shipping_days"] is not None
                else None
            ),
        )
    return jsonify({"offer": offer}), 201


@bp.get("/api/v1/admin/offers")
@require_auth("admin")
def admin_list_offers():
    db = get_db()
    supplier_id = request.args.get("supplier_id", type=int)
    product_id = request.args.get("product_id", type=int)
    status = request.args.get("status")
    limit = min(int(request.args.get("limit", "100")), 500)
    offset = int(request.args.get("offset", "0"))
    with db.read_transaction() as conn:
        offers = supplier_service.list_offers(
            conn,
            supplier_id=supplier_id,
            product_id=product_id,
            status=status,
            limit=limit,
            offset=offset,
        )
    return jsonify({"offers": offers})


# ---- Admin Fulfillment Orders / Routing Exceptions -------------------------


@bp.get("/api/v1/admin/fulfillment-orders")
@require_auth("admin")
def admin_list_fulfillment_orders():
    db = get_db()
    status = request.args.get("status")
    supplier_id = request.args.get("supplier_id", type=int)
    limit = min(int(request.args.get("limit", "50")), 200)
    offset = int(request.args.get("offset", "0"))
    with db.read_transaction() as conn:
        sql = """
            SELECT fo.*, o.order_number, s.display_name AS supplier_name,
                   sl.city, sl.province
            FROM fulfillment_orders fo
            JOIN orders             o  ON o.id  = fo.order_id
            JOIN suppliers          s  ON s.id  = fo.supplier_id
            JOIN supplier_locations sl ON sl.id = fo.supplier_location_id
            WHERE 1=1
        """
        params: list = []
        if status:
            sql += " AND fo.status = ?"
            params.append(status)
        if supplier_id:
            sql += " AND fo.supplier_id = ?"
            params.append(supplier_id)
        sql += " ORDER BY fo.created_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    return jsonify({"fulfillment_orders": rows})


@bp.get("/api/v1/admin/fulfillment-orders/<int:fo_id>")
@require_auth("admin")
def admin_get_fulfillment_order(fo_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        fo = fulfillment_service.read_fulfillment_order(conn, fo_id=fo_id)
        audit = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM routing_audit WHERE fulfillment_order_id = ? ORDER BY created_at ASC",
                (fo_id,),
            ).fetchall()
        ]
        state_log = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM fulfillment_state_log WHERE fulfillment_order_id = ? ORDER BY created_at ASC",
                (fo_id,),
            ).fetchall()
        ]
    return jsonify({"fulfillment_order": fo, "routing_audit": audit, "state_log": state_log})


@bp.post("/api/v1/admin/fulfillment-orders/<int:fo_id>/deliver")
@require_auth("admin")
def admin_mark_delivered(fo_id: int):
    """Admin can mark any fulfillment order as delivered."""
    db = get_db()
    with db.write_transaction() as conn:
        fulfillment_service.supplier_mark_delivered(
            conn,
            fulfillment_order_id=fo_id,
            supplier_id=None,
            actor_user_id=g.current_user["id"],
            actor_type="admin",
        )
        fo = fulfillment_service.read_fulfillment_order(conn, fo_id=fo_id)
    return jsonify({"fulfillment_order": fo})


@bp.get("/api/v1/admin/routing-exceptions")
@require_auth("admin")
def admin_routing_exceptions():
    """List routing audit entries of type 'exception'."""
    db = get_db()
    limit = min(int(request.args.get("limit", "50")), 200)
    offset = int(request.args.get("offset", "0"))
    with db.read_transaction() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                """
            SELECT ra.*, fo.status AS fo_status, o.order_number
            FROM routing_audit ra
            LEFT JOIN fulfillment_orders fo ON fo.id = ra.fulfillment_order_id
            LEFT JOIN orders              o  ON o.id  = fo.order_id
            WHERE ra.event_type = 'exception'
            ORDER BY ra.created_at DESC
            LIMIT ? OFFSET ?
            """,
                (limit, offset),
            ).fetchall()
        ]
    return jsonify({"routing_exceptions": rows})


@bp.get("/api/v1/admin/routing/preview")
@require_auth("admin")
def admin_routing_preview():
    """Preview routing for a product + customer city without placing an order."""
    from app.services.fulfillment_engine import route

    db = get_db()
    product_id = request.args.get("product_id", type=int)
    qty = int(request.args.get("quantity", "1"))
    province = request.args.get("province", "")
    city = request.args.get("city", "")
    if not product_id or not province or not city:
        raise ValidationError("product_id, province و city الزامی است")
    with db.read_transaction() as conn:
        result = route(
            conn,
            product_id=product_id,
            quantity_needed=qty,
            customer_province=province,
            customer_city=city,
        )
    return jsonify(
        {
            "policy_type": result.policy_type,
            "selected": _candidate_dict(result.selected) if result.selected else None,
            "candidates": [_candidate_dict(c) for c in result.candidates],
            "unavailable": result.unavailable_reason,
        }
    )


def _candidate_dict(c) -> dict:
    return {
        "offer_id": c.offer_id,
        "supplier_id": c.supplier_id,
        "supplier_name": c.supplier_name,
        "location_id": c.location_id,
        "city": c.location_city,
        "province": c.location_province,
        "geo_tier": c.geo_tier,
        "price": c.selling_price_minor,
        "stock": c.stock_available,
        "score": c.total_score,
        "scores": c.scores,
        "eligible": c.eligible,
        "reason": c.ineligible_reason,
    }
