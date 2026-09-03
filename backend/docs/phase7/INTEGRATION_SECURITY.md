# Integration Security

## Introduction

The Phase 7 integration layer connects 60online to external systems: ERP software, the tax authority, logistics carriers, and product registries. Each of these connections introduces a new attack surface. This document describes the security controls applied at every layer of the integration stack, from credential storage to webhook ingestion to data export.

The guiding principle is **fail-closed**: when in doubt about whether an operation is safe, the system rejects it. Accepting an unverified webhook, guessing a vendor endpoint, or exposing one tenant's data to another are all failure modes that closed defaults prevent.

---

## Tenant Isolation

Every resource in the integration layer is scoped to a `supplier_id`. No query, no adapter method, and no API endpoint may access integration data belonging to a different supplier.

### connector_accounts Isolation

```sql
-- CORRECT: always filter by supplier_id
SELECT * FROM connector_accounts
WHERE supplier_id = ? AND connector_type = ?;

-- WRONG: missing supplier_id filter allows cross-tenant access
SELECT * FROM connector_accounts WHERE connector_type = ?;
```

The `connector_accounts` table enforces this at the schema level with a composite unique constraint:

```sql
UNIQUE(supplier_id, connector_type, connector_label)
```

This prevents a single supplier from registering duplicate connectors of the same type, but more importantly it creates a natural index that makes supplier-scoped queries the obvious default.

### integration_events Isolation

The `integration_events` outbox table is similarly scoped. The outbox worker always filters by `supplier_id` when processing events, and it passes the `supplier_id` to every adapter call so the adapter can scope its credential lookup accordingly.

### API Layer Enforcement

Flask route handlers extract the authenticated `supplier_id` from the JWT and pass it explicitly to every service function. Service functions never accept a `supplier_id` from the request body or query string — they always use the value from the authenticated session.

```python
@bp.route("/connector-accounts", methods=["GET"])
@require_supplier_auth
def list_connector_accounts(supplier_id: int):
    # supplier_id comes from the auth decorator, not from request args
    accounts = get_connector_accounts(db=get_db(), supplier_id=supplier_id)
    return jsonify(accounts)
```

---

## Credential Management

### The credential_ref Pattern

Connector credentials (API keys, passwords, OAuth tokens, RSA private keys) are never stored in the `connector_accounts` table. The table stores only a `credential_ref`: an opaque reference key that points to the credential in an external secrets store.

```sql
-- connector_accounts schema (Phase 7)
CREATE TABLE connector_accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id     INTEGER NOT NULL REFERENCES suppliers(id),
    connector_type  TEXT NOT NULL,
    connector_label TEXT NOT NULL DEFAULT 'default',
    -- Reference key only. Never the actual credential.
    credential_ref  TEXT,
    ...
);
```

In the Phase 7 deployment (single-server, development-grade), the secrets store is an environment variable map keyed by `credential_ref`. In a production deployment, this would be replaced by a dedicated secrets manager (HashiCorp Vault, AWS Secrets Manager, or equivalent).

The adapter receives the `credential_ref` at construction time and calls `_resolve_credentials(credential_ref)` only at the moment of the API call. The resolved credential is never logged, never returned from an API endpoint, and never stored in a database column.

### Credential Rotation

When a credential is rotated, only the secrets store entry needs to change. The `connector_accounts.credential_ref` value stays the same if the reference key is stable. This means that credential rotation does not require a database migration or a connector account update — the adapter picks up the new value on its next call.

### Logging Policy

The integration layer never logs the following values:
- API keys or bearer tokens
- Passwords or shared secrets
- RSA private key material
- HMAC signing secrets

Log messages that would otherwise include these values must substitute the `credential_ref` or a redacted placeholder. The logging middleware applies a regex-based scrubber to catch accidental credential leakage.

---

## Webhook Security

### HMAC-SHA256 Verification

All incoming webhooks must be verified before the payload is processed. The standard method is HMAC-SHA256 over the raw request body:

