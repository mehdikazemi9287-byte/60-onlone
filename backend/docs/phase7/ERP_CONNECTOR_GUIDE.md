# ERP Connector Guide

## Introduction

This guide explains how to add a new ERP connector to the 60online platform. It covers the review-and-certification workflow, the current status of all planned ERP adapters, and a concrete implementation skeleton you can use as a starting point.

The golden rule of ERP integration in this codebase is: **never invent an API**. Iranian ERP vendors in particular often have undocumented or partner-only APIs. If you cannot find official documentation with a citable URL, the adapter ships as `NOT IMPLEMENTED`. A clearly labelled stub is safer than a fabricated endpoint that silently corrupts data.

---

## Certification Workflow

Adding a new ERP connector is a six-step process. Each step has a defined exit criterion before the next step begins.

### Step 1: Verify Official Documentation

Find the vendor's official API documentation. It must be published by the vendor, not a third-party blog or forum post. Record the exact URL and the document version or date.

For Iranian vendors (Sepidar, Rahkaran, Holo), the API documentation is typically distributed under NDA or requires a signed partner agreement. If you cannot obtain the official documentation, stop here and file a `NOT IMPLEMENTED` stub with a note explaining the documentation status.

For international vendors (SAP, Odoo), public documentation exists and is citable:
- SAP: `https://api.sap.com/` — the SAP Business Accelerator Hub hosts Business One and S/4HANA service APIs.
- Odoo: `https://www.odoo.com/documentation/17.0/developer/reference/external_api.html` — the XML-RPC and JSON-RPC external API.

### Step 2: Document URL, Version, and Authentication Method

Before writing any code, create a record in `VERIFIED_CONNECTOR_MATRIX.md` with:

- The official documentation URL.
- The API version being targeted.
- The authentication method (API key, OAuth 2.0, session cookie, XML-RPC credentials, RSA key, etc.).
- Whether a sandbox or test environment is available.

This record must be committed before Step 3. It creates an audit trail linking the code to the vendor specification it was built against.

### Step 3: Implement the Stub

Create the adapter file at `backend/integrations/erp/<vendor_slug>_adapter.py`. The stub must:

1. Inherit from `ConnectorAdapterBase`.
2. Implement `get_capabilities()` with the correct `connector_id` and `documentation_url`.
3. Raise `ConnectorError(ConnectorErrorCode.NOT_IMPLEMENTED, ...)` in every method body.
4. Include a module-level docstring citing the documentation URL and version.

This stub is what ships when official documentation exists but the implementation has not yet been written.

### Step 4: Implement the Real Adapter

Replace each `NOT_IMPLEMENTED` raise with actual HTTP calls to the vendor API. Requirements:

- Use the `requests` library with a configurable timeout (default 10 seconds).
- Map all vendor error responses to the appropriate `ConnectorErrorCode`.
- Respect `Retry-After` headers for rate-limited responses.
- Never store credentials in the adapter; always read them from the `credential_ref` passed at construction time.
- All monetary amounts passed to or received from the vendor must be converted to/from integer IRR rials before entering the 60online data layer.

### Step 5: Write Tests

Every adapter must have a corresponding test file at `backend/tests/test_<vendor_slug>_adapter.py`. Tests must cover:

- `get_capabilities()` returns the correct `connector_id` and capability list.
- Each implemented method returns the expected normalised shape when given a mocked HTTP response.
- Each vendor error code is mapped to the correct `ConnectorErrorCode`.
- `verify_webhook()` rejects payloads with invalid HMAC signatures.

Tests must run without network access. Use `responses` or `unittest.mock` to intercept HTTP calls.

### Step 6: Certify

A connector is certified when:

- All tests pass with 100% coverage of the adapter file.
- The `VERIFIED_CONNECTOR_MATRIX.md` entry shows `implementation_status = production`.
- A senior developer has reviewed the credential handling, error mapping, and currency conversion logic.
- The connector has been run against the vendor's sandbox environment (if available) and the results have been recorded.

---

## Current ERP Status Matrix

| Connector | Status | Documentation | Auth Method | Notes |
|-----------|--------|---------------|-------------|-------|
| Mock ERP | Simulator | — | None | Synthetic data; full capability set |
| CSV Export | Simulator | — | None | Exports accounting journal entries to CSV |
| Sepidar ERP | NOT IMPLEMENTED | No public docs | Partner API key (unverified) | Requires signed partner agreement with Sepidar Co. |
| Rahkaran ERP | NOT IMPLEMENTED | No public docs | Unknown | No English or Persian public API documentation found |
| Holo ERP | NOT IMPLEMENTED | No public docs | Unknown | No public API documentation found |
| SAP Business One / S/4HANA | NOT IMPLEMENTED | `https://api.sap.com/` | Session cookie / OAuth 2.0 | Public docs available; implementation not started |
| Odoo | NOT IMPLEMENTED | `https://www.odoo.com/documentation/17.0/developer/reference/external_api.html` | XML-RPC / JSON-RPC with API key | Public docs available; implementation not started |

### Notes on Iranian ERP Vendors

**Sepidar** (سپیدار): A popular Iranian ERP widely used in mid-market manufacturing and distribution. The vendor has a REST API, but it is distributed under a partner agreement and requires a signed NDA. The exact endpoint structure, authentication flow, and data model cannot be documented here without access to that agreement. Attempting to reverse-engineer the API from network captures would produce an unreliable adapter.

**Rahkaran** (ره‌کاران): Another Iranian ERP commonly used in retail and service businesses. No public API documentation has been located as of Phase 7. Integration must wait for official documentation.

