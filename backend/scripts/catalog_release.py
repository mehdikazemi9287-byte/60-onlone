"""Reviewable SQLite catalogue release; never replace a live database.
Preview returns a plan hash. Apply requires that hash and an exclusive journal.
Rollback preserves newly created publications as hidden rows and never touches
users, orders, money, supplier offers or inventory.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
KEYS = {"master_products": "id", "catalog_publications": "master_product_id"}


def _row(conn, table, key):
    row = conn.execute("SELECT * FROM " + table + " WHERE " + KEYS[table] + "=?", (key,)).fetchone()
    return dict(row) if row else None


def plan(conn):
    operations = {}

    def edit(table, key, changes):
        identity = (table, key)
        before = _row(conn, table, key)
        current = operations.get(identity, {}).get("after", before)
        after = {**(current or {}), **changes}
        operations[identity] = {"table": table, "key": key, "before": before, "after": after}

    publications = json.loads((ROOT / "recovery/catalog_publications.json").read_text())
    for row in publications["records"]:
        mid = row["master_product_id"]
        master = _row(conn, "master_products", mid)
        if not master or master["canonical_name_fa"] != row["canonical_name_fa"]:
            raise ValueError("Master identity changed: " + str(mid))
        if conn.execute(
            "SELECT 1 FROM products WHERE master_product_id=? AND is_active=1", (mid,)
        ).fetchone():
            continue
        existing = _row(conn, "catalog_publications", mid)
        if existing:
            if existing["slug"] != row["slug"]:
                raise ValueError("Publication slug conflict: " + str(mid))
            if existing["is_visible"] == 0:
                edit("catalog_publications", mid, {"is_visible": 1})
            continue
        edit(
            "catalog_publications",
            mid,
            {
                "master_product_id": mid,
                "slug": row["slug"],
                "category_slug": row["category_slug"],
                "currency": row["currency"],
                "is_visible": 1,
                "is_purchasable": 0,
                "verified_price_minor": None,
                "price_status": "pending",
                "publication_reason": row["publication_reason"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )
    images = json.loads((ROOT / "recovery/catalog_images.json").read_text())
    for row in images["records"]:
        if row["status"] != "recovered":
            continue
        image = ROOT.parent / "frontend/public" / row["local_url"].lstrip("/")
        if not image.is_file() or hashlib.sha256(image.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Image asset missing or changed: " + row["sha256"])
        for mid in row["master_ids"]:
            master = _row(conn, "master_products", mid)
            if not master:
                raise ValueError("Image master missing: " + str(mid))
            urls = json.loads(master["image_urls_json"] or "[]")
            if row["source_url"] in urls:
                edit(
                    "master_products",
                    mid,
                    {
                        "image_urls_json": json.dumps(
                            [row["local_url"] if u == row["source_url"] else u for u in urls],
                            ensure_ascii=False,
                        )
                    },
                )
    corrections = json.loads((ROOT / "recovery/catalog_corrections.json").read_text())
    for row in corrections["categories"]:
        mid = row["master_id"]
        master = _row(conn, "master_products", mid)
        if master["canonical_name_fa"] != row["name"]:
            raise ValueError("Category master identity changed")
        if master["category"] not in (row["old_category"], row["category"]):
            raise ValueError("Category was independently changed: " + str(mid))
        edit("master_products", mid, {"category": row["category"]})
        if _row(conn, "catalog_publications", mid) or ("catalog_publications", mid) in operations:
            edit("catalog_publications", mid, {"category_slug": row["category"]})
    for row in corrections["excluded_images"]:
        master = _row(conn, "master_products", row["master_id"])
        urls = json.loads(master["image_urls_json"] or "[]")
        cleaned = [u for u in urls if u not in row["original_images"]]
        if cleaned != urls:
            edit(
                "master_products",
                row["master_id"],
                {"image_urls_json": json.dumps(cleaned, ensure_ascii=False)},
            )
    return [op for op in operations.values() if op["before"] != op["after"]]


def digest(operations):
    return hashlib.sha256(
        json.dumps(operations, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def apply(conn, operations):
    for op in operations:
        table, key = op["table"], op["key"]
        if _row(conn, table, key) != op["before"]:
            raise ValueError("Data changed after preview")
        after = op["after"]
        if op["before"] is None:
            columns = list(after)
            conn.execute(
                "INSERT INTO "
                + table
                + "("
                + ",".join(columns)
                + ") VALUES ("
                + ",".join("?" for _ in columns)
                + ")",
                [after[c] for c in columns],
            )
        else:
            changed = {k: v for k, v in after.items() if op["before"].get(k) != v}
            if changed:
                conn.execute(
                    "UPDATE "
                    + table
                    + " SET "
                    + ",".join(k + "=?" for k in changed)
                    + " WHERE "
                    + KEYS[table]
                    + "=?",
                    [*changed.values(), key],
                )


def rollback_plan(conn, journal):
    result = []
    for op in reversed(journal["operations"]):
        current = _row(conn, op["table"], op["key"])
        restored = op["before"] if op["before"] is not None else {**op["after"], "is_visible": 0}
        if current == op["before"] or current == restored:
            continue
        if current != op["after"]:
            raise ValueError("Independent edit prevents automatic rollback: " + str(op["key"]))
        result.append(
            {"table": op["table"], "key": op["key"], "before": current, "after": restored}
        )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--journal")
    parser.add_argument("--rollback")
    args = parser.parse_args()
    if args.confirm and (not args.expected_plan_sha256 or not args.journal):
        parser.error("Apply requires --expected-plan-sha256 and a NEW --journal path")
    conn = sqlite3.connect(
        "file:" + str(Path(args.database).resolve()) + ("?mode=rw" if args.confirm else "?mode=ro"),
        uri=True,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if args.confirm:
        conn.execute("BEGIN IMMEDIATE")
    else:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
    try:
        operations = (
            rollback_plan(conn, json.loads(Path(args.rollback).read_text()))
            if args.rollback
            else plan(conn)
        )
        checksum = digest(operations)
        if args.confirm:
            if checksum != args.expected_plan_sha256:
                raise ValueError("Plan changed; review a fresh preview")
            apply(conn, operations)
            if conn.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Foreign key violation")
            journal = {"plan_sha256": checksum, "operations": operations}
            fd = os.open(args.journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as file:
                json.dump(journal, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            conn.commit()
        print(
            json.dumps(
                {
                    "confirmed": args.confirm,
                    "operations": len(operations),
                    "plan_sha256": checksum,
                    "new_publications": sum(
                        o["table"] == "catalog_publications" and o["before"] is None
                        for o in operations
                    ),
                }
            )
        )
    finally:
        if conn.in_transaction:
            conn.rollback()
        conn.close()


if __name__ == "__main__":
    main()
