"""BLOCKER 1 regression test — migration 0008 on a POPULATED database.

Verifies that 0008_shipment_states.sql:
  - succeeds when shipment_booking_log and webhook_events rows referencing
    shipments exist (FK enforcement is ON throughout);
  - preserves every parent and child row with the same primary key;
  - leaves PRAGMA foreign_keys = ON and zero FK violations;
  - recreates all required indexes and the unique constraint;
  - accepts the two new status values ('out_for_delivery', 'returned')
    on shipments inserted after the migration.

This test does NOT use AppTestCase (which always applies all migrations).
It builds a minimal DB manually at schema 0007, inserts real FK-satisfying
rows, then upgrades to 0008 and runs comprehensive post-migration checks.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

# Make sure the backend src is importable regardless of CWD.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import Database
from app.core import migrator


# ── paths ────────────────────────────────────────────────────────────────────

_BACKEND_DIR    = Path(__file__).resolve().parents[1]
_MIGRATIONS_DIR = _BACKEND_DIR / "migrations"

# All migration files up to (and including) 0007.
_PRE_MIGRATION_FILES = sorted(
    p for p in _MIGRATIONS_DIR.glob("*.sql")
    if p.stem[:4].isdigit() and int(p.stem[:4]) <= 7
)

# The migration under test.
_MIGRATION_0008 = _MIGRATIONS_DIR / "0008_shipment_states.sql"


# ── helpers ──────────────────────────────────────────────────────────────────

def _apply_up_to_0007(db: Database, staging_dir: Path) -> None:
    """Copy migrations 0001-0007 to a temp staging dir and upgrade."""
    for path in _PRE_MIGRATION_FILES:
        shutil.copy(path, staging_dir / path.name)
    migrator.upgrade(db, staging_dir)


def _index_names(db: Database) -> set[str]:
    """Return all index names that belong to the 'shipments' table."""
    rows = db.query(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='shipments'"
    )
    return {r["name"] for r in rows}


# ── test ─────────────────────────────────────────────────────────────────────

class Migration0008PopulatedDBTest(unittest.TestCase):
    """
    Regression test: migrate 0007 → 0008 with FK-referencing rows in place.

    Schema at 0007 already contains shipment_booking_log and webhook_events,
    both of which have FK columns pointing to shipments.id.  Migration 0008
    rebuilds the shipments table (CREATE … / INSERT … / DROP / RENAME).
    Without PRAGMA defer_foreign_keys = ON the DROP TABLE would fail under
    PRAGMA foreign_keys = ON.  This test proves it does NOT fail.
    """

    def setUp(self) -> None:
        self.tmpdir    = tempfile.mkdtemp(prefix="70online-mig0008-test-")
        self.db_path   = os.path.join(self.tmpdir, "test0008.db")
        self.staging   = Path(self.tmpdir) / "migrations"
        self.staging.mkdir()
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── fixtures ──────────────────────────────────────────────────────────────

    def _insert_fixture_rows(self) -> dict:
        """Insert a real FK chain into the 0007-schema DB and return their ids.

        Insertion order satisfies all FK constraints (FK enforcement is ON).
        Returns a dict of all inserted primary keys so assertions can verify
        row survival after the migration.
        """
        with self.db.write_transaction() as conn:

            # 1. users — no FK deps
            cur = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name) "
                "VALUES (?,?,?,?)",
                (
                    "mig0008@test.example",
                    "mig0008@test.example",
                    "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",  # length ≥ 40, has '$'
                    "تست مهاجرت ۸",
                ),
            )
            user_id = int(cur.lastrowid)

            # 2. suppliers — user_id FK is optional (ON DELETE SET NULL)
            cur = conn.execute(
                "INSERT INTO suppliers "
                "(legal_name, display_name, national_id, supplier_type, status, rating_x10) "
                "VALUES (?,?,?,?,?,?)",
                ("شرکت آزمایشی مهاجرت", "آزمایشی مهاجرت", "9876543210", "retailer", "active", 40),
            )
            supplier_id = int(cur.lastrowid)

            # 3. supplier_locations — references suppliers
            cur = conn.execute(
                "INSERT INTO supplier_locations "
                "(supplier_id, province, city, status, "
                " can_local_delivery, can_intercity_shipping, can_pickup, prep_time_minutes) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (supplier_id, "تهران", "تهران", "active", 1, 1, 0, 60),
            )
            location_id = int(cur.lastrowid)

            # 4. orders — references users
            #    CHECK: total_minor = subtotal_minor + shipping_fee_minor
            cur = conn.execute(
                "INSERT INTO orders "
                "(order_number, user_id, status, subtotal_minor, shipping_fee_minor, "
                " total_minor, currency, recipient_name, recipient_phone, "
                " shipping_province, shipping_city, shipping_line1) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "ORD-MIG0008-TEST-001",
                    user_id,
                    "paid",
                    1_000_000, 0, 1_000_000,  # total = subtotal + shipping (CHECK satisfied)
                    "IRR",
                    "تست مهاجرت",
                    "09121234567",
                    "تهران", "تهران", "خیابان آزمایشی، پلاک ۸",
                ),
            )
            order_id = int(cur.lastrowid)

            # 5. fulfillment_orders — references orders + suppliers + supplier_locations
            cur = conn.execute(
                "INSERT INTO fulfillment_orders "
                "(order_id, supplier_id, supplier_location_id, status, "
                " fulfillment_type, gross_payable_minor) "
                "VALUES (?,?,?,?,?,?)",
                (order_id, supplier_id, location_id, "assigned", "delivery", 1_000_000),
            )
            fo_id = int(cur.lastrowid)

            # 6. carrier_configs — no FK deps
            cur = conn.execute(
                "INSERT INTO carrier_configs "
                "(provider_code, name_fa, province, capabilities, cost_minor, is_active) "
                "VALUES (?,?,?,?,?,?)",
                ("mock", "حامل آزمایشی مهاجرت ۸", "تهران", "local,intercity", 50_000, 1),
            )
            cc_id = int(cur.lastrowid)

            # 7. shipments — references fulfillment_orders + carrier_configs
            #    Uses 'in_transit' — valid in pre-0008 CHECK
            cur = conn.execute(
                "INSERT INTO shipments "
                "(fulfillment_order_id, carrier_config_id, provider_code, "
                " status, booking_idempotency_key, shipping_payer, cost_minor, currency) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    fo_id, cc_id, "mock",
                    "in_transit", "ikey-mig0008-test-001",
                    "customer", 50_000, "IRR",
                ),
            )
            shipment_id = int(cur.lastrowid)

            # 8. shipment_booking_log (TWO rows) — references shipments (NOT NULL FK)
            cur = conn.execute(
                "INSERT INTO shipment_booking_log "
                "(shipment_id, phase, outcome) VALUES (?,?,?)",
                (shipment_id, "phase_a", "success"),
            )
            sbl_id_1 = int(cur.lastrowid)

            cur = conn.execute(
                "INSERT INTO shipment_booking_log "
                "(shipment_id, phase, outcome) VALUES (?,?,?)",
                (shipment_id, "external", "success"),
            )
            sbl_id_2 = int(cur.lastrowid)

            # 9. webhook_events — shipment_id is nullable REFERENCES shipments(id)
            cur = conn.execute(
                "INSERT INTO webhook_events "
                "(provider_code, provider_event_id, shipment_id, raw_payload, outcome) "
                "VALUES (?,?,?,?,?)",
                ("mock", "evt-mig0008-reg-test-001", shipment_id, '{"type":"in_transit"}', "accepted"),
            )
            we_id = int(cur.lastrowid)

        return {
            "user_id":     user_id,
            "supplier_id": supplier_id,
            "location_id": location_id,
            "order_id":    order_id,
            "fo_id":       fo_id,
            "cc_id":       cc_id,
            "shipment_id": shipment_id,
            "sbl_id_1":    sbl_id_1,
            "sbl_id_2":    sbl_id_2,
            "we_id":       we_id,
        }

    # ── main test ─────────────────────────────────────────────────────────────

    def test_migration_0008_succeeds_on_populated_database(self):
        """Migration 0007→0008 must succeed with FK-referencing rows in place.

        Verifies:
          1. Schema at 0007 after initial setup (not yet at 0008).
          2. FK enforcement is ON before migration (bad-FK insert fails).
          3. Migration runs without error (the critical assertion).
          4. Schema version advances to '0008'.
          5. All fixture rows survive with unchanged primary keys.
          6. PRAGMA foreign_key_check returns zero violations.
          7. PRAGMA foreign_keys = 1 (still ON after migration).
          8. All required indexes and unique constraints exist.
          9. New status values ('out_for_delivery', 'returned') are accepted.
         10. Invalid status values are still rejected.
         11. Pre-existing 'in_transit' shipment status is unchanged.
        """

        # ── Step 1: Apply migrations 0001-0007 only ───────────────────────────
        _apply_up_to_0007(self.db, self.staging)

        schema_before = migrator.current_version(self.db)
        self.assertEqual(
            schema_before, "0007",
            f"pre-migration: schema must be 0007, got {schema_before!r}",
        )

        # ── Step 2: Insert real FK-satisfying fixture rows ────────────────────
        ids = self._insert_fixture_rows()
        shipment_id = ids["shipment_id"]
        sbl_id_1    = ids["sbl_id_1"]
        sbl_id_2    = ids["sbl_id_2"]
        we_id       = ids["we_id"]

        # Verify rows exist before migration.
        with self.db.read_transaction() as conn:
            self.assertIsNotNone(
                conn.execute("SELECT id FROM shipments WHERE id=?", (shipment_id,)).fetchone(),
                "pre: shipment must exist",
            )
            sbl_count = conn.execute(
                "SELECT COUNT(*) AS n FROM shipment_booking_log WHERE shipment_id=?",
                (shipment_id,),
            ).fetchone()["n"]
            self.assertEqual(sbl_count, 2, "pre: two booking_log rows expected")

            we_row = conn.execute(
                "SELECT id FROM webhook_events WHERE id=?", (we_id,)
            ).fetchone()
            self.assertIsNotNone(we_row, "pre: webhook_events row must exist")

        # ── Step 3: Verify FK enforcement is ON before migration ──────────────
        fk_before = self.db.connection.execute("PRAGMA foreign_keys").fetchone()[0]
        self.assertEqual(fk_before, 1, "pre: PRAGMA foreign_keys must be 1 (ON)")

        # Inserting a booking_log row with a non-existent shipment_id MUST fail.
        non_existent_ship_id = 999_999
        with self.assertRaises(
            Exception,
            msg="pre: FK enforcement must reject invalid shipment_id reference",
        ):
            with self.db.write_transaction() as conn:
                conn.execute(
                    "INSERT INTO shipment_booking_log "
                    "(shipment_id, phase, outcome) VALUES (?,?,?)",
                    (non_existent_ship_id, "phase_a", "failure"),
                )

        # ── Step 4: Apply migration 0008 (the critical assertion) ─────────────
        shutil.copy(_MIGRATION_0008, self.staging / _MIGRATION_0008.name)
        try:
            migrator.upgrade(self.db, self.staging)
        except Exception as exc:
            self.fail(
                f"Migration 0007→0008 MUST succeed on a populated database, "
                f"but it raised {type(exc).__name__}: {exc}"
            )

        # ── Step 5: Schema version is now 0008 ────────────────────────────────
        schema_after = migrator.current_version(self.db)
        self.assertEqual(
            schema_after, "0008",
            f"post-migration: schema must be '0008', got {schema_after!r}",
        )

        # ── Step 6: All rows survived with original primary keys ──────────────
        with self.db.read_transaction() as conn:
            ship_row = conn.execute(
                "SELECT * FROM shipments WHERE id=?", (shipment_id,)
            ).fetchone()
            self.assertIsNotNone(
                ship_row,
                f"post: shipment id={shipment_id} must survive migration",
            )
            self.assertEqual(
                int(ship_row["id"]), shipment_id,
                "post: shipment primary key must be unchanged",
            )
            self.assertEqual(
                ship_row["status"], "in_transit",
                "post: migrated shipment status must be unchanged ('in_transit')",
            )
            self.assertEqual(
                ship_row["booking_idempotency_key"], "ikey-mig0008-test-001",
                "post: booking_idempotency_key must be preserved",
            )

            # shipment_booking_log rows
            sbl_rows = conn.execute(
                "SELECT id, phase FROM shipment_booking_log WHERE shipment_id=? ORDER BY id",
                (shipment_id,),
            ).fetchall()
            self.assertEqual(
                len(sbl_rows), 2,
                "post: both booking_log rows must survive",
            )
            self.assertEqual(
                int(sbl_rows[0]["id"]), sbl_id_1,
                "post: first booking_log row must have same id",
            )
            self.assertEqual(
                int(sbl_rows[1]["id"]), sbl_id_2,
                "post: second booking_log row must have same id",
            )
            self.assertEqual(
                sbl_rows[0]["phase"], "phase_a",
                "post: first booking_log phase must be unchanged",
            )

            # webhook_events row
            we_row = conn.execute(
                "SELECT id, shipment_id FROM webhook_events WHERE id=?", (we_id,)
            ).fetchone()
            self.assertIsNotNone(we_row, "post: webhook_events row must survive migration")
            self.assertEqual(int(we_row["id"]), we_id, "post: webhook_events id unchanged")
            self.assertEqual(
                int(we_row["shipment_id"]), shipment_id,
                "post: webhook_events.shipment_id FK must still point to correct shipment",
            )

        # ── Step 7: PRAGMA foreign_key_check — zero violations ────────────────
        fk_violations = self.db.connection.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(
            len(fk_violations), 0,
            f"post: foreign_key_check must return 0 violations; got: {fk_violations}",
        )

        # ── Step 8: PRAGMA foreign_keys still ON ──────────────────────────────
        fk_after = self.db.connection.execute("PRAGMA foreign_keys").fetchone()[0]
        self.assertEqual(
            fk_after, 1,
            "post: PRAGMA foreign_keys must remain 1 (ON) after migration",
        )

        # ── Step 9: Required indexes exist ────────────────────────────────────
        idx = _index_names(self.db)
        required_indexes = {
            "idx_shipments_fo",
            "idx_shipments_provider",
            "idx_shipments_tracking",
            "idx_shipments_ikey",   # UNIQUE index
        }
        for name in required_indexes:
            self.assertIn(name, idx, f"post: index '{name}' must exist on shipments")

        # Confirm the unique index is flagged as unique in sqlite_master.
        ikey_entry = self.db.query_one(
            "SELECT * FROM sqlite_master WHERE type='index' AND name='idx_shipments_ikey'"
        )
        self.assertIsNotNone(ikey_entry, "post: idx_shipments_ikey must exist in sqlite_master")
        # sqlite_master.sql contains 'UNIQUE' for a UNIQUE index.
        self.assertIn(
            "UNIQUE", (ikey_entry["sql"] or "").upper(),
            "post: idx_shipments_ikey must be a UNIQUE index",
        )

        # ── Step 10: New status values are accepted after migration ───────────
        # 'out_for_delivery'
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                "INSERT INTO shipments "
                "(fulfillment_order_id, carrier_config_id, provider_code, "
                " status, booking_idempotency_key, shipping_payer, cost_minor, currency) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    ids["fo_id"], ids["cc_id"], "mock",
                    "out_for_delivery", "ikey-mig0008-ofd-test",
                    "customer", 50_000, "IRR",
                ),
            )
            ofd_id = int(cur.lastrowid)

        # 'returned'
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                "INSERT INTO shipments "
                "(fulfillment_order_id, carrier_config_id, provider_code, "
                " status, booking_idempotency_key, shipping_payer, cost_minor, currency) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    ids["fo_id"], ids["cc_id"], "mock",
                    "returned", "ikey-mig0008-ret-test",
                    "customer", 50_000, "IRR",
                ),
            )
            ret_id = int(cur.lastrowid)

        with self.db.read_transaction() as conn:
            ofd_row = conn.execute(
                "SELECT status FROM shipments WHERE id=?", (ofd_id,)
            ).fetchone()
            ret_row = conn.execute(
                "SELECT status FROM shipments WHERE id=?", (ret_id,)
            ).fetchone()
        self.assertIsNotNone(ofd_row, "post: out_for_delivery shipment must be insertable")
        self.assertEqual(ofd_row["status"], "out_for_delivery", "post: status must be out_for_delivery")
        self.assertIsNotNone(ret_row, "post: returned shipment must be insertable")
        self.assertEqual(ret_row["status"], "returned", "post: status must be returned")

        # ── Step 11: Invalid status still rejected ────────────────────────────
        with self.assertRaises(
            Exception,
            msg="post: CHECK constraint must still reject invalid status values",
        ):
            with self.db.write_transaction() as conn:
                conn.execute(
                    "INSERT INTO shipments "
                    "(fulfillment_order_id, carrier_config_id, provider_code, "
                    " status, booking_idempotency_key, shipping_payer, cost_minor, currency) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        ids["fo_id"], ids["cc_id"], "mock",
                        "INVALID_STATUS_NOT_IN_CHECK", "ikey-mig0008-bad-status",
                        "customer", 0, "IRR",
                    ),
                )

        # Final foreign_key_check after all insertions
        fk_final = self.db.connection.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(
            len(fk_final), 0,
            f"final: foreign_key_check must return 0 violations; got: {fk_final}",
        )


if __name__ == "__main__":
    unittest.main()
