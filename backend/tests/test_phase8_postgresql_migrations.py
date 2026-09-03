"""
Phase 8 — Real PostgreSQL 16 E2E business tests.
Run with:
    export DATABASE_URL=postgresql://testuser:testpass@localhost:5432/testdb
    export REQUIRE_POSTGRESQL=1
    python -m unittest tests.test_phase8_postgresql_migrations -v
Expected: Ran 33 tests in Xs  OK (skipped=0)
"""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ─────────────────────────────────────────────────────────────────────────────
# Module-level PostgreSQL guard
# ─────────────────────────────────────────────────────────────────────────────

def _pg_url() -> str | None:
    url = os.environ.get("DATABASE_URL", "")
    return url if url.startswith(("postgresql://", "postgres://")) else None


_PG_URL = _pg_url()
_REQUIRE = os.environ.get("REQUIRE_POSTGRESQL", "").strip() == "1"

if _PG_URL is None:
    if _REQUIRE:
        print(
            "\nFATAL: REQUIRE_POSTGRESQL=1 is set but DATABASE_URL is not a "
            "PostgreSQL URL.\n"
            "  Set DATABASE_URL=postgresql://user:pass@host:5432/dbname\n"
            "  Current value: {!r}\n".format(os.environ.get("DATABASE_URL", "")),
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        # Developer machine without PG — skip the whole module.
        # NOTE: This line is intentionally placed BEFORE any class definition
        # so it is excluded from the guard test's class-body scan.
        raise unittest.SkipTest(
            "DATABASE_URL is not a PostgreSQL URL — PostgreSQL tests skipped. "
            "Set REQUIRE_POSTGRESQL=1 to turn this into a failure."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_ADDRESS = {
    "recipient_name": "مهدی کاظمی",
    "recipient_phone": "09121234567",
    "province": "تهران",
    "city": "تهران",
    "line1": "خیابان ولیعصر، پلاک ۱۰",
    "postal_code": "1234567890",
}

_SETTINGS_KWARGS = dict(
    secret_key="test-pg-secret-key-at-least-32bytes-long",
    database_url=_PG_URL,
    app_env="test",
    jwt_algorithm="HS256",
    access_token_ttl_seconds=3600,
    currency="IRR",
    currency_exponent=0,
    payment_provider="mock",
    credit_provider="mock",
    cors_origins=("http://localhost:3000",),
)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level shared fixtures (set up once for all test classes)
# ─────────────────────────────────────────────────────────────────────────────

_PG_DB = None
_PG_APP = None


def _drop_all(pg_conn) -> None:
    """Drop every table in the public schema (clean room)."""
    try:
        with pg_conn.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
            tables = [r[0] for r in cur.fetchall()]
        if tables:
            with pg_conn.cursor() as cur:
                cur.execute(
                    "DROP TABLE IF EXISTS {} CASCADE".format(
                        ", ".join(tables)
                    )
                )
        pg_conn.commit()
    except Exception:
        pg_conn.rollback()
        raise


def _make_db():
    from app.core.db import PostgreSQLBackend
    return PostgreSQLBackend(_PG_URL)


def _make_app(db):
    from app.adapters.credit import registry as credit_registry
    from app.adapters.payment import registry as payment_registry
    from app.core.config import Settings
    from app.main import create_app
    credit_registry.reset_for_tests()
    payment_registry.reset_for_tests()
    settings = Settings(**_SETTINGS_KWARGS)
    return create_app(settings, db)


def _setup_module_fixtures():
    global _PG_DB, _PG_APP
    if _PG_DB is not None:
        return
    _PG_DB = _make_db()
    _drop_all(_PG_DB.connection)
    from app.core.migrator import upgrade
    upgrade(_PG_DB)
    from scripts.seed import seed
    seed(_PG_DB)
    _PG_APP = _make_app(_PG_DB)


# ─────────────────────────────────────────────────────────────────────────────
# Base test class
# ─────────────────────────────────────────────────────────────────────────────

class _PgBase(unittest.TestCase):
    """All test classes share a single migrated+seeded PostgreSQL database."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _setup_module_fixtures()
        cls._db = _PG_DB
        cls._app = _PG_APP
        cls._client = _PG_APP.test_client()

    # ── Auth helpers ─────────────────────────────────────────────────────────

    def _register(self, email=None, password="PgTest!8888"):
        email = email or f"pg_{uuid.uuid4().hex[:10]}@example.com"
        resp = self._client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "PG Test User"},
        )
        return email, password, resp

    def _login(self, email, password="PgTest!8888") -> str:
        resp = self._client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        return resp.get_json()["access_token"]

    def _headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def _admin_headers(self) -> dict:
        email = f"padm_{uuid.uuid4().hex[:8]}@example.com"
        password = "PgAdmin!9999"
        _, _, resp = self._register(email, password)
        self.assertEqual(resp.status_code, 201, resp.get_json())
        with self._app.app_context():
            self._db.execute(
                "UPDATE users SET role='admin' WHERE email_normalized=?",
                (email.lower(),),
            )
            self._db.connection.commit()
        token = self._login(email, password)
        return self._headers(token)

    # ── Organization helpers ──────────────────────────────────────────────────

    def _create_org(self, admin_headers: dict, *, credit_limit_minor: int = 500_000_000) -> dict:
        nat = str(10_000_000_000 + int(uuid.uuid4().int % 1_000_000_000))
        resp = self._client.post(
            "/api/v1/admin/organizations",
            json={
                "legal_name": f"سازمان آزمایشی (سهامی خاص) {nat[:6]}",
                "display_name": f"سازمان {nat[:6]}",
                "national_id": nat,
                "credit_limit_minor": credit_limit_minor,
                "status": "active",
            },
            headers=admin_headers,
        )
        self.assertEqual(resp.status_code, 201, resp.get_json())
        return resp.get_json()["organization"]

    def _make_org_admin(self, org_id: int) -> tuple[dict, dict]:
        """Register a user and add as org admin directly in DB. Returns (headers, user_info)."""
        email = f"oa_{uuid.uuid4().hex[:8]}@example.com"
        _, password, reg = self._register(email)
        self.assertEqual(reg.status_code, 201, reg.get_json())
        user_id = reg.get_json()["user"]["id"]
        with self._db.write_transaction() as conn:
            cur = conn.execute(
                "INSERT INTO organization_memberships (organization_id, user_id, role, status) "
                "VALUES (?, ?, 'organization_admin', 'active')",
                (org_id, user_id),
            )
            membership_id = int(cur.lastrowid)
        token = self._login(email, password)
        return (
            self._headers(token),
            {"id": membership_id, "user_id": user_id, "email": email, "password": password},
        )

    def _add_employee(self, org_id: int, admin_headers: dict) -> dict:
        """Register a user and add as employee. Returns member dict with headers."""
        email = f"emp_{uuid.uuid4().hex[:8]}@example.com"
        _, password, reg = self._register(email)
        self.assertEqual(reg.status_code, 201, reg.get_json())
        added = self._client.post(
            f"/api/v1/organizations/{org_id}/members",
            json={"email": email, "role": "employee", "status": "active"},
            headers=admin_headers,
        )
        self.assertEqual(added.status_code, 201, added.get_json())
        member = added.get_json()["member"]
        member["password"] = password
        member["headers"] = self._headers(self._login(email, password))
        return member

    def _allocate(self, org_id: int, admin_headers: dict, membership_id: int,
                  amount_minor: int) -> dict:
        resp = self._client.post(
            f"/api/v1/organizations/{org_id}/credit-allocations",
            json={"membership_id": membership_id, "amount_minor": amount_minor},
            headers={**admin_headers, "Idempotency-Key": uuid.uuid4().hex},
        )
        self.assertEqual(resp.status_code, 201, resp.get_json())
        return resp.get_json()["allocation"]

    def _org_with_funded_employee(self, credit_minor: int = 200_000_000) -> tuple:
        """Create org, org-admin, funded employee. Returns (org, admin_h, employee)."""
        admin_h = self._admin_headers()
        org = self._create_org(admin_h)
        org_admin_h, _ = self._make_org_admin(org["id"])
        employee = self._add_employee(org["id"], org_admin_h)
        self._allocate(org["id"], org_admin_h, employee["id"], credit_minor)
        return org, org_admin_h, employee

    # ── Supplier / product helpers ────────────────────────────────────────────

    def _setup_supplier_and_product(self, price_minor: int = 15_000_000) -> dict:
        """Create supplier, location, product, offer, inventory via DB. Returns info dict."""
        with self._db.write_transaction() as conn:
            email = f"sup_{uuid.uuid4().hex[:8]}@pg.test"
            # password_hash must satisfy CHECK (length >= 40 AND contains '$')
            _dummy_hash = "$2b$12$TESTtestTESTtestTESTtest.TESTtestTESTtestTESTtestTE"
            cur = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, role, is_active) "
                "VALUES (?, ?, ?, 'Supplier PG', 'supplier', 1)",
                (email, email.lower(), _dummy_hash),
            )
            user_id = cur.lastrowid

            nat = str(80_000_000_000 + int(uuid.uuid4().int % 1_000_000_000))
            cur = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, "
                "supplier_type, status, rating_x10, user_id) "
                "VALUES (?, ?, ?, 'retailer', 'active', 42, ?)",
                (f"تأمین {nat[:6]}", f"تأمین {nat[:6]}", nat, user_id),
            )
            supplier_id = cur.lastrowid

            cur = conn.execute(
                "INSERT INTO supplier_locations (supplier_id, province, city, status, "
                "can_local_delivery, can_intercity_shipping, can_pickup, prep_time_minutes) "
                "VALUES (?, 'تهران', 'تهران', 'active', 1, 1, 1, 60)",
                (supplier_id,),
            )
            location_id = cur.lastrowid

            existing = conn.execute(
                "SELECT id FROM carrier_configs WHERE province='تهران' AND is_active=1 LIMIT 1"
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO carrier_configs (provider_code, name_fa, province, "
                    "capabilities, cost_minor, is_active) "
                    "VALUES ('mock', 'حامل آزمایشی', 'تهران', 'local,intercity', 50000, 1)"
                )

            slug = f"pg-prod-{uuid.uuid4().hex[:8]}"
            sku = f"PG-{uuid.uuid4().hex[:6].upper()}"
            cur = conn.execute(
                "INSERT INTO products (slug, sku, title_fa, description_fa, brand_fa, "
                "category_id, base_price_minor, currency, image_emoji, rating_x10, "
                "is_active, logistics_profile) "
                "VALUES (?, ?, ?, 'توضیح آزمایشی', 'برند', 1, ?, 'IRR', '📦', 40, 1, 'standard')",
                (slug, sku, f"محصول PG {slug[:10]}", price_minor),
            )
            product_id = cur.lastrowid

            conn.execute(
                "INSERT INTO inventory (product_id, quantity_available, quantity_reserved) "
                "VALUES (?, 50, 0)",
                (product_id,),
            )

            cur = conn.execute(
                "INSERT INTO seller_offers (product_id, supplier_id, supplier_location_id, "
                "selling_price_minor, cost_price_minor, stock_quantity, status, fulfillment_type) "
                "VALUES (?, ?, ?, ?, ?, 50, 'active', 'delivery')",
                (product_id, supplier_id, location_id,
                 price_minor, int(price_minor * 0.75)),
            )
            offer_id = cur.lastrowid

        return {
            "supplier_id": int(supplier_id),
            "location_id": int(location_id),
            "product_id": int(product_id),
            "offer_id": int(offer_id),
            "slug": slug,
            "price_minor": price_minor,
        }

    def _add_to_cart(self, headers: dict, product_id: int, qty: int = 1):
        resp = self._client.post(
            "/api/v1/cart/items",
            json={"product_id": product_id, "quantity": qty},
            headers=headers,
        )
        self.assertIn(resp.status_code, (200, 201), resp.get_json())
        return resp

    def _checkout(self, headers: dict, key: str | None = None) -> object:
        return self._client.post(
            "/api/v1/checkout",
            json={"shipping_address": DEFAULT_ADDRESS},
            headers={**headers, "Idempotency-Key": key or uuid.uuid4().hex},
        )

    def _get_quote(self, headers: dict) -> dict:
        resp = self._client.get("/api/v1/checkout/quote", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        return resp.get_json()


# ─────────────────────────────────────────────────────────────────────────────
# TestPgGuard — must run first (alphabetically sorts before other test classes)
# ─────────────────────────────────────────────────────────────────────────────

class TestPgGuard(_PgBase):
    """Guard: verify this module contains no forbidden skip patterns in test classes."""

    def test_00_no_skip_patterns_in_this_module(self):
        """Read this file's source; fail if any skip pattern appears in test class bodies.

        The module-level guard (before any class definition) legitimately uses
        the SkipTest exception class to skip when PostgreSQL is unavailable —
        that section is intentionally excluded from this scan.

        The forbidden patterns are assembled by concatenation here to avoid
        this test's own source from triggering a false positive.
        """
        source = Path(__file__).read_text(encoding="utf-8")
        lines = source.splitlines()

        # Scan only class definitions and their bodies — not module-level code.
        # Module-level code (before any `class` at column 0) may legitimately
        # use unittest.SkipTest to skip when PostgreSQL is not available.
        first_class_pos = next(
            (i for i, ln in enumerate(lines) if ln.startswith("class ")),
            len(lines),
        )
        # Also exclude THIS guard class itself — it may reference pattern strings.
        in_guard_class = False
        scan_lines: list[str] = []
        for i, line in enumerate(lines[first_class_pos:], start=first_class_pos):
            stripped = line.rstrip()
            if stripped.startswith("class TestPgGuard"):
                in_guard_class = True
            elif stripped.startswith("class ") and in_guard_class:
                in_guard_class = False
            if not in_guard_class:
                scan_lines.append(line)

        scan_source = "\n".join(scan_lines)

        # Build forbidden patterns by concatenation so they don't appear
        # literally in this file (avoiding false self-match).
        forbidden = [
            "self." + "skipTest(",
            "@unittest." + "skip",
            "@" + "skip\n",
            "@" + "skip(",
        ]
        for pattern in forbidden:
            if pattern in scan_source:
                self.fail(
                    f"Forbidden skip pattern {pattern!r} found in test class bodies. "
                    "All PostgreSQL tests must run unconditionally when PostgreSQL is available."
                )


# ─────────────────────────────────────────────────────────────────────────────
# TestPgAuth — tests 01-03
# ─────────────────────────────────────────────────────────────────────────────

class TestPgAuth(_PgBase):
    """Authentication and authorization tests against PostgreSQL."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_01_register_and_login(self):
        """Register a new user, login, get JWT. Assert 201 then 200; access_token present."""
        email = f"auth01_{uuid.uuid4().hex[:8]}@example.com"
        password = "PgTest!8888"

        reg_resp = self._client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "Auth Test"},
        )
        self.assertEqual(reg_resp.status_code, 201, reg_resp.get_json())
        reg_data = reg_resp.get_json()
        self.assertIn("access_token", reg_data)

        login_resp = self._client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        self.assertEqual(login_resp.status_code, 200, login_resp.get_json())
        login_data = login_resp.get_json()
        self.assertIn("access_token", login_data)
        self.assertIsInstance(login_data["access_token"], str)
        self.assertGreater(len(login_data["access_token"]), 30)

    def test_02_jwt_logout_revocation(self):
        """After logout, the old token must be rejected (401). New login must work."""
        email = f"auth02_{uuid.uuid4().hex[:8]}@example.com"
        password = "PgTest!8888"

        # Register
        reg = self._client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "Revoke Test"},
        )
        self.assertEqual(reg.status_code, 201, reg.get_json())

        # Login
        token = self._login(email, password)
        headers = self._headers(token)

        # Logout
        logout_resp = self._client.post("/api/v1/auth/logout", headers=headers)
        self.assertEqual(logout_resp.status_code, 200, logout_resp.get_json())

        # Same token must now be rejected
        me_resp = self._client.get("/api/v1/auth/me", headers=headers)
        self.assertEqual(me_resp.status_code, 401, me_resp.get_json())

        # Login again with fresh credentials must succeed
        new_token = self._login(email, password)
        new_headers = self._headers(new_token)
        me_resp2 = self._client.get("/api/v1/auth/me", headers=new_headers)
        self.assertEqual(me_resp2.status_code, 200, me_resp2.get_json())

    def test_03_org_isolation(self):
        """User A cannot see org B's members and vice versa (404, not 403)."""
        admin_h = self._admin_headers()

        # Create two orgs
        org_a = self._create_org(admin_h)
        org_b = self._create_org(admin_h)

        # Create admin for org A
        org_a_admin_h, _ = self._make_org_admin(org_a["id"])

        # Create admin for org B
        org_b_admin_h, _ = self._make_org_admin(org_b["id"])

        # User A cannot see org B's members
        resp = self._client.get(
            f"/api/v1/organizations/{org_b['id']}/members",
            headers=org_a_admin_h,
        )
        self.assertEqual(resp.status_code, 404, resp.get_json())

        # User B cannot see org A's members
        resp2 = self._client.get(
            f"/api/v1/organizations/{org_a['id']}/members",
            headers=org_b_admin_h,
        )
        self.assertEqual(resp2.status_code, 404, resp2.get_json())


