# Phase 7 Architecture: Universal Integration & Automation Hub

## Overview

Phase 7 transforms 60online from a standalone e-commerce backend into a Universal Integration & Automation Hub. The goal is to connect the platform to the broader ecosystem of Iranian and international business software: ERP systems, tax authorities, logistics carriers, barcode/RFID hardware, and product identity registries.

Every integration is designed around a strict "no fabrication" policy. If an official API specification cannot be found or verified, the adapter is shipped as `NOT IMPLEMENTED` with a clearly documented reason. This prevents subtle data corruption or phantom integrations that appear to work in tests but fail silently in production.

The platform remains grounded in its Phase 1–6 foundations: Flask, SQLite with WAL journal mode, raw SQL over an integer minor-unit ledger (all monetary amounts in IRR rials, stored as plain integers), and a migration-numbered schema versioned from 0001 through 0018.

---

## Component Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                        60online Backend                             │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐    │
│  │  Order API   │   │ Product API  │   │   Scanner / RFID API │    │
│  └──────┬───────┘   └──────┬───────┘   └──────────┬───────────┘    │
│         │                  │                        │               │
│         └──────────────────┼────────────────────────┘               │
│                            │                                        │
│                   ┌────────▼────────┐                               │
│                   │  Event Service  │  (integration_events outbox)  │
│                   └────────┬────────┘                               │
│                            │                                        │
│          ┌─────────────────┼──────────────────┐                     │
│          │                 │                  │                     │
│  ┌───────▼──────┐  ┌───────▼──────┐  ┌───────▼──────┐             │
│  │  Accounting  │  │     Tax      │  │  Logistics   │             │
│  │   Service    │  │   Service    │  │   Service    │             │
│  └───────┬──────┘  └───────┬──────┘  └───────┬──────┘             │
│          │                 │                  │                     │
│  ┌───────▼──────┐  ┌───────▼──────┐  ┌───────▼──────┐             │
│  │  ERP Adapter │  │  Tax Adapter │  │  Carrier     │             │
│  │  (v2 API)    │  │  (v2 API)    │  │  Adapter v2  │             │
│  └───────┬──────┘  └───────┬──────┘  └───────┬──────┘             │
│          │                 │                  │                     │
│  ┌───────▼──────────────────▼──────────────────▼──────┐            │
│  │              Circuit Breaker Layer                  │            │
│  │  (CLOSED / OPEN / HALF_OPEN persisted in DB)        │            │
│  └──────────────────────────┬──────────────────────────┘            │
│                             │                                       │
│                    External Vendors                                 │
│          (Sepidar, Rahkaran, Moadian, AloPeyk, etc.)               │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│         Product Identity Graph          │
│                                         │
│  Identifier types: GTIN8/12/13/14,      │
│  UPC, EAN, ISBN, SUPPLIER_SKU,          │
│  ERP_CODE, MPN, RFID_EPC, SGTIN, …     │
│                                         │
│  4-Stage Resolution Pipeline            │
│  Stage 1: Global GTIN                   │
│  Stage 2: Supplier SKU                  │
│  Stage 3: MPN                           │
│  Stage 4: RFID / QR fallback            │
└─────────────────────────────────────────┘
```

---

## Data Flow: Order to ERP Sync

```
Order placed (Order API)
        │
        ▼
integration_events INSERT  ──►  outbox worker polls every 30s
        │
        ▼
EventService.dispatch(event)
        │
        ├──► AccountingAdapter.post_invoice(invoice_payload)
        │            │
        │            ▼
        │       CircuitBreaker.call()
        │            │
        │       [CLOSED] ──► HTTP to ERP
        │       [OPEN]   ──► raise ConnectorError(CIRCUIT_OPEN)
        │       [HALF_OPEN] ──► single probe request
        │
        └──► TaxAdapter.submit_invoice(tax_payload)
                     │
                     ▼
               [MockTaxAdapter] returns simulated acknowledgement
               [MoadianAdapter] NOT IMPLEMENTED
```

---

## Data Flow: RFID Scan to Inventory Update

```
Scanner hardware → POST /api/v1/scanner/rfid-event
        │
        ▼
Parse EPC → decode SGTIN (Company prefix + Item ref + Serial)
        │
        ▼
Product Identity Graph: resolve SGTIN → internal product_id
        │  Stage 1: exact GTIN match in product_identifiers
        │  Stage 2: supplier SKU cross-reference
        │  Stage 3: MPN match
        │  Stage 4: manual queue if unresolved
        │
        ▼
Update warehouse_locations (last_seen_location, last_seen_at, rssi)
        │
        ▼