**Holo** (هلو): A widely used Iranian accounting and inventory software, popular with small and medium businesses. No public REST API documentation found. The software does expose CSV/Excel export which is covered by the CSV Export adapter.

---

## Implementation Skeleton

Use this skeleton as the starting point for any new ERP adapter. Replace `VENDOR_NAME` and fill in the implementation details.

```python
"""
VENDOR_NAME ERP Adapter for 60online Phase 7.

Official API Documentation: <INSERT_URL_HERE>
API Version Targeted: <INSERT_VERSION>
Authentication: <INSERT_AUTH_METHOD>
Sandbox Available: <YES/NO>

Status: NOT IMPLEMENTED
Reason: <Explain why — e.g. "Partner API docs not yet obtained" or
         "Implementation in progress; target Q3 2026">
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from ..connector_base import (
    ConnectorAdapterBase,
    CapabilityDeclaration,
    SyncCursor,
    ConnectorError,
    ConnectorErrorCode,
    WebhookVerificationResult,
    CAPABILITY_INVENTORY_READ,
    CAPABILITY_INVENTORY_WRITE,
    CAPABILITY_ORDER_READ,
    CAPABILITY_INVOICE_POST,
    CAPABILITY_WEBHOOK_RECEIVE,
)


class VendorNameERPAdapter(ConnectorAdapterBase):
    """
    ERP adapter for VENDOR_NAME.

    This class is a NOT IMPLEMENTED stub. Every public method raises
    ConnectorError(NOT_IMPLEMENTED) until the implementation is written
    against the official API documentation.

    Parameters
    ----------
    credential_ref : str
        Reference key used to look up the encrypted API credentials
        from the secrets store. Never pass the raw credential value.
    base_url : str
        The vendor API base URL. For example, the self-hosted Odoo
        instance URL or the SAP Business One service layer URL.
    timeout : int
        HTTP request timeout in seconds. Defaults to 10.
    """

    CONNECTOR_ID = "vendor_name_erp"
    DISPLAY_NAME = "VENDOR_NAME ERP"
    API_VERSION = "unknown"
    DOCS_URL = ""

    def __init__(
        self,
        credential_ref: str,
        base_url: str = "",
        timeout: int = 10,
    ):
        self._credential_ref = credential_ref
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def get_capabilities(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(
            connector_id=self.CONNECTOR_ID,
            display_name=self.DISPLAY_NAME,
            capabilities=[
                CAPABILITY_INVENTORY_READ,
                CAPABILITY_ORDER_READ,
                CAPABILITY_INVOICE_POST,
                CAPABILITY_WEBHOOK_RECEIVE,
            ],
            api_version=self.API_VERSION,
            requires_credentials=True,
            supports_sandbox=False,
            documentation_url=self.DOCS_URL,
        )

    def health_check(self) -> bool:
        # TODO: Implement a lightweight ping to the vendor's health endpoint.
        # Until implemented, always return False to prevent the circuit
        # breaker from treating this connector as healthy.
        return False

    def fetch_inventory(
        self,
        cursor: SyncCursor,
        page_size: int = 100,
    ) -> Tuple[List[Dict[str, Any]], SyncCursor]:
        raise ConnectorError(
            ConnectorErrorCode.NOT_IMPLEMENTED,
            f"{self.DISPLAY_NAME} inventory sync is not yet implemented. "
            f"See {self.DOCS_URL} for the API specification.",
        )

    def fetch_orders(
        self,
        cursor: SyncCursor,
        page_size: int = 50,
    ) -> Tuple[List[Dict[str, Any]], SyncCursor]:
        raise ConnectorError(
            ConnectorErrorCode.NOT_IMPLEMENTED,
            f"{self.DISPLAY_NAME} order sync is not yet implemented.",
        )

    def post_invoice(self, invoice: Dict[str, Any]) -> str:
        raise ConnectorError(
            ConnectorErrorCode.NOT_IMPLEMENTED,
            f"{self.DISPLAY_NAME} invoice posting is not yet implemented.",
        )

    def verify_webhook(
        self,
        headers: Dict[str, str],
        raw_body: bytes,
        secret: str,
    ) -> WebhookVerificationResult:
        # Fail-closed: reject all webhooks until verification is implemented.
        return WebhookVerificationResult(verified=False)

    def _resolve_credentials(self) -> Dict[str, str]:
        """
        Look up the actual credentials from the secrets store using
        self._credential_ref. This method must never be called on a
        NOT IMPLEMENTED adapter in production.

        Returns a dict with vendor-specific keys, e.g.:
          {"api_key": "...", "company_db": "..."}
        """
        # TODO: Integrate with the credential store in Phase 8.
        raise ConnectorError(
            ConnectorErrorCode.AUTH_FAILURE,
            "Credential resolution not yet implemented for this adapter.",
        )
```

---

## CSV Export Adapter (Simulator)

The CSV Export adapter is a production-grade simulator that exports invoice and payment data to CSV files. It is useful when an ERP system can accept CSV uploads but does not have a REST API. It is also the fallback adapter for any ERP whose API integration has not been implemented.

The adapter protects against CSV injection by prefixing any cell that begins with `=`, `+`, `-`, or `@` with a single apostrophe. This prevents a crafted product name or invoice note from executing arbitrary formulas when the exported file is opened in Microsoft Excel or LibreOffice Calc.

See `INTEGRATION_SECURITY.md` for the full CSV injection protection specification.
