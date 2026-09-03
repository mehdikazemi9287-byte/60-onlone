"""Invoices API — Phase 6 Final (Repaired: Blocker 4 tenant isolation).

POST /api/v1/invoices             — create invoice
GET  /api/v1/invoices             — list invoices
GET  /api/v1/invoices/<id>        — get invoice with lines
POST /api/v1/invoices/<id>/match  — trigger three-way match

SECURITY: For supplier role, supplier_id is ALWAYS derived server-side from
authenticated identity. body.supplier_id and query.supplier_id are IGNORED
for authorization decisions. No existence leakage (404 not 403 on cross-supplier).
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.core.deps import require_auth, get_db
from app.core.errors import ValidationError, NotFoundError
from app.services import invoice_service, three_way_match_service

bp = Blueprint("invoices", __name__)


def _get_caller_supplier_id(db) -> int | None:
    """Return supplier_id for the authenticated supplier user, or None if not supplier role."""
    if g.current_user["role"] != "supplier":
        return None
    with db.read_transaction() as conn:
        sup_row = conn.execute(
            "SELECT id FROM suppliers WHERE user_id = ?", (g.current_user["id"],)
        ).fetchone()
    return int(sup_row["id"]) if sup_row else None


def _require_supplier_id_from_auth(db) -> int:
    """Derive supplier_id from auth token. Raises ValidationError if not found."""
    sid = _get_caller_supplier_id(db)
    if sid is None:
        raise ValidationError("حساب تأمین‌کننده یافت نشد")
    return sid


@bp.post("/api/v1/invoices")
@require_auth("admin", "supplier")
def create_invoice():
    db = get_db()
    data = request.get_json(silent=True) or {}

    # BLOCKER 4: supplier_id comes from auth, not body
    if g.current_user["role"] == "supplier":
        supplier_id = _require_supplier_id_from_auth(db)
    else:
        # admin: trust body.supplier_id
        raw_sid = data.get("supplier_id")
        if not raw_sid:
            raise ValidationError("supplier_id الزامی است")
        supplier_id = int(raw_sid)

    invoice_number = data.get("invoice_number")
    if not invoice_number:
        raise ValidationError("invoice_number الزامی است")
    invoice_date = data.get("invoice_date")
    if not invoice_date:
        raise ValidationError("invoice_date الزامی است")

    lines = data.get("lines", [])
    for line in lines:
        for field in ("unit_price_minor", "line_total_minor", "tax_minor"):
            if field in line and isinstance(line[field], float):
                raise ValidationError(f"مقدار {field} باید عدد صحیح (ریال) باشد")

    with db.write_transaction() as conn:
        inv = invoice_service.create_invoice(
            conn,
            supplier_id=supplier_id,
            invoice_number=str(invoice_number),
            invoice_date=str(invoice_date),
            lines=lines,
            source_type=data.get("source_type", "manual"),
            created_by=g.current_user["id"],
            connector_account_id=data.get("connector_account_id"),
            tax_minor=int(data.get("tax_minor", 0)),
            currency=data.get("currency", "IRR"),
            raw_json=data.get("raw_json"),
        )
    return jsonify({"invoice": inv}), 201


@bp.get("/api/v1/invoices")
@require_auth("admin", "supplier")
def list_invoices():
    db = get_db()

    # BLOCKER 4: supplier always gets their own invoices; cannot pass supplier_id filter
    if g.current_user["role"] == "supplier":
        supplier_id = _get_caller_supplier_id(db)
    else:
        supplier_id = request.args.get("supplier_id", type=int)

    status = request.args.get("status")
    limit = min(request.args.get("limit", 50, type=int), 200)
    offset = request.args.get("offset", 0, type=int)

    with db.read_transaction() as conn:
        result = invoice_service.list_invoices(
            conn,
            supplier_id=supplier_id,
            status=status,
            limit=limit,
            offset=offset,
        )
    return jsonify(result), 200


@bp.get("/api/v1/invoices/<int:invoice_id>")
@require_auth("admin", "supplier")
def get_invoice(invoice_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        try:
            inv = invoice_service.get_invoice(conn, invoice_id)
        except NotFoundError:
            raise  # re-raise as-is

        # BLOCKER 4: supplier ownership check — 404 not 403 (no existence leakage)
        if g.current_user["role"] == "supplier":
            sup_row = conn.execute(
                "SELECT id FROM suppliers WHERE user_id = ?", (g.current_user["id"],)
            ).fetchone()
            caller_sid = int(sup_row["id"]) if sup_row else None
            if caller_sid is None or int(inv["supplier_id"]) != caller_sid:
                raise NotFoundError("فاکتور یافت نشد")

    return jsonify({"invoice": inv}), 200


@bp.post("/api/v1/invoices/<int:invoice_id>/match")
@require_auth("admin")
def match_invoice(invoice_id: int):
    db = get_db()
    data = request.get_json(silent=True) or {}

    with db.read_transaction() as conn:
        inv = invoice_service.get_invoice(conn, invoice_id)

    supplier_id = inv["supplier_id"]

    with db.write_transaction() as conn:
        result = three_way_match_service.perform_match(
            conn,
            supplier_id=supplier_id,
            invoice_id=invoice_id,
            procurement_order_id=data.get("procurement_order_id"),
            fulfillment_order_id=data.get("fulfillment_order_id"),
            tolerance_bps=int(data.get("tolerance_bps", 100)),
            checked_by=g.current_user["id"],
            notes=data.get("notes"),
        )
    return jsonify({"match": result}), 200