Emit inventory.rfid_seen event → outbox
```

---

## Technology Choices

### Flask and Raw SQL

Phase 7 continues the project-wide decision to avoid ORM abstraction. All database interaction is raw SQL through a thin `get_db()` helper, which returns a SQLite connection with WAL journal mode and foreign key enforcement enabled. This keeps query plans explicit and migration reasoning straightforward.

SQLite WAL mode is critical for Phase 7 because the outbox worker and the HTTP request handlers write concurrently. WAL allows readers to proceed without blocking writers, preventing timeout cascades during burst event processing.

### Integer Minor Units for Money

All monetary values are stored and computed as plain integers representing Iranian Rials. There are no fractional units. Tax amounts, invoice totals, and logistics fees are all integers. This eliminates floating-point rounding errors that would otherwise accumulate across multi-line invoices.

### ConnectorAdapter v2

The v2 adapter contract was designed in Phase 7 to replace the ad-hoc integration code from earlier phases. It introduces `CapabilityDeclaration`, `SyncCursor`, and a structured `ConnectorError` hierarchy. Every adapter — whether a real vendor implementation or a simulator — must implement this contract. See `CONNECTOR_CONTRACT_V2.md` for the full specification.

### Circuit Breaker Persistence

Unlike in-memory circuit breakers (common in JVM frameworks), the 60online circuit breaker state is stored in the `connector_accounts` table. The columns `circuit_state`, `circuit_failure_count`, `circuit_opened_at`, and `circuit_next_attempt_at` persist across process restarts. This is essential for a single-process Flask deployment where there is no shared in-memory state between Gunicorn workers.

### Outbox / Inbox Pattern

Integration events are written to the `integration_events` table in the same SQLite transaction as the business operation. A background worker polls this table and dispatches events to adapters. Failed deliveries are retried with exponential backoff (base 2, capped at 3600 seconds). After 10 consecutive failures, events are promoted to dead-letter status. This pattern guarantees at-least-once delivery without requiring a separate message broker.

---

## Design Principles

**1. No Fabricated Vendor Contracts.** If the official API specification for a vendor has not been reviewed and cited, the adapter is marked `NOT IMPLEMENTED`. The connector matrix (`VERIFIED_CONNECTOR_MATRIX.md`) is the authoritative record of what is and is not implemented.

**2. Fail-Closed on Ambiguity.** Webhook verification defaults to rejection if the signature cannot be validated. The circuit breaker defaults to OPEN (failing fast) rather than CLOSED (optimistic). Product identity resolution that cannot reach a high-confidence match routes to human review rather than silently guessing.

**3. Historical Reproducibility.** Tax rates are stored with `effective_from` / `effective_until` date ranges. Invoice tax is always computed using the invoice date, never today's date. This allows any historical invoice to be recomputed identically months or years later.

**4. Tenant Isolation.** Each `connector_account` row is scoped to a `supplier_id`. No query or adapter method may access another tenant's credentials or events. See `INTEGRATION_SECURITY.md`.

**5. Schema Migrations are Append-Only.** Migrations 0016, 0017, and 0018 add new tables and columns. No existing column has been removed or renamed since Phase 1. Rollback is achieved by deploying the previous application version; the database schema is forward-only.

---

## Migration History (Phase 7)

| Migration | File | Purpose |
|-----------|------|---------|
| 0016 | `0016_connector_accounts.sql` | Adds `connector_accounts`, `integration_events`, `connector_webhooks` tables and circuit breaker columns |
| 0017 | `0017_product_identity.sql` | Adds `product_identifiers`, `product_identity_links`, `identity_resolution_queue` tables |
| 0018 | `0018_tax_and_logistics.sql` | Adds `tax_categories`, `tax_rates`, `shipments`, `warehouse_locations`, `rfid_events` tables |

---

## Phase 7 Sub-System Documentation Index

| Document | Description |
|----------|-------------|
| `CONNECTOR_CONTRACT_V2.md` | Full v2 adapter contract and error semantics |
| `ERP_CONNECTOR_GUIDE.md` | How to add and certify ERP connectors |
| `LOGISTICS_CONNECTOR_GUIDE.md` | Carrier adapter contract and carrier status |
| `PRODUCT_IDENTITY_GUIDE.md` | Identity graph and 4-stage resolution |
| `SCANNER_RFID_GUIDE.md` | RFID hardware integration and scan-to-locate |
| `TAX_INTEGRATION_FOUNDATION.md` | Tax categories, rates, Moadian overview |
| `INTEGRATION_SECURITY.md` | Tenant isolation, credential hygiene, webhook security |
| `PHASE7_AUDIT_EVIDENCE.md` | Test counts, migration evidence, status matrix |
| `VERIFIED_CONNECTOR_MATRIX.md` | Complete connector status table |
