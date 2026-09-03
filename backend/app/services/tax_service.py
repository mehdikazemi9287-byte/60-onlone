"""Tax Service — Phase 7 VAT/Tax Foundation.

Provides:
  - Tax category CRUD (backed by tax_categories table)
  - Tax rate lookup with historical reproducibility (tax_rates table)
  - Product-to-category assignment
  - Org-level exemption checks
  - Tax calculation delegating to the registered TaxAdapter

CRITICAL INVARIANT:
  Tax rates are ALWAYS looked up by (category_code, effective_date). Never use
  "current" rate for historical documents. This ensures issued invoices remain
  reproducible under audit.

TAX SERVICE CONTRACT VERSION: 1.0
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.db import query, write_transaction
from app.core.errors import NotFoundError, ValidationError


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Tax category CRUD
# ─────────────────────────────────────────────────────────────────────────────

def get_tax_categories(*, active_only: bool = True) -> list[dict]:
    """Return all tax categories."""
    if active_only:
        rows = query("SELECT * FROM tax_categories WHERE is_active=1 ORDER BY code", ())
    else:
        rows = query("SELECT * FROM tax_categories ORDER BY code", ())
    return [dict(r) for r in rows]


def get_tax_category(code: str) -> dict:
    """Return one tax category by code."""
    row = query(
        "SELECT * FROM tax_categories WHERE code=?", (code.upper(),), one=True
    )
    if row is None:
        raise NotFoundError(f"دسته مالیاتی '{code}' یافت نشد")
    return dict(row)


def create_tax_category(
    *,
    code: str,
    name_fa: str,
    name_en: str = "",
    description: str = "",
    is_active: bool = True,
) -> dict:
    """Create a new tax category."""
    code = code.upper().strip()
    if not code:
        raise ValidationError("کد دسته مالیاتی الزامی است")

    now = _now_iso()
    with write_transaction() as conn:
        try:
            conn.execute(
                """
                INSERT INTO tax_categories
                    (code, name_fa, name_en, description, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (code, name_fa, name_en, description, 1 if is_active else 0, now),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValidationError(f"دسته مالیاتی '{code}' از قبل وجود دارد")
            raise
    return get_tax_category(code)


# ─────────────────────────────────────────────────────────────────────────────
# Tax rate lookup — historical reproducibility
# ─────────────────────────────────────────────────────────────────────────────

def get_rate_bps(
    tax_category_code: str,
    *,
    effective_date: str,
    jurisdiction: str = "IR",
) -> int:
    """Return the tax rate in basis points effective on the given date.

    Uses the rate whose effective_from <= effective_date AND
    (effective_until IS NULL OR effective_until >= effective_date).

    Raises NotFoundError if no applicable rate found.

    IMPORTANT: Always pass the invoice date, never the current date,
    to ensure historical reproducibility.
    """
    code = tax_category_code.upper()
    row = query(
        """
        SELECT rate_bps FROM tax_rates
        WHERE tax_category_id = (SELECT id FROM tax_categories WHERE code=?)
          AND effective_from <= ?
          AND (effective_until IS NULL OR effective_until >= ?)
          AND (jurisdiction IS NULL OR jurisdiction = ?)
        ORDER BY effective_from DESC
        LIMIT 1
        """,
        (code, effective_date, effective_date, jurisdiction),
        one=True,
    )
    if row is None:
        raise NotFoundError(
            f"نرخ مالیاتی برای دسته '{code}' در تاریخ {effective_date} یافت نشد"
        )
    return row["rate_bps"]


def get_all_rates(tax_category_code: str) -> list[dict]:
    """Return rate history for a tax category."""
    code = tax_category_code.upper()
    rows = query(
        """
        SELECT r.id, r.rate_bps, r.effective_from, r.effective_until,
               r.jurisdiction, r.notes, r.created_by
        FROM tax_rates r
        JOIN tax_categories c ON c.id = r.tax_category_id
        WHERE c.code = ?
        ORDER BY r.effective_from DESC
        """,
        (code,),
    )
    return [dict(r) for r in rows]


def create_tax_rate(
    *,
    tax_category_code: str,
    rate_bps: int,
    effective_from: str,
    effective_until: str | None = None,
    jurisdiction: str = "IR",
    jurisdiction_detail: str = "",
    notes: str = "",
    created_by: int | None = None,
) -> dict:
    """Add a new effective-dated tax rate."""
    code = tax_category_code.upper()
    cat = get_tax_category(code)  # raises NotFoundError if missing

    if not (0 <= rate_bps <= 10000):
        raise ValidationError("rate_bps باید بین 0 و 10000 باشد")

    now = _now_iso()
    with write_transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO tax_rates
                (tax_category_id, rate_bps, effective_from, effective_until,
                 jurisdiction, jurisdiction_detail, notes, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cat["id"],
                rate_bps,
                effective_from,
                effective_until,
                jurisdiction,
                jurisdiction_detail,
                notes,
                created_by,
                now,
            ),
        )
        return {"id": cur.lastrowid, "tax_category_code": code, "rate_bps": rate_bps,
                "effective_from": effective_from, "effective_until": effective_until}


