# Tax Integration Foundation

## Introduction

Phase 7 establishes the foundational data model and adapter interface for tax calculation and electronic invoice submission in the Iranian market. The design addresses two requirements that are in tension: the need to compute taxes correctly for new invoices, and the need to reproduce the exact tax calculation of any historical invoice months or years later.

The solution is a versioned tax rate table with effective date ranges. No tax calculation ever uses "today's date" to look up a rate. Every invoice carries its own `invoice_date`, and the rate lookup always uses that date. This single invariant, if consistently enforced, makes the entire tax calculation layer historically reproducible.

---

## Iranian VAT Overview

Iran levies a Value Added Tax (VAT) governed by قانون مالیات بر ارزش افزوده (the Value Added Tax Act). The standard rate has been revised several times since the law's original passage in 1387 (2008). As of 1403 (2024), the standard rate is **9%**, which is stored in the system as **900 basis points**.

The tax is administered by the Sazman-e Amoor-e Maliyati (سازمان امور مالیاتی کشور — Iran's Tax Affairs Organisation). The organisation operates two systems relevant to 60online:

1. **Traditional VAT declaration** — periodic (seasonal) VAT returns filed by businesses. This is handled by accounting adapters posting summarised figures to the ERP.

2. **Moadian (سامانه مودیان)** — Iran's mandatory real-time e-invoicing system. Every sales invoice above a threshold must be submitted to Moadian within a defined window. **This is NOT IMPLEMENTED in Phase 7.** See the Moadian section below.

---

## Database Schema

### tax_categories

```sql
CREATE TABLE tax_categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    name_fa     TEXT NOT NULL,
    name_en     TEXT NOT NULL,
    description TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Seed data (inserted in migration 0018)
INSERT INTO tax_categories (code, name_fa, name_en, description) VALUES
('STANDARD',        'استاندارد',        'Standard',         'Standard Iranian VAT rate'),
('REDUCED',         'کاهش‌یافته',      'Reduced',          'Reduced rate for specific goods'),
('ZERO',            'صفر',              'Zero-rated',       'Taxable but at 0% (exportable goods)'),
('EXEMPT',          'معاف',             'Exempt',           'Not subject to VAT'),
('DIGITAL_SERVICES','خدمات دیجیتال',   'Digital Services', 'Digital goods and services'),
('FOOD_BASIC',      'مواد غذایی اساسی','Basic Food',       'Unprocessed staple foods');
```

### tax_rates

```sql
CREATE TABLE tax_rates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tax_category_id INTEGER NOT NULL REFERENCES tax_categories(id),
    -- Rate in basis points (bps). 900 = 9.00%
    rate_bps        INTEGER NOT NULL,
    -- The date from which this rate applies (inclusive), YYYY-MM-DD
    effective_from  TEXT NOT NULL,
    -- The date until which this rate applies (inclusive). NULL = still current.
    effective_until TEXT,
    -- Free-text citation of the legal basis for this rate
    legal_basis     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    -- Constraint: no two active rates for the same category should overlap
    CHECK(effective_until IS NULL OR effective_until >= effective_from)
);

-- Standard 9% VAT rate, effective from 1402-01-01 (March 21, 2023)
INSERT INTO tax_rates (tax_category_id, rate_bps, effective_from, legal_basis)
SELECT id, 900, '2023-03-21',
       'قانون مالیات بر ارزش افزوده - نرخ 9 درصد - مصوب مجلس شورای اسلامی'
FROM tax_categories WHERE code = 'STANDARD';

INSERT INTO tax_rates (tax_category_id, rate_bps, effective_from, legal_basis)
SELECT id, 0, '2023-03-21', 'Zero-rated under Iranian VAT law'
FROM tax_categories WHERE code IN ('ZERO', 'EXEMPT', 'FOOD_BASIC');
```

---

## Critical Invariant: Use Invoice Date, Never Today's Date

This invariant must be enforced at every call site. It is not optional.

```python
# CORRECT
rate = get_tax_rate(category_code='STANDARD', as_of_date=invoice.invoice_date)

# WRONG — breaks historical reproducibility
rate = get_tax_rate(category_code='STANDARD', as_of_date=date.today())
```

### Rate Lookup Function

```python
from datetime import date
from typing import Optional

def get_tax_rate(
    db,
    category_code: str,
    as_of_date: str,  # YYYY-MM-DD string matching invoice_date
) -> int:
    """
    Return the tax rate in basis points for the given category on the given date.

    Parameters
    ----------
    db : sqlite3.Connection
        Active database connection.
    category_code : str
        One of: STANDARD, REDUCED, ZERO, EXEMPT, DIGITAL_SERVICES, FOOD_BASIC.
    as_of_date : str
        The invoice date in YYYY-MM-DD format. Must come from the invoice,
        never from datetime.date.today() or datetime.datetime.now().

    Returns
    -------
    int
        Rate in basis points. 900 = 9.00%. 0 = zero-rated or exempt.

    Raises
    ------
    ValueError
        If no rate is found for the given category and date combination.
        This indicates a gap in the tax_rates table that must be filled.
    """
    row = db.execute(
        """
        SELECT tr.rate_bps
        FROM tax_rates tr
        JOIN tax_categories tc ON tc.id = tr.tax_category_id
        WHERE tc.code = ?
          AND tr.effective_from <= ?
          AND (tr.effective_until IS NULL OR tr.effective_until >= ?)
        ORDER BY tr.effective_from DESC
        LIMIT 1
        """,
        (category_code, as_of_date, as_of_date),
    ).fetchone()

    if row is None:
        raise ValueError(
            f"No tax rate found for category '{category_code}' on date '{as_of_date}'. "
            f"Check the tax_rates table for coverage gaps."
        )

    return row[0]
```

### Tax Calculation

```python
def calculate_tax_irr(
    line_total_irr: int,
    category_code: str,
    invoice_date: str,
    db,
) -> int:
    """
    Calculate the tax amount in integer Iranian Rials.

    All arithmetic is integer arithmetic. There is no floating-point
    division anywhere in this function. The rate is divided by 10000
    (basis points denominator) using integer division, which rounds
    toward zero. This matches the rounding convention used in the
    Moadian specification.

    Parameters
    ----------
    line_total_irr : int
        The pre-tax line total in integer IRR rials.
    category_code : str
        Tax category code.
    invoice_date : str
        Invoice date in YYYY-MM-DD. Used for rate lookup. Never pass today's date.

    Returns
    -------
    int
        Tax amount in integer IRR rials.
    """
    rate_bps = get_tax_rate(db, category_code, invoice_date)
    # Integer arithmetic: (line_total * rate_bps) // 10000
    return (line_total_irr * rate_bps) // 10000
```

---

## TaxAdapter Contract

```python
from abc import ABC, abstractmethod
from typing import Any, Dict

class TaxAdapterBase(ABC):
    """
    Abstract base for all Phase 7 tax adapters.

    Two adapters exist in Phase 7:
    - MockTaxAdapter: simulator for development and testing
    - MoadianAdapter: NOT IMPLEMENTED (requires INTA registration + RSA key)
    """

    @abstractmethod
    def calculate_tax(self, invoice: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate the tax breakdown for an invoice.

        The adapter may apply vendor-specific rounding or line-item
        aggregation rules that differ from the local calculation.
        For MockTaxAdapter, this simply applies the rate_bps from the
        tax_rates table. For Moadian, this would apply INTA's calculation
        rules if they differ from the local rules.

        Parameters
        ----------
        invoice : dict
            Must include invoice_date, line_items (each with
            amount_irr and tax_category_code).

        Returns
        -------
        dict
            tax_amount_irr (int), rate_bps (int), breakdown (list)
        """
        ...

    @abstractmethod
    def submit_invoice(self, invoice: Dict[str, Any]) -> str:
        """
        Submit an invoice to the tax authority.

        Returns a submission reference ID assigned by the authority.
        For MockTaxAdapter, returns a synthetic reference.
        For MoadianAdapter, raises ConnectorError(NOT_IMPLEMENTED).
        """
        ...

    @abstractmethod
    def get_submission_status(self, reference_id: str) -> Dict[str, Any]:
        """
        Check the status of a previously submitted invoice.

        Returns dict with: status (str), accepted_at (str|None),
        rejection_reason (str|None).
        """
        ...
```

---

## MockTaxAdapter

The `MockTaxAdapter` is the only tax adapter in production use as of Phase 7. It performs all tax calculations locally using the `tax_rates` table and returns a simulated submission reference without making any network calls.

```python
import uuid
from datetime import datetime, timezone

class MockTaxAdapter(TaxAdapterBase):

    def __init__(self, db):
        self._db = db

    def calculate_tax(self, invoice: dict) -> dict:
        total_tax_irr = 0
        breakdown = []
        for line in invoice.get("line_items", []):
            rate_bps = get_tax_rate(
                self._db,
                line["tax_category_code"],
                invoice["invoice_date"],
            )
            tax_irr = (line["amount_irr"] * rate_bps) // 10000
            total_tax_irr += tax_irr
            breakdown.append({
                "line_id": line.get("id"),
                "amount_irr": line["amount_irr"],
                "rate_bps": rate_bps,
                "tax_irr": tax_irr,
            })
        return {
            "tax_amount_irr": total_tax_irr,
            "breakdown": breakdown,
        }

    def submit_invoice(self, invoice: dict) -> str:
        return f"MOCK-TAX-{uuid.uuid4().hex[:12].upper()}"

    def get_submission_status(self, reference_id: str) -> dict:
        return {
            "status": "accepted",
            "accepted_at": datetime.now(timezone.utc).isoformat(),
            "rejection_reason": None,
        }
```

---

## Moadian (سامانه مودیان) — NOT IMPLEMENTED

Moadian is Iran's mandatory electronic invoicing system, operated by the Tax Affairs Organisation. All businesses above the registration threshold are required to submit their sales invoices to Moadian in real-time (within a defined window of the transaction time).

### Why NOT IMPLEMENTED

The Moadian adapter is not implemented in Phase 7 because the integration requires:

1. **INTA Registration**: The business must register with the Tax Affairs Organisation's Integration Technical Network Authority (INTA — اداره کل انفورماتیک). This registration is performed by a human representative and results in the issuance of a client identifier.

2. **RSA Key Pair**: After INTA registration, the business generates an RSA key pair. The private key signs every invoice payload before submission. The public key is registered with INTA. Without a registered key pair, the Moadian API will reject all requests.

3. **API Specification**: The official Moadian API specification (`https://tax.gov.ir/`) requires a registered account to access. The full specification is not publicly downloadable without INTA credentials.

The adapter stub exists at `backend/integrations/tax/moadian_adapter.py` and raises `ConnectorError(NOT_IMPLEMENTED)` on every method call. When INTA registration is complete and the API specification is obtained, the implementation can be added without changing the interface.

**Reference**: The official Moadian portal is at `https://tax.gov.ir/`. The technical integration documentation is accessible to registered INTA members.
