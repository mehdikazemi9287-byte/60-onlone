# Phase 7 Audit Evidence

## Overview

This document records the implementation evidence for Phase 7 of the 60online platform. It lists the test files, migration files, and adapter implementations that constitute the Phase 7 deliverable. It also acknowledges all `NOT IMPLEMENTED` components with the specific technical or contractual reasons why they were not implemented.

The purpose of this document is to provide a clear, honest account of what was built, what was not built, and why. Any reviewer — internal, external, or regulatory — should be able to read this document and understand the precise state of the integration platform.

---

## Test Files

Phase 7 added 9 test files. All tests are located in `backend/tests/` and are executable with `pytest -v`.

| # | Test File | Test Count | What It Covers |
|---|-----------|-----------|----------------|
| 1 | `test_connector_base.py` | 18 | CapabilityDeclaration fields, all 14 CAPABILITY_* constants, SyncCursor serialisation/deserialisation, ConnectorErrorCode enum values, WebhookVerificationResult defaults |
| 2 | `test_mock_erp_adapter.py` | 14 | MockERPAdapter capability declaration, `post_invoice()` returns synthetic reference, `fetch_inventory()` returns synthetic records, `fetch_orders()` pagination cursor, `health_check()` returns True |
| 3 | `test_csv_export_adapter.py` | 11 | CSV output format, column headers, CSV injection sanitisation for `=`, `+`, `-`, `@`, tab, and carriage return prefixes, IRR amount formatting as integers |
| 4 | `test_circuit_breaker.py` | 16 | CLOSED→OPEN transition on failure threshold, OPEN→HALF_OPEN after `next_attempt_at`, HALF_OPEN→CLOSED on probe success, HALF_OPEN→OPEN on probe failure, persistence across simulated restarts, `circuit_failure_count` increment/reset |
| 5 | `test_outbox_worker.py` | 13 | Event insertion in same transaction as business operation, exponential backoff calculation (base 2, max 3600s), dead-letter promotion after 10 failures, idempotent retry on transient errors, event ordering (created_at ascending) |
| 6 | `test_product_identity.py` | 21 | Stage 1 GTIN exact match, Stage 2 supplier SKU match with supplier_id scoping, Stage 3 MPN single match (confidence 8500), Stage 3 MPN multiple match (confidence 5000, routed to queue), Stage 4 SGTIN→GTIN decode, all identifier type values, identity_resolution_queue insertion on unresolved, batch resolution API response format |
| 7 | `test_rfid_scanner.py` | 17 | EPC decode for valid SGTIN-96, EPC decode rejection for non-SGTIN header, SGTIN component extraction (company prefix, item ref, serial), GS1 check digit calculation, warehouse_locations UPSERT on new scan, move detection when location changes, rfid_events append-only insertion, batch endpoint validation (max 500 events) |
| 8 | `test_tax_foundation.py` | 15 | Standard rate lookup returns 900 bps, rate lookup uses invoice_date not today, effective_until boundary (rate on last valid day), gap detection raises ValueError, integer arithmetic for tax calculation (no floating point), MockTaxAdapter calculate_tax, MockTaxAdapter submit_invoice returns synthetic reference, multi-line invoice tax breakdown |
| 9 | `test_not_implemented_stubs.py` | 22 | Each NOT IMPLEMENTED adapter raises `ConnectorError(NOT_IMPLEMENTED)` — Sepidar, Rahkaran, Holo, SAP, Odoo (ERP); AloPeyk, Post_IR, Tipax, Chapar (logistics); Moadian (tax). Each stub's `get_capabilities()` returns the correct `connector_id`. Each stub's `verify_webhook()` returns `verified=False` (fail-closed). |

**Total Phase 7 tests: 147**

---

## Migration Files

Phase 7 introduced three migration files, numbered sequentially from the Phase 6 baseline.

### Migration 0016: connector_accounts

**File**: `backend/migrations/0016_connector_accounts.sql`