# ─────────────────────────────────────────────────────────────────────────────
# Product-category assignment
# ─────────────────────────────────────────────────────────────────────────────

def get_product_tax_category(product_id: int, *, effective_date: str) -> str:
    """Return the tax_category_code for a product on a given date.

    Falls back to 'STANDARD' if no assignment found.
    """
    row = query(
        """
        SELECT c.code
        FROM tax_product_assignments a
        JOIN tax_categories c ON c.id = a.tax_category_id
        WHERE a.product_id = ?
          AND a.effective_from <= ?
          AND (a.effective_until IS NULL OR a.effective_until >= ?)
        ORDER BY a.effective_from DESC
        LIMIT 1
        """,
        (product_id, effective_date, effective_date),
        one=True,
    )
    return row["code"] if row else "STANDARD"


def assign_product_tax_category(
    product_id: int,
    tax_category_code: str,
    *,
    effective_from: str,
    effective_until: str | None = None,
    assigned_by: int | None = None,
) -> dict:
    """Assign a tax category to a product."""
    code = tax_category_code.upper()
    cat = get_tax_category(code)
    now = _now_iso()
    with write_transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO tax_product_assignments
                (product_id, tax_category_id, effective_from, effective_until, assigned_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (product_id, cat["id"], effective_from, effective_until, assigned_by, now),
        )
        return {"id": cur.lastrowid, "product_id": product_id,
                "tax_category_code": code, "effective_from": effective_from}


# ─────────────────────────────────────────────────────────────────────────────
# Org exemption
# ─────────────────────────────────────────────────────────────────────────────

def is_exempt(
    organization_id: int,
    tax_category_code: str,
    *,
    effective_date: str,
) -> bool:
    """True if the organization has a valid exemption for this category on the given date."""
    code = tax_category_code.upper()
    row = query(
        """
        SELECT e.id
        FROM tax_org_exemptions e
        JOIN tax_categories c ON c.id = e.tax_category_id
        WHERE e.organization_id = ?
          AND c.code = ?
          AND e.effective_from <= ?
          AND (e.effective_until IS NULL OR e.effective_until >= ?)
        LIMIT 1
        """,
        (organization_id, code, effective_date, effective_date),
        one=True,
    )
    return row is not None


