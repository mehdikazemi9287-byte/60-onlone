"""Mock Tax Adapter — deterministic, in-memory, for testing and demonstration only.

SIMULATOR-ONLY — rates in this adapter are configurable demo values and do NOT
represent current verified Iranian tax law.  Production tax lookups must always
use the effective-dated tax_rates table:
  STANDARD: 900 bps (9%) through 2024-03-19; 1000 bps (10%) from 2024-03-20.

Demo rates used by this simulator (for unit tests — not law):
  STANDARD         = 900 bps  (DEMO ONLY — historical seed; production reads tax_rates)
  REDUCED          = 0 bps    (placeholder; Iran has no statutory reduced rate yet)
  ZERO             = 0 bps
  EXEMPT           = 0 bps
  DIGITAL_SERVICES = 900 bps  (same as STANDARD for demo purposes)
  FOOD_BASIC       = 0 bps    (basic foodstuffs exempt)
"""
from __future__ import annotations

from app.adapters.tax.base import (
    TaxAdapter,
    TaxAdapterError,
    TaxCalculationResult,
    TaxLineInput,
    TaxLineResult,
)


# ─────────────────────────────────────────────────────────────────────────────
# Hardcoded rate table (mirrors 0016 migration seeds)
# ─────────────────────────────────────────────────────────────────────────────

_RATES_BPS: dict[str, int] = {
    "STANDARD":        900,   # 9%
    "REDUCED":           0,   # placeholder
    "ZERO":              0,
    "EXEMPT":            0,
    "DIGITAL_SERVICES": 900,
    "FOOD_BASIC":        0,
}

_DEFAULT_RATE_BPS = 900  # fall back to standard


class MockTaxAdapter(TaxAdapter):
    """In-memory tax adapter for testing and demonstration.

    Deterministic: same inputs → same outputs.
    No external API calls.
    """

    adapter_name = "MOCK_TAX"
    implementation_status = "simulator"

    def __init__(self):
        self._submissions: list[dict] = []
        self._next_ref = 9000

    def capabilities(self) -> dict:
        return {
            "adapter_name": self.adapter_name,
            "implementation_status": self.implementation_status,
            "supported": ["calculate_tax", "submit_invoice", "get_submission_status"],
        }

    def health_check(self) -> dict:
        return {
            "healthy": True,
            "message": f"MOCK_TAX adapter — {len(self._submissions)} تسلیم‌شده",
            "latency_ms": 0,
        }

    def calculate_tax(
        self,
        lines: list[TaxLineInput],
        *,
        effective_date: str,
        jurisdiction: str = "IR",
    ) -> TaxCalculationResult:
        """Calculate tax using hardcoded rate table.

        Uses effective_date in result metadata (not for rate lookup in mock —
        rates are static. Real adapter must query tax_rates table by date).
        """
        if not lines:
            raise TaxAdapterError(
                "MOCK_TAX: calculate_tax requires at least one line",
                code="validation_error",
            )

        # All lines must share the same tax category in this simplified mock
        cat = lines[0].tax_category_code.upper() if lines else "STANDARD"
        rate_bps = _RATES_BPS.get(cat, _DEFAULT_RATE_BPS)

        line_results: list[TaxLineResult] = []
        total_subtotal = 0
        total_tax = 0

        for ln in lines:
            line_cat = ln.tax_category_code.upper()
            line_rate = _RATES_BPS.get(line_cat, _DEFAULT_RATE_BPS)
            subtotal = ln.quantity * ln.unit_price_minor
            # Integer arithmetic — floor
            tax = subtotal * line_rate // 10000  # integer floor — no floats
            total_subtotal += subtotal
            total_tax += tax
            line_results.append(TaxLineResult(
                description=ln.description,
                quantity=ln.quantity,
                unit_price_minor=ln.unit_price_minor,
                line_subtotal_minor=subtotal,
                tax_rate_bps=line_rate,
                tax_category_code=line_cat,
                tax_minor=tax,
                line_total_minor=subtotal + tax,
            ))

        return TaxCalculationResult(
            tax_category_code=cat,
            rate_bps=rate_bps,
            subtotal_minor=total_subtotal,
            tax_minor=total_tax,
            total_minor=total_subtotal + total_tax,
            lines=line_results,
            jurisdiction=jurisdiction,
            effective_date=effective_date,
        )

    def submit_invoice(self, tax_result: TaxCalculationResult, *, metadata: dict | None = None) -> dict:
        ref = f"MOCK-TAX-{self._next_ref:06d}"
        self._next_ref += 1
        self._submissions.append({
            "external_ref": ref,
            "total_minor": tax_result.total_minor,
            "tax_minor": tax_result.tax_minor,
            "effective_date": tax_result.effective_date,
        })
        return {
            "acknowledged": True,
            "external_ref": ref,
            "message": f"فاکتور مالیاتی mock ثبت شد — ref: {ref}",
        }

    def get_submission_status(self, external_ref: str) -> dict:
        for s in self._submissions:
            if s["external_ref"] == external_ref:
                return {"status": "accepted", "external_ref": external_ref}
        return {"status": "not_found", "external_ref": external_ref}

    @property
    def submission_count(self) -> int:
        return len(self._submissions)