This migration creates the infrastructure for the ConnectorAdapter v2 system.

Tables added:
- `connector_accounts` — one row per supplier-connector pair. Stores `connector_type`, `connector_label`, `credential_ref` (reference key, not the credential), and all circuit breaker columns: `circuit_state` (CLOSED/OPEN/HALF_OPEN), `circuit_failure_count`, `circuit_opened_at`, `circuit_next_attempt_at`, `circuit_success_count`.
- `integration_events` — the outbox table. Stores `event_type`, `payload_json`, `status` (pending/processing/completed/failed/dead_letter), `attempt_count`, `next_attempt_at`, `last_error`, and `supplier_id`.
- `connector_webhooks` — maps incoming webhook paths to connector accounts. Stores `webhook_path`, `secret_ref` (credential_ref to the HMAC secret), and `connector_account_id`.

Indices added: `idx_integration_events_status_next_attempt`, `idx_integration_events_supplier`, `idx_connector_accounts_supplier_type`.

### Migration 0017: product_identity

**File**: `backend/migrations/0017_product_identity.sql`

This migration creates the Product Identity Graph tables.

Tables added:
- `product_identifiers` — stores all known identifiers for each product. Columns: `product_id`, `identifier_type` (enum), `identifier_value`, `source`, `confidence_bps`, `verified_at`.
- `product_identity_links` — directed graph edges between identifiers. Columns: `from_identifier_id`, `to_identifier_id`, `link_type` (same_product/variant_of/replaces).
- `identity_resolution_queue` — identifiers that could not be automatically resolved. Columns: `raw_identifier`, `identifier_type`, `source_context` (JSON), `attempted_stages` (JSON array), `resolution_result`, `resolved_product_id`, `reviewer_id`, `reviewed_at`.
- `gtin_lookup_cache` — planned cache for GS1 Verified by GS1 lookups. Created empty; populated only when GS1 lookup is implemented.

### Migration 0018: tax_and_logistics

**File**: `backend/migrations/0018_tax_and_logistics.sql`

This migration adds tax, logistics, and RFID tables.

Tables added:
- `tax_categories` — category codes (STANDARD, REDUCED, ZERO, EXEMPT, DIGITAL_SERVICES, FOOD_BASIC) with Persian and English names.
- `tax_rates` — versioned rates with `effective_from` / `effective_until` date ranges and `legal_basis` citation text. Seeded with the 9% (900 bps) standard rate effective from 2023-03-21.
- `shipments` — logistics shipment records. Columns: `order_id`, `carrier_type`, `carrier_tracking_number`, `carrier_reference`, `idempotency_key` (UNIQUE), `status`, `price_irr`, `label_url`, `booked_at`.
- `warehouse_locations` — current location of each RFID-tagged unit. Columns: `rfid_epc` (UNIQUE), `product_id`, `location_code`, `last_seen_at`, `last_rssi_dbm`, `last_antenna_port`, `reader_id`, `move_count`.
- `rfid_events` — immutable log of RFID reads. Columns: `reader_id`, `antenna_port`, `epc_hex`, `sgtin`, `gtin`, `rssi_dbm`, `read_at`, `location_code`, `resolved_product_id`, `resolution_confidence_bps`, `resolution_stage`.

Columns added to existing tables:
- `scanner_readers.location_code` — links each reader to a warehouse zone.
- `scanner_readers.reader_type` — values: `barcode`, `rfid_fixed`, `rfid_handheld`.

---

## Adapter Implementation Status Matrix

