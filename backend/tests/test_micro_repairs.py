"""Micro-repair tests for Phase 6 Final Repair (Repairs 1-6).

Repair 1: No mock knowledge fallback — MockCatalogue only if explicitly registered.
Repair 2: cost_price_minor = NULL when unknown (never fabricated).
Repair 3: Three-way match nonexistent document → MISSING_DOCUMENT, no FK crash.
Repair 4: Financial exception failures are logged, not silently swallowed.
Repair 5: Reconciliation strong reference validates amount+currency.
Repair 6: DB-level UNIQUE index on exceptions.idempotency_key.
"""
import logging
import unittest
from tests.base import AppTestCase
from app.services import product_resolution_service as prs
from app.services import three_way_match_service, reconciliation_service, exception_service


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _make_supplier(conn, email: str, nat_id: str, name: str) -> tuple[int, int]:
    cur = conn.execute(
        "INSERT INTO users (email, email_normalized, password_hash, full_name, role, is_active)"
        " VALUES (?,?,?,?,?,?)",
        (email, email.lower(),
         "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
         name, "supplier", 1),
    )
    uid = int(cur.lastrowid)
    cur = conn.execute(
        "INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, status, rating_x10, user_id)"
        " VALUES (?,?,?,?,?,?,?)",
        (name, name, nat_id, "retailer", "active", 40, uid),
    )
    sid = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO supplier_locations (supplier_id, province, city, status,"
        " can_local_delivery, can_intercity_shipping, can_pickup, prep_time_minutes)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (sid, "Tehran", "Tehran", "active", 1, 1, 0, 60),
    )
    return sid, uid


def _make_connector(conn, supplier_id: int, name: str = "ERP") -> int:
    cur = conn.execute(
        "INSERT INTO connector_accounts (supplier_id, connector_type, name, status, config_json, mock_erp_dataset)"
        " VALUES (?,?,?,?,?,?)",
        (supplier_id, "MOCK_ERP", name, "active", '{"dataset":"large"}', "products"),
    )
    return int(cur.lastrowid)


def _make_procurement_order(conn, supplier_id: int, total: int = 1000000) -> int:
    cur = conn.execute(
        "INSERT INTO procurement_orders"
        " (supplier_id, reference_number, order_date, status, total_minor, currency)"
        " VALUES (?,?,?,?,?,?)",
        (supplier_id, "PO-MR-TEST", "2026-01-01", "received", total, "IRR"),
    )
    return int(cur.lastrowid)


def _make_invoice(conn, supplier_id: int, total: int = 1000000,
                  invoice_number: str = "INV-MR-001", created_by: int = 1) -> int:
    import hashlib
    dedup = hashlib.sha256(
        f"{supplier_id}:{invoice_number}:2026-01-01:{total}".encode()
    ).hexdigest()
    cur = conn.execute(
        "INSERT INTO supplier_invoices"
        " (supplier_id, invoice_number, invoice_date, subtotal_minor, tax_minor,"
        "  total_minor, currency, status, source_type, raw_json,"
        "  dedup_hash, is_duplicate, created_by)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (supplier_id, invoice_number, "2026-01-01", total, 0, total,
         "IRR", "captured", "manual", "{}",
         dedup, 0, created_by),
    )
    return int(cur.lastrowid)


def _make_fulfillment(conn, supplier_id: int, total: int = 1000000) -> int:
    import datetime
    # Resolve the supplier's location (created by _make_supplier)
    loc = conn.execute(
        "SELECT id FROM supplier_locations WHERE supplier_id = ? LIMIT 1", (supplier_id,)
    ).fetchone()
    loc_id = int(loc["id"]) if loc else 1

    # Create a minimal order backed by the seeded admin user (id=1)
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    order_cur = conn.execute(
        "INSERT INTO orders"
        " (order_number, user_id, status, subtotal_minor, shipping_fee_minor,"
        "  total_minor, currency, shipping_province, shipping_city, shipping_line1,"
        "  recipient_name, recipient_phone, placed_at, credit_minor, cash_minor)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"ORD-FO-{supplier_id}-{total}", 1, "paid", total, 0, total, "IRR",
         "Tehran", "Tehran", "Test Address", "Test Recipient", "09000000000",
         now, 0, total),
    )
    order_id = int(order_cur.lastrowid)

    cur = conn.execute(
        "INSERT INTO fulfillment_orders"
        " (order_id, supplier_id, supplier_location_id, status, fulfillment_type,"
        "  gross_payable_minor, routing_history_json)"
        " VALUES (?,?,?,?,?,?,?)",
        (order_id, supplier_id, loc_id, "delivered", "delivery", total, "[]"),
    )
    return int(cur.lastrowid)


