"""Phase 7 — Logistics Adapter tests.

Tests:
  - MockCarrierAdapter: get_quotes, create_shipment, cancel_shipment, get_tracking,
    normalize_webhook
  - MockCarrierAdapter: idempotent shipment (same idempotency key → same external_id)
  - NOT IMPLEMENTED carrier stubs: AloPeyk, Post, Tipax, Chapar raise NotImplementedError
  - CarrierAdapter base v2 contract: cancel_shipment, get_tracking, normalize_webhook default raise
  - Phase 7 logistics additions don't break existing mock tests
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.logistics.mock import MockCarrierAdapter, _hmac_sha256_hex
from app.adapters.logistics.base import (
    CarrierAdapter,
    ShipmentCreateRequest,
    ShipmentQuoteRequest,
    WebhookVerificationError,
)
from app.adapters.logistics.alopeyk import AloPeykCarrierAdapter
from app.adapters.logistics.post import IranPostCarrierAdapter
from app.adapters.logistics.tipax import TipaxCarrierAdapter
from app.adapters.logistics.chapar import ChaparCarrierAdapter


class TestMockCarrierAdapterPhase7(unittest.TestCase):

    def setUp(self):
        self.adapter = MockCarrierAdapter()

    def _make_create_request(self, key: str = "test-key-001") -> ShipmentCreateRequest:
        return ShipmentCreateRequest(
            fulfillment_order_id=1,
            carrier_config_id=0,
            origin_province="تهران",
            origin_city="تهران",
            destination_province="اصفهان",
            destination_city="اصفهان",
            booking_idempotency_key=key,
            cost_minor=120_000,
        )

    def test_get_quotes_returns_list(self):
        req = ShipmentQuoteRequest(
            fulfillment_order_id=1,
            provider_code="mock",
            origin_province="تهران",
            origin_city="تهران",
            destination_province="مشهد",
            destination_city="مشهد",
        )
        quotes = self.adapter.get_quotes(req)
        self.assertGreater(len(quotes), 0)
        for q in quotes:
            self.assertGreater(q.cost_minor, 0)

    def test_create_shipment_returns_result(self):
        result = self.adapter.create_shipment(self._make_create_request())
        self.assertTrue(result.succeeded)
        self.assertIsNotNone(result.external_shipment_id)
        self.assertIsNotNone(result.tracking_code)

    def test_create_shipment_idempotent(self):
        """Same idempotency key → same external_shipment_id."""
        req = self._make_create_request("idempotent-key-xyz")
        result1 = self.adapter.create_shipment(req)
        result2 = self.adapter.create_shipment(req)
        self.assertEqual(result1.external_shipment_id, result2.external_shipment_id)
        self.assertEqual(result1.tracking_code, result2.tracking_code)

    def test_cancel_shipment_success(self):
        result = self.adapter.create_shipment(self._make_create_request("cancel-key"))
        ext_id = result.external_shipment_id
        cancel = self.adapter.cancel_shipment(ext_id)
        self.assertTrue(cancel.succeeded)
        self.assertEqual(cancel.external_shipment_id, ext_id)

    def test_cancel_shipment_unknown_id_fails(self):
        cancel = self.adapter.cancel_shipment("UNKNOWN-ID-XYZ")
        self.assertFalse(cancel.succeeded)
        self.assertIsNotNone(cancel.failure_reason)

    def test_get_tracking_returns_result(self):
        result = self.adapter.create_shipment(self._make_create_request("track-key"))
        tracking = self.adapter.get_tracking(result.external_shipment_id)
        self.assertEqual(tracking.external_shipment_id, result.external_shipment_id)
        self.assertEqual(tracking.current_status, "in_transit")
        self.assertGreater(len(tracking.events), 0)

    def test_get_tracking_events_have_status(self):
        result = self.adapter.create_shipment(self._make_create_request("track-key-2"))
        tracking = self.adapter.get_tracking(result.external_shipment_id)
        for event in tracking.events:
            self.assertIn(event.status, {
                "created", "picked_up", "in_transit", "out_for_delivery",
                "delivered", "failed", "returned"
            })

    def test_normalize_webhook(self):
        body = {
            "event_id": "evt-norm-001",
            "event_type": "delivered",
            "shipment_id": "MOCK-ABCDEF",
        }
        event = self.adapter.normalize_webhook({}, body)
        self.assertEqual(event.event_type, "delivered")
        self.assertEqual(event.new_status, "delivered")
        self.assertEqual(event.external_shipment_id, "MOCK-ABCDEF")

    def test_verify_webhook_accepted(self):
        raw = b'{"event": "test"}'
        sig = _hmac_sha256_hex(raw)
        headers = {
            "X-Mock-Signature": sig,
            "X-Mock-Event-Id": "evt-001",
            "X-Mock-Shipment-Id": "MOCK-TEST",
            "X-Mock-Event-Type": "in_transit",
        }
        event = self.adapter.verify_webhook(headers, raw)
        self.assertEqual(event.new_status, "in_transit")

    def test_verify_webhook_rejected_bad_sig(self):
        raw = b'{"event": "test"}'
        headers = {
            "X-Mock-Signature": "badbad",
            "X-Mock-Event-Id": "evt-002",
            "X-Mock-Shipment-Id": "MOCK-TEST",
            "X-Mock-Event-Type": "delivered",
        }
        with self.assertRaises(WebhookVerificationError):
            self.adapter.verify_webhook(headers, raw)


class TestCarrierAdapterBaseV2(unittest.TestCase):
    """Base class default implementations should raise NotImplementedError."""

    def setUp(self):
        self.adapter = CarrierAdapter()

    def test_cancel_shipment_raises(self):
        with self.assertRaises(NotImplementedError):
            self.adapter.cancel_shipment("SOME-ID")

    def test_get_tracking_raises(self):
        with self.assertRaises(NotImplementedError):
            self.adapter.get_tracking("SOME-ID")

    def test_normalize_webhook_raises(self):
        with self.assertRaises(NotImplementedError):
            self.adapter.normalize_webhook({}, {})

    def test_verify_webhook_raises(self):
        with self.assertRaises(WebhookVerificationError):
            self.adapter.verify_webhook({}, b"")


class TestNotImplementedCarrierStubs(unittest.TestCase):
    """All NOT IMPLEMENTED carrier stubs must raise, not fabricate."""

    STUB_CLASSES = [
        AloPeykCarrierAdapter,
        IranPostCarrierAdapter,
        TipaxCarrierAdapter,
        ChaparCarrierAdapter,
    ]

    def _make_quote_req(self) -> ShipmentQuoteRequest:
        return ShipmentQuoteRequest(
            fulfillment_order_id=1,
            provider_code="stub",
            origin_province="تهران",
            origin_city="تهران",
            destination_province="تهران",
            destination_city="تهران",
        )

    def _make_create_req(self) -> ShipmentCreateRequest:
        return ShipmentCreateRequest(
            fulfillment_order_id=1,
            carrier_config_id=0,
            origin_province="تهران",
            origin_city="تهران",
            destination_province="تهران",
            destination_city="تهران",
            booking_idempotency_key="stub-key",
            cost_minor=100_000,
        )

    def test_all_stubs_get_quotes_raise(self):
        for cls in self.STUB_CLASSES:
            adapter = cls()
            with self.assertRaises(NotImplementedError):
                adapter.get_quotes(self._make_quote_req())

    def test_all_stubs_create_shipment_raise(self):
        for cls in self.STUB_CLASSES:
            adapter = cls()
            with self.assertRaises(NotImplementedError):
                adapter.create_shipment(self._make_create_req())

    def test_all_stubs_cancel_raise(self):
        for cls in self.STUB_CLASSES:
            adapter = cls()
            with self.assertRaises(NotImplementedError):
                adapter.cancel_shipment("SOME-ID")

    def test_all_stubs_get_tracking_raise(self):
        for cls in self.STUB_CLASSES:
            adapter = cls()
            with self.assertRaises(NotImplementedError):
                adapter.get_tracking("SOME-ID")

    def test_all_stubs_verify_webhook_raise(self):
        for cls in self.STUB_CLASSES:
            adapter = cls()
            with self.assertRaises(WebhookVerificationError):
                adapter.verify_webhook({}, b"")

    def test_all_stubs_have_not_implemented_status(self):
        for cls in self.STUB_CLASSES:
            adapter = cls()
            self.assertEqual(adapter.implementation_status, "not_implemented")


if __name__ == "__main__":
    unittest.main()
