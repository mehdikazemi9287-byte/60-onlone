"""Product Identity Service — Phase 7 Identity Graph.

Implements the deterministic GTIN / SKU / ERP code resolution pipeline:

  STAGE 1 — Global GTIN lookup (GTIN8/12/13/14, UPC, EAN, ISBN)
    Exact match in product_identifiers (no supplier scope).
    Confidence: HIGH (1000 bps = 100%).

  STAGE 2 — Supplier-scoped SKU/ERP match
    SUPPLIER_SKU or ERP_CODE with supplier_id scope.
    Confidence: HIGH (1000 bps).

  STAGE 3 — MPN + brand match
    Match on MPN + (optional) brand across all suppliers.
    Confidence: MEDIUM (700 bps).

  STAGE 4 — Barcode / QR / RFID match
    QR_CODE, RFID_EPC, SGTIN in product_identifiers.
    Confidence: HIGH (900 bps) for RFID/SGTIN; MEDIUM (700 bps) for QR.

  UNRESOLVED — queue for human review in identity_resolution_queue.

IDENTIFIER TYPES (from migration 0017):
  GTIN8, GTIN12, GTIN13, GTIN14, UPC, EAN, ISBN13, ISBN10,
  SUPPLIER_SKU, ERP_CODE, MPN, MANUFACTURER_CODE,
  RFID_EPC, SGTIN, SERIAL, BATCH_LOT,
  QR_CODE, GS1_DIGITAL_LINK, EXTERNAL_MARKETPLACE, INTERNAL

PRODUCT IDENTITY CONTRACT VERSION: 1.0
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.core.db import query, write_transaction


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Identifier types that are globally unique (no supplier scope needed)
_GLOBAL_IDENTIFIER_TYPES = frozenset({
    "GTIN8", "GTIN12", "GTIN13", "GTIN14",
    "UPC", "EAN", "ISBN13", "ISBN10",
    "GS1_DIGITAL_LINK",
})

# Identifier types scoped to a supplier
_SUPPLIER_SCOPED_TYPES = frozenset({
    "SUPPLIER_SKU", "ERP_CODE", "MPN", "MANUFACTURER_CODE", "INTERNAL",
})

# RFID / physical label types
_RFID_TYPES = frozenset({"RFID_EPC", "SGTIN", "SERIAL", "BATCH_LOT"})

# Confidence thresholds in basis points
_CONFIDENCE_HIGH   = 1000
_CONFIDENCE_MEDIUM =  700
_CONFIDENCE_LOW    =  400


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Core resolution pipeline
# ─────────────────────────────────────────────────────────────────────────────

def resolve_identifier(
    identifier_type: str,
    identifier_value: str,
    *,
    supplier_id: int | None = None,
) -> dict:
    """Resolve an identifier to a product_id using the deterministic pipeline.

    Returns:
        {
          "resolved": bool,
          "product_id": int | None,
          "confidence_bps": int,
          "stage": str,           # resolution stage name
          "identifier_type": str,
          "identifier_value": str,
        }
    """
    id_type = identifier_type.upper()
    id_value = identifier_value.strip()

    # Stage 1: Global GTIN/barcode
    if id_type in _GLOBAL_IDENTIFIER_TYPES:
        product_id = _lookup_global(id_type, id_value)
        if product_id:
            return _resolved(product_id, _CONFIDENCE_HIGH, "stage1_global_gtin",
                             id_type, id_value)

    # Stage 2: Supplier-scoped SKU / ERP
    if id_type in _SUPPLIER_SCOPED_TYPES and supplier_id:
        product_id = _lookup_supplier_scoped(id_type, id_value, supplier_id)
        if product_id:
            return _resolved(product_id, _CONFIDENCE_HIGH, "stage2_supplier_sku",
                             id_type, id_value)

    # Stage 3: MPN cross-supplier (medium confidence)
    if id_type == "MPN":
        product_id = _lookup_mpn(id_value)
        if product_id:
            return _resolved(product_id, _CONFIDENCE_MEDIUM, "stage3_mpn",
                             id_type, id_value)

    # Stage 4: RFID / QR
    if id_type in _RFID_TYPES:
        product_id = _lookup_global(id_type, id_value)
        confidence = _CONFIDENCE_HIGH if id_type in ("RFID_EPC", "SGTIN") else _CONFIDENCE_MEDIUM
        if product_id:
            return _resolved(product_id, confidence, "stage4_rfid", id_type, id_value)

    if id_type == "QR_CODE":
        product_id = _lookup_global("QR_CODE", id_value)
        if product_id:
            return _resolved(product_id, _CONFIDENCE_MEDIUM, "stage4_qr", id_type, id_value)

    # Unresolved
    return {
        "resolved": False,
        "product_id": None,
        "confidence_bps": 0,
        "stage": "unresolved",
        "identifier_type": id_type,
        "identifier_value": id_value,
    }


def _resolved(product_id: int, confidence: int, stage: str,
              id_type: str, id_value: str) -> dict:
    return {
        "resolved": True,
        "product_id": product_id,
        "confidence_bps": confidence,
        "stage": stage,
        "identifier_type": id_type,
        "identifier_value": id_value,
    }


def _lookup_global(id_type: str, id_value: str) -> int | None:
    """Look up identifier globally (no supplier scope)."""
    row = query(
        """
        SELECT product_id FROM product_identifiers
        WHERE identifier_type = ? AND identifier_value = ?
          AND (supplier_id IS NULL OR supplier_id = 0)
        LIMIT 1
        """,
        (id_type, id_value),
        one=True,
    )
    if row:
        return row["product_id"]
    # Also check supplier-scoped if no global match (fallback)
    row = query(
        """
        SELECT product_id FROM product_identifiers
        WHERE identifier_type = ? AND identifier_value = ?
        LIMIT 1
        """,
        (id_type, id_value),
        one=True,
    )
    return row["product_id"] if row else None


def _lookup_supplier_scoped(id_type: str, id_value: str, supplier_id: int) -> int | None:
    row = query(
        """
        SELECT product_id FROM product_identifiers
        WHERE identifier_type = ? AND identifier_value = ? AND supplier_id = ?
        LIMIT 1
        """,
        (id_type, id_value, supplier_id),
        one=True,
    )
    return row["product_id"] if row else None


def _lookup_mpn(mpn_value: str) -> int | None:
    """MPN lookup — returns product_id if exactly one product matches."""
    rows = query(
        """
        SELECT DISTINCT product_id FROM product_identifiers
        WHERE identifier_type = 'MPN' AND identifier_value = ?
        """,
        (mpn_value,),
    )
    if rows and len(rows) == 1:
        return rows[0]["product_id"]
    return None  # ambiguous or not found


# ─────────────────────────────────────────────────────────────────────────────
# Register identifier
# ─────────────────────────────────────────────────────────────────────────────

def register_identifier(
    product_id: int,
    identifier_type: str,
    identifier_value: str,
    *,
    supplier_id: int | None = None,
    confidence_bps: int = 1000,
    source: str = "manual",
) -> dict:
    """Register or update an identifier for a product.

    Returns: {registered: bool, product_id: int, action: 'created'|'exists'}
    """
    id_type = identifier_type.upper()
    now = _now_iso()

    # Check for existing
    existing = query(
        """
        SELECT id FROM product_identifiers
        WHERE identifier_type=? AND identifier_value=?
          AND (supplier_id IS ? OR supplier_id = ?)
        LIMIT 1
        """,
        (id_type, identifier_value, supplier_id, supplier_id or 0),
        one=True,
    )
    if existing:
        return {"registered": True, "product_id": product_id, "action": "exists"}

    with write_transaction() as conn:
        conn.execute(
            """
            INSERT INTO product_identifiers
                (product_id, identifier_type, identifier_value, supplier_id,
                 confidence_bps, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (product_id, id_type, identifier_value, supplier_id,
             confidence_bps, source, now),
        )
    return {"registered": True, "product_id": product_id, "action": "created"}