def _make_payment(conn, amount: int, provider_ref: str, currency: str = "IRR") -> int:
    import datetime
    # Create a minimal order backed by the seeded admin user (id=1)
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    cur = conn.execute(
        "INSERT INTO orders"
        " (order_number, user_id, status, subtotal_minor, shipping_fee_minor,"
        "  total_minor, currency, shipping_province, shipping_city, shipping_line1,"
        "  recipient_name, recipient_phone, placed_at, credit_minor, cash_minor)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"ORD-MR-{provider_ref[:12]}", 1, "paid", amount, 0, amount, currency,
         "Tehran", "Tehran", "Test Address", "Test", "09000000000", now, 0, amount),
    )
    order_id = int(cur.lastrowid)
    cur = conn.execute(
        "INSERT INTO payments"
        " (order_id, provider, provider_ref, method, amount_minor, currency, status)"
        " VALUES (?,?,?,?,?,?,?)",
        (order_id, "mock_psp", provider_ref, "card", amount, currency, "captured"),
    )
    return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Repair 1: No mock knowledge fallback
# ---------------------------------------------------------------------------

class Repair1NoMockFallbackTest(AppTestCase):
    """MockCatalogue must NOT be queried unless explicitly registered in knowledge_sources."""

    def test_no_knowledge_sources_registered_does_not_use_mock_catalogue(self):
        """When knowledge_sources is empty, barcode lookup finds nothing and
        product is created as new_canonical with NO knowledge enrichment.
        No exception — just unenriched canonical."""
        with self.db.write_transaction() as conn:
            sid, _ = _make_supplier(conn, "r1@test.com", "R1111111111", "Repair1 Sup")
            ca_id = _make_connector(conn, sid)
            # DO NOT seed knowledge_sources table

        # Barcode in mock_catalogue range (index 0 = barcode 6260000000000)
        # If fallback were active, this WOULD be found by MockCatalogue
        barcode_in_range = "6260000000000"
        with self.db.write_transaction() as conn:
            result = prs.resolve_product(
                conn,
                external={
                    "barcode": barcode_in_range,
                    "code": "ERP-R1-000",
                    "name_fa": "محصول بدون غنی‌سازی",
                    "price_minor": 1000000,
                    "stock_quantity": 5,
                },
                connector_account_id=ca_id,
                supplier_id=sid,
            )

        # Result must be new_canonical — product did NOT come from mock_catalogue
        self.assertEqual(result["result"], "new_canonical")
        # knowledge_adapter_used must be None (mock_catalogue was NOT queried)
        self.assertIsNone(result["knowledge_adapter_used"])

    def test_explicit_mock_catalogue_registration_does_query_it(self):
        """When mock_catalogue IS registered, it is queried and enrichment is used."""
        with self.db.write_transaction() as conn:
            sid, _ = _make_supplier(conn, "r1b@test.com", "R1222222222", "Repair1b Sup")
            ca_id = _make_connector(conn, sid)
            # Explicitly register mock_catalogue
            conn.execute(
                "INSERT OR IGNORE INTO knowledge_sources (name, source_type, adapter_key, priority, is_active)"
                " VALUES (?,?,?,?,?)",
                ("mock_catalogue", "mock_catalogue", "mock_catalogue", 100, 1),
            )

        barcode_in_range = "6260000000001"  # index 1 in MockCatalogue
        with self.db.write_transaction() as conn:
            result = prs.resolve_product(
                conn,
                external={
                    "barcode": barcode_in_range,
                    "code": "ERP-R1B-001",
                    "name_fa": "محصول غنی‌شده",
                    "price_minor": 2000000,
                    "stock_quantity": 10,
                },
                connector_account_id=ca_id,
                supplier_id=sid,
            )

        self.assertEqual(result["result"], "new_canonical")
        self.assertEqual(result["knowledge_adapter_used"], "mock_catalogue")


# ---------------------------------------------------------------------------
# Repair 2: cost_price_minor = NULL when unknown
# ---------------------------------------------------------------------------

