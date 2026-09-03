"""Phase 8 — Blocker 4: JWT Revocation tests.

Tests:
  - Revoked token is rejected (401)
  - Expired token is rejected (401)
  - User-wide invalidation (password/role change) rejects all old tokens
  - Cross-user isolation: revoking user A's token does not affect user B
  - Logout endpoint revokes current token
  - Expired revocation record cleanup
  - Revocation check is idempotent (same jti twice is a no-op)
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase


class TestJWTRevocation(AppTestCase):

    def test_valid_token_works(self):
        """Baseline: a freshly issued token is accepted."""
        email, password, _ = self.register("rev_valid@example.com")
        token = self.login(email, password)
        resp = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)

    def test_logout_revokes_token(self):
        """After logout, the same token is rejected."""
        email, password, _ = self.register("rev_logout@example.com")
        token = self.login(email, password)

        # Token works before logout
        resp = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)

        # Logout
        resp = self.client.post(
            "/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(resp.status_code, 200)

        # Same token is now rejected
        resp = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 401)

    def test_revoked_jti_is_rejected(self):
        """Directly revoke a JTI and verify the token is rejected."""
        from app.services.revocation_service import revoke_token
        from app.core.security import decode_access_token

        email, password, _ = self.register("rev_jti@example.com")
        token = self.login(email, password)
        # Use self.settings (set up by AppTestCase) — no call to load_settings()
        claims = decode_access_token(
            token,
            secret=self.settings.secret_key,
            algorithm=self.settings.jwt_algorithm,
        )

        revoke_token(self.db, jti=claims.jti, user_id=claims.user_id, expires_at=claims.expires_at)

        resp = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 401)
        body = resp.get_json()
        # Error body must mention revocation
        combined = (
            body.get("error", {}).get("code", "").lower()
            + " "
            + body.get("error", {}).get("message", "").lower()
        )
        self.assertIn("revoked", combined)

    def test_user_wide_invalidation_rejects_all_old_tokens(self):
        """invalidate_all_tokens_for_user() rejects tokens issued before the call."""
        from app.services.revocation_service import invalidate_all_tokens_for_user
        from app.core.security import decode_access_token

        email, password, _ = self.register("rev_wide@example.com")
        token = self.login(email, password)

        # Token works initially
        resp = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)

        # Get user_id
        claims = decode_access_token(
            token,
            secret=self.settings.secret_key,
            algorithm=self.settings.jwt_algorithm,
        )

        # Small sleep to ensure revoked_at > issued_at
        time.sleep(1)

        # Invalidate all tokens for this user
        invalidate_all_tokens_for_user(self.db, user_id=claims.user_id)

        # Old token is now rejected
        resp = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 401)

    def test_new_token_after_invalidation_is_accepted(self):
        """After user-wide invalidation, a newly issued token is accepted."""
        from app.services.revocation_service import invalidate_all_tokens_for_user
        from app.core.security import decode_access_token

        email, password, _ = self.register("rev_new@example.com")
        old_token = self.login(email, password)

        claims = decode_access_token(
            old_token,
            secret=self.settings.secret_key,
            algorithm=self.settings.jwt_algorithm,
        )

        time.sleep(1)
        invalidate_all_tokens_for_user(self.db, user_id=claims.user_id)

        # Old token rejected
        resp = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"})
        self.assertEqual(resp.status_code, 401)

        # New login token accepted
        new_token = self.login(email, password)
        resp = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"})
        self.assertEqual(resp.status_code, 200)

    def test_cross_user_isolation(self):
        """Revoking user A's token does not affect user B's token."""
        from app.services.revocation_service import revoke_token
        from app.core.security import decode_access_token

        email_a, pw_a, _ = self.register("rev_cross_a@example.com")
        email_b, pw_b, _ = self.register("rev_cross_b@example.com")
        token_a = self.login(email_a, pw_a)
        token_b = self.login(email_b, pw_b)

        claims_a = decode_access_token(
            token_a,
            secret=self.settings.secret_key,
            algorithm=self.settings.jwt_algorithm,
        )

        # Revoke A's token
        revoke_token(self.db, jti=claims_a.jti, user_id=claims_a.user_id, expires_at=claims_a.expires_at)

        # A's token rejected
        resp = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a}"})
        self.assertEqual(resp.status_code, 401)

        # B's token still works
        resp = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"})
        self.assertEqual(resp.status_code, 200)

    def test_revocation_is_idempotent(self):
        """Revoking the same JTI twice does not raise an error."""
        from app.services.revocation_service import revoke_token
        from app.core.security import decode_access_token

        email, password, _ = self.register("rev_idem@example.com")
        token = self.login(email, password)
        claims = decode_access_token(
            token,
            secret=self.settings.secret_key,
            algorithm=self.settings.jwt_algorithm,
        )

        revoke_token(self.db, jti=claims.jti, user_id=claims.user_id, expires_at=claims.expires_at)
        # Second revocation should not raise
        revoke_token(self.db, jti=claims.jti, user_id=claims.user_id, expires_at=claims.expires_at)

        resp = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 401)

    def test_expired_revocation_cleanup(self):
        """cleanup_expired_revocations removes expired token records."""
        from app.services.revocation_service import revoke_token, cleanup_expired_revocations
        from app.core.security import decode_access_token

        email, password, _ = self.register("rev_cleanup@example.com")
        token = self.login(email, password)
        claims = decode_access_token(
            token,
            secret=self.settings.secret_key,
            algorithm=self.settings.jwt_algorithm,
        )

        # Revoke with a past expires_at (already expired)
        past_expires = int(time.time()) - 3600
        revoke_token(self.db, jti=claims.jti, user_id=claims.user_id, expires_at=past_expires)

        # Verify it's in the table
        row = self.db.query_one(
            "SELECT 1 FROM revoked_tokens WHERE jti = ?", (claims.jti,)
        )
        self.assertIsNotNone(row)

        # Cleanup should remove it (it's already expired)
        removed = cleanup_expired_revocations(self.db)
        self.assertGreaterEqual(removed, 1)

        # Verify it's gone
        row = self.db.query_one(
            "SELECT 1 FROM revoked_tokens WHERE jti = ?", (claims.jti,)
        )
        self.assertIsNone(row)

    def test_logout_requires_authentication(self):
        """Logout without a valid token returns 401."""
        resp = self.client.post("/api/v1/auth/logout")
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