```python
import hashlib
import hmac
from flask import request, abort

def verify_webhook_hmac(raw_body: bytes, secret: str, signature_header: str) -> bool:
    """
    Verify an HMAC-SHA256 webhook signature.

    Parameters
    ----------
    raw_body : bytes
        The unmodified request body. Must be read before JSON parsing,
        because JSON parsing may reorder keys.
    secret : str
        The shared HMAC signing secret (from the credential store).
    signature_header : str
        The signature value from the request header (e.g. X-Carrier-Signature).
        May be prefixed with 'sha256=' depending on the vendor convention.

    Returns
    -------
    bool
        True only if the computed digest matches the provided signature.
        Uses hmac.compare_digest to prevent timing attacks.
    """
    sig = signature_header.lstrip("sha256=")
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(sig, expected)
```

### Fail-Closed Default

The base `ConnectorAdapterBase.verify_webhook()` method returns `WebhookVerificationResult(verified=False)`. Adapters that do not override this method will reject all webhooks. This is intentional: a connector that has not implemented webhook verification is safer failing closed than accepting unverified payloads.

The webhook endpoint returns `HTTP 401 Unauthorized` for any webhook that fails verification. It does not return `200 OK` with an error body, because some vendor retry systems interpret any 2xx as a successful delivery.

### Replay Attack Prevention

Webhook handlers check the `idempotency_key` from `WebhookVerificationResult` against the `integration_events` table before processing. If an event with the same key has already been processed, the handler returns `HTTP 200` (to suppress the vendor's retry) but does not reprocess the payload. This prevents duplicate deliveries from triggering duplicate side effects.

---

## CSV Injection Protection

The CSV Export adapter converts invoice and payment data to CSV files that may be opened in Microsoft Excel or LibreOffice Calc. Both programs treat cells beginning with `=`, `+`, `-`, or `@` as formula expressions, which creates a risk of formula injection if product names or descriptions contain these characters.

The adapter sanitises every cell value before writing:

```python
_CSV_INJECTION_PREFIXES = ('=', '+', '-', '@', '\t', '\r')

def sanitise_csv_cell(value: str) -> str:
    """
    Prevent CSV formula injection by prefixing dangerous cell values
    with a single apostrophe. The apostrophe causes Excel and Calc to
    treat the cell as a literal string, not a formula.

    This protection applies to all user-supplied string values:
    product names, invoice notes, customer names, address fields.
    """
    if value and value[0] in _CSV_INJECTION_PREFIXES:
        return "'" + value
    return value
```

This protection is applied unconditionally to all string values. Numeric columns (amounts, quantities, IDs) are never passed through this function because they are formatted as integers, not strings.

---

## The NOT FABRICATED Rule

No adapter in the 60online codebase may invent a vendor API endpoint, authentication mechanism, or data format. Every claim about a vendor's API must be traceable to a cited official source.

This rule exists because fabricated integrations create a specific class of failure: they appear to work in development (with mock servers or unit tests) but fail silently or destructively in production when they encounter a real vendor system.

The enforcement mechanism is the `VERIFIED_CONNECTOR_MATRIX.md` file. Every connector must have an entry in this file. The entry must include the `documentation_url` field. If no official documentation URL can be provided, the `implementation_status` must be `not_implemented`.

Attempting to merge a connector with a fabricated endpoint or a `documentation_url` pointing to unofficial sources (forums, blog posts, reverse-engineered specifications) is a review rejection criterion.

---

## Security Checklist for New Connectors

Before a new connector can be merged into the main branch, the following security requirements must be verified by a reviewer:

- [ ] Credentials are stored as `credential_ref` only; no plaintext secrets in the database.
- [ ] All API calls use the `credential_ref` resolution pattern; resolved credentials are never logged.
- [ ] The `verify_webhook()` method is implemented for any adapter declaring `CAPABILITY_WEBHOOK_RECEIVE`.
- [ ] Webhook handler uses `hmac.compare_digest()`, not `==`, for signature comparison.
- [ ] Idempotency keys are checked before processing webhook payloads.
- [ ] All database queries include a `supplier_id` filter.
- [ ] The connector entry in `VERIFIED_CONNECTOR_MATRIX.md` includes a valid official documentation URL (or is marked `not_implemented`).
- [ ] No endpoint URL, authentication parameter, or data schema was inferred or fabricated without an official source.
- [ ] CSV export cells are sanitised with `sanitise_csv_cell()` for all string values.
- [ ] The HTTP client uses a connection timeout (default: 10 seconds) to prevent adapter calls from blocking indefinitely.