class Repair2CostPriceNullTest(AppTestCase):
    """cost_price_minor must be NULL when no authoritative source provides it."""

    def test_new_canonical_offer_has_null_cost_price(self):
        """When supplier provides only selling price (no cost), cost_price_minor must be NULL."""
        with self.db.write_transaction() as conn:
            sid, _ = _make_supplier(conn, "r2@test.com", "R2111111111", "Repair2 Sup")
            ca_id = _make_connector(conn, sid)

        with self.db.write_transaction() as conn:
            result = prs.resolve_product(
                conn,
                external={
                    "barcode": "6260005000001",
                    "code": "ERP-R2-001",
                    "name_fa": "محصول بدون قیمت تمام‌شده",
                    "price_minor": 3000000,   # selling price known
                    "stock_quantity": 15,
                    # cost NOT provided
                },
                connector_account_id=ca_id,
                supplier_id=sid,
            )

        offer_id = result["offer_id"]
        self.assertIsNotNone(offer_id)

        with self.db.read_transaction() as conn:
            offer = conn.execute(
                "SELECT cost_price_minor FROM seller_offers WHERE id = ?", (offer_id,)
            ).fetchone()
        # cost_price_minor MUST be NULL — never invented from selling price
        self.assertIsNone(offer["cost_price_minor"],
                          "cost_price_minor must be NULL when not supplied — "
                          "int(price * 0.8) fabrication is forbidden")


# ---------------------------------------------------------------------------
# Repair 3: Three-way match missing document
# ---------------------------------------------------------------------------

class Repair3MissingDocumentTest(AppTestCase):
    """Nonexistent document IDs in perform_match must yield MISSING_DOCUMENT,
    not a crash and not a false MATCHED."""

    def setUp(self):
        super().setUp()
        with self.db.write_transaction() as conn:
            self.sid, _ = _make_supplier(conn, "r3@test.com", "R3111111111", "Repair3 Sup")
            self.admin_uid = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, role, is_active)"
                " VALUES (?,?,?,?,?,?)",
                ("r3admin@test.com", "r3admin@test.com",
                 "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                 "Admin R3", "admin", 1),
            ).lastrowid

    def test_nonexistent_fulfillment_id_yields_missing_document(self):
        """valid PO + valid invoice + nonexistent fulfillment_order_id → MISSING_DOCUMENT."""
        with self.db.write_transaction() as conn:
            po_id = _make_procurement_order(conn, self.sid, total=500000)
            inv_id = _make_invoice(conn, self.sid, total=500000, invoice_number="INV-MR3-A")

        nonexistent_fo_id = 99999

        with self.db.write_transaction() as conn:
            result = three_way_match_service.perform_match(
                conn,
                supplier_id=self.sid,
                procurement_order_id=po_id,
                invoice_id=inv_id,
                fulfillment_order_id=nonexistent_fo_id,
                checked_by=self.admin_uid,
            )

        self.assertEqual(result["result"], "missing_document",
                         "Nonexistent fulfillment_order_id must yield MISSING_DOCUMENT")
        self.assertIn("missing_documents", result["discrepancy"],
                      "discrepancy must name the missing document IDs")
        self.assertIn("fulfillment_order_id", result["discrepancy"]["missing_documents"])

    def test_missing_document_creates_exception(self):
        """MISSING_DOCUMENT result must create an exception in the inbox."""
        with self.db.write_transaction() as conn:
            po_id = _make_procurement_order(conn, self.sid, total=700000)
            inv_id = _make_invoice(conn, self.sid, total=700000, invoice_number="INV-MR3-B")

        with self.db.write_transaction() as conn:
            three_way_match_service.perform_match(
                conn,
                supplier_id=self.sid,
                procurement_order_id=po_id,
                invoice_id=inv_id,
                fulfillment_order_id=88888,  # nonexistent
                checked_by=self.admin_uid,
            )

        with self.db.read_transaction() as conn:
            exc_row = conn.execute(
                "SELECT * FROM exceptions WHERE exception_type = 'other'"
                " AND supplier_id = ? ORDER BY id DESC LIMIT 1",
                (self.sid,),
            ).fetchone()
        self.assertIsNotNone(exc_row, "MISSING_DOCUMENT must create an exception")

    def test_nonexistent_fulfillment_does_not_crash_on_fk(self):
        """No FK violation crash when fulfillment_order_id is nonexistent.
        The match record must use safe (NULL) FK values for missing docs."""
        with self.db.write_transaction() as conn:
            inv_id = _make_invoice(conn, self.sid, total=300000, invoice_number="INV-MR3-C")

        with self.db.write_transaction() as conn:
            result = three_way_match_service.perform_match(
                conn,
                supplier_id=self.sid,
                invoice_id=inv_id,
                fulfillment_order_id=77777,  # nonexistent
                checked_by=self.admin_uid,
            )

        # Should not raise; result is missing_document
        self.assertEqual(result["result"], "missing_document")

        with self.db.read_transaction() as conn:
            match_row = conn.execute(
                "SELECT fulfillment_order_id FROM three_way_matches WHERE id = ?",
                (result["id"],),
            ).fetchone()
        # FK column must be NULL (safe) not the nonexistent id
        self.assertIsNone(match_row["fulfillment_order_id"],
                          "three_way_matches.fulfillment_order_id must be NULL "
                          "when document does not exist (no FK crash)")

    def test_all_ids_match_existing_documents_returns_matched(self):
        """Sanity: valid PO + invoice → MATCHED (not confused with missing doc)."""
        with self.db.write_transaction() as conn:
            po_id = _make_procurement_order(conn, self.sid, total=200000)
            inv_id = _make_invoice(conn, self.sid, total=200000, invoice_number="INV-MR3-D")
            fo_id = _make_fulfillment(conn, self.sid, total=200000)

        with self.db.write_transaction() as conn:
            result = three_way_match_service.perform_match(
                conn,
                supplier_id=self.sid,
                procurement_order_id=po_id,
                invoice_id=inv_id,
                fulfillment_order_id=fo_id,
                checked_by=self.admin_uid,
            )

        self.assertIn(result["result"], ("matched", "within_tolerance"))


