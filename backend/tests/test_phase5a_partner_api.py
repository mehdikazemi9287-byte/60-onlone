"""Phase 5A: partner API keys, partner endpoints, signed webhooks, inbound web services."""
from __future__ import annotations

import json
import socket
import time

from app.api import partner_v1
from app.api.v1 import admin_partner_api
from app.core import api_keys
from app.core.errors import ValidationError
from app.services import partner_webhook_service as hooks
from tests.base import TEST_SECRET, AppTestCase


def _public_resolver(host, port, proto=None):  # noqa: ARG001
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


class _Base(AppTestCase):
    def setUp(self):
        super().setUp()
        for bp in (partner_v1.bp, admin_partner_api.bp):  # registered by app/main.py
            if bp.name not in self.app.blueprints:
                self.app.register_blueprint(bp)
        self.admin = self.admin_headers()
        self.sup = self.create_test_supplier()
        self.offer = self.create_test_product_with_offer(self.sup["supplier_id"], self.sup["location_id"], stock=50)

    def make_client(self, scopes, **extra):
        body = {"name": "شریک تست", "owner_type": "supplier", "supplier_id": self.sup["supplier_id"],
                "scopes": scopes, **extra}
        r = self.client.post("/api/v1/admin/partner-clients", json=body, headers=self.admin)
        self.assertEqual(r.status_code, 201, r.get_json())
        d = r.get_json()
        return d["client"], d["key"]["api_key"]


class KeyAuthTests(_Base):
    def test_success_fail_revoked_scope(self):
        client, key = self.make_client(["catalog:read"])
        r = self.client.get("/api/partner/v1/me", headers={"X-Api-Key": key})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["client"]["scopes"], ["catalog:read"])
        # plaintext never stored
        with self.db.read_transaction() as c:
            stored = [tuple(x) for x in c.execute("SELECT prefix, secret_hash FROM partner_api_keys").fetchall()]
        self.assertTrue(all(key.split(".")[1] not in h for _, h in stored))
        for bad in ("", "nope", key + "x", key.split(".")[0] + ".wrong", "pk_000000000000.abc"):
            r = self.client.get("/api/partner/v1/me", headers={"X-Api-Key": bad})
            self.assertEqual(r.status_code, 401, bad)
            self.assertEqual(r.get_json()["error"]["code"], "invalid_api_key")
        r = self.client.get("/api/partner/v1/orders", headers={"X-Api-Key": key})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["error"]["code"], "insufficient_scope")
        r = self.client.get("/api/partner/v1/catalog/products?limit=1", headers={"X-Api-Key": key})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertIn("next_cursor", r.get_json())
        kid = client["keys"][0]["id"]
        r = self.client.post(f"/api/v1/admin/partner-clients/{client['id']}/keys/{kid}/rotate", headers=self.admin)
        self.assertEqual(r.status_code, 201)
        new_key = r.get_json()["key"]["api_key"]
        r = self.client.get("/api/partner/v1/me", headers={"X-Api-Key": key})
        self.assertEqual(r.get_json()["error"]["code"], "api_key_revoked")
        self.assertEqual(self.client.get("/api/partner/v1/me", headers={"X-Api-Key": new_key}).status_code, 200)
        # non-admin cannot manage clients
        _, cust = self.new_customer()
        self.assertEqual(self.client.get("/api/v1/admin/partner-clients", headers=cust).status_code, 403)
        with self.db.read_transaction() as c:
            n = c.execute("SELECT COUNT(*) FROM audit_logs WHERE action LIKE 'partner_%'").fetchone()[0]
        self.assertGreaterEqual(n, 3)

    def test_rate_limit(self):
        _, key = self.make_client(["catalog:read"], rate_limit_per_minute=2)
        h = {"X-Api-Key": key}
        self.assertEqual(self.client.get("/api/partner/v1/me", headers=h).status_code, 200)
        self.assertEqual(self.client.get("/api/partner/v1/me", headers=h).status_code, 200)
        r = self.client.get("/api/partner/v1/me", headers=h)
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.get_json()["error"]["code"], "rate_limited")
        self.assertIn("Retry-After", r.headers)

    def test_openapi(self):
        r = self.client.get("/api/partner/v1/openapi.json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["openapi"], "3.1.0")


class OfferScopeTests(_Base):
    def test_upsert_own_supplier_only(self):
        _, key = self.make_client(["offers:write"])
        h = {"X-Api-Key": key}
        r = self.client.put("/api/partner/v1/offers", headers=h,
                            json={"product_id": self.offer["product_id"], "stock_quantity": 3})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["offer"]["id"], self.offer["offer_id"])
        self.assertEqual(r.get_json()["offer"]["stock_quantity"], 3)
        with self.db.read_transaction() as c:  # stock 3 <= threshold -> offer.stock_low recorded
            self.assertEqual(c.execute("SELECT COUNT(*) FROM partner_webhook_events WHERE event_type='offer.stock_low'").fetchone()[0], 1)
        # another supplier's key creates its OWN offer, never touches the first one
        other = self.create_test_supplier()
        body = {"name": "دیگری", "owner_type": "supplier", "supplier_id": other["supplier_id"], "scopes": ["offers:write"]}
        key2 = self.client.post("/api/v1/admin/partner-clients", json=body, headers=self.admin).get_json()["key"]["api_key"]
        r = self.client.put("/api/partner/v1/offers", headers={"X-Api-Key": key2},
                            json={"product_id": self.offer["product_id"], "stock_quantity": 9, "selling_price_minor": 1_000_000})
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertEqual(r.get_json()["offer"]["supplier_id"], other["supplier_id"])
        with self.db.read_transaction() as c:
            row = c.execute("SELECT supplier_id, stock_quantity FROM seller_offers WHERE id=?", (self.offer["offer_id"],)).fetchone()
        self.assertEqual((row[0], row[1]), (self.sup["supplier_id"], 3))
        # an organization key cannot write offers
        org = self.create_organization()
        body = {"name": "سازمان", "owner_type": "organization", "organization_id": org["id"], "scopes": ["offers:write", "credit:read"]}
        key3 = self.client.post("/api/v1/admin/partner-clients", json=body, headers=self.admin).get_json()["key"]["api_key"]
        r = self.client.put("/api/partner/v1/offers", headers={"X-Api-Key": key3}, json={"product_id": self.offer["product_id"]})
        self.assertEqual(r.status_code, 403)
        r = self.client.get("/api/partner/v1/credit/balance", headers={"X-Api-Key": key3})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["balance"]["organization_id"], org["id"])


