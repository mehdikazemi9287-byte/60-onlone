"""آمادگی راه‌اندازی وامبی: readiness, usage metrics and attribution.

All suppliers, products and prices below are SYNTHETIC TEST FIXTURES created in a throwaway SQLite database
(tests/base.py); they are labelled «آزمایشی» and never reach runtime business data.
"""
from __future__ import annotations

import io
import json
import os
import uuid
from contextlib import redirect_stdout
from unittest import mock

from app.services import vambi_launch_service as launch
from tests.base import AppTestCase

READY_ENV = {"KAVENEGAR_SENDER": "SECRET-LINE-10004321", "STOREFRONT_PRICE_VISIBILITY": "public",
             "VAMBI_DOMAIN": "vambi.ir", "VAMBI_MIN_COMPARABLE": "2"}


class LaunchBase(AppTestCase):
    def supplier(self) -> dict:
        sup = self.create_test_supplier()
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE suppliers SET provenance='real' WHERE id=?", (sup["supplier_id"],))
        return sup

    def offer(self, sup: dict, product_id: int, price: int, *, fresh: bool = True, mode: str = "fixed") -> int:
        """Synthetic test offer with a confirmed (fresh) or stale price."""
        stamp = "datetime('now')" if fresh else "datetime('now','-3 days')"
        with self.db.write_transaction() as conn:
            oid = conn.execute(
                f"""INSERT INTO seller_offers (product_id, supplier_id, supplier_location_id, selling_price_minor,
                        cost_price_minor, stock_quantity, status, fulfillment_type, pricing_mode, channel, provenance,
                        last_price_confirmed_at, last_inventory_confirmed_at)
                    VALUES (?,?,?,?,?,5,'active','delivery',?,'retail','real',{stamp},{stamp})""",
                (product_id, sup["supplier_id"], sup["location_id"], price, price // 2, mode)).lastrowid
        return int(oid)

    def make_product(self, sup: dict, price: int = 1_000_000) -> int:
        p = self.create_test_product_with_offer(sup["supplier_id"], sup["location_id"], price_minor=price)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE seller_offers SET provenance='real', pricing_mode='fixed', channel='retail', "
                         "last_price_confirmed_at=datetime('now'), last_inventory_confirmed_at=datetime('now') "
                         "WHERE id=?", (p["offer_id"],))
        return int(p["product_id"])

    def readiness(self, env=None):
        with self.db.read_transaction() as conn:
            return launch.readiness(conn, env=READY_ENV if env is None else env)


class ReadinessTest(LaunchBase):
    def test_comparable_threshold(self):
        base = self.readiness()["checks"][0]["value"]
        a, b = self.supplier(), self.supplier()
        p1, p2, p3 = self.make_product(a), self.make_product(a), self.make_product(a)
        self.offer(b, p1, 900_000)                 # two sellers, both fresh → comparable
        self.offer(b, p2, 900_000, fresh=False)    # second seller's price is stale → not comparable
        self.offer(b, p3, 950_000, mode="rfq_only")  # second seller only quotes → no verified price
        env = {**READY_ENV, "VAMBI_MIN_COMPARABLE": str(base + 1)}
        r = self.readiness(env)
        c = r["checks"][0]
        self.assertEqual((c["key"], c["value"], c["threshold"], c["ok"]), ("comparable_products", base + 1, base + 1, True))
        self.assertTrue(r["ready"], r)
        r = self.readiness({**env, "VAMBI_MIN_COMPARABLE": str(base + 2)})
        self.assertFalse(r["checks"][0]["ok"])
        self.assertFalse(r["ready"])
        # A suspended seller no longer counts.
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE suppliers SET status='suspended' WHERE id=?", (b["supplier_id"],))
        self.assertEqual(self.readiness(env)["checks"][0]["value"], base)

    def test_default_threshold_is_50(self):
        self.assertEqual(launch.min_comparable({}), 50)
        self.assertEqual(launch.min_comparable({"VAMBI_MIN_COMPARABLE": "abc"}), 50)
        self.assertEqual(launch.min_comparable({"VAMBI_MIN_COMPARABLE": "7"}), 7)

    def test_settings_checks_and_no_secret_leak(self):
        r = self.readiness({"VAMBI_MIN_COMPARABLE": "1"})
        by = {c["key"]: c for c in r["checks"]}
        self.assertFalse(by["KAVENEGAR_SENDER"]["ok"])
        self.assertFalse(by["STOREFRONT_PRICE_VISIBILITY"]["ok"])  # default "public" is not a decision
        self.assertFalse(by["SSO_ORIGINS"]["ok"])
        self.assertTrue(by["migrations"]["ok"], by["migrations"])
        self.assertFalse(r["ready"])
        r = self.readiness({**READY_ENV, "STOREFRONT_PRICE_VISIBILITY": "bogus"})
        self.assertFalse({c["key"]: c for c in r["checks"]}["STOREFRONT_PRICE_VISIBILITY"]["ok"])
        r = self.readiness()
        self.assertNotIn("SECRET-LINE-10004321", json.dumps(r, ensure_ascii=False))
        self.assertEqual({c["key"]: c for c in r["checks"]}["KAVENEGAR_SENDER"]["detail"], "set")

    def test_missing_migration_reported(self):
        with self.db.write_transaction() as conn:
            conn.execute("DELETE FROM schema_migrations WHERE version='0082'")  # throwaway test DB only
        m = {c["key"]: c for c in self.readiness()["checks"]}["migrations"]
        self.assertEqual((m["ok"], m["missing"]), (False, ["0082"]))

    def test_admin_only_endpoint(self):
        url = "/api/v1/admin/vambi/readiness"
        self.assertEqual(self.client.get(url).status_code, 401)
        _, h = self.new_customer()
        self.assertEqual(self.client.get(url, headers=h).status_code, 403)
        with mock.patch.dict(os.environ, READY_ENV):
            r = self.client.get(url, headers=self.admin_headers())
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertIn("ready", r.get_json())
        self.assertNotIn("SECRET-LINE-10004321", r.get_data(as_text=True))

    def test_script_read_only_and_exit_code(self):
        from scripts import vambi_readiness as script
        url = self.settings.database_url
        before = os.path.getmtime(url[len("sqlite:///"):])
        out = io.StringIO()
        with mock.patch.dict(os.environ, {**READY_ENV, "DATABASE_URL": url, "VAMBI_MIN_COMPARABLE": "100000"}), redirect_stdout(out):
            code = script.main([])
        self.assertEqual(code, 1)
        self.assertIn("NOT READY", out.getvalue())
        self.assertNotIn("SECRET-LINE-10004321", out.getvalue())
        with mock.patch.dict(os.environ, {**READY_ENV, "DATABASE_URL": url, "VAMBI_MIN_COMPARABLE": "1"}), redirect_stdout(io.StringIO()):
            self.assertEqual(script.main(["--json"]), 0 if self.readiness({**READY_ENV, "VAMBI_MIN_COMPARABLE": "1"})["ready"] else 1)
        self.assertEqual(os.path.getmtime(url[len("sqlite:///"):]), before)
        with mock.patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{self.tmpdir}/missing-{uuid.uuid4().hex}.db"}):
            with self.assertRaises(SystemExit):
                script.main([])