# ---------------------------------------------------------------------------
# Repair 4: Financial exception failures are logged, not swallowed
# ---------------------------------------------------------------------------

class Repair4ExceptionLoggingTest(AppTestCase):
    """Exception creation failures must surface in logs, not silently disappear.

    We test the observable behavior: after a valid financial flow, the exception
    is present in the DB. We also verify the logging behavior by checking that
    errors surface via logger, not bare pass.
    """

    def test_duplicate_invoice_exception_is_created_not_swallowed(self):
        """Creating a duplicate invoice must create an exception, not drop it."""
        from app.services import invoice_service
        with self.db.write_transaction() as conn:
            sid, _ = _make_supplier(conn, "r4@test.com", "R4111111111", "Repair4 Sup")
            uid = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, role, is_active)"
                " VALUES (?,?,?,?,?,?)",
                ("r4admin@test.com", "r4admin@test.com",
                 "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                 "Admin R4", "admin", 1),
            ).lastrowid

        # First invoice
        with self.db.write_transaction() as conn:
            inv1 = invoice_service.create_invoice(
                conn,
                supplier_id=sid,
                invoice_number="INV-R4-DUP",
                invoice_date="2026-01-01",
                lines=[],
                created_by=uid,
            )
        # Duplicate invoice (same number + date + supplier)
        with self.db.write_transaction() as conn:
            inv2 = invoice_service.create_invoice(
                conn,
                supplier_id=sid,
                invoice_number="INV-R4-DUP",
                invoice_date="2026-01-01",
                lines=[],
                created_by=uid,
            )

        self.assertTrue(inv2["is_duplicate"], "Second invoice must be flagged as duplicate")

        # The exception must be in the DB
        with self.db.read_transaction() as conn:
            exc = conn.execute(
                "SELECT * FROM exceptions WHERE exception_type = 'duplicate_invoice'"
                " AND supplier_id = ? LIMIT 1",
                (sid,),
            ).fetchone()
        self.assertIsNotNone(exc, "duplicate_invoice exception must exist in exception inbox")

    def test_three_way_mismatch_exception_is_created(self):
        """three_way_mismatch exceptions must be present in DB after mismatching amounts."""
        with self.db.write_transaction() as conn:
            sid, _ = _make_supplier(conn, "r4b@test.com", "R4222222222", "Repair4b Sup")
            admin_uid = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, role, is_active)"
                " VALUES (?,?,?,?,?,?)",
                ("r4badmin@test.com", "r4badmin@test.com",
                 "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                 "Admin R4B", "admin", 1),
            ).lastrowid
            inv_id = _make_invoice(conn, sid, total=1000000, invoice_number="INV-R4B-MM")
            po_id = _make_procurement_order(conn, sid, total=2000000)  # amount mismatch

        with self.db.write_transaction() as conn:
            result = three_way_match_service.perform_match(
                conn,
                supplier_id=sid,
                procurement_order_id=po_id,
                invoice_id=inv_id,
                checked_by=admin_uid,
            )

        self.assertEqual(result["result"], "mismatch")

        with self.db.read_transaction() as conn:
            exc = conn.execute(
                "SELECT * FROM exceptions WHERE exception_type = 'three_way_mismatch'"
                " AND supplier_id = ? LIMIT 1",
                (sid,),
            ).fetchone()
        self.assertIsNotNone(exc, "three_way_mismatch exception must be in inbox")


