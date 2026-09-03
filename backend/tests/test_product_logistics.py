"""Tests for BLOCKER 4 — product logistics profiles and carrier eligibility.

Tests _required_capabilities() and _find_matching_carrier_config() from
logistics_service against real DB data created by deterministic fixtures.
"""
from __future__ import annotations

import unittest

from tests.base import AppTestCase
from app.services import logistics_service


def _checkout_fo(tc: AppTestCase, logistics_profile: str = "standard") -> int:
    """Create test supplier + product + customer checkout; return fo_id."""
    supplier_info = tc.create_test_supplier(province="تهران", city="تهران")
    product_info = tc.create_test_product_with_offer(
        supplier_info["supplier_id"], supplier_info["location_id"],
        logistics_profile=logistics_profile,
    )
    _, customer_h = tc.new_customer()
    tc.add_to_cart(customer_h, product_info["product_id"], 1)
    resp = tc.checkout(customer_h)
    tc.assertEqual(resp.status_code, 201, resp.get_json())

    with tc.db.read_transaction() as conn:
        fo = conn.execute(
            "SELECT fo.* FROM fulfillment_orders fo "
            "JOIN orders o ON o.id = fo.order_id ORDER BY fo.id DESC LIMIT 1"
        ).fetchone()
    return fo["id"]


class RequiredCapabilitiesTest(AppTestCase):
    """Unit tests for _required_capabilities() against real DB FOs."""

    def test_standard_product_has_no_required_caps(self):
        """A standard-profile product produces empty required capabilities."""
        fo_id = _checkout_fo(self, "standard")
        with self.db.read_transaction() as conn:
            caps = logistics_service._required_capabilities(conn, fo_id)
        self.assertEqual(caps, "", f"standard profile should produce no caps; got {caps!r}")

    def test_perishable_requires_cold_chain_cap(self):
        """Perishable profile → required caps include 'cold_chain'."""
        fo_id = _checkout_fo(self, "perishable")
        with self.db.read_transaction() as conn:
            caps = logistics_service._required_capabilities(conn, fo_id)
        self.assertIn("cold_chain", caps.split(","),
                      f"perishable should require cold_chain; got {caps!r}")

    def test_cold_chain_required_profile_requires_cold_chain(self):
        """cold_chain_required profile → 'cold_chain' in required caps."""
        fo_id = _checkout_fo(self, "cold_chain_required")
        with self.db.read_transaction() as conn:
            caps = logistics_service._required_capabilities(conn, fo_id)
        self.assertIn("cold_chain", caps.split(","),
                      f"cold_chain_required should require cold_chain; got {caps!r}")

    def test_local_only_requires_local_cap(self):
        """local_only profile → 'local' in required caps."""
        fo_id = _checkout_fo(self, "local_only")
        with self.db.read_transaction() as conn:
            caps = logistics_service._required_capabilities(conn, fo_id)
        self.assertIn("local", caps.split(","),
                      f"local_only should require local cap; got {caps!r}")

    def test_bulky_requires_bulky_cap(self):
        """bulky profile → 'bulky' in required caps."""
        fo_id = _checkout_fo(self, "bulky")
        with self.db.read_transaction() as conn:
            caps = logistics_service._required_capabilities(conn, fo_id)
        self.assertIn("bulky", caps.split(","),
                      f"bulky should require bulky cap; got {caps!r}")

    def test_fragile_requires_fragile_cap(self):
        """fragile profile → 'fragile' in required caps."""
        fo_id = _checkout_fo(self, "fragile")
        with self.db.read_transaction() as conn:
            caps = logistics_service._required_capabilities(conn, fo_id)
        self.assertIn("fragile", caps.split(","),
                      f"fragile should require fragile cap; got {caps!r}")


