# Verified Connector Matrix

## Purpose

This document is the authoritative record of every connector integrated (or planned for integration) in the 60online Phase 7 platform. Each row in the tables below must be kept up to date as connectors are implemented, deprecated, or their status changes.

The `Implementation Status` column uses the following values:

| Status | Meaning |
|--------|---------|
| `production` | Fully implemented, tested, and in active use. |
| `simulator` | A mock/stub that implements the full contract with synthetic data. No real vendor connection. Safe to use in development and testing. |
| `not_implemented` | A stub that raises `ConnectorError(NOT_IMPLEMENTED)`. Must not be used in production. |
| `deprecated` | Previously implemented; now removed or superseded. Do not use. |

The `Official Docs URL` column must contain a verifiable URL to the vendor's official API documentation, or one of these explicit placeholders:
- `no_public_docs` — Vendor does not publish public API documentation.
- `partner_only` — Documentation exists but is distributed only to signed partners.
- `registration_required` — Documentation is available but requires account registration to access.

---

## ERP and Accounting Connectors

These connectors implement the `ConnectorAdapterBase` interface and post invoices, sync inventory, and fetch orders from ERP and accounting systems.

| Connector Name | Type | Implementation Status | Official Docs URL | Auth Method | Sandbox Available |
|----------------|------|-----------------------|-------------------|-------------|-------------------|
| MANUAL | ERP / Internal | production | — | None (internal) | N/A |
| MOCK_ERP | ERP | simulator | — | None | N/A |
| CSV_IMPORT | ERP | simulator | — | None (file upload) | N/A |
| SEPIDAR_ERP | ERP | not_implemented | `partner_only` | Partner API key (unverified) | Unknown |
| RAHKARAN_ERP | ERP | not_implemented | `no_public_docs` | Unknown | Unknown |
| HOLO_ERP | ERP | not_implemented | `no_public_docs` | Unknown | Unknown |
| SAP_ERP | ERP | not_implemented | `https://api.sap.com/` | Session cookie / OAuth 2.0 | Yes (SAP Business Technology Platform trial) |
| ODOO_ERP | ERP | not_implemented | `https://www.odoo.com/documentation/17.0/developer/reference/external_api.html` | XML-RPC or JSON-RPC with API key | Yes (Odoo Online free trial) |

### Accounting Subsystems

These are the accounting-specific adapter implementations within the ERP connector framework.

| Adapter | Status | Official Docs URL | Notes |
|---------|--------|-------------------|-------|
| MOCK (accounting simulator) | simulator | — | Full invoice and payment simulation |
| CSV (accounting export) | simulator | — | Exports double-entry journal CSV; CSV injection protected |
| SEPIDAR (accounting) | not_implemented | `partner_only` | Same restriction as SEPIDAR_ERP |
| RAHKARAN (accounting) | not_implemented | `no_public_docs` | Same restriction as RAHKARAN_ERP |
| HOLO (accounting) | not_implemented | `no_public_docs` | Same restriction as HOLO_ERP |
| SAP (accounting) | not_implemented | `https://api.sap.com/` | SAP Business One Service Layer covers accounting |
| ODOO (accounting) | not_implemented | `https://www.odoo.com/documentation/17.0` | Odoo Accounting module accessible via external API |

---

## Logistics / Carrier Connectors

These connectors implement the `CarrierAdapterBase` interface and provide quote retrieval, shipment booking, cancellation, tracking, and webhook ingestion.

| Connector Name | Type | Implementation Status | Official Docs URL | Auth Method | Sandbox Available | Notes |
|----------------|------|-----------------------|-------------------|-------------|-------------------|-------|
| MOCK_CARRIER | Carrier | simulator | — | None | N/A | Synthetic tracking data; HMAC verification with test secret |
| ALOPEYK | Carrier | not_implemented | `partner_only` | Partner client ID + secret | Unknown | AloPeyk (الوپیک) on-demand logistics. API requires signed partnership agreement. |
| POST_IR | Carrier | not_implemented | `no_public_docs` | Unknown | Unknown | Iran Post (پست ایران) national carrier. No machine-readable public API found. |
| TIPAX | Carrier | not_implemented | `no_public_docs` | Unknown | Unknown | Tipax (تیپاکس) express parcel. No public API documentation found. |
| CHAPAR | Carrier | not_implemented | `no_public_docs` | Unknown | Unknown | Chapar (چاپار) express parcel. No public API documentation found. |

---

## Tax Authority Connectors

These connectors implement the `TaxAdapterBase` interface and handle tax calculation, invoice submission, and status retrieval.