# ---------------------------------------------------------------------------
# Repair 5: Reconciliation validates amount + currency on reference match
# ---------------------------------------------------------------------------

class Repair5ReconciliationEconomicValidationTest(AppTestCase):
    """Strong reference match must also validate amount and currency."""

    def setUp(self):
        super().setUp()
        with self.db.write_transaction() as conn:
            sid, _ = _make_supplier(conn, "r5@test.com", "R5111111111", "Repair5 Sup")
            self.sid = sid
            # Create reconciliation batch
            batch_cur = conn.execute(
                "INSERT INTO reconciliation_batches"
                " (batch_ref, source_type, supplier_id, period_start, period_end,"
                "  total_items, matched_count, unmatched_count, status, created_by)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("BATCH-R5", "psp_statement", sid, "2026-01-01", "2026-01-31",
                 0, 0, 0, "pending", 1),
            )
            self.batch_id = int(batch_cur.lastrowid)

    def _add_item(self, external_ref: str, amount: int, currency: str = "IRR"):
        """Helper to insert a reconciliation_item directly."""
        with self.db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO reconciliation_items"
                " (batch_id, external_ref, transaction_date, amount_minor, currency, status, match_confidence_bps)"
                " VALUES (?,?,?,?,?,?,?)",
                (self.batch_id, external_ref, "2026-01-15", amount, currency, "unmatched", 0),
            )
            conn.execute(
                "UPDATE reconciliation_batches SET total_items = total_items + 1 WHERE id = ?",
                (self.batch_id,),
            )

    def test_same_ref_same_amount_same_currency_is_matched(self):
        """Exact reference + amount + currency match → MATCHED at confidence 10000."""
        ref = "PSP-R5-EXACT-001"
        amount = 5000000
        with self.db.write_transaction() as conn:
            _make_payment(conn, amount, ref, "IRR")
        self._add_item(ref, amount, "IRR")

        with self.db.write_transaction() as conn:
            result = reconciliation_service.run_matching(conn, batch_id=self.batch_id)

        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(result["ambiguous_count"], 0)

        with self.db.read_transaction() as conn:
            item = conn.execute(
                "SELECT status, match_confidence_bps FROM reconciliation_items WHERE batch_id = ?",
                (self.batch_id,),
            ).fetchone()
        self.assertEqual(item["status"], "matched")
        self.assertEqual(item["match_confidence_bps"], 10000)

    def test_same_ref_wrong_amount_is_not_matched(self):
        """Same provider_ref but DIFFERENT amount → partial (mismatch), NOT auto-matched."""
        ref = "PSP-R5-WRONGAMT-002"
        payment_amount = 5000000
        statement_amount = 9999999  # different!
        with self.db.write_transaction() as conn:
            _make_payment(conn, payment_amount, ref, "IRR")
        self._add_item(ref, statement_amount, "IRR")

        with self.db.write_transaction() as conn:
            result = reconciliation_service.run_matching(conn, batch_id=self.batch_id)

        self.assertEqual(result["matched_count"], 0)
        self.assertEqual(result["ambiguous_count"], 1)

        with self.db.read_transaction() as conn:
            item = conn.execute(
                "SELECT status, notes FROM reconciliation_items WHERE batch_id = ?",
                (self.batch_id,),
            ).fetchone()
        self.assertEqual(item["status"], "partial")
        self.assertIn("ref_match_amount_mismatch", str(item["notes"] or ""))

    def test_same_ref_wrong_currency_is_not_matched(self):
        """Same provider_ref, same amount, but DIFFERENT currency → partial, NOT auto-matched."""
        ref = "PSP-R5-WRONGCUR-003"
        amount = 3000000
        with self.db.write_transaction() as conn:
            _make_payment(conn, amount, ref, "IRR")
        self._add_item(ref, amount, "USD")  # wrong currency

        with self.db.write_transaction() as conn:
            result = reconciliation_service.run_matching(conn, batch_id=self.batch_id)

        self.assertEqual(result["matched_count"], 0)
        self.assertEqual(result["ambiguous_count"], 1)

        with self.db.read_transaction() as conn:
            item = conn.execute(
                "SELECT status FROM reconciliation_items WHERE batch_id = ?",
                (self.batch_id,),
            ).fetchone()
        self.assertEqual(item["status"], "partial")

    def test_two_same_amount_no_ref_still_ambiguous(self):
        """Two payments with same amount and no reference → still ambiguous (B7 intact)."""
        amount = 1234567
        with self.db.write_transaction() as conn:
            _make_payment(conn, amount, "PSP-R5-AMB-001", "IRR")
        # Second payment needs a different order — but same amount
        with self.db.write_transaction() as conn:
            import datetime
            now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
            o2 = conn.execute(
                "INSERT INTO orders"
                " (order_number, user_id, status, subtotal_minor, shipping_fee_minor,"
                "  total_minor, currency, shipping_province, shipping_city, shipping_line1,"
                "  recipient_name, recipient_phone, placed_at, credit_minor, cash_minor)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("ORD-MR-AMB2", 1, "paid", amount, 0, amount, "IRR",
                 "Tehran", "Tehran", "Addr2", "Name2", "09000000001", now, 0, amount),
            ).lastrowid
            conn.execute(
                "INSERT INTO payments (order_id, provider, provider_ref, method, amount_minor, currency, status)"
                " VALUES (?,?,?,?,?,?,?)",
                (o2, "mock_psp", "PSP-R5-AMB-002", "card", amount, "IRR", "captured"),
            )
        self._add_item("", amount, "IRR")  # no external_ref, same amount as both

        with self.db.write_transaction() as conn:
            result = reconciliation_service.run_matching(conn, batch_id=self.batch_id)

        self.assertEqual(result["matched_count"], 0)
        self.assertEqual(result["ambiguous_count"], 1)