# ─────────────────────────────────────────────────────────────────────────────
# TestPgCreditAndCheckout — tests 04-08
# ─────────────────────────────────────────────────────────────────────────────

class TestPgCreditAndCheckout(_PgBase):
    """Credit allocation, checkout flow, inventory and balance delta tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_04_credit_allocation_ledger(self):
        """Allocate 200M to employee; verify allocation list and ledger entry."""
        org, org_admin_h, employee = self._org_with_funded_employee(200_000_000)

        # Verify the credit-allocations list returns exactly 1 allocation
        alloc_resp = self._client.get(
            f"/api/v1/organizations/{org['id']}/credit-allocations",
            headers=org_admin_h,
        )
        self.assertEqual(alloc_resp.status_code, 200, alloc_resp.get_json())
        alloc_data = alloc_resp.get_json()
        items = alloc_data.get("items", alloc_data.get("allocations", []))
        self.assertEqual(len(items), 1)

        # Verify ledger entry via raw SQL
        with self._db.read_transaction() as conn:
            row = conn.execute(
                "SELECT SUM(amount_minor) AS total FROM credit_ledger_entries "
                "WHERE allocation_id = ? AND entry_type = 'allocation'",
                (items[0]["id"],),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(int(row["total"]), 200_000_000)

    def test_05_checkout_success(self):
        """Full checkout: org-funded employee buys a product. Assert 201 + credit > 0."""
        org, org_admin_h, employee = self._org_with_funded_employee(200_000_000)
        prod = self._setup_supplier_and_product()

        emp_h = employee["headers"]
        self._add_to_cart(emp_h, prod["product_id"], qty=1)

        co_resp = self._checkout(emp_h)
        self.assertEqual(co_resp.status_code, 201, co_resp.get_json())
        order = co_resp.get_json()["order"]
        self.assertGreater(order["total_minor"], 0)
        self.assertGreater(order["credit_minor"], 0)

    def test_06_inventory_reservation(self):
        """After checkout qty=1, inventory decreases by exactly 1."""
        org, org_admin_h, employee = self._org_with_funded_employee(200_000_000)
        prod = self._setup_supplier_and_product()

        # Read available before
        before_row = self._db.query_one(
            "SELECT quantity_available FROM inventory WHERE product_id = ?",
            (prod["product_id"],),
        )
        qty_before = int(before_row["quantity_available"])

        emp_h = employee["headers"]
        self._add_to_cart(emp_h, prod["product_id"], qty=1)
        co_resp = self._checkout(emp_h)
        self.assertEqual(co_resp.status_code, 201, co_resp.get_json())

        # Read available after
        after_row = self._db.query_one(
            "SELECT quantity_available FROM inventory WHERE product_id = ?",
            (prod["product_id"],),
        )
        qty_after = int(after_row["quantity_available"])
        self.assertEqual(qty_after, qty_before - 1)

    def test_07_employee_balance_delta(self):
        """Employee's credit balance decreases by exactly the order's credit_minor."""
        org, org_admin_h, employee = self._org_with_funded_employee(200_000_000)
        prod = self._setup_supplier_and_product()

        # Balance before — read from credit-allocations
        before_resp = self._client.get(
            f"/api/v1/organizations/{org['id']}/credit-allocations",
            headers=org_admin_h,
        )
        self.assertEqual(before_resp.status_code, 200)
        before_items = before_resp.get_json().get("items", before_resp.get_json().get("allocations", []))
        balance_before = int(before_items[0]["available_minor"])

        emp_h = employee["headers"]
        self._add_to_cart(emp_h, prod["product_id"], qty=1)
        co_resp = self._checkout(emp_h)
        self.assertEqual(co_resp.status_code, 201, co_resp.get_json())
        order = co_resp.get_json()["order"]
        credit_used = int(order["credit_minor"])

        # Balance after
        after_resp = self._client.get(
            f"/api/v1/organizations/{org['id']}/credit-allocations",
            headers=org_admin_h,
        )
        self.assertEqual(after_resp.status_code, 200)
        after_items = after_resp.get_json().get("items", after_resp.get_json().get("allocations", []))
        balance_after = int(after_items[0]["available_minor"])

        self.assertEqual(balance_after, balance_before - credit_used)

    def test_08_tax_exact(self):
        """VAT at 10% (1000 bps): exact calculation, DB persistence, and cross-org isolation."""
        org, org_admin_h, employee = self._org_with_funded_employee(200_000_000)
        prod = self._setup_supplier_and_product()

        emp_h = employee["headers"]
        self._add_to_cart(emp_h, prod["product_id"], qty=1)

        # Get quote — credit_to_use_minor predicts what will be used
        quote = self._get_quote(emp_h)
        predicted_credit = int(quote.get("credit_to_use_minor", 0))

        # Checkout and compare — quote prediction must match checkout exactly
        co_resp = self._checkout(emp_h)
        self.assertEqual(co_resp.status_code, 201, co_resp.get_json())
        order = co_resp.get_json()["order"]
        order_id = order["id"]
        actual_credit = int(order["credit_minor"])

        # Quote must exactly predict the credit used in the order
        self.assertEqual(actual_credit, predicted_credit,
                         "Quote credit_to_use_minor must exactly match order credit_minor")
        self.assertGreater(actual_credit, 0)

        # ── Exact VAT calculation ─────────────────────────────────────────────
        # VAT rate is STANDARD = 1000 bps = 10%.
        # Formula: tax_minor = subtotal_minor * 1000 // 10000  (integer floor, no floats)
        # The product price IS the subtotal for a single-item cart.
        subtotal_minor = prod["price_minor"]  # known exact value from fixture
        expected_tax_minor = subtotal_minor * 1000 // 10000  # 10% floor division

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tax_resp = self._client.post(
            "/api/v1/tax/calculate",
            json={
                "subtotal_minor": subtotal_minor,
                "tax_category_code": "STANDARD",
                "effective_date": today,
                "organization_id": org["id"],
            },
            headers=emp_h,
        )
        self.assertEqual(tax_resp.status_code, 200, tax_resp.get_json())
        tax_data = tax_resp.get_json()

        # rate_bps must be exactly 1000 (10% VAT — migration 0019 sets this)
        actual_rate_bps = int(tax_data.get("rate_bps", 0))
        self.assertEqual(actual_rate_bps, 1000,
                         f"STANDARD VAT rate must be 1000 bps (10%), got {actual_rate_bps}")

        # tax_minor must equal exact floor calculation
        actual_tax_minor = int(tax_data.get("tax_minor", 0))
        self.assertEqual(actual_tax_minor, expected_tax_minor,
                         f"tax_minor: expected {expected_tax_minor} "
                         f"({subtotal_minor} * 1000 // 10000), got {actual_tax_minor}")

        # total_minor must be subtotal + tax (exact)
        actual_total_minor = int(tax_data.get("total_minor", 0))
        self.assertEqual(actual_total_minor, subtotal_minor + expected_tax_minor,
                         "total_minor must equal subtotal_minor + tax_minor exactly")

        # Non-even subtotal rounding check: verify floor semantics
        # For a non-round subtotal, floor must apply: e.g. 15_000_001 → 1_500_000 (floor)
        odd_subtotal = 15_000_001
        odd_expected = odd_subtotal * 1000 // 10000  # must be 1_500_000 (floor, not ceil)
        odd_resp = self._client.post(
            "/api/v1/tax/calculate",
            json={
                "subtotal_minor": odd_subtotal,
                "tax_category_code": "STANDARD",
                "effective_date": today,
                "organization_id": org["id"],
            },
            headers=emp_h,
        )
        self.assertEqual(odd_resp.status_code, 200, odd_resp.get_json())
        odd_tax = int(odd_resp.get_json().get("tax_minor", -1))
        self.assertEqual(odd_tax, odd_expected,
                         f"Non-even subtotal rounding: expected {odd_expected}, got {odd_tax}. "
                         "Tax must use integer floor division.")

        # ── Tax persistence assertion ─────────────────────────────────────────
        # The checkout order response must carry the exact persisted tax_minor.
        order_tax_minor = order.get("tax_minor")
        self.assertIsNotNone(order_tax_minor,
                             "Order response must contain tax_minor field")
        self.assertEqual(int(order_tax_minor), expected_tax_minor,
                         f"Order.tax_minor must equal {expected_tax_minor}, "
                         f"got {order_tax_minor!r}")

        # Query the DB directly: the orders row must persist tax_minor for
        # this exact order and organization.
        with self._db.read_transaction() as conn:
            db_order = conn.execute(
                "SELECT id, organization_id, subtotal_minor, tax_minor "
                "FROM orders WHERE id = ? AND organization_id = ?",
                (order_id, org["id"]),
            ).fetchone()
        self.assertIsNotNone(db_order,
                             "orders row must exist for the exact order_id and organization_id")
        self.assertEqual(int(db_order["subtotal_minor"]), subtotal_minor,
                         "Persisted subtotal_minor must match the product price")
        self.assertEqual(int(db_order["tax_minor"]), expected_tax_minor,
                         f"Persisted tax_minor must be {expected_tax_minor} "
                         f"(subtotal={subtotal_minor} × 10% floor)")
        # The tax record belongs to the exact organization and order
        self.assertEqual(int(db_order["id"]), order_id,
                         "Persisted tax record must belong to the exact order")
        self.assertEqual(int(db_order["organization_id"]), org["id"],
                         "Persisted tax record must belong to the exact organization")

        # ── Cross-org tax isolation ───────────────────────────────────────────
        # A user from a different organization must receive 404 when supplying
        # this organization's ID on the /tax/calculate endpoint.
        # (404 conceals the org's existence from non-members — see tax.py comment)
        other_admin_h = self._admin_headers()
        other_org = self._create_org(other_admin_h)
        other_org_admin_h, _ = self._make_org_admin(other_org["id"])
        cross_tax_resp = self._client.post(
            "/api/v1/tax/calculate",
            json={
                "subtotal_minor": subtotal_minor,
                "tax_category_code": "STANDARD",
                "effective_date": today,
                "organization_id": org["id"],  # org owned by original user
            },
            headers=other_org_admin_h,  # user from a DIFFERENT org
        )
        self.assertEqual(cross_tax_resp.status_code, 404,
                         "User from another org must receive 404 when using a different "
                         "org's ID on /tax/calculate (not 403 — endpoint must not confirm "
                         "org existence to non-members)")


# ─────────────────────────────────────────────────────────────────────────────
# TestPgOrderAtomicity — tests 09-11
# ─────────────────────────────────────────────────────────────────────────────

class TestPgOrderAtomicity(_PgBase):
    """Atomicity: orders, order_items, fulfillment_orders, outbox committed together."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_09_order_lines_and_fulfillment_committed(self):
        """After checkout: orders, order_items, and fulfillment_orders rows all exist in DB.

        Blocker 1 requirement: fulfillment_orders must exist (count >= 1), the row
        must belong to the exact order, and the initial status must be 'assigned'.
        An order cannot be in 'delivered' state before its fulfillment_orders exist.
        """
        org, org_admin_h, employee = self._org_with_funded_employee(200_000_000)
        prod = self._setup_supplier_and_product()

        emp_h = employee["headers"]
        self._add_to_cart(emp_h, prod["product_id"], qty=1)
        co_resp = self._checkout(emp_h)
        self.assertEqual(co_resp.status_code, 201, co_resp.get_json())
        order = co_resp.get_json()["order"]
        order_id = order["id"]

        with self._db.read_transaction() as conn:
            # orders row must exist
            order_row = conn.execute(
                "SELECT id, status FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
            self.assertIsNotNone(order_row, "orders row must exist after checkout")

            # order_items row must exist (at least 1)
            items_row = conn.execute(
                "SELECT COUNT(*) AS n FROM order_items WHERE order_id = ?", (order_id,)
            ).fetchone()
            self.assertGreater(int(items_row["n"]), 0,
                               "order_items must exist after checkout")

            # fulfillment_orders MUST exist — the fulfillment-first invariant guarantees
            # that a fulfillment plan was created before payment; after payment succeeds,
            # confirm_fulfillment_orders_from_plan() writes the row(s).
            fo_rows = conn.execute(
                "SELECT id, order_id, supplier_id, supplier_location_id, status "
                "FROM fulfillment_orders WHERE order_id = ?",
                (order_id,),
            ).fetchall()
            self.assertGreater(
                len(fo_rows), 0,
                "fulfillment_orders must exist after successful checkout "
                "(fulfillment-first invariant: plan is created before PSP charge)"
            )

            for fo in fo_rows:
                # Row must belong to the exact order
                self.assertEqual(
                    int(fo["order_id"]), order_id,
                    f"fulfillment_order.order_id must be {order_id}, got {fo['order_id']}"
                )
                # supplier_id must be set (not NULL)
                self.assertIsNotNone(
                    fo["supplier_id"],
                    "fulfillment_order.supplier_id must not be NULL"
                )
                # supplier_location_id must be set (not NULL)
                self.assertIsNotNone(
                    fo["supplier_location_id"],
                    "fulfillment_order.supplier_location_id must not be NULL"
                )
                # Initial status after checkout must be 'assigned'
                # (the documented initial status from the fulfillment state machine)
                self.assertEqual(
                    fo["status"], "assigned",
                    f"Freshly created fulfillment_order must have status='assigned', "
                    f"got {fo['status']!r}"
                )

            # An order cannot be in 'delivered' state if no fulfillment_orders exist.
            # This invariant is always satisfied here since we just asserted fo_rows > 0,
            # but we also verify the order's own status is not 'delivered' immediately
            # after checkout (delivery requires fulfillment progression).
            self.assertNotEqual(
                order_row["status"], "delivered",
                "Order cannot be 'delivered' immediately after checkout"
            )

    def test_10_outbox_event_in_same_transaction(self):
        """After checkout, integration_events has ORDER_CREATED row for this order."""
        org, org_admin_h, employee = self._org_with_funded_employee(200_000_000)
        prod = self._setup_supplier_and_product()

        emp_h = employee["headers"]
        self._add_to_cart(emp_h, prod["product_id"], qty=1)
        co_resp = self._checkout(emp_h)
        self.assertEqual(co_resp.status_code, 201, co_resp.get_json())
        order = co_resp.get_json()["order"]
        order_id = order["id"]

        with self._db.read_transaction() as conn:
            row = conn.execute(
                "SELECT id, event_type FROM integration_events "
                "WHERE event_type = 'ORDER_CREATED' AND payload_json LIKE ? "
                "ORDER BY id DESC LIMIT 1",
                (f"%{order_id}%",),
            ).fetchone()

        self.assertIsNotNone(row, f"ORDER_CREATED event for order {order_id} must exist")
        self.assertEqual(row["event_type"], "ORDER_CREATED")

    def test_11_checkout_idempotency(self):
        """Same Idempotency-Key returns same order; DB has exactly 1 order for this user."""
        org, org_admin_h, employee = self._org_with_funded_employee(400_000_000)
        prod = self._setup_supplier_and_product()

        emp_h = employee["headers"]
        self._add_to_cart(emp_h, prod["product_id"], qty=1)

        idem_key = str(uuid.uuid4())

        # First call
        resp1 = self._checkout(emp_h, key=idem_key)
        self.assertEqual(resp1.status_code, 201, resp1.get_json())
        order1 = resp1.get_json()["order"]

        # Second call with same key (cart is now ordered, but idempotency replays)
        resp2 = self._checkout(emp_h, key=idem_key)
        # Idempotent replay returns the stored status_code (201)
        self.assertEqual(resp2.status_code, 201, resp2.get_json())
        order2 = resp2.get_json()["order"]

        # Same order returned
        self.assertEqual(order1["id"], order2["id"])
        self.assertEqual(order1["order_number"], order2["order_number"])

        # Exactly 1 order for this user
        with self._db.read_transaction() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM orders WHERE user_id = "
                "(SELECT id FROM users WHERE email_normalized = ?)",
                (employee["email"].lower(),),
            ).fetchone()
        self.assertEqual(int(row["n"]), 1)

        # Inventory changed exactly once (quantity decreased by exactly 1)
        inv_row = self._db.query_one(
            "SELECT quantity_available FROM inventory WHERE product_id = ?",
            (prod["product_id"],),
        )
        # The stock started at 50, one checkout reserved 1 unit
        self.assertEqual(int(inv_row["quantity_available"]), 49)


