"""Shared test harness: a real migrated + seeded database per test case."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.credit import registry as credit_registry  # noqa: E402
from app.adapters.payment import registry as payment_registry  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.db import Database  # noqa: E402
from app.main import create_app  # noqa: E402
from scripts.seed import seed  # noqa: E402

TEST_SECRET = "test-secret-not-used-outside-tests-0123456789abcdef"


class AppTestCase(unittest.TestCase):
    """Boots the real app against a throwaway on-disk SQLite database."""

    seed_data = True

    def setUp(self) -> None:
        os.environ["TEST_SALES_OVERRIDE"] = "1"
        self.tmpdir = tempfile.mkdtemp(prefix="60online-test-")
        db_path = os.path.join(self.tmpdir, "test.db")
        self.settings = Settings(
            secret_key=TEST_SECRET,
            database_url=f"sqlite:///{db_path}",
            app_env="test",
            jwt_algorithm="HS256",
            access_token_ttl_seconds=3600,
            currency="IRR",
            currency_exponent=0,
            payment_provider="mock",
            credit_provider="mock",
            cors_origins=("http://localhost:3000",),
        )
        payment_registry.reset_for_tests()
        credit_registry.reset_for_tests()
        self.db = Database(db_path)
        if self.seed_data:
            seed(self.db)
        else:
            from app.core.migrator import upgrade

            upgrade(self.db)
        self.app = create_app(self.settings, self.db)
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # -- helpers -----------------------------------------------------------
    def register(self, email: str | None = None, password: str = "Passw0rd!23", **extra):
        email = email or f"u{uuid.uuid4().hex[:10]}@example.com"
        response = self.client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "کاربر تست", **extra},
        )
        return email, password, response

    def login(self, email: str, password: str) -> str:
        response = self.client.post("/api/v1/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["access_token"]

    def new_customer(self) -> tuple[str, dict]:
        """Returns (token, auth_header)."""
        email, password, response = self.register()
        self.assertEqual(response.status_code, 201, response.get_json())
        token = response.get_json()["access_token"]
        return token, {"Authorization": f"Bearer {token}"}

    def product(self, slug: str = "office-paper-a4-carton") -> dict:
        response = self.client.get(f"/api/v1/products/{slug}")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["product"]

    def set_stock(self, product_id: int, quantity: int) -> None:
        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE inventory SET quantity_available = ? WHERE product_id = ?",
                (quantity, product_id),
            )

    DEFAULT_ADDRESS = {
        "recipient_name": "مهدی کاظمی",
        "recipient_phone": "09121234567",
        "province": "تهران",
        "city": "تهران",
        "line1": "خیابان ولیعصر، پلاک ۱۰",
        "postal_code": "1234567890",
    }

    # ------------------------------------------------ Phase 2 helpers ----
    def admin_headers(self) -> dict:
        """Platform admin (users.role = 'admin'), used to create organizations."""
        email, password, _ = self.register(f"padmin{uuid.uuid4().hex[:8]}@example.com")
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET role = 'admin' WHERE email_normalized = ?", (email,))
        return {"Authorization": f"Bearer {self.login(email, password)}"}

    def create_organization(self, *, national_id: str | None = None, status: str = "active",
                            credit_limit_minor: int = 10_000_000_000, name: str = "سازمان تست") -> dict:
        headers = self.admin_headers()
        national_id = national_id or str(10_000_000_000 + int(uuid.uuid4().int % 1_000_000_000))
        response = self.client.post(
            "/api/v1/admin/organizations",
            json={"legal_name": f"{name} (سهامی خاص)", "display_name": name,
                  "national_id": national_id, "credit_limit_minor": credit_limit_minor,
                  "status": status},
            headers=headers,
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["organization"]

    def make_org_admin(self, org_id: int, email: str | None = None) -> tuple[dict, dict]:
        """Returns (auth_headers, member). Inserted directly: the first admin of an
        organization cannot be added through an endpoint that requires an admin."""
        email = email or f"orgadmin{uuid.uuid4().hex[:8]}@example.com"
        _, password, response = self.register(email)
        self.assertEqual(response.status_code, 201, response.get_json())
        user_id = response.get_json()["user"]["id"]
        with self.db.write_transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO organization_memberships (organization_id, user_id, role, status) "
                "VALUES (?,?, 'organization_admin', 'active')",
                (org_id, user_id),
            )
            membership_id = int(cursor.lastrowid)
        token = self.login(email, password)
        return {"Authorization": f"Bearer {token}"}, {"id": membership_id, "user_id": user_id,
                                                      "email": email, "password": password}

    def add_employee(self, org_id: int, admin_headers: dict, *, email: str | None = None,
                     role: str = "employee", status: str = "active") -> dict:
        """Registers a user, adds them to the org, returns member + auth headers."""
        email = email or f"emp{uuid.uuid4().hex[:8]}@example.com"
        _, password, response = self.register(email)
        self.assertEqual(response.status_code, 201, response.get_json())
        added = self.client.post(
            f"/api/v1/organizations/{org_id}/members",
            json={"email": email, "role": role, "status": status},
            headers=admin_headers,
        )
        self.assertEqual(added.status_code, 201, added.get_json())
        member = added.get_json()["member"]
        member["password"] = password
        member["headers"] = {"Authorization": f"Bearer {self.login(email, password)}"}
        return member

    def allocate(self, org_id: int, admin_headers: dict, membership_id: int, amount_minor: int,
                 *, key: str | None = None, expect: int = 201, **extra):
        return self.client.post(
            f"/api/v1/organizations/{org_id}/credit-allocations",
            json={"membership_id": membership_id, "amount_minor": amount_minor, **extra},
            headers={**admin_headers, "Idempotency-Key": key or uuid.uuid4().hex},
        )

    def org_fixture(self, *, credit_minor: int = 200_000_000, **alloc):
        """Organization + admin + one funded employee. The common Phase 2 setup."""
        org = self.create_organization()
        admin_headers, admin = self.make_org_admin(org["id"])
        employee = self.add_employee(org["id"], admin_headers)
        if credit_minor:
            response = self.allocate(org["id"], admin_headers, employee["id"], credit_minor, **alloc)
            self.assertEqual(response.status_code, 201, response.get_json())
            employee["allocation"] = response.get_json()["allocation"]
        return org, admin_headers, admin, employee

    def quote(self, headers: dict) -> dict:
        response = self.client.get("/api/v1/checkout/quote", headers=headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def add_to_cart(self, headers: dict, product_id: int, quantity: int):
        return self.client.post(
            "/api/v1/cart/items", json={"product_id": product_id, "quantity": quantity},
            headers=headers,
        )

    def trial_balance(self) -> tuple[int, int]:
        from app.services import ledger_service

        with self.db.read_transaction() as conn:
            return ledger_service.trial_balance(conn)

    def checkout(self, headers: dict, key: str | None = None, address: dict | None = None):
        return self.client.post(
            "/api/v1/checkout",
            json={"shipping_address": address or self.DEFAULT_ADDRESS},
            headers={**headers, "Idempotency-Key": key or uuid.uuid4().hex},
        )

    def create_test_supplier(self, *, province: str = "تهران", city: str = "تهران",
                              capabilities: str = "local,intercity") -> dict:
        """Create a deterministic supplier with linked user, location, and carrier config.
        Returns dict: supplier_id, location_id, user_id, email, password, token, headers
        """
        import uuid
        email = f"sup{uuid.uuid4().hex[:8]}@test70.com"
        password = "SupTest!123"
        _, _, reg_resp = self.register(email, password)
        self.assertEqual(reg_resp.status_code, 201, reg_resp.get_json())
        user_id = reg_resp.get_json()["user"]["id"]
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET role='supplier' WHERE id=?", (user_id,))
        token = self.login(email, password)
        nat_id = str(90000000000 + int(uuid.uuid4().int % 1_000_000_000))
        with self.db.write_transaction() as conn:
            sup_cursor = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, "
                "status, rating_x10, user_id) VALUES (?,?,?, 'retailer', 'active', 42, ?)",
                (f"آزمایشی {nat_id}", f"آزمایشی {nat_id[:6]}", nat_id, user_id),
            )
            supplier_id = int(sup_cursor.lastrowid)
            loc_cursor = conn.execute(
                "INSERT INTO supplier_locations (supplier_id, province, city, status, "
                "can_local_delivery, can_intercity_shipping, can_pickup, prep_time_minutes) "
                "VALUES (?,?,?, 'active', 1, 1, 1, 60)",
                (supplier_id, province, city),
            )
            location_id = int(loc_cursor.lastrowid)
            # Ensure a carrier config exists for this province
            existing_cc = conn.execute(
                "SELECT id FROM carrier_configs WHERE provider_code='mock' AND province=? AND is_active=1",
                (province,)
            ).fetchone()
            if not existing_cc:
                conn.execute(
                    "INSERT INTO carrier_configs (provider_code, name_fa, province, city, "
                    "capabilities, cost_minor, is_active) VALUES (?,?,?,?,?,50000,1)",
                    ("mock", f"حامل آزمایشی {province}", province, None, capabilities),
                )
        return {
            "supplier_id": supplier_id,
            "location_id": location_id,
            "user_id": user_id,
            "email": email,
            "password": password,
            "token": token,
            "headers": {"Authorization": f"Bearer {token}"},
        }

    def create_test_product_with_offer(self, supplier_id: int, location_id: int, *,
                                        price_minor: int = 15_000_000,
                                        cost_minor: int | None = None,
                                        stock: int = 50,
                                        logistics_profile: str = "standard",
                                        fulfillment_type: str = "delivery") -> dict:
        """Create a unique test product with an offer from the given supplier.
        Returns dict: product_id, slug, offer_id
        """
        import uuid
        slug = f"test-product-{uuid.uuid4().hex[:10]}"
        sku  = f"TEST-{uuid.uuid4().hex[:8].upper()}"
        cost = cost_minor or int(price_minor * 0.75)
        with self.db.write_transaction() as conn:
            # Get or create a test category
            cat = conn.execute(
                "SELECT id FROM categories WHERE slug='office' LIMIT 1"
            ).fetchone()
            cat_id = int(cat["id"]) if cat else 1
            prod_cursor = conn.execute(
                "INSERT INTO products (slug, sku, title_fa, description_fa, brand_fa, "
                "category_id, base_price_minor, currency, image_emoji, rating_x10, is_active, "
                "logistics_profile) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (slug, sku, f"محصول آزمایشی {slug[:12]}", "توضیحات آزمایشی", "برند آزمایشی",
                 cat_id, price_minor, "IRR", "📦", 40, 1, logistics_profile),
            )
            product_id = int(prod_cursor.lastrowid)
            conn.execute(
                "INSERT INTO inventory (product_id, quantity_available, quantity_reserved) "
                "VALUES (?,?,0)",
                (product_id, stock),
            )
            offer_cursor = conn.execute(
                "INSERT INTO seller_offers (product_id, supplier_id, supplier_location_id, "
                "selling_price_minor, cost_price_minor, stock_quantity, status, fulfillment_type) "
                "VALUES (?,?,?,?,?,?, 'active', ?)",
                (product_id, supplier_id, location_id, price_minor, cost, stock, fulfillment_type),
            )
            offer_id = int(offer_cursor.lastrowid)
        return {"product_id": product_id, "slug": slug, "offer_id": offer_id}