class CarrierEligibilityTest(AppTestCase):
    """Tests for _find_matching_carrier_config() capability filtering."""

    # Use a unique province prefix for each test to avoid interference
    # with seeded carrier configs.

    def _insert_carrier(self, province: str, capabilities: str, cost: int = 80_000) -> int:
        """Insert a test carrier config and return its id."""
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                "INSERT INTO carrier_configs "
                "(provider_code, name_fa, province, city, capabilities, cost_minor, is_active) "
                "VALUES ('mock', ?, ?, NULL, ?, ?, 1)",
                (f"حامل آزمایشی {province} {capabilities}", province, capabilities, cost),
            )
            return int(cur.lastrowid)

    def test_carrier_without_cold_chain_ineligible_for_perishable(self):
        """A carrier without cold_chain must NOT be selected for a perishable FO."""
        prov = "test_cold_prov_" + __import__("uuid").uuid4().hex[:6]

        # Carrier WITHOUT cold_chain (cheapest, should be skipped)
        cc_no_cold = self._insert_carrier(prov, "local,intercity", cost=50_000)
        # Carrier WITH cold_chain
        cc_cold = self._insert_carrier(prov, "local,cold_chain", cost=90_000)

        with self.db.read_transaction() as conn:
            result = logistics_service._find_matching_carrier_config(
                conn,
                provider_code="mock",
                dest_province=prov,
                dest_city="testcity",
                required_capabilities="cold_chain",
            )

        self.assertIsNotNone(result, "a cold_chain carrier exists and should be returned")
        returned_caps = {c.strip() for c in result["capabilities"].split(",") if c.strip()}
        self.assertIn("cold_chain", returned_caps,
                      f"selected carrier must have cold_chain; got {result['capabilities']!r}")

        # Verify the non-cold_chain carrier was NOT selected (its id != cc_cold)
        self.assertNotEqual(
            result["id"], cc_no_cold,
            "the carrier without cold_chain must not be selected for perishable",
        )

    def test_local_only_intercity_carrier_ineligible(self):
        """An intercity-only carrier must NOT be selected for a local_only product.

        Deactivates national carriers (province=NULL) so the intercity-only carrier
        in our custom province is the only candidate.  Expects None — no eligible carrier.
        """
        prov = "test_local_prov_" + __import__("uuid").uuid4().hex[:6]

        # Deactivate national carriers for this test (each test gets its own DB)
        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE carrier_configs SET is_active=0 WHERE province IS NULL"
            )

        # Only an intercity-only carrier is available in our custom province
        self._insert_carrier(prov, "intercity", cost=60_000)

        with self.db.read_transaction() as conn:
            result = logistics_service._find_matching_carrier_config(
                conn,
                provider_code="mock",
                dest_province=prov,
                dest_city="testcity",
                required_capabilities="local",
            )

        self.assertIsNone(
            result,
            "an intercity-only carrier must not be returned when local is required; "
            f"got {result}",
        )

    def test_standard_product_intercity_carrier_eligible(self):
        """Any carrier is eligible for a standard product (no special capabilities required)."""
        prov = "test_std_prov_" + __import__("uuid").uuid4().hex[:6]

        cc_id = self._insert_carrier(prov, "local,intercity", cost=70_000)

        with self.db.read_transaction() as conn:
            result = logistics_service._find_matching_carrier_config(
                conn,
                provider_code="mock",
                dest_province=prov,
                dest_city="testcity",
                required_capabilities="",
            )

        self.assertIsNotNone(
            result,
            "a standard product must match any available carrier",
        )
        self.assertEqual(result["id"], cc_id)

    def test_carrier_without_bulky_ineligible_for_bulky_product(self):
        """A carrier without 'bulky' cap must NOT be selected for a bulky FO."""
        prov = "test_bulky_prov_" + __import__("uuid").uuid4().hex[:6]

        # Cheap carrier WITHOUT bulky cap — should be skipped
        cc_no_bulky = self._insert_carrier(prov, "local,intercity", cost=40_000)
        # Eligible carrier WITH bulky cap
        cc_bulky = self._insert_carrier(prov, "local,intercity,bulky", cost=95_000)

        with self.db.read_transaction() as conn:
            result = logistics_service._find_matching_carrier_config(
                conn,
                provider_code="mock",
                dest_province=prov,
                dest_city="testcity",
                required_capabilities="bulky",
            )

        self.assertIsNotNone(result, "a bulky-capable carrier exists and should be returned")
        returned_caps = {c.strip() for c in result["capabilities"].split(",") if c.strip()}
        self.assertIn("bulky", returned_caps,
                      f"selected carrier must have bulky cap; got {result['capabilities']!r}")
        self.assertNotEqual(
            result["id"], cc_no_bulky,
            "the carrier without bulky cap must not be selected for a bulky product",
        )

    def test_carrier_without_fragile_ineligible_for_fragile_product(self):
        """A carrier without 'fragile' cap must NOT be selected for a fragile FO."""
        prov = "test_fragile_prov_" + __import__("uuid").uuid4().hex[:6]

        # Cheap carrier WITHOUT fragile cap — should be skipped
        cc_no_fragile = self._insert_carrier(prov, "local,intercity", cost=45_000)
        # Eligible carrier WITH fragile cap
        cc_fragile = self._insert_carrier(prov, "local,intercity,fragile", cost=100_000)

        with self.db.read_transaction() as conn:
            result = logistics_service._find_matching_carrier_config(
                conn,
                provider_code="mock",
                dest_province=prov,
                dest_city="testcity",
                required_capabilities="fragile",
            )

        self.assertIsNotNone(result, "a fragile-capable carrier exists and should be returned")
        returned_caps = {c.strip() for c in result["capabilities"].split(",") if c.strip()}
        self.assertIn("fragile", returned_caps,
                      f"selected carrier must have fragile cap; got {result['capabilities']!r}")
        self.assertNotEqual(
            result["id"], cc_no_fragile,
            "the carrier without fragile cap must not be selected for a fragile product",
        )


if __name__ == "__main__":
    unittest.main()
