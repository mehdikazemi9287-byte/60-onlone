"""Price alert SMS lifecycle — audit 2026-11-10 findings SO-02, SO-03, N1, N3.

SYNTHETIC fixtures only (see tests/test_price_alerts.py): throwaway SQLite per test, in-process senders, no network.
Each test fails on the code before the fix (consent read only at event creation; events marked "sent" before the
provider call; no recovery of stuck digests; console sender accepted on staging).
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from app.adapters import sms as sms_mod
from app.adapters.sms import ConsoleSms, SmsError, SmsOutcomeUnknown
from app.core.db import Database
from app.core.migrator import upgrade
from app.services import price_alert_service as svc
from tests.test_price_alerts import PriceAlertFixtures

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


class CrashSms(ConsoleSms):
    """Synthetic: the process dies inside the provider call (BaseException is not caught by the job)."""

    def send_text(self, phone, text):
        raise SystemExit("synthetic kill during provider call")


class UnknownSms(ConsoleSms):
    def send_text(self, phone, text):
        raise SmsOutcomeUnknown("synthetic read timeout")


class RefSms(ConsoleSms):
    def send_text(self, phone, text):
        super().send_text(phone, text)
        return "synthetic-msg-1"


class SmsLifecycleTest(PriceAlertFixtures):
    def setUp(self):
        super().setUp()
        self._env = {k: os.environ.get(k) for k in ("APP_ENV", "SMS_PROVIDER")}

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    # helpers
    def at(self, hours):
        return self.now + dt.timedelta(hours=hours)

    def generate(self, hours):
        """Create alert events without dispatching SMS."""
        svc.run_watches(self.db, self.at(hours))
        svc.run_sellers(self.db, self.at(hours))

    def send(self, hours, sender=None):
        return svc.send_digests(self.db, sender=sender or ConsoleSms(), now=self.at(hours))

    def events(self):
        with self.db.read_transaction() as conn:
            return [dict(r) for r in conn.execute("SELECT sms_status, sms_reason, level FROM price_alert_events ORDER BY id")]

    def digests(self):
        with self.db.read_transaction() as conn:
            return [dict(r) for r in conn.execute("SELECT status, provider_ref FROM price_alert_sms ORDER BY id")]

    def buyer_with_pending(self):
        _, consumer = self.new_customer()
        self.verify_phone(consumer)
        w = self.watch(consumer)["watch"]
        self.tick()
        self.set_price(self.offer1, price=900_000)
        self.generate(1)
        self.assertEqual([e["sms_status"] for e in self.events()], ["pending"])
        return consumer, w

    # SO-02 — opt-out between creation and dispatch
    def test_sms_off_before_dispatch_sends_nothing(self):
        consumer, w = self.buyer_with_pending()
        r = self.client.patch(f"/api/v1/me/price-watches/{w['id']}", json={"sms_enabled": False}, headers=consumer)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.events(), [{"sms_status": "canceled", "sms_reason": "sms_disabled", "level": "consumer"}])
        self.send(1)
        self.assertEqual(ConsoleSms.texts, [])
        self.assertEqual(len(self.notes(consumer)), 1)  # the in-site notice stays

    def test_pause_before_dispatch_sends_nothing(self):
        consumer, w = self.buyer_with_pending()
        self.client.patch(f"/api/v1/me/price-watches/{w['id']}", json={"active": False}, headers=consumer)
        self.send(1)
        self.assertEqual(ConsoleSms.texts, [])
        self.assertEqual(self.events()[0]["sms_reason"], "watch_paused")

    # N3 — deleting the alert cancels its queue
    def test_delete_before_dispatch_sends_nothing(self):
        consumer, w = self.buyer_with_pending()
        self.assertIn(self.client.delete(f"/api/v1/me/price-watches/{w['id']}", headers=consumer).status_code, (200, 204))
        self.assertEqual(self.events()[0]["sms_status"], "canceled")
        self.send(1)
        self.assertEqual(ConsoleSms.texts, [])

    def test_reservation_rereads_consent(self):
        """A flag changed outside update_watch, and a legacy line whose watch is gone, are both refused at reserve."""
        _, other = self.new_customer()
        self.verify_phone(other)
        consumer, w = self.buyer_with_pending()
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE price_watches SET sms_enabled=0 WHERE id=?", (w["id"],))
        r = self.send(1)
        self.assertEqual((ConsoleSms.texts, r["canceled"]), ([], 1))
        self.assertEqual(self.events()[0]["sms_reason"], "sms_disabled")
        with self.db.write_transaction() as conn:  # legacy: pending line whose watch was deleted before this fix
            conn.execute("UPDATE price_alert_events SET sms_status='pending', sms_reason=NULL, watch_id=NULL")
        self.send(2)
        self.assertEqual(ConsoleSms.texts, [])
        self.assertEqual(self.events()[0]["sms_reason"], "watch_deleted")

    def test_seller_opt_out_cancels_queued_seller_lines(self):
        s2 = self.make_seller("رقیب")
        o3 = self.make_offer(s2["supplier_id"], self.pid, 1_500_000)
        self.verify_phone(self.s1["headers"])
        self.tick()
        self.set_price(o3, price=500_000)
        self.generate(1)
        seller = [e for e in self.events() if e["level"] == "seller"]
        self.assertTrue(seller and all(e["sms_status"] == "pending" for e in seller))
        r = self.client.patch("/api/v1/supplier/price-alerts/settings", json={"sms_enabled": False}, headers=self.s1["headers"])
        self.assertEqual(r.status_code, 200)
        self.send(1)
        self.assertEqual(ConsoleSms.texts, [])
        self.assertTrue(all(e["sms_status"] == "canceled" and e["sms_reason"] == "seller_sms_off"
                            for e in self.events() if e["level"] == "seller"))

    def test_unrelated_user_opt_out_does_not_cancel_others(self):
        consumer, w = self.buyer_with_pending()
        _, other = self.new_customer()
        w2 = self.watch(other)["watch"]
        self.client.patch(f"/api/v1/me/price-watches/{w2['id']}", json={"sms_enabled": False}, headers=other)
        self.assertEqual(self.client.patch(f"/api/v1/me/price-watches/{w['id']}", json={"sms_enabled": False},
                                           headers=other).status_code, 404)
        self.send(1)
        self.assertEqual(len(ConsoleSms.texts), 1)
        self.assertEqual(self.events()[0]["sms_status"], "sent")

    # SO-03 — "sent" only after the provider accepted
    def test_event_is_not_sent_before_the_provider_call(self):
        self.buyer_with_pending()
        seen = []
        test = self

        class Probe(ConsoleSms):
            def send_text(self, phone, text):
                seen.append((test.events()[0]["sms_status"], test.digests()[0]["status"]))
                super().send_text(phone, text)

        self.send(1, Probe())
        self.assertEqual(seen, [("reserved", "sending")])
        self.assertEqual(self.events()[0]["sms_status"], "sent")
        self.assertEqual(self.digests()[0]["status"], "sent")

    def test_provider_ref_is_recorded(self):
        self.buyer_with_pending()
        self.send(1, RefSms())
        self.assertEqual(self.digests(), [{"status": "sent", "provider_ref": "synthetic-msg-1"}])

    def test_crash_during_call_becomes_unknown_and_frees_the_cap(self):
        os.environ["PRICE_ALERT_USER_DAILY_SMS"] = "1"
        consumer, _ = self.buyer_with_pending()
        with self.assertRaises(SystemExit):
            self.send(1, CrashSms())
        self.assertEqual((self.events()[0]["sms_status"], self.digests()[0]["status"]), ("reserved", "sending"))
        # a second item for the same user, later the same Tehran day
        pid2, slug2 = self.make_product()
        o2 = self.make_offer(self.s1["supplier_id"], pid2, 2_000_000)
        self.client.post("/api/v1/me/price-watches", json={"slug": slug2}, headers=consumer)
        svc.run_watches(self.db, self.at(2))
        self.set_price(o2, price=1_900_000)
        self.generate(3)
        r = self.send(3)
        self.assertEqual(r["recovered"], {"released": 0, "unknown": 1})
        statuses = [e["sms_status"] for e in self.events()]
        self.assertEqual(statuses, ["unknown", "sent"])  # stuck row not counted against the 1/day cap
        self.assertEqual(len(ConsoleSms.texts), 1)
        self.send(4)
        self.assertEqual(len(ConsoleSms.texts), 1)  # the unknown line is never resent blindly

    def test_crash_after_reservation_is_released_and_sent_once(self):
        self.buyer_with_pending()
        stats = {k: 0 for k in ("canceled", "skipped_item", "skipped_cap", "unavailable")}
        with self.db.write_transaction() as conn:  # reserved, then the process dies before the provider call
            self.assertIsNotNone(svc._reserve_digest(conn, self._uid(), "buyer", self.at(1), ConsoleSms(), stats))
        self.assertEqual(self.digests()[0]["status"], "reserved")
        r = self.send(2)
        self.assertEqual(r["recovered"], {"released": 1, "unknown": 0})
        self.assertEqual(len(ConsoleSms.texts), 1)
        self.assertEqual([d["status"] for d in self.digests()], ["failed", "sent"])
        self.assertEqual(self.events()[0]["sms_status"], "sent")

    def test_fresh_reservation_is_not_recovered(self):
        self.buyer_with_pending()
        stats = {k: 0 for k in ("canceled", "skipped_item", "skipped_cap", "unavailable")}
        with self.db.write_transaction() as conn:
            svc._reserve_digest(conn, self._uid(), "buyer", self.at(1), ConsoleSms(), stats)
        self.assertEqual(svc.recover_stuck(self.db, self.at(1) + dt.timedelta(minutes=5)), {"released": 0, "unknown": 0})

    def test_unknown_outcome_is_not_retried(self):
        self.buyer_with_pending()
        r = self.send(1, UnknownSms())
        self.assertEqual((r["unknown"], r["failed"], r["sent"]), (1, 0, 0))
        self.assertEqual((self.events()[0]["sms_status"], self.digests()[0]["status"]), ("unknown", "unknown"))
        self.send(2)
        self.assertEqual(ConsoleSms.texts, [])

    def _uid(self):
        with self.db.read_transaction() as conn:
            return int(conn.execute("SELECT user_id FROM price_alert_events ORDER BY id LIMIT 1").fetchone()[0])

    # N1 — console sender refused outside development/test
    def test_console_sender_refused_on_staging_and_production(self):
        os.environ.pop("SMS_PROVIDER", None)
        for env in ("staging", "production"):
            os.environ["APP_ENV"] = env
            with self.assertRaises(SmsError):
                sms_mod.sender_from_env()
        os.environ["APP_ENV"] = "test"
        self.assertIsInstance(sms_mod.sender_from_env(), ConsoleSms)

    def test_staging_digest_is_unavailable_not_sent(self):
        self.buyer_with_pending()
        os.environ.pop("SMS_PROVIDER", None)
        os.environ["APP_ENV"] = "staging"
        r = svc.send_digests(self.db, sender=None, now=self.at(1))
        self.assertEqual((r["sent"], r["unavailable"]), (0, 1))
        self.assertEqual(ConsoleSms.texts, [])
        self.assertEqual(self.events()[0]["sms_status"], "unavailable")

    def test_staging_otp_refuses_console(self):
        from app.services import otp_service
        os.environ.pop("SMS_PROVIDER", None)
        os.environ["APP_ENV"] = "staging"
        with self.db.write_transaction() as conn:
            with self.assertRaises(otp_service.SmsUnavailable):
                otp_service.request_code(conn, phone="09120000001", secret="s" * 40, sender=ConsoleSms())
        self.assertNotIn("09120000001", ConsoleSms.outbox)

    def test_console_texts_are_bounded(self):
        for i in range(sms_mod.CONSOLE_TEXTS_KEPT + 5):
            ConsoleSms().send_text("09120000000", str(i))
        self.assertEqual(len(ConsoleSms.texts), sms_mod.CONSOLE_TEXTS_KEPT)


class KavenegarOutcomeTest(unittest.TestCase):
    """Provider reply classification without network (urlopen is patched)."""

    def setUp(self):
        self.s = sms_mod.KavenegarSms("synthetic-key", "tpl", sender="1000")

    def test_read_timeout_is_unknown(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("read")):
            with self.assertRaises(SmsOutcomeUnknown):
                self.s.send_text("09120000000", "x")

    def test_connection_error_is_plain_failure(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            with self.assertRaises(SmsError) as cm:
                self.s.send_text("09120000000", "x")
        self.assertNotIsInstance(cm.exception, SmsOutcomeUnknown)

    def test_accepted_returns_message_id(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b'{"return":{"status":200},"entries":[{"messageid":8792343}]}'
        with mock.patch("urllib.request.urlopen", return_value=resp):
            self.assertEqual(self.s.send_text("09120000000", "x"), "8792343")


class Migration0083Test(unittest.TestCase):
    """0083 keeps existing price alert rows and accepts the new states (SQLite rebuild)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="60online-m83-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rows_survive_and_new_states_are_allowed(self):
        old = Path(self.tmp) / "old"
        old.mkdir()
        for p in MIGRATIONS.glob("*.sql"):
            if p.name < "0083":
                shutil.copy(p, old / p.name)
        db = Database(str(Path(self.tmp) / "m.db"))
        try:
            upgrade(db, directory=old)
            with db.write_transaction() as conn:
                uid = conn.execute("INSERT INTO users (email, email_normalized, password_hash, full_name) VALUES ('m83@example.com','m83@example.com','scrypt$synthetic-test-hash-not-a-real-password-0000','آزمایشی')").lastrowid
                cat = conn.execute("SELECT id FROM categories ORDER BY id LIMIT 1").fetchone()
                cat = cat[0] if cat else conn.execute("INSERT INTO categories (slug, name_fa) VALUES ('m83','آزمایشی')").lastrowid
                pid = conn.execute("INSERT INTO products (slug, sku, title_fa, category_id, base_price_minor) VALUES ('m83','m83','آزمایشی',?,1)",
                                   (cat,)).lastrowid
                sid = conn.execute("INSERT INTO price_alert_sms (user_id, run_hour, day, item_count, status, created_at) "
                                   "VALUES (?, '2026-11-01T06', '2026-11-01', 1, 'sending', '2026-11-01T06:00:00Z')", (uid,)).lastrowid
                conn.execute("INSERT INTO price_alert_events (user_id, product_id, level, alert_type, dedupe_key, sms_text, sms_status,"
                             " sms_id, created_at, day) VALUES (?,?, 'consumer', 'price_target', 'k1', 't', 'sent', ?, '2026-11-01T06:00:00Z',"
                             " '2026-11-01')", (uid, pid, sid))
            self.assertEqual(upgrade(db)[:1], ["0083"])  # later migrations (0084+) may follow
            with db.write_transaction() as conn:
                self.assertEqual(tuple(conn.execute("SELECT status FROM price_alert_sms").fetchone()), ("sending",))
                self.assertEqual(tuple(conn.execute("SELECT sms_status, sms_id FROM price_alert_events").fetchone()), ("sent", sid))
                conn.execute("UPDATE price_alert_sms SET status='unknown', attempt_at='x', provider_ref='r', finished_at='y'")
                conn.execute("UPDATE price_alert_events SET sms_status='canceled', sms_reason='watch_deleted'")
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute("UPDATE price_alert_events SET sms_status='bogus'")
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            # the legacy 'sending' row of the old code is resolved by recovery
            with db.write_transaction() as conn:
                conn.execute("UPDATE price_alert_sms SET status='sending', attempt_at=NULL")
                conn.execute("UPDATE price_alert_events SET sms_status='sent'")
            self.assertEqual(svc.recover_stuck(db, dt.datetime(2026, 11, 2, tzinfo=dt.timezone.utc)), {"released": 0, "unknown": 1})
            with db.read_transaction() as conn:
                self.assertEqual(conn.execute("SELECT sms_status FROM price_alert_events").fetchone()[0], "unknown")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
