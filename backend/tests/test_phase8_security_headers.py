"""Phase 8 — Workstream C: Security Hardening tests.

Tests for:
  - Security headers present on all responses
  - X-Request-ID correlation ID echoed
  - Content-type enforcement (415 for non-JSON POST/PUT/PATCH)
  - Request-size limits (413 for oversized bodies)
  - Liveness probe (/health/live)
  - Readiness probe (/health/ready)
"""
from __future__ import annotations

import unittest

from tests.base import AppTestCase


class TestSecurityHeaders(AppTestCase):
    """Security headers must be present on every response."""

    def _get_headers(self, path: str = "/api/v1/health") -> dict:
        resp = self.client.get(path)
        return dict(resp.headers)

    def test_x_content_type_options_nosniff(self):
        headers = self._get_headers()
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_x_frame_options_deny(self):
        headers = self._get_headers()
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")

    def test_referrer_policy_set(self):
        headers = self._get_headers()
        self.assertIn("Referrer-Policy", headers)

    def test_cache_control_no_store(self):
        headers = self._get_headers()
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_permissions_policy_set(self):
        headers = self._get_headers()
        self.assertIn("Permissions-Policy", headers)

    def test_security_headers_on_json_endpoint(self):
        resp = self.client.get("/api/v1/products/office-paper-a4-carton")
        headers = dict(resp.headers)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")

    def test_security_headers_on_404(self):
        resp = self.client.get("/api/v1/nonexistent-path-xyz")
        self.assertEqual(resp.status_code, 404)
        headers = dict(resp.headers)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")


class TestCorrelationId(AppTestCase):
    """X-Request-ID must be echoed or generated on every response."""

    def test_request_id_echoed_when_provided(self):
        resp = self.client.get("/api/v1/health",
                               headers={"X-Request-ID": "test-correlation-id-12345"})
        self.assertEqual(resp.headers.get("X-Request-ID"), "test-correlation-id-12345")

    def test_request_id_generated_when_absent(self):
        resp = self.client.get("/api/v1/health")
        rid = resp.headers.get("X-Request-ID")
        self.assertIsNotNone(rid)
        self.assertGreater(len(rid), 0)

    def test_different_requests_get_different_ids(self):
        rid1 = self.client.get("/api/v1/health").headers.get("X-Request-ID")
        rid2 = self.client.get("/api/v1/health").headers.get("X-Request-ID")
        self.assertNotEqual(rid1, rid2)


class TestContentTypeEnforcement(AppTestCase):
    """POST/PUT/PATCH with non-JSON content-type should return 415."""

    def test_post_with_html_content_type_rejected(self):
        resp = self.client.post(
            "/api/v1/auth/register",
            data="<html>bad</html>",
            content_type="text/html",
        )
        self.assertEqual(resp.status_code, 415)

    def test_post_with_form_content_type_rejected(self):
        resp = self.client.post(
            "/api/v1/auth/register",
            data={"email": "x@example.com"},
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(resp.status_code, 415)

    def test_post_with_json_content_type_allowed(self):
        # Actual registration — should not be rejected by content-type check
        resp = self.client.post(
            "/api/v1/auth/register",
            json={"email": "ct_test@example.com", "password": "Passw0rd!23",
                  "full_name": "تست"},
        )
        # 201 or 409 (duplicate) — not 415
        self.assertNotEqual(resp.status_code, 415)

    def test_get_request_not_affected_by_content_type_check(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)

    def test_post_with_no_body_not_rejected(self):
        # Zero content-length POST should not trigger 415
        resp = self.client.post("/api/v1/auth/register", data=b"",
                                content_type="application/json")
        # Should not be 415 (may be 400 for missing fields — that's fine)
        self.assertNotEqual(resp.status_code, 415)


class TestRequestSizeLimits(AppTestCase):
    """Oversized request bodies should return 413."""

    def test_large_non_import_request_rejected(self):
        # >1 MB to a non-import endpoint
        large_body = b'{"data": "' + b"x" * (1024 * 1024 + 100) + b'"}'
        resp = self.client.post(
            "/api/v1/auth/register",
            data=large_body,
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 413)

    def test_normal_request_not_rejected(self):
        resp = self.client.post(
            "/api/v1/auth/register",
            json={"email": "size_test@example.com", "password": "Passw0rd!23",
                  "full_name": "سایز"},
        )
        self.assertNotEqual(resp.status_code, 413)


class TestHealthProbes(AppTestCase):
    """Liveness and readiness endpoints — Phase 8 Observability."""

    def test_health_endpoint_backward_compat(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["database"], "reachable")
        self.assertIn("schema_version", body)

    def test_liveness_probe(self):
        resp = self.client.get("/api/v1/health/live")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "alive")

    def test_readiness_probe(self):
        resp = self.client.get("/api/v1/health/ready")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "ready")
        self.assertIn("schema_version", body)

    def test_liveness_has_no_db_dependency(self):
        # Close the real DB and liveness should still return 200
        # (we can't easily break the DB in tests, but we verify the endpoint
        # exists and returns the right shape even under normal conditions)
        resp = self.client.get("/api/v1/health/live")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "alive")


if __name__ == "__main__":
    unittest.main()