| Adapter | Category | Status | Reason if NOT IMPLEMENTED |
|---------|----------|--------|--------------------------|
| MockERPAdapter | ERP | Simulator | Production-grade simulator |
| CSVExportAdapter | ERP | Simulator | Production-grade simulator |
| SepidarERPAdapter | ERP | NOT IMPLEMENTED | Partner API; docs require signed NDA with Sepidar Co. |
| RahkaranERPAdapter | ERP | NOT IMPLEMENTED | No public API documentation found |
| HoloERPAdapter | ERP | NOT IMPLEMENTED | No public API documentation found |
| SAPERPAdapter | ERP | NOT IMPLEMENTED | Public docs at api.sap.com exist; implementation not started |
| OdooERPAdapter | ERP | NOT IMPLEMENTED | Public docs at odoo.com/documentation/17.0 exist; implementation not started |
| MockCarrierAdapter | Logistics | Simulator | Production-grade simulator |
| AloPeykAdapter | Logistics | NOT IMPLEMENTED | Partner agreement required; no public docs |
| PostIRAdapter | Logistics | NOT IMPLEMENTED | No public API documentation found |
| TipaxAdapter | Logistics | NOT IMPLEMENTED | No public API documentation found |
| ChaparAdapter | Logistics | NOT IMPLEMENTED | No public API documentation found |
| MockTaxAdapter | Tax | Simulator | Production-grade simulator |
| MoadianAdapter | Tax | NOT IMPLEMENTED | Requires INTA registration + RSA key pair from Tax Affairs Organisation |

---

## NOT IMPLEMENTED Acknowledgments

This section explicitly acknowledges each unimplemented component and provides the authoritative reason for the deferral. This prevents any ambiguity about whether these omissions are oversights or deliberate, documented decisions.

### Sepidar ERP

The Sepidar ERP API is distributed under a partner agreement. The adapter stub (`sepidar_adapter.py`) exists and raises `ConnectorError(NOT_IMPLEMENTED)`. Implementation requires: (1) signing a partnership agreement with Sepidar Co. (شرکت سپیدار سیستم); (2) receiving the API documentation; (3) implementing against the documented endpoints.

### Rahkaran ERP

No public API documentation for Rahkaran has been located. The adapter stub exists. Implementation requires: (1) contacting Rahkaran's technical team to obtain API documentation; (2) implementing against documented endpoints.

### Holo ERP

No public REST API documentation for Holo (هلو) has been located. Holo exposes CSV/Excel export, which is covered by the CSV Export adapter. A REST API integration would require a direct agreement with the Holo vendor.

### SAP ERP

The SAP Business Accelerator Hub at `https://api.sap.com/` provides full API documentation for both SAP Business One and S/4HANA. The documentation is publicly accessible. The adapter is `NOT IMPLEMENTED` because the implementation work has not been prioritised, not because documentation is unavailable.

### Odoo ERP

The Odoo external API documentation at `https://www.odoo.com/documentation/17.0/developer/reference/external_api.html` provides a complete XML-RPC and JSON-RPC specification. The adapter is `NOT IMPLEMENTED` for the same reason as SAP: the work has not been started, not because documentation is unavailable.

### AloPeyk Logistics

AloPeyk (الوپیک) is an Iranian on-demand logistics company. Their API requires a signed partnership agreement. No public documentation is available. The adapter stub raises `ConnectorError(NOT_IMPLEMENTED)`.

### Post.ir, Tipax, Chapar Logistics

All three Iranian express carriers (Post.ir, Tipax, Chapar) either do not publish a machine-readable API or restrict API access to business partners. All three adapter stubs raise `ConnectorError(NOT_IMPLEMENTED)`.

### Moadian Tax

The Moadian (سامانه مودیان) electronic invoicing system requires: (1) INTA (اداره کل انفورماتیک) registration; (2) an RSA key pair with the public key registered with INTA; (3) access to the API specification at `https://tax.gov.ir/`. None of these prerequisites are in place as of Phase 7. The adapter stub raises `ConnectorError(NOT_IMPLEMENTED)`.

### GS1 Verified by GS1 Lookup

The `gtin_lookup_cache` table and lookup integration require a GS1 member account. The 60online platform does not have a GS1 membership as of Phase 7. The `GS1LookupAdapter` raises `ConnectorError(NOT_IMPLEMENTED)`.