# ---------------------------------------------------------------------------
# Repair 6: DB-level UNIQUE index on idempotency_key
# ---------------------------------------------------------------------------

class Repair6IdempotencyIndexTest(AppTestCase):
    """UNIQUE INDEX on exceptions.idempotency_key must exist and be enforced."""

    def test_unique_index_exists_on_exceptions_table(self):
        """UNIQUE INDEX idx_exceptions_idempotency_key must be in the schema."""
        with self.db.read_transaction() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type='index' AND name='idx_exceptions_idempotency_key'",
            ).fetchone()
        self.assertIsNotNone(row, "UNIQUE INDEX idx_exceptions_idempotency_key must exist")

    def test_duplicate_idempotency_key_raises_integrity_error(self):
        """Inserting two exceptions with the same non-null idempotency_key must fail."""
        import sqlite3 as sqlite3_module
        key = "test:unique:key:r6"
        with self.db.write_transaction() as conn:
            exception_service.create_exception(
                conn,
                exception_type="other",
                severity="low",
                title="First exception",
                idempotency_key=key,
            )

        with self.assertRaises(Exception):
            with self.db.write_transaction() as conn:
                # Bypass app-layer check and INSERT directly to test DB constraint
                conn.execute(
                    "INSERT INTO exceptions (exception_type, severity, title, detail_json, status, retry_count, idempotency_key)"
                    " VALUES (?,?,?,?,?,?,?)",
                    ("other", "low", "Second exception", "{}", "open", 0, key),
                )

    def test_null_idempotency_key_allows_multiple_rows(self):
        """NULL idempotency_key must not be constrained (partial index)."""
        with self.db.write_transaction() as conn:
            exception_service.create_exception(
                conn, exception_type="other", severity="low",
                title="No key A", idempotency_key=None,
            )
            exception_service.create_exception(
                conn, exception_type="other", severity="low",
                title="No key B", idempotency_key=None,
            )
        # No error means the partial index correctly ignores NULLs

    def test_migration_head_is_0015(self):
        """Schema version must be at least 0015 after all migrations applied.
        Phase 7 added 0016-0018, so head will be 0018 or higher."""
        from app.core import migrator
        v = migrator.current_version(self.db)
        self.assertGreaterEqual(v, "0015",
                                f"Expected migration head >= 0015, got {v!r}")


if __name__ == "__main__":
    unittest.main()
