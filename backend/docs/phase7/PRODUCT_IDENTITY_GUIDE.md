# Product Identity Guide

## Introduction

Product identity management is one of the hardest problems in multi-supplier e-commerce. The same physical product may appear under dozens of different identifiers across suppliers, ERP systems, barcodes, and RFID tags. Without a principled way to resolve these identifiers to a single canonical product record, inventory counts diverge, duplicate listings accumulate, and order fulfilment errors increase.

Phase 7 introduces the **Product Identity Graph**: a set of database tables and a four-stage deterministic resolution pipeline that links arbitrary external identifiers to 60online's internal `product_id`. The pipeline is designed to be deterministic — identical inputs always produce identical outputs — and auditable, so that any resolution decision can be traced back to the data that drove it.

---

## Supported Identifier Types

The `product_identifiers` table stores all known identifiers for each product. The `identifier_type` column is an enum with the following values:

| Identifier Type | Description | Example |
|----------------|-------------|---------|
| `GTIN8` | 8-digit Global Trade Item Number | `12345678` |
| `GTIN12` | 12-digit GTIN (UPC-A) | `012345678905` |
| `GTIN13` | 13-digit GTIN (EAN-13) | `5901234123457` |
| `GTIN14` | 14-digit GTIN (shipping container) | `10012345678902` |
| `UPC` | Universal Product Code (alias for GTIN12) | `012345678905` |
| `EAN` | European Article Number (alias for GTIN13) | `5901234123457` |
| `ISBN` | International Standard Book Number | `9780306406157` |
| `SUPPLIER_SKU` | Supplier's internal stock-keeping unit | `SUPP-ABC-0042` |
| `ERP_CODE` | ERP system's internal product code | `ERP-10042` |
| `MPN` | Manufacturer Part Number | `MPN-XYZ-2024-REV3` |
| `RFID_EPC` | Electronic Product Code from RFID tag | `3034257BF7194E4000001A85` |
| `SGTIN` | Serialised GTIN (GTIN + serial number) | `0614141.107346.2017` |
| `QR_CODE` | Arbitrary QR code payload | `https://example.com/product/42` |
| `INTERNAL` | 60online internal product UUID | `prod_01J...` |

### Schema

```sql
CREATE TABLE product_identifiers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    identifier_type TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    source          TEXT NOT NULL,  -- 'manual', 'erp_sync', 'rfid_scan', 'gs1_lookup'
    confidence_bps  INTEGER NOT NULL DEFAULT 10000,  -- basis points, 10000 = 100%
    verified_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(identifier_type, identifier_value)
);

CREATE TABLE product_identity_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_identifier_id INTEGER NOT NULL REFERENCES product_identifiers(id),
    to_identifier_id   INTEGER NOT NULL REFERENCES product_identifiers(id),
    link_type       TEXT NOT NULL,  -- 'same_product', 'variant_of', 'replaces'
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE identity_resolution_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_identifier  TEXT NOT NULL,
    identifier_type TEXT NOT NULL,
    source_context  TEXT,   -- JSON: where the identifier came from
    attempted_stages TEXT,  -- JSON array of stages attempted
    resolution_result TEXT, -- 'resolved', 'conflict', 'unresolved'
    resolved_product_id INTEGER REFERENCES products(id),
    reviewer_id     INTEGER REFERENCES users(id),
    reviewed_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

---

## 4-Stage Deterministic Resolution Pipeline

When a new identifier arrives (from an ERP sync, RFID scan, or manual entry), the resolution pipeline attempts to find the corresponding `product_id` in order of decreasing certainty. Each stage has a defined confidence threshold. If a stage resolves the identifier, the pipeline stops and records the result. If all four stages fail, the identifier is placed in the `identity_resolution_queue` for human review.

### Stage 1: Global GTIN Match

The first stage looks for an exact match on any GTIN-family identifier: GTIN8, GTIN12, GTIN13, GTIN14, UPC, EAN, or ISBN. GTINs are globally unique identifiers assigned by GS1 (the international barcode registry), so an exact GTIN match has the highest confidence level.

```
Incoming: identifier_type=GTIN13, value=5901234123457

SELECT p.id
FROM product_identifiers pi
JOIN products p ON p.id = pi.product_id
WHERE pi.identifier_type IN ('GTIN8','GTIN12','GTIN13','GTIN14','UPC','EAN','ISBN')
  AND pi.identifier_value = '5901234123457'
LIMIT 1;

→ Match found → confidence_bps = 10000 (100%) → RESOLVED
→ No match → proceed to Stage 2
```

**Confidence**: 10000 bps (100%) — GTIN uniqueness is enforced by GS1 registration.

### Stage 2: Supplier SKU Cross-Reference

The second stage searches `SUPPLIER_SKU` and `ERP_CODE` identifiers scoped to the same supplier. A supplier SKU is only unique within a single supplier's namespace, so the lookup must be filtered by `supplier_id`.

```
Incoming: identifier_type=SUPPLIER_SKU, value=SUPP-ABC-0042, supplier_id=17

SELECT p.id
FROM product_identifiers pi
JOIN products p ON p.id = pi.product_id
WHERE pi.identifier_type IN ('SUPPLIER_SKU', 'ERP_CODE')
  AND pi.identifier_value = 'SUPP-ABC-0042'
  AND p.supplier_id = 17