class WebhookTests(_Base):
    def test_signature_and_delivery(self):
        client, _ = self.make_client(["orders:read"])
        with self.db.write_transaction() as c:
            sub = hooks.create_subscription(c, client_id=client["id"], url="https://hooks.example.com/60",
                                            event_types=["order.created"], master_key=TEST_SECRET, actor_user_id=None,
                                            resolver=_public_resolver)
            hooks.emit(c, "order.created", {"order_id": 1}, supplier_ids=[self.sup["supplier_id"]], event_key="order.created:1")
            self.assertIsNone(hooks.emit(c, "order.created", {"order_id": 1}, event_key="order.created:1"))
            hooks.emit(c, "order.created", {"order_id": 2}, supplier_ids=[999999], event_key="order.created:2")
        sent = []
        calls = {"n": 0}

        def sender(url, body, headers):
            calls["n"] += 1
            sent.append((url, body, headers))
            return 500 if calls["n"] == 1 else 200

        stats = hooks.deliver_due(self.db, master_key=TEST_SECRET, sender=sender, resolver=_public_resolver)
        self.assertEqual(stats["retry"], 1)
        self.assertEqual(len(sent), 1)  # other supplier's event not delivered to this client
        url, body, headers = sent[0]
        secret = sub["signing_secret"]
        sig = headers["X-60Online-Signature"]
        self.assertTrue(api_keys.verify_signature(secret, sig, body))
        self.assertFalse(api_keys.verify_signature(secret, sig, body + b" "))
        self.assertFalse(api_keys.verify_signature("whsec_wrong", sig, body))
        self.assertFalse(api_keys.verify_signature(secret, sig, body, now=int(time.time()) + 400))
        self.assertEqual(json.loads(body)["type"], "order.created")
        from datetime import datetime, timedelta, timezone
        later = datetime.now(timezone.utc) + timedelta(minutes=5)
        stats = hooks.deliver_due(self.db, master_key=TEST_SECRET, sender=sender, resolver=_public_resolver, now=later)
        self.assertEqual(stats["delivered"], 1)
        with self.db.read_transaction() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM webhook_delivery_attempts").fetchone()[0], 2)

    def test_ssrf_refusal(self):
        for url in ("http://hooks.example.com/x", "https://127.0.0.1/x", "https://10.0.0.5/x", "https://169.254.169.254/",
                    "https://localhost/x", "https://user:pw@hooks.example.com/", "https://[::1]/x"):
            with self.assertRaises(ValidationError, msg=url):
                hooks.validate_webhook_url(url)
        with self.assertRaises(ValidationError):
            hooks.validate_webhook_url("https://hooks.example.com:8443/x", resolver=_public_resolver)
        self.assertTrue(hooks.validate_webhook_url("https://hooks.example.com:8443/x", allow_custom_port=True,
                                                   resolver=_public_resolver))
        with self.assertRaises(ValidationError):  # override relaxes port only, never private IPs
            hooks.validate_webhook_url("https://127.0.0.1:8443/x", allow_custom_port=True)
        client, _ = self.make_client(["orders:read"])
        r = self.client.post(f"/api/v1/admin/partner-clients/{client['id']}/webhooks", headers=self.admin,
                             json={"url": "https://127.0.0.1/hook", "event_types": ["order.created"]})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.get_json()["error"]["code"], "webhook_url_private")


