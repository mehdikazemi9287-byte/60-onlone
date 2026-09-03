from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.migrator import current_version, discover, upgrade  # noqa: E402
from tests.base import AppTestCase  # noqa: E402


class CorsTest(AppTestCase):
    def test_allowed_origin_gets_cors_headers(self):
        response = self.client.get("/api/v1/products", headers={"Origin": "http://localhost:3000"})
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"), "http://localhost:3000"
        )
        self.assertIn("Idempotency-Key", response.headers.get("Access-Control-Allow-Headers", ""))

    def test_unknown_origin_gets_no_cors_headers(self):
        response = self.client.get("/api/v1/products", headers={"Origin": "https://evil.example"})
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_preflight_is_answered_for_a_real_route(self):
        response = self.client.options(
            "/api/v1/checkout", headers={"Origin": "http://localhost:3000"}
        )
        self.assertIn(response.status_code, (200, 204))
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"), "http://localhost:3000"
        )

    def test_no_wildcard_origin_is_ever_sent(self):
        response = self.client.get("/api/v1/products", headers={"Origin": "http://localhost:3000"})
        self.assertNotEqual(response.headers.get("Access-Control-Allow-Origin"), "*")


class MigrationTest(AppTestCase):
    seed_data = False

    def test_migrations_are_discovered_in_order(self):
        versions = [v for v, _, _ in discover()]
        self.assertEqual(versions, sorted(versions))
        self.assertIn("0001", versions)

    def test_upgrade_is_idempotent(self):
        self.assertEqual(upgrade(self.db), [])  # setUp already applied them
        self.assertEqual(current_version(self.db), discover()[-1][0])

    def test_every_migration_is_recorded_with_a_checksum(self):
        rows = self.db.query("SELECT version, name, checksum FROM schema_migrations")
        self.assertEqual(len(rows), len(discover()))
        for row in rows:
            self.assertEqual(len(row["checksum"]), 64)

    def test_no_money_column_is_stored_as_a_float(self):
        """Grep the live schema: REAL/FLOAT/DOUBLE must not appear anywhere."""
        offenders = []
        tables = [
            r["name"]
            for r in self.db.query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            for column in self.db.query(f"PRAGMA table_info({table})"):
                declared = (column["type"] or "").upper()
                if any(t in declared for t in ("REAL", "FLOAT", "DOUB")):
                    offenders.append(f"{table}.{column['name']} {declared}")
        self.assertEqual(offenders, [], f"floating-point money columns found: {offenders}")

    def test_money_columns_are_integers(self):
        expected = {
            "products": ["base_price_minor"],
            "cart_items": ["unit_price_minor"],
            "orders": ["subtotal_minor", "shipping_fee_minor", "total_minor"],
            "order_items": ["unit_price_minor", "line_total_minor"],
            "payments": ["amount_minor"],
            "ledger_entries": ["amount_minor"],
        }
        for table, columns in expected.items():
            info = {r["name"]: (r["type"] or "").upper() for r in self.db.query(f"PRAGMA table_info({table})")}
            for column in columns:
                self.assertIn(column, info, f"{table}.{column} is missing")
                self.assertEqual(info[column], "INTEGER", f"{table}.{column} is {info[column]}")


class ErrorEnvelopeTest(AppTestCase):
    def test_every_error_uses_the_same_envelope(self):
        cases = [
            self.client.get("/api/v1/nope"),
            self.client.get("/api/v1/products/nope"),
            self.client.get("/api/v1/cart"),
            self.client.post("/api/v1/auth/login", json={"email": "x@y.z", "password": "nope"}),
        ]
        for response in cases:
            body = response.get_json()
            self.assertIn("error", body, response.data)
            self.assertIn("code", body["error"])
            self.assertIn("message", body["error"])

    def test_method_not_allowed_is_json(self):
        response = self.client.put("/api/v1/products")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.get_json()["error"]["code"], "method_not_allowed")


if __name__ == "__main__":
    unittest.main()
