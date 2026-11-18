from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase  # noqa: E402


class RegisterTest(AppTestCase):
    def test_register_returns_token_and_user(self):
        _, _, response = self.register("new.user@example.com")
        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertIn("access_token", body)
        self.assertEqual(body["user"]["email"], "new.user@example.com")
        self.assertEqual(body["user"]["role"], "customer")
        self.assertNotIn("password", str(body))

    def test_password_is_never_stored_in_plaintext(self):
        password = "Sup3rSecret!x"
        email, _, _ = self.register("hash.check@example.com", password=password)
        row = self.db.query_one(
            "SELECT password_hash FROM users WHERE email_normalized = ?", (email,)
        )
        self.assertNotEqual(row["password_hash"], password)
        self.assertNotIn(password, row["password_hash"])
        self.assertTrue(row["password_hash"].startswith("scrypt$"))

    def test_no_plaintext_password_anywhere_in_the_database(self):
        password = "Uniq2ePassPhrase!"
        self.register("scan@example.com", password=password)
        tables = [
            r["name"]
            for r in self.db.query("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        for table in tables:
            columns = [r["name"] for r in self.db.query(f"PRAGMA table_info({table})")]
            for row in self.db.query(f"SELECT * FROM {table}"):
                for column in columns:
                    self.assertNotIn(
                        password, str(row[column] or ""),
                        f"plaintext password leaked into {table}.{column}",
                    )

    def test_duplicate_email_is_rejected(self):
        self.register("dup@example.com")
        _, _, again = self.register("dup@example.com")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.get_json()["error"]["code"], "email_taken")

    def test_email_is_case_insensitive_for_uniqueness(self):
        self.register("Case@Example.com")
        _, _, again = self.register("case@example.COM")
        self.assertEqual(again.status_code, 409)

    def test_weak_password_is_rejected(self):
        _, _, response = self.register("weak@example.com", password="123")
        self.assertEqual(response.status_code, 422)
        self.assertIn("password", response.get_json()["error"]["details"])

    def test_all_numeric_password_is_rejected(self):
        _, _, response = self.register("num@example.com", password="1234567890")
        self.assertEqual(response.status_code, 422)

    def test_invalid_email_is_rejected(self):
        _, _, response = self.register("not-an-email")
        self.assertEqual(response.status_code, 422)
        self.assertIn("email", response.get_json()["error"]["details"])

    def test_non_json_body_is_rejected(self):
        response = self.client.post("/api/v1/auth/register", data="hello")
        # 415 (content-type enforcement middleware) or 422 (JSON parse failure).
        # Both mean the non-JSON body was correctly rejected.
        self.assertIn(response.status_code, (415, 422))

    def test_registration_is_audited(self):
        email, _, _ = self.register("audited@example.com")
        row = self.db.query_one(
            "SELECT COUNT(*) n FROM audit_logs WHERE action = 'user.registered'"
        )
        self.assertGreaterEqual(row["n"], 1)


class LoginTest(AppTestCase):
    def test_login_succeeds_with_correct_credentials(self):
        email, password, _ = self.register()
        response = self.client.post("/api/v1/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.get_json())

    def test_login_fails_with_wrong_password(self):
        email, _, _ = self.register()
        response = self.client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-one"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_credentials")

    def test_unknown_email_gives_the_same_error_as_wrong_password(self):
        """No account enumeration."""
        email, _, _ = self.register()
        wrong_pw = self.client.post("/api/v1/auth/login", json={"email": email, "password": "nope"})
        unknown = self.client.post(
            "/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope"}
        )
        self.assertEqual(wrong_pw.status_code, unknown.status_code)
        self.assertEqual(wrong_pw.get_json()["error"], unknown.get_json()["error"])

    def test_failed_login_is_audited(self):
        email, _, _ = self.register()
        self.client.post("/api/v1/auth/login", json={"email": email, "password": "bad"})
        row = self.db.query_one(
            "SELECT COUNT(*) n FROM audit_logs WHERE action = 'user.login_failed'"
        )
        self.assertEqual(row["n"], 1)

    def test_disabled_account_cannot_log_in(self):
        email, password, _ = self.register()
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET is_active = 0 WHERE email_normalized = ?", (email,))
        response = self.client.post("/api/v1/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["code"], "account_disabled")

    def test_seeded_demo_user_can_log_in(self):
        response = self.client.post(
            "/api/v1/auth/login", json={"email": "demo@60online.ir", "password": "Demo!2345"}
        )
        self.assertEqual(response.status_code, 200)


class MeAndRbacTest(AppTestCase):
    def test_me_requires_a_token(self):
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)

    def test_me_rejects_a_garbage_token(self):
        response = self.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer xx.yy.zz"})
        self.assertEqual(response.status_code, 401)

    def test_me_rejects_a_non_bearer_scheme(self):
        response = self.client.get("/api/v1/auth/me", headers={"Authorization": "Basic abc"})
        self.assertEqual(response.status_code, 401)

    def test_me_returns_the_current_user(self):
        _, headers = self.new_customer()
        response = self.client.get("/api/v1/auth/me", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["user"]["role"], "customer")

    def test_supplier_role_cannot_reach_customer_cart(self):
        """RBAC is enforced, and the DB role is authoritative over the token."""
        email, password, _ = self.register("supplier@example.com")
        token = self.login(email, password)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET role = 'supplier' WHERE email_normalized = ?", (email,))
        response = self.client.get("/api/v1/cart", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"]["code"], "permission_denied")

    def test_admin_role_inherits_customer_access(self):
        email, password, _ = self.register("adm@example.com")
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET role = 'admin' WHERE email_normalized = ?", (email,))
        token = self.login(email, password)
        response = self.client.get("/api/v1/cart", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 200)

    def test_deactivated_user_token_stops_working_immediately(self):
        email, password, _ = self.register("revoke@example.com")
        token = self.login(email, password)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET is_active = 0 WHERE email_normalized = ?", (email,))
        response = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