# ─────────────────────────────────────────────────────────────────────────────
# Tax calculation (in-process, no external adapter needed for basic use)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_line_tax(
    *,
    subtotal_minor: int,
    tax_category_code: str,
    effective_date: str,
    organization_id: int | None = None,
    jurisdiction: str = "IR",
) -> dict:
    """Calculate tax for a single line subtotal.

    Returns:
        {
          "subtotal_minor": int,
          "tax_category_code": str,
          "rate_bps": int,
          "tax_minor": int,
          "total_minor": int,
        }
    """
    code = tax_category_code.upper()

    # Check org exemption
    if organization_id and is_exempt(organization_id, code, effective_date=effective_date):
        rate_bps = 0
    else:
        try:
            rate_bps = get_rate_bps(code, effective_date=effective_date, jurisdiction=jurisdiction)
        except NotFoundError:
            # Fall back to STANDARD if category rate not found
            rate_bps = get_rate_bps("STANDARD", effective_date=effective_date, jurisdiction=jurisdiction)

    tax_minor = subtotal_minor * rate_bps // 10000  # integer floor — no floats
    return {
        "subtotal_minor": subtotal_minor,
        "tax_category_code": code,
        "rate_bps": rate_bps,
        "tax_minor": tax_minor,
        "total_minor": subtotal_minor + tax_minor,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Connection-aware tax functions
# These accept an existing db connection so they can be called from within
# a write transaction without going through _get_db() / a new transaction.
# ─────────────────────────────────────────────────────────────────────────────

def get_rate_bps_with_conn(
    conn,
    tax_category_code: str,
    *,
    effective_date: str,
    jurisdiction: str = "IR",
) -> int:
    """Return the tax rate in basis points using an existing connection.

    Identical logic to get_rate_bps() but uses the caller's conn.execute()
    so it is safe to call from within an open write transaction.

    Raises NotFoundError if no applicable rate is found.
    """
    code = tax_category_code.upper()
    row = conn.execute(
        """
        SELECT rate_bps FROM tax_rates
        WHERE tax_category_id = (SELECT id FROM tax_categories WHERE code=?)
          AND effective_from <= ?
          AND (effective_until IS NULL OR effective_until >= ?)
          AND (jurisdiction IS NULL OR jurisdiction = ?)
        ORDER BY effective_from DESC
        LIMIT 1
        """,
        (code, effective_date, effective_date, jurisdiction),
    ).fetchone()
    if row is None:
        raise NotFoundError(
            f"نرخ مالیاتی برای دسته '{code}' در تاریخ {effective_date} یافت نشد"
        )
    return row["rate_bps"]


def is_exempt_with_conn(
    conn,
    organization_id: int,
    tax_category_code: str,
    *,
    effective_date: str,
) -> bool:
    """True if org has a valid exemption for this category, using an existing conn."""
    code = tax_category_code.upper()
    row = conn.execute(
        """
        SELECT e.id
        FROM tax_org_exemptions e
        JOIN tax_categories c ON c.id = e.tax_category_id
        WHERE e.organization_id = ?
          AND c.code = ?
          AND e.effective_from <= ?
          AND (e.effective_until IS NULL OR e.effective_until >= ?)
        LIMIT 1
        """,
        (organization_id, code, effective_date, effective_date),
    ).fetchone()
    return row is not None


def calculate_line_tax_with_conn(
    conn,
    *,
    subtotal_minor: int,
    tax_category_code: str = "STANDARD",
    effective_date: str,
    organization_id: int | None = None,
    jurisdiction: str = "IR",
) -> dict:
    """Calculate tax for a subtotal using an existing connection.

    Safe to call from within a write transaction — no new transaction is opened.

    Returns:
        {
          "subtotal_minor": int,       taxable base
          "tax_category_code": str,
          "rate_bps": int,             basis points (e.g. 1000 = 10 %)
          "tax_minor": int,            integer floor, no floats
          "total_minor": int,          subtotal_minor + tax_minor
        }
    """
    code = tax_category_code.upper()

    # Check org exemption
    if organization_id and is_exempt_with_conn(
        conn, organization_id, code, effective_date=effective_date
    ):
        rate_bps = 0
    else:
        try:
            rate_bps = get_rate_bps_with_conn(
                conn, code, effective_date=effective_date, jurisdiction=jurisdiction
            )
        except NotFoundError:
            # Fall back to STANDARD if specific category rate is not found
            rate_bps = get_rate_bps_with_conn(
                conn, "STANDARD", effective_date=effective_date, jurisdiction=jurisdiction
            )

    tax_minor = subtotal_minor * rate_bps // 10000  # integer floor — no floats
    return {
        "subtotal_minor": subtotal_minor,
        "tax_category_code": code,
        "rate_bps": rate_bps,
        "tax_minor": tax_minor,
        "total_minor": subtotal_minor + tax_minor,
    }
