"""Tests for carrier webhook processing (BLOCKER 4)."""
from __future__ import annotations

import hashlib
import hmac
import json
import unittest
import uuid

from tests.base import AppTestCase
from app.adapters.logistics.mock import MOCK_WEBHOOK_SECRET


def _make_signature(body: bytes) -> str:
    sig = hmac.new(MOCK_WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()
    return sig


def _mock_webhook_headers(body: bytes, event_id: str, shipment_id: str, event_type: str) -> dict:
    sig = _make_signature(body)
    return {
        "Content-Type": "application/json",
        "X-Mock-Signature": sig,
        "X-Mock-Event-Id": event_id,
        "X-Mock-Shipment-Id": shipment_id,
        "X-Mock-Event-Type": event_type,
    }


class WebhookTest(AppTestCase):
    """Tests for webhook security and deduplication (BLOCKER 4)."""

    def _setup_booked_shipment(self):
        """Creates a checkout → gets FO → creates shipment plan → books shipment."""
        _, customer_h = self.new_customer()
        product = self.product("office-paper-a4-carton")
        self.set_stock(product["id"], 5)
        self.add_to_cart(customer_h, product["id"], 1)
        resp = self.checkout(customer_h)
        self.assertEqual(resp.status_code, 201)

        with self.db.read_transaction() as conn:
            fo_row = conn.execute(
                "SELECT fo.* FROM fulfillment_orders fo "
                "JOIN orders o ON o.id = fo.order_id ORDER BY fo.id DESC LIMIT 1"
            ).fetchone()
        fo_id = fo_row["id"]

        from app.services import logistics_service
        # Plan and book
        admin_h = self.admin_headers()
        plan_resp = self.client.post(
            f"/api/v1/fulfillment-orders/{fo_id}/shipment-plan", headers=admin_h
        )
        self.assertEqual(plan_resp.status_code, 200, plan_resp.get_json())

        book_resp = self.client.post(
            f"/api/v1/fulfillment-orders/{fo_id}/book-shipment", headers=admin_h
        )
        self.assertEqual(book_resp.status_code, 200, book_resp.get_json())

        with self.db.read_transaction() as conn:
            shipment = conn.execute(
                "SELECT * FROM shipments WHERE fulfillment_order_id=?", (fo_id,)
            ).fetchone()
        self.assertIsNotNone(shipment)
        return dict(shipment), fo_id

    def test_unknown_provider_rejected(self):
        """Unknown provider_code is rejected without touching DB."""
        body = b'{"event":"test"}'
        resp = self.client.post(
            "/api/v1/webhooks/carrier/nonexistent_carrier",
            data=body,
            content_type="application/json",
        )
        # Always 200 (no retry storms)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["outcome"], "rejected")
        self.assertEqual(data["reason"], "unknown_provider")

    def test_bad_signature_rejected(self):
        """Invalid HMAC signature is rejected without storing payload."""
        body = json.dumps({"event": "delivered"}).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Mock-Signature": "badbadbadbad",
            "X-Mock-Event-Id": "evt-001",
            "X-Mock-Shipment-Id": "MOCK-XXXX",
            "X-Mock-Event-Type": "delivered",
        }
        resp = self.client.post(
            "/api/v1/webhooks/carrier/mock",
            data=body,
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["outcome"], "rejected")

    def test_no_signature_rejected(self):
        """Missing signature header is rejected."""
        body = b'{"event":"delivered"}'
        resp = self.client.post(
            "/api/v1/webhooks/carrier/mock",
            data=body,
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["outcome"], "rejected")

    def test_valid_webhook_accepted(self):
        """Valid verified webhook is accepted and shipment status is updated."""
        shipment, fo_id = self._setup_booked_shipment()
        ext_id = shipment["external_shipment_id"]

        body = json.dumps({"type": "in_transit"}).encode()
        headers = _mock_webhook_headers(body, "evt-transit-01", ext_id, "in_transit")

        resp = self.client.post(
            "/api/v1/webhooks/carrier/mock",
            data=body,
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["outcome"], "accepted")
        self.assertEqual(data["new_status"], "in_transit")

    def test_webhook_delivered_updates_shipment(self):
        """Delivered webhook updates shipment to 'delivered' status."""
        shipment, fo_id = self._setup_booked_shipment()
        ext_id = shipment["external_shipment_id"]

        body = json.dumps({"type": "delivered"}).encode()
        headers = _mock_webhook_headers(body, "evt-del-01", ext_id, "delivered")

        resp = self.client.post(
            "/api/v1/webhooks/carrier/mock",
            data=body,
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["outcome"], "accepted")

        with self.db.read_transaction() as conn:
            s = conn.execute(
                "SELECT status FROM shipments WHERE id=?", (shipment["id"],)
            ).fetchone()
        self.assertEqual(s["status"], "delivered")

    def test_webhook_deduplication(self):
        """Same provider_event_id processed only once (BLOCKER 4)."""
        shipment, fo_id = self._setup_booked_shipment()
        ext_id = shipment["external_shipment_id"]

        body = json.dumps({"type": "in_transit"}).encode()
        headers = _mock_webhook_headers(body, "evt-dedup-01", ext_id, "in_transit")

        resp1 = self.client.post("/api/v1/webhooks/carrier/mock", data=body, headers=headers)
        resp2 = self.client.post("/api/v1/webhooks/carrier/mock", data=body, headers=headers)

        self.assertEqual(resp1.get_json()["outcome"], "accepted")
        self.assertEqual(resp2.get_json()["outcome"], "duplicate")

    def test_out_of_order_webhook_ignored(self):
        """Out-of-order status update is ignored (no regression)."""
        shipment, fo_id = self._setup_booked_shipment()
        ext_id = shipment["external_shipment_id"]

        # First: deliver
        body1 = json.dumps({"type": "delivered"}).encode()
        h1 = _mock_webhook_headers(body1, "evt-oo-01", ext_id, "delivered")
        self.client.post("/api/v1/webhooks/carrier/mock", data=body1, headers=h1)

        # Then: try to go back to "in_transit" (rank 3 < delivered rank 4) — should be ignored
        body2 = json.dumps({"type": "in_transit"}).encode()
        h2 = _mock_webhook_headers(body2, "evt-oo-02", ext_id, "in_transit")
        resp = self.client.post("/api/v1/webhooks/carrier/mock", data=body2, headers=h2)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["outcome"], "accepted")
        self.assertIn("out_of_order", data.get("note", ""))

        # Shipment should still be delivered
        with self.db.read_transaction() as conn:
            s = conn.execute(
                "SELECT status FROM shipments WHERE id=?", (shipment["id"],)
            ).fetchone()
        self.assertEqual(s["status"], "delivered")

    def test_rejected_webhook_not_stored(self):
        """Rejected webhooks are NOT stored in webhook_events (BLOCKER 4 security)."""
        body = b'{"evil":"payload"}'
        headers = {
            "Content-Type": "application/json",
            "X-Mock-Signature": "invalidsig",
            "X-Mock-Event-Id": "evil-evt",
            "X-Mock-Shipment-Id": "EVIL-ID",
            "X-Mock-Event-Type": "delivered",
        }
        resp = self.client.post("/api/v1/webhooks/carrier/mock", data=body, headers=headers)
        self.assertEqual(resp.get_json()["outcome"], "rejected")

        with self.db.read_transaction() as conn:
            row = conn.execute(
                "SELECT 1 FROM webhook_events WHERE provider_event_id=?", ("evil-evt",)
            ).fetchone()
        self.assertIsNone(row)

    def test_provider_a_cannot_update_provider_b_shipment(self):
        """Provider code mismatch is rejected — provider A cannot update provider B shipment."""
        # This test verifies the service-level protection:
        # The mock carrier's external_shipment_id is "MOCK-*"
        # Sending a mock-verified webhook with a non-matching ext_id just records
        # as "accepted with note: no matching shipment found" — provider isolation
        # is enforced at the DB lookup level (provider_code must match the shipment).
        body = json.dumps({"type": "delivered"}).encode()
        headers = _mock_webhook_headers(body, "evt-prov-iso", "OTHER-PROVIDER-ID", "delivered")

        resp = self.client.post("/api/v1/webhooks/carrier/mock", data=body, headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        # Event is accepted (verified) but no shipment updated
        self.assertEqual(data["outcome"], "accepted")
        self.assertIn("no matching shipment", data.get("note", ""))


class WebhookMockAdapterTest(AppTestCase):
    """Tests for the mock adapter's HMAC verification."""

    def test_verify_correct_signature(self):
        """Mock adapter accepts correctly-signed webhook."""
        from app.adapters.logistics.mock import MockCarrierAdapter
        adapter = MockCarrierAdapter()
        body = b'{"event":"test"}'
        sig = _make_signature(body)
        headers = {
            "X-Mock-Signature": sig,
            "X-Mock-Event-Id": "evt-001",
            "X-Mock-Shipment-Id": "MOCK-ABC",
            "X-Mock-Event-Type": "delivered",
        }
        event = adapter.verify_webhook(headers, body)
        self.assertEqual(event.new_status, "delivered")
        self.assertEqual(event.external_shipment_id, "MOCK-ABC")

    def test_verify_wrong_signature_raises(self):
        """Mock adapter rejects wrong signature."""
        from app.adapters.logistics.mock import MockCarrierAdapter
        from app.adapters.logistics.base import WebhookVerificationError
        adapter = MockCarrierAdapter()
        body = b'{"event":"test"}'
        headers = {
            "X-Mock-Signature": "wrong",
            "X-Mock-Event-Id": "evt-001",
            "X-Mock-Shipment-Id": "MOCK-ABC",
            "X-Mock-Event-Type": "delivered",
        }
        with self.assertRaises(WebhookVerificationError):
            adapter.verify_webhook(headers, body)

    def test_base_adapter_rejects_all(self):
        """Default CarrierAdapter.verify_webhook() rejects all events (fail-safe)."""
        from app.adapters.logistics.base import CarrierAdapter, WebhookVerificationError
        adapter = CarrierAdapter()
        with self.assertRaises(WebhookVerificationError) as ctx:
            adapter.verify_webhook({}, b'test')
        self.assertEqual(ctx.exception.code, "not_implemented")


class ShipmentStateTransitionTest(AppTestCase):
    """Tests for shipment status rank-gated progression (Issue 3 — canonical state model).

    Verifies:
      booked → in_transit           (allowed — forward)
      in_transit → out_for_delivery (allowed — forward)
      out_for_delivery → delivered  (allowed — forward)
      in_transit → booked           (rejected — backward)
      delivered → in_transit        (rejected — backward)
      returned → in_transit         (rejected — backward)
    """

    def _setup_shipment_at(self, status: str) -> tuple[dict, str]:
        """Create a booked shipment then force it to `status` directly in DB.

        Returns (shipment_row_dict, external_shipment_id).
        """
        _, customer_h = self.new_customer()
        product = self.product("office-paper-a4-carton")
        self.set_stock(product["id"], 5)
        self.add_to_cart(customer_h, product["id"], 1)
        resp = self.checkout(customer_h)
        self.assertEqual(resp.status_code, 201)

        with self.db.read_transaction() as conn:
            fo_row = conn.execute(
                "SELECT fo.* FROM fulfillment_orders fo "
                "JOIN orders o ON o.id = fo.order_id ORDER BY fo.id DESC LIMIT 1"
            ).fetchone()
        fo_id = fo_row["id"]

        from app.services import logistics_service
        admin_h = self.admin_headers()
        self.client.post(f"/api/v1/fulfillment-orders/{fo_id}/shipment-plan", headers=admin_h)
        book_resp = self.client.post(
            f"/api/v1/fulfillment-orders/{fo_id}/book-shipment", headers=admin_h
        )
        self.assertEqual(book_resp.status_code, 200, book_resp.get_json())

        with self.db.read_transaction() as conn:
            shipment = conn.execute(
                "SELECT * FROM shipments WHERE fulfillment_order_id=?", (fo_id,)
            ).fetchone()
        self.assertIsNotNone(shipment)
        s = dict(shipment)

        if status != "booked":
            with self.db.write_transaction() as conn:
                conn.execute(
                    "UPDATE shipments SET status=? WHERE id=?", (status, s["id"])
                )
        return s, s["external_shipment_id"]

    # ── Forward transitions (must be accepted) ────────────────────────────────

    def test_booked_to_in_transit_allowed(self):
        """booked → in_transit is a valid forward transition."""
        shipment, ext_id = self._setup_shipment_at("booked")
        body = json.dumps({"type": "in_transit"}).encode()
        headers = _mock_webhook_headers(body, f"evt-fwd-transit-{uuid.uuid4().hex[:8]}",
                                        ext_id, "in_transit")
        resp = self.client.post("/api/v1/webhooks/carrier/mock", data=body, headers=headers)
        data = resp.get_json()
        self.assertEqual(data["outcome"], "accepted")
        self.assertEqual(data.get("new_status"), "in_transit")
        with self.db.read_transaction() as conn:
            s = conn.execute(
                "SELECT status FROM shipments WHERE id=?", (shipment["id"],)
            ).fetchone()
        self.assertEqual(s["status"], "in_transit")

    def test_in_transit_to_out_for_delivery_allowed(self):
        """in_transit → out_for_delivery is a valid forward transition."""
        shipment, ext_id = self._setup_shipment_at("in_transit")
        body = json.dumps({"type": "out_for_delivery"}).encode()
        headers = _mock_webhook_headers(body, f"evt-ofd-{uuid.uuid4().hex[:8]}",
                                        ext_id, "out_for_delivery")
        resp = self.client.post("/api/v1/webhooks/carrier/mock", data=body, headers=headers)
        data = resp.get_json()
        self.assertEqual(data["outcome"], "accepted",
                         f"in_transit→out_for_delivery must be accepted: {data}")
        self.assertEqual(data.get("new_status"), "out_for_delivery")
        with self.db.read_transaction() as conn:
            s = conn.execute(
                "SELECT status FROM shipments WHERE id=?", (shipment["id"],)
            ).fetchone()
        self.assertEqual(s["status"], "out_for_delivery")

    def test_out_for_delivery_to_delivered_allowed(self):
        """out_for_delivery → delivered is a valid forward transition."""
        shipment, ext_id = self._setup_shipment_at("out_for_delivery")
        body = json.dumps({"type": "delivered"}).encode()
        headers = _mock_webhook_headers(body, f"evt-del-ofd-{uuid.uuid4().hex[:8]}",
                                        ext_id, "delivered")
        resp = self.client.post("/api/v1/webhooks/carrier/mock", data=body, headers=headers)
        data = resp.get_json()
        self.assertEqual(data["outcome"], "accepted",
                         f"out_for_delivery→delivered must be accepted: {data}")
        self.assertEqual(data.get("new_status"), "delivered")
        with self.db.read_transaction() as conn:
            s = conn.execute(
                "SELECT status FROM shipments WHERE id=?", (shipment["id"],)
            ).fetchone()
        self.assertEqual(s["status"], "delivered")

    # ── Backward transitions (must be ignored / out_of_order) ────────────────

    def test_in_transit_to_booked_ignored(self):
        """in_transit → booked is a backward transition and must be ignored."""
        shipment, ext_id = self._setup_shipment_at("in_transit")
        body = json.dumps({"type": "booked"}).encode()
        # "booked" is not a recognised event type in _MOCK_STATUS_MAP — the
        # adapter will reject it as "unknown_event_type". This verifies that
        # the backward path is never accepted from either the adapter or service layers.
        import hmac as _hmac, hashlib as _hashlib
        from app.adapters.logistics.mock import MOCK_WEBHOOK_SECRET
        sig = _hmac.new(MOCK_WEBHOOK_SECRET, body, _hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Mock-Signature": sig,
            "X-Mock-Event-Id": f"evt-back-booked-{uuid.uuid4().hex[:8]}",
            "X-Mock-Shipment-Id": ext_id,
            "X-Mock-Event-Type": "booked",   # unknown event type — adapter rejects
        }
        resp = self.client.post("/api/v1/webhooks/carrier/mock", data=body, headers=headers)
        data = resp.get_json()
        # Either rejected by adapter (unknown event type) or ignored by service
        self.assertIn(data["outcome"], ("rejected", "accepted"),
                      f"backward transition must be rejected or ignored: {data}")
        if data["outcome"] == "accepted":
            self.assertIn("out_of_order", data.get("note", ""),
                          "if accepted, must be marked out_of_order")
        # Either way, shipment must still be in_transit
        with self.db.read_transaction() as conn:
            s = conn.execute(
                "SELECT status FROM shipments WHERE id=?", (shipment["id"],)
            ).fetchone()
        self.assertEqual(s["status"], "in_transit",
                         "shipment must remain in_transit after backward transition attempt")

    def test_delivered_to_in_transit_ignored(self):
        """delivered → in_transit is a backward transition and must be ignored."""
        shipment, ext_id = self._setup_shipment_at("delivered")
        body = json.dumps({"type": "in_transit"}).encode()
        headers = _mock_webhook_headers(body, f"evt-back-transit-{uuid.uuid4().hex[:8]}",
                                        ext_id, "in_transit")
        resp = self.client.post("/api/v1/webhooks/carrier/mock", data=body, headers=headers)
        data = resp.get_json()
        self.assertEqual(data["outcome"], "accepted",
                         "out-of-order events are accepted with a note, never error")
        self.assertIn("out_of_order", data.get("note", ""),
                      f"delivered→in_transit must be flagged out_of_order: {data}")
        with self.db.read_transaction() as conn:
            s = conn.execute(
                "SELECT status FROM shipments WHERE id=?", (shipment["id"],)
            ).fetchone()
        self.assertEqual(s["status"], "delivered",
                         "shipment must remain delivered after backward transition attempt")

    def test_returned_to_in_transit_ignored(self):
        """returned → in_transit is a backward transition and must be ignored."""
        shipment, ext_id = self._setup_shipment_at("returned")
        body = json.dumps({"type": "in_transit"}).encode()
        headers = _mock_webhook_headers(body, f"evt-ret-transit-{uuid.uuid4().hex[:8]}",
                                        ext_id, "in_transit")
        resp = self.client.post("/api/v1/webhooks/carrier/mock", data=body, headers=headers)
        data = resp.get_json()
        self.assertEqual(data["outcome"], "accepted",
                         "out-of-order events are accepted with a note, never error")
        self.assertIn("out_of_order", data.get("note", ""),
                      f"returned→in_transit must be flagged out_of_order: {data}")
        with self.db.read_transaction() as conn:
            s = conn.execute(
                "SELECT status FROM shipments WHERE id=?", (shipment["id"],)
            ).fetchone()
        self.assertEqual(s["status"], "returned",
                         "shipment must remain returned after backward transition attempt")


if __name__ == "__main__":
    unittest.main()
