# Scanner and RFID Integration Guide

## Introduction

Phase 7 extends the Phase 6 barcode scanner API to support RFID readers and the serialised product tracking they enable. RFID events feed directly into the Product Identity Graph (resolving EPC/SGTIN codes to internal product records) and update warehouse location data in near-real-time.

The scanner infrastructure is intentionally hardware-agnostic. The API accepts events from any reader that can make HTTP POST requests, including Zebra fixed readers, handheld terminals, and Raspberry Pi-based DIY readers. The platform does not depend on a proprietary SDK.

---

## Database Tables

### warehouse_locations

Tracks the last known physical location of each product unit, keyed by RFID EPC or SGTIN.

```sql
CREATE TABLE warehouse_locations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id         INTEGER NOT NULL REFERENCES suppliers(id),
    product_id          INTEGER REFERENCES products(id),
    -- EPC or SGTIN of the specific serialised unit
    rfid_epc            TEXT NOT NULL,
    -- Human-readable zone/bin code, e.g. "ZONE-A/RACK-3/BIN-7"
    location_code       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,
    -- RSSI in dBm at the time of last read
    last_rssi_dbm       INTEGER,
    -- Antenna port that last read this tag
    last_antenna_port   INTEGER,
    reader_id           TEXT NOT NULL,
    move_count          INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(rfid_epc)
);

CREATE INDEX idx_warehouse_locations_product
    ON warehouse_locations(product_id);

CREATE INDEX idx_warehouse_locations_location
    ON warehouse_locations(location_code);
```

### rfid_events

Immutable log of every RFID read. This table is append-only and is never updated after insertion. It provides the audit trail for all location history.

```sql
CREATE TABLE rfid_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    reader_id       TEXT NOT NULL,
    antenna_port    INTEGER NOT NULL,
    -- Raw EPC as a hex string, uppercase, no spaces
    epc_hex         TEXT NOT NULL,
    -- Decoded SGTIN if the EPC is a GS1 SGTIN-96 or SGTIN-198
    sgtin           TEXT,
    -- Decoded GTIN extracted from SGTIN (17-digit padded)
    gtin            TEXT,
    -- Signal strength in dBm (negative integer)
    rssi_dbm        INTEGER,
    -- ISO-8601 UTC timestamp from the reader's clock
    read_at         TEXT NOT NULL,
    -- Location code associated with this reader/antenna at read time
    location_code   TEXT NOT NULL,
    -- Result of product identity resolution
    resolved_product_id INTEGER REFERENCES products(id),
    resolution_confidence_bps INTEGER,
    resolution_stage INTEGER,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_rfid_events_epc ON rfid_events(epc_hex);
CREATE INDEX idx_rfid_events_read_at ON rfid_events(read_at);
CREATE INDEX idx_rfid_events_reader ON rfid_events(reader_id, read_at);
```

### scanner_readers (Phase 6, extended in Phase 7)

```sql
-- Added in Phase 7: location_code column links reader to physical zone
ALTER TABLE scanner_readers ADD COLUMN location_code TEXT;
ALTER TABLE scanner_readers ADD COLUMN reader_type TEXT DEFAULT 'barcode';
-- reader_type: 'barcode' | 'rfid_fixed' | 'rfid_handheld'
```

---

## RFID Event Structure

Each RFID read is submitted as a JSON object. Readers may batch multiple reads in a single request.

```json
{
  "reader_id": "READER-ZONE-A-001",
  "antenna_port": 2,
  "epc_hex": "3034257BF7194E4000001A85",
  "rssi_dbm": -62,
  "read_at": "2026-08-08T09:14:33Z",
  "location_code": "ZONE-A/RACK-3/BIN-7"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `reader_id` | string | Yes | Unique identifier of the RFID reader device |
| `antenna_port` | integer | Yes | Antenna port number (1-indexed) |
| `epc_hex` | string | Yes | Raw EPC as uppercase hex string, no separators |
| `rssi_dbm` | integer | No | Received Signal Strength Indicator in dBm |
| `read_at` | string | Yes | ISO-8601 UTC timestamp from the reader |
| `location_code` | string | Yes | Physical location code of the reader/antenna |

---

## EPC Decoding and SGTIN Extraction

When an EPC arrives, the platform attempts to decode it as a GS1 SGTIN-96 (the most common encoding used in retail). The decoding extracts the GS1 company prefix, item reference, and serial number, which together form an SGTIN and can be used to derive the base GTIN.

```python
def decode_epc_sgtin96(epc_hex: str) -> dict | None:
    """
    Decode a GS1 SGTIN-96 EPC into its components.

    SGTIN-96 binary structure (96 bits):
      Header   : 8 bits  (value 0x30 = SGTIN-96)
      Filter   : 3 bits  (item/case/pallet filter)
      Partition: 3 bits  (determines GS1 company prefix length)
      Company  : variable (depends on partition)
      Item ref : variable (depends on partition)
      Serial   : 38 bits

    Returns dict with keys: gtin, company_prefix, item_ref, serial
    Returns None if the EPC is not a valid SGTIN-96.
    """
    if len(epc_hex) != 24:
        return None

    raw = int(epc_hex, 16)
    header = (raw >> 88) & 0xFF

    if header != 0x30:
        # Not an SGTIN-96 header
        return None

    filter_val = (raw >> 85) & 0x07
    partition = (raw >> 82) & 0x07

    # GS1 partition table: (company_prefix_bits, item_ref_bits, company_prefix_digits)
    partition_table = {
        0: (40, 4,  12),
        1: (37, 7,  11),
        2: (34, 10, 10),
        3: (30, 14,  9),
        4: (27, 17,  8),
        5: (24, 20,  7),
        6: (20, 24,  6),
    }

    if partition not in partition_table:
        return None

    cp_bits, ir_bits, cp_digits = partition_table[partition]

    serial_bits = 38
    item_ref_start = serial_bits
    company_start = item_ref_start + ir_bits

    serial = raw & ((1 << serial_bits) - 1)
    item_ref = (raw >> item_ref_start) & ((1 << ir_bits) - 1)
    company_prefix = (raw >> company_start) & ((1 << cp_bits) - 1)

    # Reconstruct GTIN-14
    cp_str = str(company_prefix).zfill(cp_digits)
    ir_str = str(item_ref).zfill(13 - cp_digits)
    gtin13_no_check = cp_str + ir_str
    check_digit = _gs1_check_digit(gtin13_no_check)
    gtin13 = gtin13_no_check + str(check_digit)

    return {
        "gtin": gtin13,
        "company_prefix": cp_str,
        "item_ref": ir_str,
        "serial": str(serial),
        "sgtin": f"{cp_str}.{ir_str}.{serial}",
        "filter": filter_val,
    }
