"""Invoice API security tests — Blocker 4 (supplier tenant isolation).

Supplier A must not access Supplier B invoices.
No existence leakage (404 not 403).
"""
import json
import unittest
from tests.base import AppTestCase
from app.core.security import create_access_token
from app.services import invoice_service


class InvoiceSecurityTest(AppTestCase):

    def setUp(self):
        super().setUp()
        with self.db.write_transaction() as conn:
            # Supplier A
            cur = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, role, is_active) VALUES (?,?,?,?,?,?)",
                ("sec_sup_a_is@test.com", "sec_sup_a_is@test.com", "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "Supplier A Sec", "supplier", 1),
            )
            self.user_a_id = int(cur.lastrowid)
            self.user_a_email = "sec_sup_a_is@test.com"
            cur = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, status, rating_x10, user_id) VALUES (?,?,?,?,?,?,?)",
                ("Sec Supplier A IS", "Sec Sup A", "SA9900001001", "retailer", "active", 40, self.user_a_id),
            )
            self.supplier_a_id = int(cur.lastrowid)

            # Supplier B
            cur = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, role, is_active) VALUES (?,?,?,?,?,?)",
                ("sec_sup_b_is@test.com", "sec_sup_b_is@test.com", "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "Supplier B Sec", "supplier", 1),
            )
            self.user_b_id = int(cur.lastrowid)
            self.user_b_email = "sec_sup_b_is@test.com"
            cur = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, status, rating_x10, user_id) VALUES (?,?,?,?,?,?,?)",
                ("Sec Supplier B IS", "Sec Sup B", "SB9900002002", "retailer", "active", 40, self.user_b_id),
            )
            self.supplier_b_id = int(cur.lastrowid)

            # Admin
            cur = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, role, is_active) VALUES (?,?,?,?,?,?)",
                ("sec_admin_is@test.com", "sec_admin_is@test.com", "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "Admin Sec", "admin", 1),
            )
            self.admin_id = int(cur.lastrowid)
            self.admin_email = "sec_admin_is@test.com"

            # Create an invoice for Supplier B
            inv = invoice_service.create_invoice(
                conn,
                supplier_id=self.supplier_b_id,
                invoice_number="INV-SEC-IS-B-001",
                invoice_date="2026-01-01",
                lines=[{"line_number": 1, "product_name": "B Product",
                        "quantity": 1, "unit_price_minor": 1000000,
                        "line_total_minor": 1000000, "tax_minor": 0}],
                source_type="manual",
                created_by=self.admin_id,
            )
            self.invoice_b_id = inv["id"]

    def _token_for(self, user_id: int, email: str, role: str) -> str:
        """Generate auth token for a user."""
        return create_access_token(
            user_id=user_id,
            email=email,
            role=role,
            secret=self.settings.secret_key,
            algorithm=self.settings.jwt_algorithm,
            ttl_seconds=self.settings.access_token_ttl_seconds,
        )

    def test_supplier_a_cannot_get_supplier_b_invoice_by_id(self):
        """Supplier A GET /invoices/<b_invoice_id> → 404 (no existence leakage)."""
        token = self._token_for(self.user_a_id, self.user_a_email, "supplier")
        resp = self.client.get(
            f"/api/v1/invoices/{self.invoice_b_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_supplier_a_cannot_list_supplier_b_invoices(self):
        """Supplier A GET /invoices list must not contain Supplier B invoices."""
        # First create an invoice for Supplier A
        token_admin = self._token_for(self.admin_id, self.admin_email, "admin")
        resp = self.client.post(
            "/api/v1/invoices",
            json={
                "supplier_id": self.supplier_a_id,
                "invoice_number": "INV-SEC-IS-A-001",
                "invoice_date": "2026-01-01",
                "lines": [{"line_number": 1, "product_name": "A Product",
                           "quantity": 1, "unit_price_minor": 2000000,
                           "line_total_minor": 2000000, "tax_minor": 0}],
            },
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        self.assertEqual(resp.status_code, 201)

        # Supplier A lists their invoices — must not see B's
        token_a = self._token_for(self.user_a_id, self.user_a_email, "supplier")
        resp = self.client.get(
            "/api/v1/invoices",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        invoice_supplier_ids = {inv["supplier_id"] for inv in data.get("items", [])}
        self.assertNotIn(self.supplier_b_id, invoice_supplier_ids,
                         "Supplier A must not see Supplier B invoices in list")

    def test_supplier_a_cannot_create_invoice_for_supplier_b(self):
        """Supplier A POST /invoices with body.supplier_id=B must use A's supplier_id or be rejected."""
        token_a = self._token_for(self.user_a_id, self.user_a_email, "supplier")
        resp = self.client.post(
            "/api/v1/invoices",
            json={
                "supplier_id": self.supplier_b_id,  # Attempted cross-supplier
                "invoice_number": "INV-CROSS-IS-001",
                "invoice_date": "2026-01-01",
                "lines": [],
            },
            headers={"Authorization": f"Bearer {token_a}"},
        )
        if resp.status_code == 201:
            # If creation succeeded, must use A's supplier_id, not B's
            data = resp.get_json()
            self.assertEqual(data["invoice"]["supplier_id"], self.supplier_a_id,
                             "Invoice must be created for supplier A, not B")
        else:
            # Validation error or auth error is also acceptable
            self.assertIn(resp.status_code, (400, 403, 422))

    def test_admin_can_access_all_invoices(self):
        """Admin can GET Supplier B's invoice by id."""
        token_admin = self._token_for(self.admin_id, self.admin_email, "admin")
        resp = self.client.get(
            f"/api/v1/invoices/{self.invoice_b_id}",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["invoice"]["supplier_id"], self.supplier_b_id)


if __name__ == "__main__":
    unittest.main()
