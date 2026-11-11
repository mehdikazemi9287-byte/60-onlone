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


class MetricsTest(LaunchBase):
    def counts(self):
        with self.db.read_transaction() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM vambi_daily_counts ORDER BY metric")]

    def test_search_counter_stores_no_query_or_user(self):
        _, h = self.new_customer()
        secret_q = "روغن-جستجوی-خصوصی"
        self.assertEqual(self.client.get(f"/api/v1/vambi/search?q={secret_q}", headers=h).status_code, 200)
        self.client.get(f"/api/v1/vambi/search?q={secret_q}")
        self.client.get(f"/api/v1/vambi/search?q={secret_q}&page=2")   # pagination is not a new search
        self.client.get("/api/v1/vambi/search")                        # landing page without a query
        rows = self.counts()
        self.assertEqual([(r["metric"], r["n"]) for r in rows], [("search", 2)])
        self.assertEqual(set(rows[0]), {"day", "metric", "n"})
        with self.db.read_transaction() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(vambi_daily_counts)")}
        self.assertEqual(cols, {"day", "metric", "n"})
        self.assertNotIn(secret_q, json.dumps(rows, ensure_ascii=False))

    def test_click_counter(self):
        for _ in range(3):
            self.assertEqual(self.client.post("/api/v1/vambi/click").status_code, 204)
        self.assertEqual([(r["metric"], r["n"]) for r in self.counts()], [("buy_click", 3)])

    def test_vambi_order_attribution(self):
        _, h = self.new_customer()
        r = self.client.post("/api/v1/me/referral", json={"code": "vambi"}, headers=h)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["source"], "vambi")
        kettle = self.product("appliance-kettle-2l")
        self.assertEqual(self.add_to_cart(h, kettle["id"], 1).status_code, 201)
        r = self.checkout(h)
        self.assertEqual(r.status_code, 201, r.get_json())
        order_id = r.get_json()["order"]["id"]
        _, h2 = self.new_customer()                       # no Vambi referral → not attributed
        self.assertEqual(self.add_to_cart(h2, kettle["id"], 1).status_code, 201)
        other = self.checkout(h2).get_json()["order"]["id"]
        with self.db.read_transaction() as conn:
            got = [r[0] for r in conn.execute("SELECT order_id FROM vambi_order_attributions")]
        self.assertEqual(got, [order_id])
        self.assertNotIn(other, got)
        m = self.client.get("/api/v1/admin/vambi/metrics?days=7", headers=self.admin_headers()).get_json()
        self.assertEqual((m["vambi_orders"]["orders"], m["vambi_orders"]["referral_landings"]), (1, 1))
        self.assertGreater(m["vambi_orders"]["total_minor"], 0)
        # "vambi" can never become an affiliate code that would earn on Vambi traffic.
        _, h3 = self.new_customer()
        r = self.client.post("/api/v1/me/affiliate", json={"code": "Vambi", "accept_terms": True}, headers=h3)
        self.assertEqual(r.status_code, 409, r.get_json())

    def test_price_update_rate(self):
        import datetime as dt
        now = dt.datetime(2026, 11, 10, 12, 0, tzinfo=dt.timezone.utc)
        iso = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        a, b, c = self.supplier(), self.supplier(), self.supplier()
        pid = self.make_product(a)
        oa, ob, oc = (self.offer(s, pid, 900_000) for s in (b, c, self.supplier()))  # oc: a fourth seller
        with self.db.write_transaction() as conn:
            sid_d = conn.execute("SELECT supplier_id FROM seller_offers WHERE id=?", (oc,)).fetchone()[0]
            uid = a["user_id"]

            def alert(sid, at, n=1):
                for k in range(n):  # several of the seller's users notified = still ONE transition
                    conn.execute("""INSERT INTO price_alert_events (user_id, product_id, supplier_id, level, alert_type,
                                    dedupe_key, sms_text, created_at, day) VALUES (?,?,?,'seller','lost_best_offer',?,'',?,?)""",
                                 (uid, pid, sid, uuid.uuid4().hex, iso(at), at.date().isoformat()))

            def change(offer_id, at, old=900_000, new=880_000):
                conn.execute("INSERT INTO offer_price_history (offer_id, old_price_minor, new_price_minor, changed_at) VALUES (?,?,?,?)",
                             (offer_id, old, new, at.strftime("%Y-%m-%dT%H:%M:%S.000Z")))

            t1 = now - dt.timedelta(days=5)
            alert(b["supplier_id"], t1, n=2); change(oa, t1 + dt.timedelta(hours=10))          # followed
            alert(c["supplier_id"], t1); change(ob, t1 + dt.timedelta(hours=80))                # too late
            change(ob, t1 - dt.timedelta(hours=1))                                              # before: ignored
            alert(sid_d, now - dt.timedelta(hours=20))                                          # window still open
            from app.services import vambi_launch_service as svc
            r = svc.price_update_rate(conn, since=now - dt.timedelta(days=30), now=now)
        self.assertEqual((r["alerts"], r["followed_by_price_change"], r["pending"], r["rate"], r["window_hours"]),
                         (2, 1, 1, 0.5, 72))

    def test_metrics_admin_only_and_days(self):
        url = "/api/v1/admin/vambi/metrics"
        self.assertEqual(self.client.get(url).status_code, 401)
        _, h = self.new_customer()
        self.assertEqual(self.client.get(url, headers=h).status_code, 403)
        admin = self.admin_headers()
        self.assertEqual(self.client.get(url + "?days=0", headers=admin).status_code, 422)
        self.assertEqual(self.client.get(url + "?days=x", headers=admin).status_code, 422)
        self.client.get("/api/v1/vambi/search?q=کتری")
        m = self.client.get(url + "?days=30", headers=admin).get_json()
        self.assertEqual(m["days"], 30)
        self.assertEqual(m["searches"]["total"], 1)
        for key in ("buy_clicks", "watches", "alerts", "vambi_orders", "seller_price_update"):
            self.assertIn(key, m)

    def test_seller_panel_price_change_is_recorded(self):
        from app.services import marketplace_offer_service as offers
        sup = self.supplier()
        pid = self.make_product(self.supplier())
        with self.db.write_transaction() as conn:
            o = offers.create(conn, supplier_id=sup["supplier_id"], actor=sup["user_id"],
                              data={"product_id": pid, "selling_price_minor": 1_000_000, "stock_quantity": 5,
                                    "supplier_location_id": sup["location_id"]})
            offers.update(conn, supplier_id=sup["supplier_id"], offer_id=o["id"], actor=sup["user_id"],
                          data={"selling_price_minor": 950_000, "stock_quantity": 5})
            rows = [tuple(r) for r in conn.execute(
                "SELECT old_price_minor, new_price_minor FROM offer_price_history WHERE offer_id=?", (o["id"],))]
        self.assertEqual(rows, [(1_000_000, 950_000)])