| Connector Name | Type | Implementation Status | Official Docs URL | Auth Method | Sandbox Available | Notes |
|----------------|------|-----------------------|-------------------|-------------|-------------------|-------|
| MOCK_TAX | Tax | simulator | — | None | N/A | Full tax calculation simulation; standard 9% VAT applied from tax_rates table |
| MOADIAN | Tax | not_implemented | `registration_required` (`https://tax.gov.ir/`) | RSA key pair (INTA-registered) | Unknown | Iran's mandatory e-invoicing system. Requires INTA registration by a legal representative. RSA key must be registered with the Tax Affairs Organisation. |

---

## Product Identity and Registry Connectors

These connectors look up product information from external registries and barcode databases.

| Connector Name | Type | Implementation Status | Official Docs URL | Auth Method | Sandbox Available | Notes |
|----------------|------|-----------------------|-------------------|-------------|-------------------|-------|
| GS1_LOOKUP | Product Registry | not_implemented | `https://www.gs1.org/services/verified-by-gs1` | GS1 member account + API key | Unknown | GS1 Verified by GS1 REST API. Requires active GS1 membership. Iranian GTINs may require lookup through GS1 Iran (Iran's GS1 Member Organisation) rather than the global service. |

---

## Connector Capability Matrix

The following table maps each connector to the CAPABILITY_* constants it declares (or will declare when implemented).

| Connector | inventory_read | inventory_write | order_read | order_write | order_status_push | invoice_post | payment_read | tax_calculate | tax_submit | tax_status_read | shipment_create | shipment_track | shipment_cancel | webhook_receive |
|-----------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| MANUAL | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| MOCK_ERP | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ | — | — | — | — | — | — | — |
| CSV_IMPORT | — | — | — | — | — | ✓ | — | — | — | — | — | — | — | — |
| SEPIDAR_ERP | * | * | * | — | * | * | * | — | — | — | — | — | — | * |
| RAHKARAN_ERP | * | * | * | — | — | * | * | — | — | — | — | — | — | — |
| HOLO_ERP | * | * | — | — | — | * | * | — | — | — | — | — | — | — |
| SAP_ERP | * | * | * | * | * | * | * | — | — | — | — | — | — | * |
| ODOO_ERP | * | * | * | * | * | * | * | — | — | — | — | — | — | * |
| MOCK_CARRIER | — | — | — | — | — | — | — | — | — | — | ✓ | ✓ | ✓ | ✓ |
| ALOPEYK | — | — | — | — | — | — | — | — | — | — | * | * | * | * |
| POST_IR | — | — | — | — | — | — | — | — | — | — | * | * | * | — |
| TIPAX | — | — | — | — | — | — | — | — | — | — | * | * | * | — |
| CHAPAR | — | — | — | — | — | — | — | — | — | — | * | * | * | — |
| MOCK_TAX | — | — | — | — | — | — | — | ✓ | ✓ | ✓ | — | — | — | — |
| MOADIAN | — | — | — | — | — | — | — | * | * | * | — | — | — | — |

**Legend**: ✓ = implemented and tested | * = planned (connector is NOT IMPLEMENTED) | — = not applicable

---

## Connector Change Log

| Date | Connector | Change | Author |
|------|-----------|--------|--------|
| 2026-08-08 | All Phase 7 connectors | Initial matrix created; all NOT IMPLEMENTED stubs registered | Phase 7 team |
| 2026-08-08 | MOCK_ERP | Simulator promoted to production-grade after test suite passes | Phase 7 team |
| 2026-08-08 | CSV_IMPORT | CSV injection protection verified; simulator promoted to production-grade | Phase 7 team |
| 2026-08-08 | MOCK_CARRIER | Full carrier contract implemented in simulator; webhook HMAC verified | Phase 7 team |
| 2026-08-08 | MOCK_TAX | Tax calculation verified against integer arithmetic invariant | Phase 7 team |

---

## How to Update This Document

When a connector's status changes, update the relevant row in the tables above and add an entry to the Connector Change Log. Do not remove rows for connectors whose status has changed; update the `Implementation Status` column instead. Rows for fully deprecated connectors should be marked `deprecated`, not deleted.

When a previously `not_implemented` connector reaches `production` status, the following additional updates are required:

1. Verify that the `Official Docs URL` field points to the specific API version that was implemented.
2. Confirm that `PHASE7_AUDIT_EVIDENCE.md` or the equivalent audit document for the phase in which it was implemented has been updated.
3. Ensure that the capability matrix row is updated to replace `*` with `✓` for all implemented capabilities.
4. Confirm that the test file for the connector is listed in the audit evidence document with an accurate test count.
