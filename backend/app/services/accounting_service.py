"""Accounting Service — Phase 7 Normalized Document Interface.

Bridges 60online's internal order/ledger data to the AccountingAdapter contract.
Responsibilities:
  1. Build AccountingDocument from internal order / payment data
  2. Delegate export to the configured accounting adapter
  3. Record the result in accounting_documents table
  4. Pull documents from external system for reconciliation

CRITICAL RULE:
  60online's internal ledger (ledger_entries / ledger_transactions) is the
  SOURCE OF TRUTH. The accounting adapter receives exports only; it NEVER
  overrides internal records.

ACCOUNTING SERVICE CONTRACT VERSION: 1.0
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.adapters.accounting.base import (
    AccountingDocument,
    AccountingDocumentType,
    AccountingLine,
)
from app.adapters.accounting.registry import get_accounting_adapter
from app.core.db import query, write_transaction
from app.core.errors import NotFoundError, ValidationError


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Connector account helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_accounting_connector(connector_account_id: int) -> dict:
    """Return accounting connector account row."""
    row = query(
        "SELECT * FROM accounting_connector_accounts WHERE id=?",
        (connector_account_id,),
        one=True,
    )
    if row is None:
        raise NotFoundError(f"حساب اتصال حسابداری #{connector_account_id} یافت نشد")
    return dict(row)


def list_accounting_connectors(
    *,
    supplier_id: int | None = None,
    organization_id: int | None = None,
) -> list[dict]:
    """Return accounting connector accounts filtered by supplier or org."""
    where = "1=1"
    params: list = []
    if supplier_id is not None:
        where += " AND supplier_id=?"
        params.append(supplier_id)
    if organization_id is not None:
        where += " AND organization_id=?"
        params.append(organization_id)
    rows = query(
        f"SELECT * FROM accounting_connector_accounts WHERE {where} ORDER BY id",
        tuple(params),
    )
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Document builders
# ─────────────────────────────────────────────────────────────────────────────

def build_invoice_document(order_id: int) -> AccountingDocument:
    """Build a normalized AccountingDocument from an order.

    Looks up order, org/buyer info, and order lines.
    Raises NotFoundError if order not found.
    """
    order = query("SELECT * FROM orders WHERE id=?", (order_id,), one=True)
    if order is None:
        raise NotFoundError(f"سفارش #{order_id} یافت نشد")

    org_name = ""
    org_national_id = ""
    if order["organization_id"]:
        org = query(
            "SELECT * FROM organizations WHERE id=?",
            (order["organization_id"],),
            one=True,
        )
        if org:
            org_name = org.get("name", "")
            org_national_id = org.get("national_id", "") or ""

    # Order lines
    lines_rows = query(
        "SELECT * FROM order_items WHERE order_id=?", (order_id,)
    )
    lines = []
    for ln in lines_rows:
        lines.append(AccountingLine(
            description=ln.get("product_name") or f"محصول #{ln.get('product_id')}",
            quantity=ln.get("quantity", 1),
            unit_price_minor=ln.get("unit_price_minor", 0),
            line_total_minor=ln.get("line_total_minor", 0),
            tax_minor=0,  # populated by tax_service in real flow
            product_code=str(ln.get("product_id", "")),
        ))

    doc_date = (order.get("created_at") or _today())[:10]

    return AccountingDocument(
        doc_type=AccountingDocumentType.SALES_INVOICE,
        doc_number=f"INV-{order_id:06d}",
        doc_date=doc_date,
        currency=order.get("currency", "IRR"),
        subtotal_minor=order.get("subtotal_minor", 0),
        tax_minor=order.get("tax_minor", 0),
        total_minor=order.get("total_minor", 0),
        counterparty_name=org_name,
        counterparty_national_id=org_national_id,
        lines=lines,
        order_id=order_id,
        organization_id=order.get("organization_id"),
    )


def build_payment_document(order_id: int) -> AccountingDocument:
    """Build a payment document for a paid order."""
    order = query("SELECT * FROM orders WHERE id=?", (order_id,), one=True)
    if order is None:
        raise NotFoundError(f"سفارش #{order_id} یافت نشد")

    doc_date = (order.get("paid_at") or order.get("created_at") or _today())[:10]

    return AccountingDocument(
        doc_type=AccountingDocumentType.PAYMENT,
        doc_number=f"PAY-{order_id:06d}",
        doc_date=doc_date,
        currency=order.get("currency", "IRR"),
        total_minor=order.get("total_minor", 0),
        order_id=order_id,
        organization_id=order.get("organization_id"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Export operations
# ─────────────────────────────────────────────────────────────────────────────

def export_order_invoice(
    order_id: int,
    *,
    connector_account_id: int,
) -> dict:
    """Export a sales invoice for an order to the configured accounting system.

    Returns adapter result dict. Records the accounting_document row.
    """
    connector = get_accounting_connector(connector_account_id)
    adapter = get_accounting_adapter(
        connector["accounting_system"],
        config=json.loads(connector.get("config_json") or "{}"),
    )

    doc = build_invoice_document(order_id)
    result = adapter.export_invoice(doc)

    _record_document(
        connector_account_id=connector_account_id,
        document_type="sales_invoice",
        direction="outbound",
        order_id=order_id,
        supplier_id=connector.get("supplier_id"),
        organization_id=connector.get("organization_id"),
        external_doc_id=result.get("external_doc_id"),
        total_minor=doc.total_minor,
        tax_minor=doc.tax_minor,
        currency=doc.currency,
        document_date=doc.doc_date,
        document_json=result,
        status="exported",
    )
    return result


def export_order_payment(
    order_id: int,
    *,
    connector_account_id: int,
) -> dict:
    """Export a payment document for a paid order."""
    connector = get_accounting_connector(connector_account_id)
    adapter = get_accounting_adapter(
        connector["accounting_system"],
        config=json.loads(connector.get("config_json") or "{}"),
    )

    doc = build_payment_document(order_id)
    result = adapter.export_payment(doc)

    _record_document(
        connector_account_id=connector_account_id,
        document_type="payment",
        direction="outbound",
        order_id=order_id,
        supplier_id=connector.get("supplier_id"),
        organization_id=connector.get("organization_id"),
        external_doc_id=result.get("external_doc_id"),
        total_minor=doc.total_minor,
        tax_minor=0,
        currency=doc.currency,
        document_date=doc.doc_date,
        document_json=result,
        status="exported",
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Record keeping
# ─────────────────────────────────────────────────────────────────────────────

def _record_document(
    *,
    connector_account_id: int,
    document_type: str,
    direction: str,
    order_id: int | None = None,
    fulfillment_order_id: int | None = None,
    supplier_id: int | None = None,
    organization_id: int | None = None,
    external_doc_id: str | None = None,
    total_minor: int = 0,
    tax_minor: int = 0,
    currency: str = "IRR",
    document_date: str = "",
    document_json: dict | None = None,
    status: str = "exported",
) -> int:
    now = _now_iso()
    with write_transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO accounting_documents (
                connector_account_id, document_type, direction,
                order_id, fulfillment_order_id, supplier_id, organization_id,
                external_doc_id, total_minor, tax_minor, currency,
                document_date, document_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                connector_account_id, document_type, direction,
                order_id, fulfillment_order_id, supplier_id, organization_id,
                external_doc_id, total_minor, tax_minor, currency,
                document_date,
                json.dumps(document_json or {}, ensure_ascii=False),
                status, now, now,
            ),
        )
        return cur.lastrowid


def list_accounting_documents(
    *,
    connector_account_id: int | None = None,
    supplier_id: int | None = None,
    organization_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """List accounting documents with optional filters."""
    where_parts = []
    params: list = []
    if connector_account_id is not None:
        where_parts.append("connector_account_id=?")
        params.append(connector_account_id)
    if supplier_id is not None:
        where_parts.append("supplier_id=?")
        params.append(supplier_id)
    if organization_id is not None:
        where_parts.append("organization_id=?")
        params.append(organization_id)
    if status is not None:
        where_parts.append("status=?")
        params.append(status)

    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    params.extend([limit, offset])
    rows = query(
        f"""
        SELECT id, connector_account_id, document_type, direction,
               order_id, supplier_id, organization_id,
               external_doc_id, total_minor, tax_minor, currency,
               document_date, status, created_at
        FROM accounting_documents
        {where}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    )
    return [dict(r) for r in rows]