# ─────────────────────────────────────────────────────────────────────────────
# Queue unresolved for human review
# ─────────────────────────────────────────────────────────────────────────────

def queue_for_review(
    identifier_type: str,
    identifier_value: str,
    *,
    raw_product_data: dict,
    connector_account_id: int | None = None,
    supplier_id: int | None = None,
    import_job_id: int | None = None,
    priority: int = 50,
) -> int:
    """Queue an unresolvable identifier for manual review.

    Returns: new identity_resolution_queue.id
    """
    now = _now_iso()
    with write_transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO identity_resolution_queue (
                identifier_type, identifier_value,
                connector_account_id, supplier_id, import_job_id,
                raw_product_data_json, resolution_stage, status,
                priority, attempt_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'unresolved', 'pending', ?, 0, ?)
            """,
            (
                identifier_type.upper(),
                identifier_value,
                connector_account_id,
                supplier_id,
                import_job_id,
                json.dumps(raw_product_data, ensure_ascii=False),
                priority,
                now,
            ),
        )
        return cur.lastrowid


# ─────────────────────────────────────────────────────────────────────────────
# Batch resolution (for import pipeline)
# ─────────────────────────────────────────────────────────────────────────────

def resolve_batch(
    items: list[dict],
    *,
    supplier_id: int | None = None,
) -> list[dict]:
    """Resolve a batch of {identifier_type, identifier_value} dicts.

    Returns same list with 'resolved', 'product_id', 'confidence_bps', 'stage' added.
    """
    results = []
    for item in items:
        result = resolve_identifier(
            item["identifier_type"],
            item["identifier_value"],
            supplier_id=supplier_id,
        )
        results.append({**item, **result})
    return results