```

---

## GS1 Verified By GS1 Lookup (NOT IMPLEMENTED)

GS1's "Verified by GS1" service (`https://www.gs1.org/services/verified-by-gs1`) provides a public API for looking up the registered brand owner of any GTIN. In Phase 7, this lookup is architecturally planned but **NOT IMPLEMENTED** because:

1. The Verified by GS1 REST API requires a GS1 member account and API key.
2. 60online does not currently have a GS1 membership.
3. Iranian GTINs are issued by the Iranian GS1 Member Organisation (GS1 Iran), and lookups for Iranian products may not be available through the global Verified by GS1 service.

Until a GS1 membership is obtained, the GTIN lookup cache (`gtin_lookup_cache` table) remains empty. The product identity pipeline operates using locally registered identifiers only. GTINs that are not found in the local database are routed to the `identity_resolution_queue`.

```sql
-- Planned table, created in migration 0017
-- Populated only when GS1 lookup is implemented
CREATE TABLE gtin_lookup_cache (
    gtin            TEXT PRIMARY KEY,
    brand_name      TEXT,
    product_name    TEXT,
    gs1_member_name TEXT,
    gs1_country_code TEXT,
    fetched_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL
);
```

---

## Scan-to-Locate Flow

The scan-to-locate flow is the primary use case for RFID in Phase 7. It enables warehouse staff to locate any serialised item by its RFID tag.

```
1. Reader detects tag EPC in ZONE-B
        │
        ▼
2. POST /api/v1/scanner/rfid-event  { epc_hex, reader_id, location_code }
        │
        ▼
3. Decode EPC → extract SGTIN → extract GTIN
        │
        ▼
4. Run 4-stage identity resolution
        │  Stage 1: GTIN13 match → product_id = 42, confidence = 100%
        │
        ▼
5. INSERT into rfid_events (append-only)
        │
        ▼
6. UPSERT into warehouse_locations
        │  UPDATE last_seen_at, last_rssi_dbm, location_code, move_count
        │
        ▼
7. Return: { product_id, product_name, location_code, confidence_bps }
```

---

## API Endpoints

### Phase 6 Endpoints (unchanged)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/scanner/scan` | Submit a barcode scan event |
| `GET` | `/api/v1/scanner/readers` | List registered scanner readers |
| `POST` | `/api/v1/scanner/readers` | Register a new reader |

### Phase 7 Additions

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/scanner/rfid-event` | Submit a single RFID read event |
| `POST` | `/api/v1/scanner/rfid-batch` | Submit a batch of RFID events (up to 500 per request) |
| `GET` | `/api/v1/scanner/locate/{epc_hex}` | Get current location of a tag by EPC |
| `GET` | `/api/v1/scanner/location/{location_code}` | List all tags currently visible at a location |
| `GET` | `/api/v1/scanner/rfid-events` | Query RFID event log (paginated, filterable by reader/date) |

### Example: Submit RFID Event

```
POST /api/v1/scanner/rfid-event
Authorization: Bearer <supplier_token>
Content-Type: application/json

{
  "reader_id": "READER-ZONE-A-001",
  "antenna_port": 1,
  "epc_hex": "3034257BF7194E4000001A85",
  "rssi_dbm": -55,
  "read_at": "2026-08-08T11:30:00Z",
  "location_code": "ZONE-A/RACK-1/BIN-2"
}

Response 200:
{
  "rfid_event_id": 10284,
  "resolved_product_id": 42,
  "resolved_product_name": "Industrial Valve DN50",
  "confidence_bps": 10000,
  "resolution_stage": 1,
  "location_code": "ZONE-A/RACK-1/BIN-2",
  "previous_location": "ZONE-B/RACK-5/BIN-12",
  "move_detected": true
}
```