class InboundTests(_Base):
    def test_hmac_and_idempotency(self):
        client, key = self.make_client(["offers:write", "shipments:write"])
        r = self.client.post(f"/api/v1/admin/partner-clients/{client['id']}/signing-secret/rotate", headers=self.admin)
        self.assertEqual(r.status_code, 201)
        secret = r.get_json()["signing_secret"]
        body = json.dumps({"items": [{"product_id": self.offer["product_id"], "stock_quantity": 40}]}).encode()
        url = "/api/partner/v1/inbound/supplier.price_stock"

        def post(raw, sig, idem="feed-0001"):
            return self.client.post(url, data=raw, content_type="application/json",
                                    headers={"X-Api-Key": key, "X-60Online-Signature": sig, "Idempotency-Key": idem})

        r = post(body, api_keys.sign("whsec_bad", body))
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["error"]["code"], "invalid_signature")
        r = post(body, api_keys.sign(secret, body, int(time.time()) - 600))
        self.assertEqual(r.status_code, 401)  # outside replay window
        r = post(body, api_keys.sign(secret, body))
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertEqual(r.get_json()["result"]["items"][0]["status"], "updated")
        r = post(body, api_keys.sign(secret, body))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["replayed"])
        other = json.dumps({"items": [{"product_id": self.offer["product_id"], "stock_quantity": 1}]}).encode()
        r = post(other, api_keys.sign(secret, other))
        self.assertEqual(r.status_code, 409)
        with self.db.read_transaction() as c:
            self.assertEqual(c.execute("SELECT stock_quantity FROM seller_offers WHERE id=?", (self.offer["offer_id"],)).fetchone()[0], 40)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM partner_inbound_messages").fetchone()[0], 1)
        track = json.dumps({"tracking_code": "NOPE", "status": "delivered"}).encode()
        r = self.client.post("/api/partner/v1/inbound/shipment.tracking", data=track, content_type="application/json",
                             headers={"X-Api-Key": key, "X-60Online-Signature": api_keys.sign(secret, track),
                                      "Idempotency-Key": "track-0001"})
        self.assertEqual(r.status_code, 404)
        r = self.client.post("/api/partner/v1/inbound/unknown.source", data=track, content_type="application/json",
                             headers={"X-Api-Key": key})
        self.assertEqual(r.status_code, 404)


class BridgeTests(_Base):
    def test_order_created_bridged_from_checkout_outbox(self):
        from app.services.integration_event_service import fan_out_business_event
        client, _ = self.make_client(["orders:read"], owner_type="platform")
        with self.db.write_transaction() as c:
            hooks.create_subscription(c, client_id=client["id"], url="https://hooks.example.com/60",
                                      event_types=["order.created"], master_key=TEST_SECRET, actor_user_id=None,
                                      resolver=_public_resolver)
            fan_out_business_event(c, event_type="ORDER_CREATED", organization_id=None,
                                   payload={"order_id": 4242, "order_number": "N-1", "total_minor": 10, "status": "paid"},
                                   base_idempotency_key="order_created:4242")
        self.assertEqual(hooks.bridge_integration_events(self.db), 1)
        self.assertEqual(hooks.bridge_integration_events(self.db), 0)
        with self.db.read_transaction() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0], 1)