LIMIT 1;

→ Match found → confidence_bps = 9000 (90%) → RESOLVED
→ No match → proceed to Stage 3
```

**Confidence**: 9000 bps (90%) — Supplier SKUs are unique per supplier, but suppliers occasionally reuse SKUs for different products.

### Stage 3: Manufacturer Part Number (MPN)

The third stage searches `MPN` identifiers. MPNs are assigned by manufacturers and are more stable than supplier SKUs, but the same manufacturer may assign the same MPN to products in different markets (regional variants). The confidence is therefore slightly lower than a full GTIN match.

```
Incoming: identifier_type=MPN, value=MPN-XYZ-2024-REV3

SELECT p.id, COUNT(*) as match_count
FROM product_identifiers pi
JOIN products p ON p.id = pi.product_id
WHERE pi.identifier_type = 'MPN'
  AND pi.identifier_value = 'MPN-XYZ-2024-REV3';

→ Exactly 1 match → confidence_bps = 8500 (85%) → RESOLVED
→ Multiple matches → confidence_bps = 5000, route to review queue
→ No match → proceed to Stage 4
```

**Confidence**: 8500 bps (85%) single match; 5000 bps (50%) if multiple products share the MPN.

### Stage 4: RFID EPC / QR Code Fallback

The fourth stage handles `RFID_EPC`, `SGTIN`, and `QR_CODE` identifiers. An SGTIN encodes both a GTIN and a serial number; the pipeline strips the serial to extract the base GTIN and loops back through Stage 1. For bare EPC and QR codes, the pipeline performs a fuzzy match against known identifiers.

```python
def resolve_sgtin(sgtin_value: str) -> Optional[int]:
    """
    Extract the GTIN from an SGTIN and resolve via Stage 1.

    SGTIN format (GS1): company_prefix.item_ref.serial
    Example: "0614141.107346.2017"
    """
    parts = sgtin_value.split(".")
    if len(parts) >= 2:
        # Reconstruct the GTIN13 from company prefix + item ref
        gtin_candidate = parts[0] + parts[1]
        gtin_candidate = gtin_candidate.zfill(13)
        return resolve_stage1(gtin_candidate, "GTIN13")
    return None
```

**Confidence**: 7000 bps (70%) for SGTIN→GTIN resolution; 4000 bps (40%) for bare QR code.

---

## Confidence Scoring

Confidence scores are stored in `product_identifiers.confidence_bps` as integer basis points (1 bps = 0.01%). The minimum confidence threshold for automatic resolution is configurable; the Phase 7 default is **7000 bps (70%)**.

Identifiers resolved below the threshold are written to `identity_resolution_queue` with `resolution_result = 'unresolved'` and await human review. This prevents low-confidence matches from silently corrupting inventory counts.

| Resolution Method | Confidence (bps) |
|------------------|-----------------|
| Manual entry (operator verified) | 10000 |
| GTIN exact match | 10000 |
| Supplier SKU (unique) | 9000 |
| MPN (single match) | 8500 |
| SGTIN → GTIN resolved | 7000 |
| MPN (multiple matches) | 5000 |
| QR code payload match | 4000 |
| Human review override | Set by reviewer |

---

## Human Review Queue

Identifiers that cannot be resolved automatically land in `identity_resolution_queue`. The admin UI (planned for Phase 8) will present these to warehouse operators with suggested candidates. The reviewer can:

- **Accept a candidate** — links the identifier to the product and sets `confidence_bps = 10000` (reviewer-verified).
- **Create a new product** — if no candidate is correct.
- **Mark as duplicate** — if the identifier should be merged with an existing product.

All review actions are recorded with `reviewer_id` and `reviewed_at` for audit purposes.

---

## Batch Resolution API

The batch resolution endpoint accepts a list of identifiers and returns resolution results for each one without modifying the database. It is intended for use by import tools and ERP sync workers that need to pre-validate a batch before committing.

```
POST /api/v1/products/identity/resolve-batch

Request:
{
  "identifiers": [
    {"type": "GTIN13", "value": "5901234123457"},
    {"type": "SUPPLIER_SKU", "value": "SUPP-ABC-0042", "supplier_id": 17},
    {"type": "MPN", "value": "UNKNOWN-MPN-XYZ"}
  ]
}

Response:
{
  "results": [
    {
      "input": {"type": "GTIN13", "value": "5901234123457"},
      "status": "resolved",
      "product_id": 42,
      "confidence_bps": 10000,
      "stage": 1
    },
    {
      "input": {"type": "SUPPLIER_SKU", "value": "SUPP-ABC-0042", "supplier_id": 17},
      "status": "resolved",
      "product_id": 42,
      "confidence_bps": 9000,
      "stage": 2
    },
    {
      "input": {"type": "MPN", "value": "UNKNOWN-MPN-XYZ"},
      "status": "unresolved",
      "product_id": null,
      "confidence_bps": 0,
      "stage": null,
      "queued_for_review": true
    }
  ]
}
```

All amounts returned by this endpoint are informational only; no monetary values are involved. The endpoint is idempotent and read-only except for the optional creation of `identity_resolution_queue` rows.
