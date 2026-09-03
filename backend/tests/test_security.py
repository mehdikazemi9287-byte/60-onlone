from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jwt  # noqa: E402

from app.core.security import (  # noqa: E402
    PasswordError,
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

SECRET = "unit-test-secret-0123456789abcdef-long-enough-for-hs256"


class PasswordHashingTest(unittest.TestCase):
    def test_digest_does_not_contain_the_password(self):
        digest = hash_password("SuperSecret!99")
        self.assertNotIn("SuperSecret!99", digest)
        self.assertTrue(digest.startswith("scrypt$"))

    def test_verify_accepts_correct_and_rejects_wrong(self):
        digest = hash_password("Passw0rd!23")
        self.assertTrue(verify_password("Passw0rd!23", digest))
        self.assertFalse(verify_password("Passw0rd!24", digest))
        self.assertFalse(verify_password("", digest))

    def test_salt_makes_digests_unique(self):
        self.assertNotEqual(hash_password("same-password"), hash_password("same-password"))

    def test_malformed_digest_is_false_not_an_exception(self):
        for bad in ("", "nonsense", "scrypt$x$y$z", "bcrypt$1$2$3$4$5"):
            self.assertFalse(verify_password("whatever", bad))

    def test_absurdly_long_password_is_rejected(self):
        with self.assertRaises(PasswordError):
            hash_password("a" * 2000)

    def test_unicode_password_roundtrips(self):
        digest = hash_password("رمزعبورفارسی۱۲۳")
        self.assertTrue(verify_password("رمزعبورفارسی۱۲۳", digest))


class TokenTest(unittest.TestCase):
    def _token(self, ttl: int = 60) -> str:
        return create_access_token(
            user_id=7, email="a@b.co", role="customer", secret=SECRET,
            algorithm="HS256", ttl_seconds=ttl,
        )

    def test_roundtrip(self):
        claims = decode_access_token(self._token(), secret=SECRET, algorithm="HS256")
        self.assertEqual(claims.user_id, 7)
        self.assertEqual(claims.role, "customer")

    def test_wrong_secret_rejected(self):
        with self.assertRaises(TokenError):
            decode_access_token(
                self._token(),
                secret="a-completely-different-secret-of-sufficient-length",
                algorithm="HS256",
            )

    def test_expired_token_rejected(self):
        token = self._token(ttl=-1)
        time.sleep(0.01)
        with self.assertRaises(TokenError):
            decode_access_token(token, secret=SECRET, algorithm="HS256")

    def test_alg_none_forgery_rejected(self):
        forged = jwt.encode({"sub": "1", "exp": 9999999999, "jti": "x"}, key="", algorithm="none")
        with self.assertRaises(TokenError):
            decode_access_token(forged, secret=SECRET, algorithm="HS256")

    def test_garbage_rejected(self):
        with self.assertRaises(TokenError):
            decode_access_token("not.a.token", secret=SECRET, algorithm="HS256")

    def test_tokens_are_unique_per_issue(self):
        self.assertNotEqual(self._token(), self._token())


if __name__ == "__main__":
    unittest.main()
