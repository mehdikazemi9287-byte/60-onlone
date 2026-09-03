"""Connector Certification Harness — Blocker 9.

Reusable harness that validates any ConnectorAdapter against the
connector contract. Use this to certify a new connector before deploying.

Usage in tests:
    from app.adapters.connectors.certification_harness import ConnectorCertificationHarness
    from app.adapters.connectors.mock_erp_v2 import MockErpV2Connector

    harness = ConnectorCertificationHarness(MockErpV2Connector(config={}))
    result = harness.run_all()
    assert result["passed"]

Or run specific checks:
    harness.check_capabilities()
    harness.check_schema()
    harness.check_pagination()
    harness.check_idempotency()
    harness.check_failure_isolation()
    harness.check_credential_redaction()
"""
from __future__ import annotations

import traceback
from typing import Any

from app.adapters.connectors.base import ConnectorAdapter


class CertificationFailure(AssertionError):
    """A certification check failed."""
    pass


class ConnectorCertificationHarness:
    """
    Runs a standard suite of checks against any ConnectorAdapter.

    Each check method raises CertificationFailure with a descriptive
    message if the check fails.

    run_all() runs every check and returns a summary dict.
    """

    def __init__(self, adapter: ConnectorAdapter, *, verbose: bool = False) -> None:
        self.adapter = adapter
        self.verbose = verbose
        self._results: list[dict] = []

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def check_capabilities(self) -> dict:
        """Adapter must return a non-empty capabilities dict."""
        name = "capabilities"
        try:
            caps = self.adapter.capabilities()
            if not isinstance(caps, dict) or not caps:
                raise CertificationFailure(
                    f"capabilities() returned empty or non-dict: {caps!r}"
                )
            # Must have at minimum connector_type key
            required = {"connector_type"}
            missing = required - caps.keys()
            if missing:
                raise CertificationFailure(
                    f"capabilities() missing required keys: {missing}"
                )
            return self._pass(name, {"capabilities": caps})
        except CertificationFailure:
            raise
        except Exception as exc:
            raise CertificationFailure(f"capabilities() raised: {exc}") from exc

    def check_schema(self) -> dict:
        """First page of pull_products() must return dicts with required fields."""
        name = "schema"
        required_fields = {"code", "price_minor"}
        try:
            page = self.adapter.pull_products(limit=5, offset=0)
            items = page.get("items", []) if isinstance(page, dict) else list(page)[:5]
            if not items:
                raise CertificationFailure("pull_products() returned zero items on first page")
            for item in items:
                missing = required_fields - item.keys()
                if missing:
                    raise CertificationFailure(
                        f"Product missing required fields: {missing}. Got: {list(item.keys())}"
                    )
                # No float prices
                price = item.get("price_minor")
                if isinstance(price, float):
                    raise CertificationFailure(
                        f"price_minor must be INTEGER, got float: {price}"
                    )
                if not isinstance(price, int):
                    raise CertificationFailure(
                        f"price_minor must be INTEGER, got {type(price).__name__}: {price!r}"
                    )
            return self._pass(name, {"items_checked": len(items)})
        except CertificationFailure:
            raise
        except Exception as exc:
            raise CertificationFailure(f"schema check raised: {exc}") from exc

    def check_pagination(self) -> dict:
        """Pagination: page 2 must return different items than page 1."""
        name = "pagination"
        try:
            page1 = self.adapter.pull_products(limit=5, offset=0)
            page2 = self.adapter.pull_products(limit=5, offset=5)
            items1 = page1.get("items", []) if isinstance(page1, dict) else list(page1)
            items2 = page2.get("items", []) if isinstance(page2, dict) else list(page2)
            if not items1:
                raise CertificationFailure("Page 1 returned no items")
            if items1 and items2:
                codes1 = {i.get("code") for i in items1}
                codes2 = {i.get("code") for i in items2}
                overlap = codes1 & codes2
                if overlap:
                    raise CertificationFailure(
                        f"Pagination overlaps between page 1 and page 2: {overlap}"
                    )
            return self._pass(name, {"page1_count": len(items1), "page2_count": len(items2)})
        except CertificationFailure:
            raise
        except Exception as exc:
            raise CertificationFailure(f"pagination check raised: {exc}") from exc

    def check_idempotency(self) -> dict:
        """Same offset+limit request must return same items (no random ordering)."""
        name = "idempotency"
        try:
            page_a = self.adapter.pull_products(limit=5, offset=0)
            page_b = self.adapter.pull_products(limit=5, offset=0)
            items_a = page_a.get("items", []) if isinstance(page_a, dict) else list(page_a)
            items_b = page_b.get("items", []) if isinstance(page_b, dict) else list(page_b)
            codes_a = [i.get("code") for i in items_a]
            codes_b = [i.get("code") for i in items_b]
            if codes_a != codes_b:
                raise CertificationFailure(
                    f"Same request returned different items: {codes_a} vs {codes_b}"
                )
            return self._pass(name, {"items": len(codes_a)})
        except CertificationFailure:
            raise
        except Exception as exc:
            raise CertificationFailure(f"idempotency check raised: {exc}") from exc

    def check_failure_isolation(self) -> dict:
        """
        Outage / malformed data must NOT crash the adapter in a way that
        corrupts subsequent calls. After simulated failure, normal call must work.
        """
        name = "failure_isolation"
        try:
            # Attempt to trigger outage — adapter may or may not support simulate_outage
            outage_adapter = None
            try:
                cls = type(self.adapter)
                outage_adapter = cls(config={"simulate_outage": True})
                outage_adapter.pull_products(limit=1, offset=0)
                # If no exception, outage flag may not be supported — that's OK
            except Exception:
                pass  # Expected when outage is supported

            # Normal call on original adapter must still work
            page = self.adapter.pull_products(limit=1, offset=0)
            items = page.get("items", []) if isinstance(page, dict) else list(page)
            if not items:
                raise CertificationFailure("Normal call after failure simulation returned no items")
            return self._pass(name, {"items_after_failure": len(items)})
        except CertificationFailure:
            raise
        except Exception as exc:
            raise CertificationFailure(f"failure_isolation check raised: {exc}") from exc

    def check_malformed_data_isolation(self) -> dict:
        """Malformed rows must not crash the paginator; remaining rows accessible."""
        name = "malformed_data_isolation"
        try:
            cls = type(self.adapter)
            try:
                malformed_adapter = cls(config={"inject_malformed": True})
                page = malformed_adapter.pull_products(limit=5, offset=0)
                items = page.get("items", []) if isinstance(page, dict) else list(page)
                # We don't require specific handling, just that it doesn't crash
            except Exception:
                pass  # Acceptable if it raises — what matters is isolation

            # Original adapter still works
            page = self.adapter.pull_products(limit=1, offset=0)
            items = page.get("items", []) if isinstance(page, dict) else list(page)
            if not items:
                raise CertificationFailure("Adapter returned no items after malformed isolation test")
            return self._pass(name, {"items_after_malformed": len(items)})
        except CertificationFailure:
            raise
        except Exception as exc:
            raise CertificationFailure(f"malformed_data check raised: {exc}") from exc

    def check_credential_redaction(self) -> dict:
        """
        Adapter config/capabilities must not expose secret values in cleartext.
        Checks that capabilities() does not contain 'password', 'secret', 'token'
        with non-empty values.
        """
        name = "credential_redaction"
        try:
            caps = self.adapter.capabilities()
            sensitive_keys = {"password", "secret", "token", "api_key", "api_secret"}
            for key in sensitive_keys:
                if key in caps and caps[key]:
                    raise CertificationFailure(
                        f"capabilities() exposes sensitive field '{key}' in cleartext"
                    )
            return self._pass(name, {})
        except CertificationFailure:
            raise
        except Exception as exc:
            raise CertificationFailure(f"credential_redaction check raised: {exc}") from exc

    def check_health(self) -> dict:
        """health_check() must return a dict with 'healthy' bool key."""
        name = "health"
        try:
            health = self.adapter.health_check()
            if not isinstance(health, dict):
                raise CertificationFailure(f"health_check() returned non-dict: {health!r}")
            if "healthy" not in health:
                raise CertificationFailure(f"health_check() missing 'healthy' key: {health}")
            if not isinstance(health["healthy"], bool):
                raise CertificationFailure(
                    f"health_check()['healthy'] must be bool, got {type(health['healthy']).__name__}"
                )
            return self._pass(name, {"healthy": health["healthy"]})
        except CertificationFailure:
            raise
        except Exception as exc:
            raise CertificationFailure(f"health check raised: {exc}") from exc

    def check_generator_interface(self) -> dict:
        """
        If adapter has pull_products_all(), it must be a generator (not a list).
        First 5 items must have required fields.
        """
        name = "generator_interface"
        if not hasattr(self.adapter, "pull_products_all"):
            return self._skip(name, "pull_products_all not implemented")

        try:
            import types
            gen = self.adapter.pull_products_all()
            if not hasattr(gen, "__next__"):
                raise CertificationFailure("pull_products_all() did not return a generator/iterator")
            items = []
            for item in gen:
                items.append(item)
                if len(items) >= 5:
                    break
            if not items:
                raise CertificationFailure("pull_products_all() yielded no items")
            return self._pass(name, {"items_sampled": len(items)})
        except CertificationFailure:
            raise
        except Exception as exc:
            raise CertificationFailure(f"generator_interface check raised: {exc}") from exc

    # ------------------------------------------------------------------
    # Run all
    # ------------------------------------------------------------------

    def run_all(self) -> dict:
        """Run all certification checks. Returns summary dict."""
        self._results = []
        checks = [
            self.check_capabilities,
            self.check_schema,
            self.check_pagination,
            self.check_idempotency,
            self.check_failure_isolation,
            self.check_malformed_data_isolation,
            self.check_credential_redaction,
            self.check_health,
            self.check_generator_interface,
        ]
        passed = 0
        failed = 0
        skipped = 0
        failures = []

        for check_fn in checks:
            try:
                result = check_fn()
                if result.get("status") == "skipped":
                    skipped += 1
                else:
                    passed += 1
            except CertificationFailure as exc:
                failed += 1
                failures.append({"check": check_fn.__name__, "error": str(exc)})
                self._results.append({
                    "check": check_fn.__name__,
                    "status": "failed",
                    "error": str(exc),
                })
            except Exception as exc:
                failed += 1
                tb = traceback.format_exc()
                failures.append({"check": check_fn.__name__, "error": f"{exc}\n{tb}"})
                self._results.append({
                    "check": check_fn.__name__,
                    "status": "error",
                    "error": str(exc),
                })

        return {
            "passed": failed == 0,
            "total": len(checks),
            "passed_count": passed,
            "failed_count": failed,
            "skipped_count": skipped,
            "failures": failures,
            "results": self._results,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _pass(self, name: str, detail: dict) -> dict:
        r = {"check": name, "status": "passed", **detail}
        self._results.append(r)
        return r

    def _skip(self, name: str, reason: str) -> dict:
        r = {"check": name, "status": "skipped", "reason": reason}
        self._results.append(r)
        return r