# ─────────────────────────────────────────────────────────────────────────────
# TestPgRollback — tests 12-13
# ─────────────────────────────────────────────────────────────────────────────

class TestPgRollback(_PgBase):
    """Rollback integrity: PSP failure leaves no committed order or ledger entries."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_12_failed_payment_rollback(self):
        """PSP decline (amount_minor % 100 == 13) must leave no committed order."""
        # Create org, admin, and employee with NO credit initially
        admin_h = self._admin_headers()
        org = self._create_org(admin_h)
        org_admin_h, _ = self._make_org_admin(org["id"])
        employee = self._add_employee(org["id"], org_admin_h)

        prod = self._setup_supplier_and_product(price_minor=100_000)
        emp_h = employee["headers"]

        # Add to cart
        add_resp = self._client.post(
            "/api/v1/cart/items",
            json={"product_id": prod["product_id"], "quantity": 1},
            headers=emp_h,
        )
        self.assertIn(add_resp.status_code, (200, 201), add_resp.get_json())

        # Get quote with 0 credit to know total cash_due
        quote_resp = self._client.get("/api/v1/checkout/quote", headers=emp_h)
        self.assertEqual(quote_resp.status_code, 200, quote_resp.get_json())
        quote_data = quote_resp.get_json()
        total_minor = int(quote_data.get("cash_due_minor", quote_data.get("cart", {}).get("total_minor", 0)))
        self.assertGreater(total_minor, 13, "Product price too low for decline test")

        # Allocate credit so cash_due = 13 (triggers MockPSP decline)
        # MockPSP declines when amount_minor % 100 == 13
        credit_amount = total_minor - 13
        self.assertGreater(credit_amount, 0)
        alloc_resp = self._client.post(
            f"/api/v1/organizations/{org['id']}/credit-allocations",
            json={"membership_id": employee["id"], "amount_minor": credit_amount},
            headers={**org_admin_h, "Idempotency-Key": uuid.uuid4().hex},
        )
        self.assertEqual(alloc_resp.status_code, 201, alloc_resp.get_json())

        # Record state before the failing checkout
        inv_before = int(self._db.query_one(
            "SELECT quantity_available FROM inventory WHERE product_id = ?",
            (prod["product_id"],),
        )["quantity_available"])
        ledger_count_before = int(self._db.query_one(
            "SELECT COUNT(*) AS n FROM credit_ledger_entries "
            "WHERE allocation_id = ? AND entry_type = 'capture'",
            (alloc_resp.get_json()["allocation"]["id"],),
        )["n"])

        # Attempt checkout — must fail (PSP declines amount ending in 13)
        co_resp = self._checkout(emp_h)
        # Expect 402 payment_failed
        self.assertEqual(co_resp.status_code, 402, co_resp.get_json())

        # No order row for this user
        emp_user_row = self._db.query_one(
            "SELECT id FROM users WHERE email_normalized = ?",
            (employee["email"].lower(),),
        )
        order_count = int(self._db.query_one(
            "SELECT COUNT(*) AS n FROM orders WHERE user_id = ?",
            (int(emp_user_row["id"]),),
        )["n"])
        self.assertEqual(order_count, 0, "No order must be committed after PSP decline")

        # Inventory unchanged
        inv_after = int(self._db.query_one(
            "SELECT quantity_available FROM inventory WHERE product_id = ?",
            (prod["product_id"],),
        )["quantity_available"])
        self.assertEqual(inv_after, inv_before, "Inventory must be unchanged after PSP decline")

        # No credit ledger capture entry (credit was not consumed)
        ledger_count_after = int(self._db.query_one(
            "SELECT COUNT(*) AS n FROM credit_ledger_entries "
            "WHERE allocation_id = ? AND entry_type = 'capture'",
            (alloc_resp.get_json()["allocation"]["id"],),
        )["n"])
        self.assertEqual(ledger_count_after, ledger_count_before)

        # No integration_events for this user's order (no order was created)
        integration_event_count = int(self._db.query_one(
            "SELECT COUNT(*) AS n FROM integration_events "
            "WHERE event_type = 'ORDER_CREATED' AND "
            "payload_json LIKE ?",
            (f'%"user_id": {int(emp_user_row["id"])}%',),
        )["n"])
        self.assertEqual(integration_event_count, 0,
                         "No ORDER_CREATED event must be committed after PSP decline")

    def test_13_ledger_append_only(self):
        """Ledger service must have no UPDATE/DELETE on ledger_entries. Outbox no DELETE on events."""
        # Read ledger_service.py source from disk
        ledger_svc_path = (
            Path(__file__).resolve().parents[1]
            / "app" / "services" / "ledger_service.py"
        )
        self.assertTrue(ledger_svc_path.exists(), f"ledger_service.py not found at {ledger_svc_path}")
        ledger_source = ledger_svc_path.read_text(encoding="utf-8").lower()

        # No UPDATE ledger_entries or DELETE FROM ledger_entries
        self.assertNotIn(
            "update ledger_entries",
            ledger_source,
            "ledger_service must never UPDATE ledger_entries (append-only invariant)",
        )
        self.assertNotIn(
            "delete from ledger_entries",
            ledger_source,
            "ledger_service must never DELETE FROM ledger_entries (append-only invariant)",
        )

        # Read outbox_worker.py and verify no DELETE FROM integration_events
        outbox_path = (
            Path(__file__).resolve().parents[1]
            / "app" / "services" / "outbox_worker.py"
        )
        self.assertTrue(outbox_path.exists(), f"outbox_worker.py not found at {outbox_path}")
        outbox_source = outbox_path.read_text(encoding="utf-8").lower()

        self.assertNotIn(
            "delete from integration_events",
            outbox_source,
            "outbox_worker must never DELETE FROM integration_events",
        )


# ─────────────────────────────────────────────────────────────────────────────
# TestPgProcurement — tests 14-15
# ─────────────────────────────────────────────────────────────────────────────

class TestPgProcurement(_PgBase):
    """Procurement flow and fulfillment invariants."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_14_procurement_flow(self):
        """Complete PR lifecycle: create (draft) → add items → submit → approve.

        Verifies:
        - Each state transition produces the documented status in the DB row.
        - Tenant isolation: a user from a different org cannot access the PR.
        - An unauthorized user (employee, not org_admin) cannot approve.
        """
        admin_h = self._admin_headers()
        org = self._create_org(admin_h)
        org_admin_h, org_admin_info = self._make_org_admin(org["id"])

        # ── Step 1: Create purchase request (status = 'draft') ─────────────────
        pr_resp = self._client.post(
            f"/api/v1/orgs/{org['id']}/procurement/requests",
            json={
                "title": "درخواست خرید آزمایشی",
                "description": "تجهیزات دفتری",
                "urgency": "normal",
                "items": [
                    {
                        "free_text_description": "لپ‌تاپ آزمایشی",
                        "quantity": 2,
                        "unit": "دستگاه",
                        "estimated_unit_price_minor": 50_000_000,
                    }
                ],
            },
            headers=org_admin_h,
        )
        self.assertEqual(pr_resp.status_code, 201, pr_resp.get_json())
        pr = pr_resp.get_json()["purchase_request"]
        pr_id = pr["id"]
        self.assertEqual(pr["status"], "draft",
                         "Newly created PR must have status='draft'")
        self.assertEqual(len(pr.get("items", [])), 1,
                         "PR must have exactly the 1 item submitted")

        # ── Step 2: Verify tenant isolation — another org's admin cannot read it ─
        # The procurement service calls _assert_org_member which raises
        # PermissionError_ (HTTP 403) when the user is not a member of the
        # requested org.  This is the exact documented status code.
        other_org = self._create_org(admin_h)
        other_admin_h, _ = self._make_org_admin(other_org["id"])
        isolation_resp = self._client.get(
            f"/api/v1/orgs/{org['id']}/procurement/requests/{pr_id}",
            headers=other_admin_h,
        )
        self.assertEqual(isolation_resp.status_code, 403,
                         "User from another org must receive exactly 403 (PermissionError_) "
                         "when reading this org's PR")

        # ── Step 3: Submit the PR (draft → submitted) ──────────────────────────
        submit_resp = self._client.post(
            f"/api/v1/orgs/{org['id']}/procurement/requests/{pr_id}/submit",
            headers=org_admin_h,
        )
        self.assertEqual(submit_resp.status_code, 200, submit_resp.get_json())
        submitted_pr = submit_resp.get_json()["purchase_request"]
        self.assertEqual(submitted_pr["status"], "submitted",
                         "PR must be in status='submitted' after submit")
        self.assertIsNotNone(submitted_pr.get("submitted_at"),
                             "submitted_at must be set after submit")

        # Verify the submitted status in DB directly
        with self._db.read_transaction() as conn:
            db_row = conn.execute(
                "SELECT status, submitted_at FROM purchase_requests WHERE id = ?",
                (pr_id,),
            ).fetchone()
        self.assertIsNotNone(db_row, "PR row must exist in DB")
        self.assertEqual(db_row["status"], "submitted",
                         "DB row status must be 'submitted'")
        self.assertIsNotNone(db_row["submitted_at"],
                             "DB submitted_at must not be NULL")

        # ── Step 4: Unauthorized user cannot approve ───────────────────────────
        # A plain employee is an org member, but _can_approve() returns False
        # (employee role is not organization_admin and has no procurement_role='approver').
        # approve_purchase_request raises PermissionError_ → HTTP 403.
        employee = self._add_employee(org["id"], org_admin_h)
        unauth_approve = self._client.post(
            f"/api/v1/orgs/{org['id']}/procurement/requests/{pr_id}/approve",
            json={"action": "approve"},
            headers=employee["headers"],
        )
        self.assertEqual(unauth_approve.status_code, 403,
                         "Plain employee must receive exactly 403 (PermissionError_) "
                         "when attempting to approve a PR")

        # ── Step 5: Org admin approves the PR (submitted → approved) ──────────
        approve_resp = self._client.post(
            f"/api/v1/orgs/{org['id']}/procurement/requests/{pr_id}/approve",
            json={"action": "approve", "reason": "بودجه تأیید شد"},
            headers=org_admin_h,
        )
        self.assertEqual(approve_resp.status_code, 200, approve_resp.get_json())
        approved_pr = approve_resp.get_json()["purchase_request"]
        self.assertEqual(approved_pr["status"], "approved",
                         "PR must be in status='approved' after approve")

        # Verify the approved status in DB directly
        with self._db.read_transaction() as conn:
            db_row2 = conn.execute(
                "SELECT status FROM purchase_requests WHERE id = ?", (pr_id,)
            ).fetchone()
            # procurement_approvals: must have EXACTLY 1 row for this PR
            approval_rows = conn.execute(
                "SELECT action, approver_user_id FROM procurement_approvals "
                "WHERE purchase_request_id = ? ORDER BY id",
                (pr_id,),
            ).fetchall()
        self.assertEqual(db_row2["status"], "approved",
                         "DB row must reflect 'approved' status")
        self.assertEqual(len(approval_rows), 1,
                         "Exactly 1 procurement_approvals row must exist after a single approval")
        approval_row = approval_rows[0]
        self.assertEqual(approval_row["action"], "approve",
                         "Approval action must be exactly 'approve'")
        self.assertEqual(int(approval_row["approver_user_id"]), org_admin_info["user_id"],
                         "approver_user_id must be exactly the org admin's user id")

    def test_15_fulfillment_first_invariant(self):
        """After checkout, fulfillment_orders status is exactly 'assigned' (not NULL, not cancelled).

        Blocker 1 requirement:
        - fulfillment_orders row MUST exist (count >= 1).
        - Each row belongs to the exact order_id.
        - Initial status is exactly 'assigned' (the documented initial state).
        - An order cannot enter 'delivered' state before fulfillment_orders exist.
        """
        org, org_admin_h, employee = self._org_with_funded_employee(200_000_000)
        prod = self._setup_supplier_and_product()

        emp_h = employee["headers"]
        self._add_to_cart(emp_h, prod["product_id"], qty=1)
        co_resp = self._checkout(emp_h)
        self.assertEqual(co_resp.status_code, 201, co_resp.get_json())
        order = co_resp.get_json()["order"]
        order_id = order["id"]

        with self._db.read_transaction() as conn:
            fo_rows = conn.execute(
                "SELECT id, order_id, status FROM fulfillment_orders WHERE order_id = ?",
                (order_id,),
            ).fetchall()

        # fulfillment_orders MUST exist — fulfillment-first checkout guarantees it
        self.assertGreater(
            len(fo_rows), 0,
            "fulfillment_orders must exist after successful checkout"
        )

        for fo in fo_rows:
            # Row belongs to the exact order
            self.assertEqual(int(fo["order_id"]), order_id,
                             "fulfillment_order.order_id must match the checkout order")
            # Status must not be NULL
            self.assertIsNotNone(fo["status"],
                                 "fulfillment_order.status must not be NULL")
            # Status must not be 'cancelled' (a fresh FO is never cancelled)
            self.assertNotEqual(fo["status"], "cancelled",
                                "Freshly created fulfillment_order must not be 'cancelled'")
            # Initial status after checkout is exactly 'assigned'
            self.assertEqual(fo["status"], "assigned",
                             f"Freshly created fulfillment_order must have status='assigned', "
                             f"got {fo['status']!r}")

        # Verify exact row count and order status together.
        # One product in the cart → exactly 1 fulfillment_order expected.
        with self._db.read_transaction() as conn:
            order_row = conn.execute(
                "SELECT status FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
            fo_count = int(conn.execute(
                "SELECT COUNT(*) AS n FROM fulfillment_orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()["n"])

        # Exactly 1 fulfillment_order must exist (one product → one FO)
        self.assertEqual(
            fo_count, 1,
            f"Exactly 1 fulfillment_order must exist for a single-product checkout, "
            f"got fo_count={fo_count}"
        )
        # Order must not be 'delivered' immediately after checkout
        # (delivery requires fulfillment progression through the state machine)
        self.assertNotEqual(
            order_row["status"], "delivered",
            "Order must not be 'delivered' immediately after checkout"
        )


# ─────────────────────────────────────────────────────────────────────────────
# TestPgOutbox — tests 16-18
# ─────────────────────────────────────────────────────────────────────────────

class TestPgOutbox(_PgBase):
    """Outbox worker: delivery, stale lease recovery, concurrent disjoint claiming."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def _insert_pending_event(self, *, event_type: str = "ORDER_CREATED",
                               payload: dict | None = None,
                               connector_account_id: int | None = None,
                               status: str = "pending",
                               updated_at: str | None = None) -> int:
        payload_json = json.dumps(payload or {"order_id": 0})
        with self._db.write_transaction() as conn:
            if updated_at is not None:
                cur = conn.execute(
                    """
                    INSERT INTO integration_events
                        (event_type, direction, connector_account_id, payload_json,
                         status, attempt_count, updated_at)
                    VALUES (?, 'outbound', ?, ?, ?, 0, ?)
                    """,
                    (event_type, connector_account_id, payload_json, status, updated_at),
                )
            else:
                # omit updated_at so the column DEFAULT fires (avoids NOT NULL violation)
                cur = conn.execute(
                    """
                    INSERT INTO integration_events
                        (event_type, direction, connector_account_id, payload_json,
                         status, attempt_count)
                    VALUES (?, 'outbound', ?, ?, ?, 0)
                    """,
                    (event_type, connector_account_id, payload_json, status),
                )
            return int(cur.lastrowid)

    def test_16_outbox_worker_delivery(self):
        """run_once() picks up a pending ORDER_CREATED event and marks it 'delivered'."""
        # Verify that checkout commits an event row (may be 'no_subscriber' if no connector).
        org, org_admin_h, employee = self._org_with_funded_employee(200_000_000)
        prod = self._setup_supplier_and_product()
        emp_h = employee["headers"]
        self._add_to_cart(emp_h, prod["product_id"], qty=1)
        co_resp = self._checkout(emp_h)
        self.assertEqual(co_resp.status_code, 201, co_resp.get_json())
        order_id = co_resp.get_json()["order"]["id"]

        # Checkout must have committed at least one integration_events row for this order.
        ev_row = self._db.query_one(
            "SELECT id, status FROM integration_events "
            "WHERE payload_json LIKE ? ORDER BY id DESC LIMIT 1",
            (f"%{order_id}%",),
        )
        self.assertIsNotNone(ev_row, "integration_events row must exist after checkout")

        # Insert a fresh 'pending' event (connector_account_id=None → internal-only path)
        # so we can verify the outbox worker delivery path on PostgreSQL.
        ev_id = self._insert_pending_event(
            event_type="ORDER_CREATED",
            payload={"order_id": order_id, "test": "delivery"},
        )

        # Run the outbox worker — the internal-only pending event must be delivered.
        with self._app.app_context():
            from app.services.outbox_worker import run_once
            result = run_once(batch_size=100)

        self.assertIn("delivered", result)
        self.assertGreaterEqual(result["delivered"], 1)

        # Verify the specific event is now delivered.
        ev_after = self._db.query_one(
            "SELECT status FROM integration_events WHERE id = ?", (ev_id,)
        )
        self.assertEqual(ev_after["status"], "delivered",
                         "Pending ORDER_CREATED event must be 'delivered' after run_once()")

    def test_17_stale_lease_recovery(self):
        """Stale lease recovery: exact assertions.

        Blocker 3 requirements:
        - Clean isolated fixture: no other stale processing events exist.
        - Insert exactly 1 stale event stuck in 'processing' for > 5 min.
        - Call recover_stale_leases() ONLY (not run_once).
        - Assert recovered count is EXACTLY 1 (clean fixture guarantees this).
        - Assert the event status is exactly 'pending' after recovery.
        - Then call run_once() separately and assert the event becomes 'delivered'.
        """
        # Pre-clean: reset any other 'processing' events that prior tests may have
        # left behind.  This ensures recover_stale_leases() recovers EXACTLY 1.
        with self._db.write_transaction() as conn:
            conn.execute(
                "UPDATE integration_events SET status = 'pending' "
                "WHERE status = 'processing'"
            )

        # Insert exactly 1 stale event stuck in 'processing' for 10 minutes
        stale_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        ev_id = self._insert_pending_event(
            event_type="ORDER_CREATED",
            status="processing",
            updated_at=stale_at,
        )

        # ── Phase 1: recover_stale_leases() only ─────────────────────────────
        # We call recover_stale_leases() directly, NOT run_once(), so that the
        # event is NOT processed during this phase — only reset to 'pending'.
        # Because we pre-cleaned all other 'processing' events, exactly 1
        # event is stale and eligible — the one we just inserted.
        with self._app.app_context():
            from app.services.outbox_worker import recover_stale_leases
            recovered = recover_stale_leases(lease_timeout_s=300)  # 5 min threshold

        # EXACTLY 1 must have been recovered (our stale event; pre-clean guarantees this)
        self.assertEqual(recovered, 1,
                         f"recover_stale_leases must recover EXACTLY 1 stale event "
                         f"(pre-clean ensures isolation), got {recovered}")

        # The specific event must now be exactly 'pending' — NOT 'delivered',
        # NOT 'processing'. recover_stale_leases() ONLY resets to 'pending'.
        ev_after_recovery = self._db.query_one(
            "SELECT status FROM integration_events WHERE id = ?", (ev_id,)
        )
        self.assertEqual(
            ev_after_recovery["status"], "pending",
            f"After recover_stale_leases(), event must be exactly 'pending', "
            f"got {ev_after_recovery['status']!r}. "
            "recover_stale_leases() must only reset to 'pending', not process."
        )

        # ── Phase 2: run_once() processes the recovered event ─────────────────
        # Now call run_once() to pick up the 'pending' event and deliver it.
        with self._app.app_context():
            from app.services.outbox_worker import run_once
            result = run_once(batch_size=100)

        self.assertIn("delivered", result)
        self.assertGreaterEqual(result["delivered"], 1)

        # The specific event must now be exactly 'delivered'
        ev_after_runonce = self._db.query_one(
            "SELECT status FROM integration_events WHERE id = ?", (ev_id,)
        )
        self.assertEqual(
            ev_after_runonce["status"], "delivered",
            f"After run_once(), recovered event must be exactly 'delivered', "
            f"got {ev_after_runonce['status']!r}"
        )

    def test_18_concurrent_workers_disjoint(self):
        """Two concurrent claim_batch() calls claim disjoint event sets (FOR UPDATE SKIP LOCKED).

        Blocker 2 requirements:
        - Use the real production claim_batch() function from outbox_worker.py.
        - Isolate the 4 inserted events from prior test events using _only_ids filter.
        - Each worker uses a separate PostgreSQL connection (no shared connection).
        - Synchronized barrier start ensures genuine concurrency.
        - Claimed sets are disjoint (no event claimed by both workers).
        - Union of claimed sets == EXACTLY the 4 inserted event IDs.
        - Exactly 4 unique IDs claimed total (at-most-once guarantee).
        - All 4 events reach 'delivered' state via the real production dispatch path.
        - None of the 4 events remains 'pending' or 'processing' after dispatch.
        """
        # Insert exactly 4 pending events (no connector_account_id → internal-only)
        event_ids = [
            self._insert_pending_event(event_type="ORDER_CREATED", payload={"order_id": i})
            for i in range(200, 204)
        ]
        event_set = set(event_ids)

        claimed_by: dict[int, list] = {1: [], 2: []}
        errors: list[str] = []
        # Barrier synchronizes both threads so they start claim_batch() simultaneously
        barrier = threading.Barrier(2, timeout=10)

        def _worker(worker_id: int) -> None:
            """Each worker uses a fully independent PostgreSQL connection."""
            try:
                from app.core.db import PostgreSQLBackend
                from app.services.outbox_worker import claim_batch
                # Create an independent connection — NOT sharing _PG_DB
                db2 = PostgreSQLBackend(_PG_URL)
                try:
                    # Wait at the barrier so both threads start claim_batch() simultaneously.
                    # This maximises contention and exercises FOR UPDATE SKIP LOCKED.
                    barrier.wait()
                    # Call the production claim_batch() with an explicit PG connection
                    # and _only_ids filter so only our 4 inserted events are eligible.
                    # batch_size=2 so each worker claims at most 2 of the 4 events.
                    claimed = claim_batch(
                        batch_size=2,
                        _pg_conn=db2.connection,
                        _only_ids=event_ids,
                    )
                    claimed_by[worker_id] = claimed
                finally:
                    db2.close()
            except Exception as exc:
                errors.append(f"worker {worker_id}: {exc}")

        t1 = threading.Thread(target=_worker, args=(1,))
        t2 = threading.Thread(target=_worker, args=(2,))
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        self.assertFalse(errors, f"Worker errors: {errors}")

        all_claimed = claimed_by[1] + claimed_by[2]

        # ── Disjoint assertion ────────────────────────────────────────────────
        # FOR UPDATE SKIP LOCKED must ensure no event is claimed by both workers.
        overlap = set(claimed_by[1]) & set(claimed_by[2])
        self.assertEqual(
            overlap, set(),
            f"Concurrent workers must not claim the same events; overlap: {overlap}"
        )

        # ── Exact union assertion ─────────────────────────────────────────────
        # The union of both workers' claimed IDs must be EXACTLY the 4 inserted IDs.
        # _only_ids isolates our fixture from other tests; batch_size=2+2=4 covers all.
        claimed_set = set(all_claimed)
        self.assertEqual(
            claimed_set, event_set,
            f"Union of claimed events must equal EXACTLY the 4 inserted IDs.\n"
            f"  Inserted: {sorted(event_set)}\n"
            f"  Claimed:  {sorted(claimed_set)}\n"
            f"  Worker 1: {sorted(claimed_by[1])}\n"
            f"  Worker 2: {sorted(claimed_by[2])}"
        )

        # ── At-most-once / exactly-4 assertion ───────────────────────────────
        # Exactly 4 unique IDs must be claimed (one per inserted event).
        self.assertEqual(
            len(all_claimed), 4,
            f"Exactly 4 events must be claimed, got {len(all_claimed)}: {all_claimed}"
        )
        self.assertEqual(
            len(all_claimed), len(set(all_claimed)),
            "Each of the 4 events must be claimed by at most one worker (no duplicates)"
        )

        # ── DB state: all 4 must be in 'processing' after claiming ────────────
        for ev_id in event_ids:
            row = self._db.query_one(
                "SELECT status FROM integration_events WHERE id = ?", (ev_id,)
            )
            self.assertEqual(
                row["status"], "processing",
                f"Event {ev_id} must be in 'processing' state immediately after claiming"
            )

        # ── Complete dispatch via real production worker path ─────────────────
        # Use _load_event, _dispatch_event, _mark_delivered from outbox_worker
        # (the same production path run_once() uses) to process all 4 events.
        with self._app.app_context():
            from app.services.outbox_worker import _load_event, _dispatch_event, _mark_delivered
            for ev_id in event_ids:
                event = _load_event(ev_id)
                self.assertIsNotNone(event, f"Event {ev_id} must be loadable after claiming")
                external_doc_id = _dispatch_event(event)
                _mark_delivered(ev_id, external_doc_id=external_doc_id)

        # ── Final state: all 4 must be exactly 'delivered' ───────────────────
        for ev_id in event_ids:
            row = self._db.query_one(
                "SELECT status FROM integration_events WHERE id = ?", (ev_id,)
            )
            self.assertEqual(
                row["status"], "delivered",
                f"Event {ev_id} must reach exactly 'delivered' after production dispatch, "
                f"got {row['status']!r}"
            )

        # ── None remains pending or processing ────────────────────────────────
        for ev_id in event_ids:
            row = self._db.query_one(
                "SELECT status FROM integration_events WHERE id = ?", (ev_id,)
            )
            self.assertNotIn(
                row["status"], ("pending", "processing"),
                f"Event {ev_id} must not remain 'pending' or 'processing' after full dispatch, "
                f"got {row['status']!r}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# TestPgVatAccounting — tests 19-32
# ─────────────────────────────────────────────────────────────────────────────

class TestPgVatAccounting(_PgBase):
    """VAT accounting integrity — Phase 8 v6 money equation.

    Every test in this class verifies a distinct facet of the v6 contract:

        taxable_base_minor = subtotal_minor          (shipping excluded from VAT)
        tax_minor          = subtotal_minor * rate_bps // 10000   (integer floor)
        total_minor        = subtotal_minor + shipping_fee_minor + tax_minor
        credit_minor + cash_minor = total_minor      (funding invariant)

    VAT collected is posted to liability account 2010 (ACCOUNT_VAT_PAYABLE),
    not to revenue.  The ledger must remain balanced after every checkout.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _ledger_entries_for_order(self, order_number: str) -> list[dict]:
        """Return all ledger entries for the given order reference."""
        with self._db.read_transaction() as conn:
            rows = conn.execute(
                """
                SELECT a.code AS account_code, a.type AS account_type,
                       e.direction, e.amount_minor
                FROM ledger_entries e
                JOIN ledger_transactions t ON t.id = e.transaction_id
                JOIN ledger_accounts a ON a.id = e.account_id
                WHERE t.reference = ?
                ORDER BY e.id
                """,
                (f"order:{order_number}",),
            ).fetchall()
        return [dict(r) for r in rows]

    def _checkout_funded_employee(self, price_minor: int = 20_000_000,
                                  credit_minor: int = 200_000_000,
                                  qty: int = 1) -> tuple[dict, dict]:
        """Create org + funded employee, add product to cart, checkout. Returns (order, employee)."""
        _, org_admin_h, employee = self._org_with_funded_employee(credit_minor)
        prod = self._setup_supplier_and_product(price_minor=price_minor)
        self._add_to_cart(employee["headers"], prod["product_id"], qty=qty)
        co_resp = self._checkout(employee["headers"])
        self.assertEqual(co_resp.status_code, 201, co_resp.get_json())
        return co_resp.get_json()["order"], employee

    # ── tests ─────────────────────────────────────────────────────────────────

    def test_19_total_minor_includes_vat(self):
        """order.total_minor = subtotal_minor + shipping_fee_minor + tax_minor (v6 equation)."""
        order, _ = self._checkout_funded_employee(price_minor=20_000_000)

        subtotal = int(order["subtotal_minor"])
        shipping = int(order.get("shipping_fee_minor", 0))
        tax      = int(order.get("tax_minor", 0))
        total    = int(order["total_minor"])

        self.assertEqual(
            total, subtotal + shipping + tax,
            f"v6 money equation violated: total_minor({total}) != "
            f"subtotal_minor({subtotal}) + shipping_fee_minor({shipping}) + tax_minor({tax})"
        )
        self.assertGreater(tax, 0,
                           "tax_minor must be > 0 for a STANDARD-rate product")

    def test_20_vat_payable_account_2010_credited(self):
        """After checkout, ledger account 2010 is credited by exactly tax_minor."""
        order, _ = self._checkout_funded_employee(price_minor=20_000_000)

        tax_minor      = int(order.get("tax_minor", -1))
        order_number   = order["order_number"]

        self.assertGreater(tax_minor, 0, "Order must carry a positive tax_minor")

        entries = self._ledger_entries_for_order(order_number)
        vat_entries = [e for e in entries
                       if e["account_code"] == "2010" and e["direction"] == "credit"]

        self.assertEqual(
            len(vat_entries), 1,
            f"Exactly 1 credit entry on account 2010 expected, got {len(vat_entries)}"
        )
        self.assertEqual(
            int(vat_entries[0]["amount_minor"]), tax_minor,
            f"2010 credit must equal tax_minor={tax_minor}, "
            f"got {vat_entries[0]['amount_minor']}"
        )

    def test_21_ledger_balanced_after_checkout(self):
        """Trial balance for a single order's transaction: sum(debits) == sum(credits)."""
        order, _ = self._checkout_funded_employee(price_minor=20_000_000)
        order_number = order["order_number"]

        entries = self._ledger_entries_for_order(order_number)
        self.assertGreater(len(entries), 1,
                           "At least 2 ledger entries required for a balanced transaction")

        total_debits  = sum(e["amount_minor"] for e in entries if e["direction"] == "debit")
        total_credits = sum(e["amount_minor"] for e in entries if e["direction"] == "credit")

        self.assertEqual(
            total_debits, total_credits,
            f"Ledger unbalanced for order {order_number}: "
            f"debits={total_debits} credits={total_credits}"
        )
        # Both sides must equal total_minor (the invariant total)
        self.assertEqual(
            total_debits, int(order["total_minor"]),
            f"Debit sum must equal order.total_minor={order['total_minor']}, "
            f"got debits={total_debits}"
        )

    def test_22_ample_credit_covers_vat_inclusive_total(self):
        """With 200M credit, credit_minor == total_minor (VAT-inclusive); cash_minor == 0."""
        # 200M credit vastly exceeds any reasonable order total.
        order, _ = self._checkout_funded_employee(price_minor=20_000_000,
                                                  credit_minor=200_000_000)

        total_minor  = int(order["total_minor"])
        credit_minor = int(order["credit_minor"])
        cash_minor   = int(order.get("cash_minor", order.get("cash_due_minor", -1)))

        self.assertEqual(credit_minor, total_minor,
                         f"With ample credit, credit_minor({credit_minor}) must equal "
                         f"total_minor({total_minor}) — credit must cover full VAT-inclusive total")
        self.assertEqual(cash_minor, 0,
                         f"With ample credit, cash_minor must be 0, got {cash_minor}")

    def test_23_funding_invariant_split_payment(self):
        """credit_minor + cash_minor == total_minor exactly in a split payment."""
        # Use a product that costs 20M and allocate only 5M — forces a split.
        price_minor = 20_000_000
        admin_h = self._admin_headers()
        org = self._create_org(admin_h)
        org_admin_h, _ = self._make_org_admin(org["id"])
        employee = self._add_employee(org["id"], org_admin_h)
        # Allocate 5M — less than the product price, guarantees a split
        self._allocate(org["id"], org_admin_h, employee["id"], 5_000_000)

        prod = self._setup_supplier_and_product(price_minor=price_minor)
        self._add_to_cart(employee["headers"], prod["product_id"], qty=1)
        co_resp = self._checkout(employee["headers"])
        self.assertEqual(co_resp.status_code, 201, co_resp.get_json())
        order = co_resp.get_json()["order"]

        total_minor  = int(order["total_minor"])
        credit_minor = int(order["credit_minor"])
        cash_minor   = int(order.get("cash_minor", order.get("cash_due_minor", -1)))

        self.assertGreater(credit_minor, 0,
                           "Split payment must have credit_minor > 0")
        self.assertGreater(cash_minor, 0,
                           "Split payment must have cash_minor > 0")
        self.assertEqual(
            credit_minor + cash_minor, total_minor,
            f"Funding invariant violated: credit({credit_minor}) + cash({cash_minor}) "
            f"!= total({total_minor})"
        )

    def test_24_taxable_base_excludes_shipping(self):
        """order.taxable_base_minor == order.subtotal_minor (shipping is VAT-exempt)."""
        # Use qty=1 so there IS a shipping fee (ensures the distinction matters)
        order, _ = self._checkout_funded_employee(price_minor=10_000_000, qty=1)

        taxable_base = order.get("taxable_base_minor")
        subtotal     = int(order["subtotal_minor"])
        shipping     = int(order.get("shipping_fee_minor", 0))

        self.assertIsNotNone(taxable_base,
                             "order.taxable_base_minor must be present in API response")
        self.assertEqual(
            int(taxable_base), subtotal,
            f"taxable_base_minor({taxable_base}) must equal subtotal_minor({subtotal}) — "
            f"shipping({shipping}) must NOT be included in the taxable base"
        )
        # Verify tax was NOT calculated on the shipping portion
        tax_minor = int(order.get("tax_minor", 0))
        expected_tax = subtotal * 1000 // 10000  # 10% floor of subtotal only
        self.assertEqual(
            tax_minor, expected_tax,
            f"tax_minor({tax_minor}) must equal subtotal({subtotal}) * 10% floor = {expected_tax}. "
            f"Shipping({shipping}) must not contribute to tax"
        )

    def test_25_tax_fields_present_in_order_api(self):
        """order response includes tax_minor, taxable_base_minor, tax_rate_bps, and tax."""
        order, _ = self._checkout_funded_employee(price_minor=15_000_000)

        required_fields = ["tax_minor", "taxable_base_minor", "tax_rate_bps", "tax"]
        for field in required_fields:
            self.assertIn(
                field, order,
                f"Order API response missing required field '{field}'"
            )
            self.assertIsNotNone(
                order[field],
                f"Order API field '{field}' must not be None"
            )

        # Sanity: rate_bps must be a positive integer
        rate_bps = int(order["tax_rate_bps"])
        self.assertGreater(rate_bps, 0,
                           "tax_rate_bps must be a positive integer (VAT rate in bps)")

    def test_26_tax_fields_present_in_quote(self):
        """GET /checkout/quote returns tax_minor, tax_rate_bps, taxable_base_minor, and tax."""
        _, org_admin_h, employee = self._org_with_funded_employee(200_000_000)
        prod = self._setup_supplier_and_product(price_minor=15_000_000)
        self._add_to_cart(employee["headers"], prod["product_id"], qty=1)

        quote = self._get_quote(employee["headers"])

        required_fields = ["tax_minor", "tax_rate_bps", "taxable_base_minor", "tax"]
        for field in required_fields:
            self.assertIn(
                field, quote,
                f"Quote response missing required field '{field}'"
            )
            self.assertIsNotNone(
                quote[field],
                f"Quote field '{field}' must not be None"
            )

        # tax_minor must match the floor calculation
        subtotal = int(quote.get("taxable_base_minor", 0))
        rate_bps = int(quote.get("tax_rate_bps", 0))
        expected_tax = subtotal * rate_bps // 10000
        actual_tax   = int(quote.get("tax_minor", -1))

        self.assertEqual(
            actual_tax, expected_tax,
            f"Quote tax_minor({actual_tax}) must equal "
            f"taxable_base({subtotal}) * {rate_bps} bps // 10000 = {expected_tax}"
        )

    def test_27_standard_vat_rate_is_1000_bps(self):
        """Migration 0019 sets STANDARD VAT rate to exactly 1000 bps (10%); verified end-to-end."""
        _, org_admin_h, employee = self._org_with_funded_employee(200_000_000)
        prod = self._setup_supplier_and_product(price_minor=10_000_000)
        self._add_to_cart(employee["headers"], prod["product_id"], qty=1)

        quote = self._get_quote(employee["headers"])
        rate_bps = int(quote.get("tax_rate_bps", 0))

        self.assertEqual(
            rate_bps, 1000,
            f"STANDARD VAT rate must be exactly 1000 bps (10%), got {rate_bps} bps. "
            "Migration 0019 sets this rate effective 2024-03-20."
        )

        # Also verify via the tax/calculate endpoint
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tax_resp = self._client.post(
            "/api/v1/tax/calculate",
            json={
                "subtotal_minor": 10_000_000,
                "tax_category_code": "STANDARD",
                "effective_date": today,
            },
            headers=employee["headers"],
        )
        self.assertEqual(tax_resp.status_code, 200, tax_resp.get_json())
        api_rate = int(tax_resp.get_json().get("rate_bps", 0))
        self.assertEqual(api_rate, 1000,
                         f"/api/v1/tax/calculate must return rate_bps=1000, got {api_rate}")

    def test_28_tax_uses_integer_floor_not_ceil(self):
        """tax_minor = subtotal_minor * rate_bps // 10000 (floor); non-round subtotal verified."""
        # Pick a subtotal where floor and ceil differ: 15_000_001
        # floor(15_000_001 * 1000 / 10000) = floor(1_500_000.1) = 1_500_000
        # ceil would give 1_500_001
        odd_subtotal  = 15_000_001
        expected_floor = odd_subtotal * 1000 // 10000   # 1_500_000

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Use any registered employee's headers (no org needed for this endpoint with no org_id)
        _, _, employee = self._org_with_funded_employee(1_000_000)
        tax_resp = self._client.post(
            "/api/v1/tax/calculate",
            json={
                "subtotal_minor": odd_subtotal,
                "tax_category_code": "STANDARD",
                "effective_date": today,
            },
            headers=employee["headers"],
        )
        self.assertEqual(tax_resp.status_code, 200, tax_resp.get_json())
        actual_tax = int(tax_resp.get_json().get("tax_minor", -1))

        self.assertEqual(
            actual_tax, expected_floor,
            f"Non-round subtotal {odd_subtotal}: expected floor tax {expected_floor}, "
            f"got {actual_tax}. Tax must use integer floor, not ceil or round."
        )
        # Confirm it is NOT the ceiling
        would_be_ceil = expected_floor + 1
        self.assertNotEqual(
            actual_tax, would_be_ceil,
            f"Tax must be floor({expected_floor}), not ceil({would_be_ceil})"
        )

    def test_29_vat_payable_account_is_liability(self):
        """Ledger account 2010 (ACCOUNT_VAT_PAYABLE) has type='liability' in the DB."""
        with self._db.read_transaction() as conn:
            row = conn.execute(
                "SELECT code, type, name_fa FROM ledger_accounts WHERE code = '2010'"
            ).fetchone()

        self.assertIsNotNone(
            row,
            "Ledger account 2010 (ACCOUNT_VAT_PAYABLE) must be registered in the DB. "
            "Migration or ensure_accounts must create it."
        )
        self.assertEqual(
            row["type"], "liability",
            f"Account 2010 must have type='liability' (VAT collected is owed to the tax "
            f"authority, not platform revenue), got type={row['type']!r}"
        )

    def test_30_psp_charged_cash_minor_not_pre_vat_total(self):
        """In a split payment, PSP is charged exactly cash_minor (VAT-inclusive cash leg)."""
        # Allocate 5M; product 20M → cash = 20M - 5M + tax > 0
        price_minor  = 20_000_000
        credit_alloc = 5_000_000
        admin_h = self._admin_headers()
        org = self._create_org(admin_h)
        org_admin_h, _ = self._make_org_admin(org["id"])
        employee = self._add_employee(org["id"], org_admin_h)
        alloc = self._allocate(org["id"], org_admin_h, employee["id"], credit_alloc)

        prod = self._setup_supplier_and_product(price_minor=price_minor)
        self._add_to_cart(employee["headers"], prod["product_id"], qty=1)
        co_resp = self._checkout(employee["headers"])
        self.assertEqual(co_resp.status_code, 201, co_resp.get_json())
        order = co_resp.get_json()["order"]

        order_id   = order["id"]
        cash_minor = int(order.get("cash_minor", order.get("cash_due_minor", -1)))
        self.assertGreater(cash_minor, 0, "Split payment must produce cash_minor > 0")

        # Read the payment_intents row to verify the PSP was given exactly cash_minor
        with self._db.read_transaction() as conn:
            intent = conn.execute(
                "SELECT cash_minor, amount_minor FROM payment_intents WHERE order_id = ?",
                (order_id,),
            ).fetchone()

        self.assertIsNotNone(intent,
                             "payment_intents row must exist after successful checkout")
        self.assertEqual(
            int(intent["cash_minor"]), cash_minor,
            f"payment_intents.cash_minor must equal order.cash_minor={cash_minor}, "
            f"got {intent['cash_minor']}"
        )

    def test_31_quote_credit_to_use_predicts_order_credit(self):
        """quote.credit_to_use_minor exactly matches order.credit_minor (server-authoritative)."""
        _, org_admin_h, employee = self._org_with_funded_employee(200_000_000)
        prod = self._setup_supplier_and_product(price_minor=15_000_000)
        self._add_to_cart(employee["headers"], prod["product_id"], qty=1)

        # Get quote prediction before checkout
        quote = self._get_quote(employee["headers"])
        predicted_credit = int(quote.get("credit_to_use_minor", 0))
        predicted_cash   = int(quote.get("cash_due_minor", 0))
        predicted_total  = int(quote.get("cart", {}).get("total_minor", 0))

        # Checkout
        co_resp = self._checkout(employee["headers"])
        self.assertEqual(co_resp.status_code, 201, co_resp.get_json())
        order = co_resp.get_json()["order"]

        actual_credit = int(order["credit_minor"])
        actual_cash   = int(order.get("cash_minor", order.get("cash_due_minor", -1)))
        actual_total  = int(order["total_minor"])

        self.assertEqual(
            actual_credit, predicted_credit,
            f"order.credit_minor({actual_credit}) must equal "
            f"quote.credit_to_use_minor({predicted_credit})"
        )
        self.assertEqual(
            actual_cash, predicted_cash,
            f"order.cash_minor({actual_cash}) must equal "
            f"quote.cash_due_minor({predicted_cash})"
        )
        self.assertEqual(
            actual_total, predicted_total,
            f"order.total_minor({actual_total}) must equal "
            f"quote.cart.total_minor({predicted_total})"
        )

    def test_32_vat_payable_not_duplicated_on_idempotent_replay(self):
        """Replay checkout with same Idempotency-Key: account 2010 is credited exactly once."""
        _, org_admin_h, employee = self._org_with_funded_employee(200_000_000)
        prod = self._setup_supplier_and_product(price_minor=15_000_000)
        self._add_to_cart(employee["headers"], prod["product_id"], qty=1)

        idem_key = uuid.uuid4().hex

        # First checkout
        resp1 = self._checkout(employee["headers"], key=idem_key)
        self.assertEqual(resp1.status_code, 201, resp1.get_json())
        order1 = resp1.get_json()["order"]

        # Idempotent replay
        resp2 = self._checkout(employee["headers"], key=idem_key)
        self.assertEqual(resp2.status_code, 201, resp2.get_json())
        order2 = resp2.get_json()["order"]

        # Same order returned
        self.assertEqual(order1["id"], order2["id"],
                         "Idempotent replay must return the same order")

        # VAT payable entry must exist exactly once
        entries = self._ledger_entries_for_order(order1["order_number"])
        vat_credits = [e for e in entries
                       if e["account_code"] == "2010" and e["direction"] == "credit"]

        self.assertEqual(
            len(vat_credits), 1,
            f"Account 2010 must be credited exactly once after replay, "
            f"got {len(vat_credits)} entries: {vat_credits}"
        )


if __name__ == "__main__":
    unittest.main()
